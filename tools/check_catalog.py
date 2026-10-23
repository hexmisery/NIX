import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nickatlas.catalog import Catalog
from nickatlas.network import Network, safe_url


def origins(catalog):
    fixed, dynamic, invalid = set(), set(), set()
    for site in catalog.sites:
        parsed = urlsplit(site.primary.profile)
        if "{" in parsed.netloc:
            dynamic.add(parsed.netloc)
            continue
        origin = f"{parsed.scheme}://{parsed.netloc}/"
        try:
            fixed.add(safe_url(origin))
        except ValueError:
            invalid.add(origin)
    return sorted(fixed), sorted(dynamic), sorted(invalid)


def host(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


async def check(net, origin):
    try:
        code, _, final, cut = await net.get(origin, max_body=65536)
        if code in (401, 403, 407, 429, 451, 999):
            state = "restricted"
        elif 200 <= code < 400:
            state = "responding" if host(final) == host(origin) else "redirected"
        else:
            state = "http_error"
        parsed = urlsplit(final)
        return {
            "origin": origin,
            "state": state,
            "http": code,
            "final_origin": f"{parsed.scheme}://{parsed.netloc}/",
        }
    except ValueError:
        return {"origin": origin, "state": "rejected", "http": 0}
    except (OSError, asyncio.TimeoutError, aiohttp.ClientError) as exc:
        return {
            "origin": origin,
            "state": "unreachable",
            "http": 0,
            "reason": type(exc).__name__,
        }


async def run(options):
    catalog = Catalog()
    if catalog.errors:
        raise ValueError("Catalog could not be loaded")
    targets, dynamic, invalid = origins(catalog)
    if options.limit:
        targets = targets[: options.limit]
    folder = options.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "availability.jsonl"
    target_set = set(targets)
    previous = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("origin") in target_set:
                previous[row["origin"]] = row
    counts = Counter(row["state"] for row in previous.values())
    queue = asyncio.Queue()
    for origin in targets:
        if origin not in previous:
            queue.put_nowait(origin)
    started = time.monotonic()
    checked = len(previous)

    def summary():
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "scope": "site availability; profile detection is not verified",
            "catalog_templates": len(catalog.sites),
            "target_origins": len(targets),
            "checked_origins": checked,
            "username_dependent_hosts_skipped": len(dynamic),
            "invalid_origins_skipped": len(invalid),
            "states": dict(counts),
            "complete": checked == len(targets),
            "elapsed_this_run_seconds": round(time.monotonic() - started, 1),
        }

    with path.open("a", encoding="utf-8") as output:
        async with Network(concurrency=64, timeout=6) as net:

            async def worker():
                nonlocal checked
                while True:
                    try:
                        origin = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    row = await check(net, origin)
                    output.write(json.dumps(row, ensure_ascii=True) + "\n")
                    output.flush()
                    counts[row["state"]] += 1
                    checked += 1
                    if checked % 250 == 0:
                        report = summary()
                        (folder / "summary.json").write_text(
                            json.dumps(report, indent=2), encoding="utf-8"
                        )
                        print(json.dumps(report), flush=True)

            await asyncio.gather(*(worker() for _ in range(64)))
    report = summary()
    (folder / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    options = parser.parse_args()
    if not 0 <= options.limit <= 100000:
        parser.error("limit must be between 0 and 100000")
    try:
        asyncio.run(run(options))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Catalog check failed: {type(exc).__name__}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Stopped; run the same command to resume.\n")


if __name__ == "__main__":
    main()
