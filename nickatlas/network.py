import asyncio
import ipaddress
import socket
import zlib
import contextvars
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp

MAX_BODY = 1024 * 1024
ROUTE = contextvars.ContextVar("nix_network_route", default=None)


def public_address(address):
    ip = ipaddress.ip_address(address.split("%")[0])
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def safe_url(url):
    try:
        p = urlsplit(url)
        if (
            p.scheme not in ("http", "https")
            or not p.hostname
            or p.username
            or p.password
            or p.port not in (None, 80, 443)
        ):
            raise ValueError()
        if any(c in url for c in ("\r", "\n", "\\")):
            raise ValueError()
        host = p.hostname.lower().rstrip(".")
        if (
            host == "localhost"
            or host.endswith((".localhost", ".local", ".internal", ".onion"))
            or "." not in host
            and ":" not in host
        ):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not public_address(host):
                raise ValueError()
        return url
    except (ValueError, TypeError):
        raise ValueError(
            "Разрешены только публичные HTTP/HTTPS-адреса на стандартных портах"
        ) from None


class PublicResolver(aiohttp.abc.AbstractResolver):
    def __init__(self):
        self.inner = aiohttp.resolver.ThreadedResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await self.inner.resolve(host, port, family)
        if not records or any(not public_address(r["host"]) for r in records):
            raise OSError("DNS вернул непубличный адрес")
        return records

    async def close(self):
        await self.inner.close()


class Network:
    def __init__(self, concurrency=16, timeout=12, proxy=None):
        self.concurrency = concurrency
        self.timeout = timeout
        self.proxy = proxy if proxy is not None else ROUTE.get()
        self.locks = {}
        self.last = {}
        self.cooldowns = set()
        self.gate = asyncio.Lock()
        self.next_request = 0.0

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(
            limit=self.concurrency,
            limit_per_host=2,
            resolver=PublicResolver(),
            ttl_dns_cache=60,
            force_close=bool(self.proxy),
        )
        if self.proxy and self.proxy.startswith(("socks4://", "socks5://")):
            await connector.close()
            from .socks_connector import PinnedSocksConnector

            connector = PinnedSocksConnector.from_url(
                self.proxy,
                limit=self.concurrency,
                limit_per_host=2,
                rdns=False,
                force_close=True,
            )
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=self.timeout),
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
            auto_decompress=False,
            headers={
                "User-Agent": "NIX (public username lookup)",
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
                "Accept-Encoding": "identity",
            },
        )
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    async def pace(self, host):
        loop = asyncio.get_running_loop()
        async with self.gate:
            now = loop.time()
            wait = max(0, self.next_request - now)
            self.next_request = max(now, self.next_request) + 1 / 40
        if wait:
            await asyncio.sleep(wait)
        wait = self.last.get(host, 0) + 0.8 - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)
        self.last[host] = loop.time()

    async def get(self, url, max_body=MAX_BODY):
        current = safe_url(url)
        for hop in range(5):
            host = urlsplit(current).hostname
            async with self.locks.setdefault(host, asyncio.Lock()):
                if host in self.cooldowns:
                    return 429, "", current, False
                await self.pace(host)
                target_url, request_options = current, {}
                if self.proxy:
                    loop = asyncio.get_running_loop()
                    records = await loop.getaddrinfo(
                        host,
                        443 if current.startswith("https:") else 80,
                        type=socket.SOCK_STREAM,
                    )
                    if not records or any(not public_address(r[4][0]) for r in records):
                        raise ValueError("Proxy destination is not public")
                    address = min(
                        records,
                        key=lambda record: ipaddress.ip_address(record[4][0]).version,
                    )[4][0]
                    numeric_host = "[" + address + "]" if ":" in address else address
                    parsed = urlsplit(current)
                    if parsed.port:
                        numeric_host += ":" + str(parsed.port)
                    target_url = urlunsplit(
                        (parsed.scheme, numeric_host, parsed.path, parsed.query, "")
                    )
                    request_options = {
                        "headers": {"Host": parsed.netloc},
                        "server_hostname": host,
                    }
                proxy = (
                    self.proxy
                    if self.proxy and self.proxy.startswith(("http://", "https://"))
                    else None
                )
                async with self.session.get(
                    target_url, allow_redirects=False, proxy=proxy, **request_options
                ) as resp:
                    if resp.status in (301, 302, 303, 307, 308) and resp.headers.get(
                        "Location"
                    ):
                        current = safe_url(urljoin(current, resp.headers["Location"]))
                        continue
                    if resp.status == 429:
                        self.cooldowns.add(host)
                    coding = (
                        resp.headers.get("Content-Encoding", "identity").lower().strip()
                    )
                    if coding not in ("identity", "gzip", "deflate", ""):
                        raise ValueError("Сайт прислал неподдерживаемый формат сжатия")
                    decoder = (
                        zlib.decompressobj(
                            16 + zlib.MAX_WBITS if coding == "gzip" else zlib.MAX_WBITS
                        )
                        if coding in ("gzip", "deflate")
                        else None
                    )
                    body = bytearray()
                    truncated = False
                    async for chunk in resp.content.iter_chunked(16384):
                        try:
                            decoded = (
                                decoder.decompress(chunk, max_body + 1 - len(body))
                                if decoder
                                else chunk
                            )
                        except zlib.error:
                            raise ValueError("Некорректный сжатый ответ") from None
                        body.extend(decoded)
                        if len(body) > max_body:
                            truncated = True
                            del body[max_body:]
                            break
                    try:
                        text = body.decode(resp.charset or "utf-8", errors="replace")
                    except LookupError:
                        text = body.decode("utf-8", errors="replace")
                    return (
                        resp.status,
                        text,
                        current if self.proxy else str(resp.url),
                        truncated,
                    )
        raise ValueError("Слишком много перенаправлений")
