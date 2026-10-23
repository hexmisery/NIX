import json
import time
from pathlib import Path

import aiohttp

from .export import atomic_text

FEED_NAMES = {"mastodon", "peers", "misskey", "peertube"}


async def cached_feed(net, root, name, url, max_body, ttl=6 * 3600):
    if name not in FEED_NAMES:
        raise ValueError("Неизвестный каталог")
    path = Path(root) / "feed-cache" / (name + ".json")
    old = None
    try:
        if path.stat().st_size <= max_body * 2:
            old = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(old, dict) and isinstance(old.get("data"), list):
                age = time.time() - float(old["updated"])
                if (
                    0 <= age < ttl
                    and (
                        not old.get("failed") or time.time() < old.get("retry_after", 0)
                    )
                    and (
                        name != "mastodon"
                        or old.get("schema") == 2
                        or time.time() < old.get("retry_after", 0)
                    )
                ):
                    return old["data"]
    except (OSError, ValueError, TypeError, KeyError):
        old = None
    try:
        code, body, _, cut = await net.get(url, max_body=max_body)
        if code != 200 or cut:
            raise ValueError("Источник не вернул полный каталог")
        data = json.loads(body)
        if name == "misskey" and isinstance(data, dict):
            data = data.get("instancesInfos")
        if name == "peertube" and isinstance(data, dict):
            data = data.get("data")
        if not isinstance(data, list):
            raise ValueError("Неподдерживаемый формат каталога")
    except (OSError, ValueError, TypeError, aiohttp.ClientError):
        if isinstance(old, dict) and isinstance(old.get("data"), list):
            atomic_text(
                path,
                json.dumps(old | {"retry_after": time.time() + 900}, ensure_ascii=True),
            )
            return old["data"]
        path.parent.mkdir(exist_ok=True)
        atomic_text(
            path,
            json.dumps(
                {
                    "schema": 2,
                    "updated": time.time(),
                    "retry_after": time.time() + 900,
                    "failed": True,
                    "data": [],
                }
            ),
        )
        raise
    if name == "mastodon":
        data = [
            {
                "domain": item.get("domain"),
                "languages": [
                    v
                    for v in item.get("languages", [])[:32]
                    if isinstance(v, str) and len(v) <= 64
                ],
            }
            for item in data[:2000]
            if isinstance(item, dict) and isinstance(item.get("languages", []), list)
        ]
    elif name == "peertube":
        data = [{"domain": r.get("host")} for r in data[:20000] if isinstance(r, dict)]
    elif name == "misskey":
        data = [
            {"domain": r.get("url"), "languages": r.get("langs", [])}
            for r in data[:10000]
            if isinstance(r, dict) and isinstance(r.get("langs", []), list)
        ]
    else:
        data = [
            item for item in data[:200000] if isinstance(item, str) and len(item) <= 253
        ]
    path.parent.mkdir(exist_ok=True)
    atomic_text(
        path,
        json.dumps(
            {"schema": 2, "updated": time.time(), "data": data}, ensure_ascii=True
        ),
    )
    return data
