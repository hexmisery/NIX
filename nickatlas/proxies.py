import asyncio
import base64
import ctypes
import hashlib
import ipaddress
import json
import os
import time
from urllib.parse import quote, unquote, urlsplit

from .export import atomic_text

MAX_PROXIES = 100_000
MAX_IMPORT_BYTES = 32 * 1024 * 1024


def normalize_proxy(value):
    value = value.strip()
    if (
        not value
        or len(value) > 2048
        or any(c.isspace() for c in value)
        or "\\" in value
    ):
        raise ValueError("Invalid proxy address")
    if "://" not in value:
        parts = value.split(":")
        if len(parts) == 4:
            value = f"http://{quote(parts[2], safe='')}:{quote(parts[3], safe='')}@{parts[0]}:{parts[1]}"
        else:
            value = "http://" + value
    try:
        p = urlsplit(value)
        if (
            p.scheme not in ("http", "https", "socks4", "socks5")
            or not p.hostname
            or not p.port
            or p.path not in ("", "/")
            or p.query
            or p.fragment
        ):
            raise ValueError()
        host = p.hostname.encode("idna").decode("ascii").lower()
        if any(c in host for c in ("%", "@", "/", "?", "#")):
            raise ValueError()
        host = f"[{host}]" if ":" in host else host
        auth = ""
        if p.username is not None:
            auth = (
                quote(unquote(p.username), safe="")
                + ":"
                + quote(unquote(p.password or ""), safe="")
                + "@"
            )
        return f"{p.scheme}://{auth}{host}:{p.port}"
    except (ValueError, UnicodeError):
        raise ValueError("Invalid proxy address") from None


def _protect(payload, decrypt=False):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    source, target = Blob(len(payload), buffer), Blob()
    crypt = ctypes.WinDLL("crypt32")
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("Could not access proxy storage")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel = ctypes.WinDLL("kernel32")
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(target.data)


class ProxyStore:
    def __init__(self, root):
        self.path = root / "proxies.private"
        self.rows, self.mode, self.selected = {}, "direct", ""
        if self.path.exists():
            payload = self.path.read_bytes()
            if payload.startswith(b"DPAPI:"):
                payload = _protect(base64.b64decode(payload[6:]), True)
            data = json.loads(payload)
            self.rows = {r["id"]: r for r in data.get("rows", [])}
            self.mode = data.get("mode", "direct")
            self.selected = data.get("selected", "")

    def save(self):
        data = json.dumps(
            {
                "rows": list(self.rows.values()),
                "mode": self.mode,
                "selected": self.selected,
            }
        ).encode()
        if os.name == "nt":
            data = b"DPAPI:" + base64.b64encode(_protect(data))
        atomic_text(self.path, data.decode())
        os.chmod(self.path, 0o600)

    def public(self):
        return {
            "mode": self.mode,
            "selected": self.selected,
            "rows": [
                {k: v for k, v in row.items() if k != "url"}
                for row in self.rows.values()
            ],
        }

    def add(self, text):
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
            raise ValueError("Proxy list exceeds 32 MB")
        urls, invalid, valid = set(), 0, 0
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                urls.add(normalize_proxy(line))
                valid += 1
            except ValueError:
                invalid += 1
            if len(urls) > MAX_PROXIES:
                raise ValueError("Proxy limit: 100000 unique addresses")
        incoming = {hashlib.sha256(url.encode()).hexdigest()[:20]: url for url in urls}
        if len(set(incoming) | set(self.rows)) > MAX_PROXIES:
            raise ValueError("Proxy limit: 100000 unique addresses")
        added = 0
        added_keys = []
        for url in sorted(urls):
            key = hashlib.sha256(url.encode()).hexdigest()[:20]
            if key in self.rows:
                continue
            p = urlsplit(url)
            host = f"[{p.hostname}]" if ":" in p.hostname else p.hostname
            self.rows[key] = {
                "id": key,
                "url": url,
                "address": f"{p.scheme}://{host}:{p.port}",
                "auth": p.username is not None,
                "status": "Unchecked",
                "latency": None,
                "ip": "",
                "checked": 0,
            }
            added += 1
            added_keys.append(key)
        try:
            self.save()
        except Exception:
            for key in added_keys:
                self.rows.pop(key, None)
            raise
        return {"added": added, "invalid": invalid, "duplicates": valid - added}

    def route(self):
        if self.mode == "direct":
            return None
        row = self.rows.get(self.selected)
        if not row or row["status"] != "Working":
            raise ValueError("Select a working proxy first")
        return row["url"]

    def configure(self, mode, selected):
        if (
            mode not in ("direct", "proxy")
            or not isinstance(selected, str)
            or selected
            and selected not in self.rows
        ):
            raise ValueError("Invalid proxy selection")
        if mode == "proxy" and (
            not selected or self.rows[selected]["status"] != "Working"
        ):
            raise ValueError("Select a working proxy first")
        self.mode, self.selected = mode, selected
        self.save()

    def remove(self, key):
        if key not in self.rows:
            raise ValueError("Unknown proxy")
        del self.rows[key]
        if self.selected == key:
            self.mode, self.selected = "direct", ""
        self.save()

    async def check(self, receive=lambda row: None):
        from .network import Network

        rows = iter(self.rows.values())
        last_save = time.monotonic()

        async def worker():
            nonlocal last_save
            for row in rows:
                start = time.monotonic()
                row.update(status="Failed", latency=None, ip="", checked=time.time())
                try:
                    async with Network(
                        concurrency=1, timeout=8, proxy=row["url"]
                    ) as net:
                        code, body, _, cut = await net.get(
                            "https://api.ipify.org?format=json", max_body=4096
                        )
                    address = str(ipaddress.ip_address(json.loads(body)["ip"]))
                    if (
                        code == 200
                        and not cut
                        and ipaddress.ip_address(address).is_global
                    ):
                        row.update(
                            status="Working",
                            ip=address,
                            latency=round((time.monotonic() - start) * 1000),
                        )
                except asyncio.CancelledError:
                    row.update(status="Unchecked", latency=None, ip="", checked=0)
                    raise
                except Exception:
                    pass
                finally:
                    receive({k: v for k, v in row.items() if k != "url"})
                if time.monotonic() - last_save >= 5:
                    self.save()
                    last_save = time.monotonic()

        tasks = [asyncio.create_task(worker()) for _ in range(min(16, len(self.rows)))]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.save()
