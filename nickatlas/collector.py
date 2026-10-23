import asyncio, json
from urllib.parse import urlsplit, urlunsplit
import aiohttp
from .customsites import preset, validate_rule
from .network import Network, safe_url


def bases(urls):
    result = []
    seen = set()
    for value in urls:
        try:
            p = urlsplit(safe_url(value.strip()))
            base = urlunsplit(
                (
                    p.scheme,
                    p.netloc,
                    p.path.rstrip("/") if "{username}" not in p.path else "",
                    "",
                    "",
                )
            )
            if "{username}" in base or "{" in base:
                continue
            safe_url(base)
        except (ValueError, TypeError):
            continue
        if base not in seen:
            seen.add(base)
            result.append(base)
    return result


async def inspect_site(net, base, hint=None):
    checks = [
        ("Discourse", "/site.json"),
        ("Mastodon", "/api/v2/instance"),
        ("Mastodon", "/api/v1/instance"),
        ("Gitea", "/api/v1/settings/api"),
    ]
    if hint == "Mastodon":
        checks = [checks[1], checks[2]]
    elif hint == "Discourse":
        checks = [checks[0]]
    for engine, path in checks:
        try:
            code, body, final, cut = await net.get(base + path, max_body=512 * 1024)
            if code in (401, 403, 429, 451):
                return None
            if (
                code != 200
                or cut
                or urlsplit(final).hostname != urlsplit(base).hostname
            ):
                continue
            obj = json.loads(body)
            if not isinstance(obj, dict):
                continue
            if engine == "Discourse":
                valid = isinstance(obj.get("categories"), list) and isinstance(
                    obj.get("post_types"), dict
                )
                title = urlsplit(base).hostname
            elif engine == "Gitea":
                valid = all(
                    type(obj.get(key)) is int
                    for key in ("max_response_items", "default_paging_num")
                )
                title = urlsplit(base).hostname
            elif path == "/api/v1/instance":
                valid = (
                    isinstance(obj.get("version"), str)
                    and isinstance(obj.get("uri"), str)
                    and isinstance(obj.get("stats"), dict)
                )
                title = obj.get("title") or urlsplit(base).hostname
            else:
                valid = (
                    isinstance(obj.get("version"), str)
                    and isinstance(obj.get("domain"), str)
                    and isinstance(obj.get("configuration"), dict)
                )
                title = obj.get("title") or obj.get("domain")
            if valid and isinstance(title, str):
                rule = validate_rule(preset(engine, base, title[:100]))
                languages = obj.get("languages", [])
                if isinstance(languages, list):
                    rule.tags = [
                        "ukrainian"
                        if v.lower().replace("_", "-").split("-")[0] == "uk"
                        else v
                        for v in languages[:32]
                        if isinstance(v, str)
                        and 1 <= len(v) <= 64
                        and all(ord(c) >= 32 for c in v)
                    ]
                return rule
        except aiohttp.ClientConnectorError:
            return None
        except (
            ValueError,
            TypeError,
            OSError,
            asyncio.TimeoutError,
            aiohttp.ClientError,
        ):
            continue
    if hint != "Discourse":
        try:
            from .fediverse import inspect_nodeinfo

            return await inspect_nodeinfo(net, base)
        except (
            ValueError,
            TypeError,
            OSError,
            asyncio.TimeoutError,
            aiohttp.ClientError,
        ):
            pass
    return None


async def collect(urls, progress=lambda message: None):
    candidates = bases(urls)
    if len(candidates) > 200:
        raise ValueError("За один проход допускается до 200 сайтов")
    queue = asyncio.Queue()
    for base in candidates:
        queue.put_nowait(base)
    found = []
    checked = 0
    async with Network(concurrency=8, timeout=8) as net:

        async def worker():
            nonlocal checked
            while not queue.empty():
                base = queue.get_nowait()
                rule = await inspect_site(net, base)
                if rule:
                    found.append(rule)
                checked += 1
                progress(
                    f"Сбор сайтов: проверено {checked} из {len(candidates)}, распознано {len(found)}"
                )

        await asyncio.gather(*(worker() for _ in range(min(8, len(candidates)))))
    return {"rules": found, "checked": checked}
