import asyncio
import json
import time
from pathlib import Path

import aiohttp

from .customsites import preset, validate_rule, write_sites, read_sites
from .export import atomic_text
from .models import canonical
from .network import Network
from .paths import assets

DIRECTORY = "https://discover.discourse.com"
MAX_PAGE = 200
BATCH_PAGES = 20
INTERVAL = 6 * 3600


def discovery_state(root, scope="all"):
    from .regions import PRIORITIES

    if scope not in PRIORITIES:
        raise ValueError("Invalid collection region")
    filename = (
        "discovery-state.json" if scope == "all" else f"discovery-state-{scope}.json"
    )
    try:
        data = json.loads((Path(root) / filename).read_text(encoding="utf-8"))
        page = data.get("next_page", 0)
        last = data.get("last_run", 0)
        if type(page) is not int or not 0 <= page < MAX_PAGE:
            raise ValueError("Некорректная страница")
        if type(last) not in (int, float) or not 0 <= last <= time.time() + 60:
            raise ValueError("Некорректное время")
        return {
            "next_page": page,
            "last_run": last,
            "finished": bool(data.get("finished", False)),
            "retry_after": max(
                0, min(time.time() + 900, float(data.get("retry_after", 0)))
            ),
        }
    except (OSError, ValueError, TypeError, AttributeError):
        try:
            manifest = json.loads(
                (assets() / "catalogs/manifest.json").read_text(encoding="utf-8")
            )
            page = manifest.get("forums", {}).get("next_page", 0)
            if type(page) is not int or not 0 <= page < MAX_PAGE:
                page = 0
        except (OSError, ValueError, TypeError, AttributeError):
            page = 0
        return {"next_page": page, "last_run": 0}


def page_rules(topics):
    rules = []
    for topic in topics[:40]:
        if not isinstance(topic, dict):
            continue
        base = topic.get("featured_link")
        title = topic.get("title", "")
        if not base or not isinstance(title, str):
            continue
        try:
            rule = validate_rule(preset("Discourse", base, title[:100]))
        except (ValueError, TypeError):
            continue
        rule.source = "Discourse Discover"
        rules.append(rule)
    return rules


async def discover_batch(
    progress=lambda message: None, start_page=0, pages=BATCH_PAGES
):
    if type(start_page) is not int or not 0 <= start_page < MAX_PAGE:
        raise ValueError("Некорректная страница каталога")
    if type(pages) is not int or not 1 <= pages <= BATCH_PAGES:
        raise ValueError("За один проход допускается от 1 до 20 страниц")
    rules, seen, signatures = [], set(), set()
    next_page, finished, warning, loaded = start_page, False, "", 0
    async with Network(concurrency=2, timeout=20) as net:
        for page in range(start_page, min(MAX_PAGE, start_page + pages)):
            progress(f"Discourse: page {page + 1} · {len(rules)} forums")
            url = DIRECTORY + "/latest.json" + (f"?page={page}" if page else "")
            try:
                code, body, _, cut = await net.get(url, max_body=2 * 1024 * 1024)
                if code != 200 or cut:
                    raise ValueError(f"Каталог форумов недоступен: HTTP {code}")
                data = json.loads(body)
                topics = data.get("topic_list", {}).get("topics")
                if not isinstance(topics, list):
                    raise ValueError("Неподдерживаемый формат каталога форумов")
            except (
                ValueError,
                TypeError,
                AttributeError,
                OSError,
                asyncio.TimeoutError,
                aiohttp.ClientError,
            ) as exc:
                if not loaded:
                    raise ValueError(
                        "Каталог форумов недоступен. Повтори позже."
                    ) from exc
                warning = (
                    "Источник недоступен; следующий проход продолжится с этой страницы."
                )
                break
            loaded += 1
            signature = tuple(str(t.get("id")) for t in topics if isinstance(t, dict))
            if not topics or signature and signature in signatures:
                finished, next_page = True, 0
                break
            signatures.add(signature)
            for rule in page_rules(topics):
                key = canonical(rule.profile)
                if key not in seen:
                    seen.add(key)
                    rules.append(rule)
            next_page = page + 1
            if next_page >= MAX_PAGE:
                finished, next_page = True, 0
    return {
        "rules": rules,
        "next_page": next_page,
        "finished": finished,
        "pages": loaded,
        "warning": warning,
    }


async def discover_forums(progress=lambda message: None, pages=BATCH_PAGES):
    return (await discover_batch(progress, pages=pages))["rules"]


def merge_discovery(path: Path, incoming):
    existing = read_sites(path)
    all_rules = {canonical(r.profile): r for r in existing}
    added = 0
    for rule in incoming:
        key = canonical(rule.profile)
        if key not in all_rules:
            added += 1
        all_rules[key] = rule
    write_sites(path, list(all_rules.values()))
    return added


def save_batch(root, data):
    root = Path(root)
    added = merge_discovery(root / "discovered-forums.json", data["rules"])
    atomic_text(
        root / "discovery-state.json",
        json.dumps({"next_page": data["next_page"], "last_run": time.time()}),
    )
    return added
