import asyncio
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

from .collector import inspect_site
from .frontier import Frontier
from .customsites import preset, validate_rule, read_sites, write_sites
from .discovery import discover_batch, discovery_state
from .export import atomic_text
from .models import canonical
from .network import Network, safe_url
from .feeds import cached_feed
from .communities import directory_rules
from .harvest_state import (
    HarvestLedger,
    cached_metadata,
    candidates as choose_candidates,
)
from .regions import PRIORITIES, SCOPES, regional_order, matches_scope

MASTODON_DIRECTORY = "https://api.joinmastodon.org/servers"
PEERS = "https://mastodon.social/api/v1/instance/peers"
LIMIT = 1024000


def domain_url(domain):
    if (
        not isinstance(domain, str)
        or len(domain) > 253
        or not re.fullmatch(r"[a-zA-Z0-9.-]+", domain)
    ):
        return None
    try:
        return safe_url("https://" + domain.lower().strip("."))
    except ValueError:
        return None


def mastodon_rules(entries):
    if not isinstance(entries, list):
        raise ValueError("Неподдерживаемый каталог Mastodon")
    rules = []
    for entry in entries[:2000]:
        if not isinstance(entry, dict):
            continue
        base = domain_url(entry.get("domain"))
        if base:
            rule = validate_rule(preset("Mastodon", base, urlsplit(base).hostname))
            languages = entry.get("languages", [])
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
            rules.append(rule)
    return rules


def auto_rules(root):
    result = {}
    for path in sorted((Path(root) / "auto-sites").glob("*.json"))[:512]:
        for rule in read_sites(path):
            result[canonical(rule.profile)] = rule
    from .discovery_store import journal_rules

    result.update(
        (canonical(r.profile), r) for r in journal_rules(Path(root).resolve())
    )
    return result


def save_auto_rules(root, incoming):
    merged = auto_rules(root)
    added = 0
    for rule in incoming:
        key = canonical(rule.profile)
        if key not in merged:
            added += 1
        merged[key] = rule
    if len(merged) > LIMIT:
        raise ValueError("Достигнут предел автосбора: 1 024 000 правил")
    folder = Path(root) / "auto-sites"
    folder.mkdir(exist_ok=True)
    rules = list(merged.values())
    for i in range(0, len(rules), 2000):
        write_sites(folder / f"{i // 2000:04d}.json", rules[i : i + 2000])
    return added


def state(root, region="all"):
    try:
        data = json.loads(
            (
                Path(root)
                / (
                    "harvest-state.json"
                    if region == "all"
                    else f"harvest-state-{region}.json"
                )
            ).read_text(encoding="utf-8")
        )
        if not isinstance(data, dict):
            raise ValueError()
        return {
            k: max(0, min(1000000, int(data.get(k, 0))))
            for k in ("peer_offset", "forum_offset")
        }
    except (OSError, ValueError, TypeError, OverflowError):
        return {"peer_offset": 0, "forum_offset": 0}


async def harvest(
    root,
    catalog,
    progress=lambda message: None,
    receive=lambda event: None,
    budget=60,
    region="all",
    subdomains=False,
    workers=24,
):
    if type(workers) is not int or workers not in (24, 64, 128):
        raise ValueError("Collector connections: 24, 64 or 128")
    ledger = HarvestLedger(root)
    frontier = Frontier(root)
    try:
        return await _harvest(
            root,
            catalog,
            progress,
            receive,
            budget,
            region,
            subdomains,
            ledger,
            workers,
            frontier,
        )
    finally:
        frontier.close()
        ledger.close()


async def _harvest(
    root,
    catalog,
    progress,
    receive,
    budget,
    region,
    subdomains,
    ledger,
    workers,
    frontier,
):
    if type(budget) is not int or not 10 <= budget <= 200:
        raise ValueError("За проход проверяется от 10 до 200 новых доменов")
    if region not in PRIORITIES:
        raise ValueError("Неизвестный приоритет регионов")
    root = Path(root)
    old_state = state(root, region)
    known = {canonical(r.profile) for r in catalog.rules}
    known_tags = {}
    for entry in catalog.rules:
        known_tags.setdefault(canonical(entry.profile), set()).update(entry.tags)
    known_json = {
        canonical(r.profile)
        for r in catalog.rules
        if r.kind in ("json_user", "webfinger")
    }
    adapted = {
        urlsplit(r.profile).hostname
        for r in catalog.rules
        if r.kind in ("json_user", "webfinger")
    }
    rules, warnings = [], []
    directory = discovery_state(root, region)
    checkpoint = directory["next_page"]
    directory_finished = directory.get("finished", False)
    next_page = checkpoint
    checked = 0
    directory_checked = False

    def accept(rule, source):
        key = canonical(rule.profile)
        previous_tags = known_tags.get(key, set())
        rule.tags = sorted(set(rule.tags) | previous_tags)[:32]
        if not matches_scope(rule.profile, rule.tags, region):
            return
        key = canonical(rule.profile)
        is_new = key not in known
        if not is_new and key in known_json and set(rule.tags) <= previous_tags:
            return
        known_tags[key] = set(rule.tags)
        known.add(key)
        known_json.add(key)
        adapted.add(urlsplit(rule.profile).hostname)
        rules.append(rule)
        receive({"rule": rule, "source": source, "new": is_new, "added": len(rules)})
        if is_new:
            ledger.added()

    for cached_rule in cached_metadata(root):
        accept(cached_rule, "Metadata cache")

    try:
        if (
            directory_finished and time.time() - directory["last_run"] < 6 * 3600
        ) or time.time() < directory.get("retry_after", 0):
            batch = {
                "rules": [],
                "next_page": checkpoint,
                "warning": "",
                "finished": directory_finished,
            }
        else:
            batch = await discover_batch(progress, start_page=checkpoint)
            directory_checked = True
        directory_finished = batch.get("finished", False)
        next_page = batch["next_page"]
        for rule in batch["rules"]:
            accept(rule, "Discourse Discover")
        if batch["warning"]:
            warnings.append(batch["warning"])
    except (ValueError, OSError, aiohttp.ClientError, asyncio.TimeoutError):
        warnings.append("Discourse Discover недоступен")
        atomic_text(
            root
            / (
                "discovery-state.json"
                if region == "all"
                else f"discovery-state-{region}.json"
            ),
            json.dumps(directory | {"retry_after": time.time() + 900}),
        )

    peers, all_peers = [], []
    async with Network(concurrency=workers, timeout=3) as net:
        try:
            progress("Reading community directory")
            for rule in await directory_rules(net, root):
                accept(rule, "Community Directory")
        except (
            ValueError,
            TypeError,
            OSError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            warnings.append("Community directory unavailable")
        try:
            progress("Загрузка каталога серверов Mastodon")
            entries = await cached_feed(
                net, root, "mastodon", MASTODON_DIRECTORY, 4 * 1024 * 1024
            )
            for rule in mastodon_rules(entries):
                accept(rule, "Mastodon Directory")
        except (
            ValueError,
            TypeError,
            OSError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            warnings.append("Каталог Mastodon недоступен")
        try:
            progress("Поиск новых доменов в публичном списке связей серверов")
            entries = await cached_feed(net, root, "peers", PEERS, 6 * 1024 * 1024)
            all_peers = [base for domain in entries if (base := domain_url(domain))]
            peers = await asyncio.to_thread(
                lambda: regional_order(all_peers, priority=region)
            )
        except (
            ValueError,
            TypeError,
            OSError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            warnings.append("Список связанных серверов недоступен")

        try:
            from .fediverse import webfinger_rule

            progress("Reading Misskey directory")
            entries = await cached_feed(
                net,
                root,
                "misskey",
                "https://instanceapp.misskey.page/instances.json",
                8 * 1024 * 1024,
            )
            for entry in entries[:10000]:
                if not isinstance(entry, dict):
                    continue
                base = domain_url(entry.get("domain"))
                if base:
                    accept(
                        webfinger_rule(
                            base, "misskey", languages=entry.get("languages", [])
                        ),
                        "JoinMisskey",
                    )
        except (
            ValueError,
            TypeError,
            OSError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            warnings.append("Misskey directory unavailable")
        try:
            from .fediverse import webfinger_rule

            progress("Reading PeerTube directory")
            entries = await cached_feed(
                net,
                root,
                "peertube",
                "https://instances.joinpeertube.org/api/v1/instances/hosts",
                4 * 1024 * 1024,
            )
            for entry in entries[:20000]:
                if not isinstance(entry, dict):
                    continue
                base = domain_url(entry.get("domain"))
                if base:
                    accept(webfinger_rule(base, "peertube"), "PeerTube Index")
        except (
            ValueError,
            TypeError,
            OSError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            warnings.append("PeerTube directory unavailable")
        from .fediverse import PATHS

        seed_engines = {"Mastodon", "Discourse", "Gitea"} | set(PATHS)
        seeds, seen_seeds = [], set()
        for entry in catalog.rules:
            host = urlsplit(entry.profile)
            if (
                entry.engine not in seed_engines
                or not host.hostname
                or "{" in host.netloc
            ):
                continue
            base = "https://" + host.netloc
            if (
                base not in seen_seeds
                and matches_scope(base, entry.tags, region)
                and frontier.due(base)
            ):
                seeds.append((base, entry.engine))
                seen_seeds.add(base)
            if len(seeds) >= 4:
                break
        if seeds:
            progress("Following public site links")
            await asyncio.gather(
                *(frontier.expand(net, base, engine) for base, engine in seeds),
                return_exceptions=True,
            )
        forum_tags = {}
        for rule in catalog.rules:
            parsed = urlsplit(rule.profile)
            if (
                parsed.hostname
                and "{" not in parsed.netloc
                and parsed.hostname not in adapted
            ):
                forum_tags.setdefault("https://" + parsed.netloc, set()).update(
                    rule.tags
                )
        for base in frontier.bases():
            forum_tags.setdefault(base, set())
        forums = regional_order(forum_tags, forum_tags, region)
        pools = [("forum_offset", forums, None), ("peer_offset", peers, "Mastodon")]
        selected, next_state = choose_candidates(
            pools, old_state, adapted, ledger, budget, subdomains, scope=region
        )
        metadata_bases = set()
        if region in SCOPES and region != "all" and len(selected) < budget:
            progress("Classifying server languages")
            metadata_recent = ledger.metadata_recent()
            recent = ledger.recent()
            selected_bases = {base for base, _ in selected}
            known_servers = []
            for entry in catalog.rules:
                host = urlsplit(entry.profile)
                if (
                    entry.engine == "Mastodon"
                    and host.hostname
                    and "{" not in host.netloc
                ):
                    base = "https://" + host.netloc
                    if not any(
                        matches_scope(base, entry.tags, scope)
                        for scope in SCOPES
                        if scope != "all"
                    ):
                        known_servers.append(base)

            pools = [
                (iter(dict.fromkeys(known_servers)), True),
                (iter(all_peers), False),
            ]
            while pools and len(selected) < budget:
                active_pools = []
                for iterator, existing_pool in pools:
                    for base in iterator:
                        if base in selected_bases or base in metadata_recent:
                            continue
                        if not existing_pool and (
                            base in recent or urlsplit(base).hostname in adapted
                        ):
                            continue
                        if any(
                            matches_scope(base, (), scope)
                            for scope in SCOPES
                            if scope != "all"
                        ):
                            continue
                        selected.append((base, "Mastodon"))
                        selected_bases.add(base)
                        metadata_bases.add(base)
                        active_pools.append((iterator, existing_pool))
                        break
                    if len(selected) >= budget:
                        break
                pools = active_pools
        candidates = [base for base, hint in selected]
        hints = dict(selected)
        queue = asyncio.Queue()
        for base in candidates[:budget]:
            queue.put_nowait(base)

        async def worker():
            nonlocal checked
            while not queue.empty():
                base = queue.get_nowait()
                rule = None
                try:
                    rule = await asyncio.wait_for(
                        inspect_site(net, base, hint=hints.get(base)), timeout=8
                    )
                except Exception:
                    pass
                if base in metadata_bases:
                    ledger.record_metadata(base, rule)
                ledger.checked(base, rule)
                checked += 1
                if rule:
                    rule.tags = sorted(set(rule.tags) | set(forum_tags.get(base, ())))[
                        :32
                    ]
                    accept(rule, "Определён " + rule.engine)
                    if matches_scope(rule.profile, rule.tags, region):
                        try:
                            await frontier.expand(net, base, rule.engine)
                        except (
                            ValueError,
                            OSError,
                            aiohttp.ClientError,
                            asyncio.TimeoutError,
                        ):
                            pass
                stats = ledger.stats()
                receive({"progress": True, **stats})
                progress(f"Checked {checked}/{len(candidates)} · added {len(rules)}")

        await asyncio.gather(*(worker() for _ in range(min(workers, len(candidates)))))
    return {
        "rules": rules,
        "state": next_state,
        "next_page": next_page,
        "checked": checked,
        "warnings": warnings,
        "region": region,
        "directory_finished": directory_finished,
        "directory_checked": directory_checked,
    }


def finish_harvest(root, result):
    added = save_auto_rules(root, result.get("rules", []))
    if not result.get("cancelled"):
        region = result.get("region", "all")
        if region not in PRIORITIES:
            raise ValueError("Неизвестный приоритет регионов")
        filename = (
            "harvest-state.json" if region == "all" else f"harvest-state-{region}.json"
        )
        atomic_text(Path(root) / filename, json.dumps(result["state"]))
        if result.get("directory_checked", True):
            atomic_text(
                Path(root)
                / (
                    "discovery-state.json"
                    if region == "all"
                    else f"discovery-state-{region}.json"
                ),
                json.dumps(
                    {
                        "next_page": result["next_page"],
                        "last_run": time.time(),
                        "finished": result.get("directory_finished", False),
                    }
                ),
            )
    return added


async def harvest_loop(
    root,
    catalog,
    progress=lambda message: None,
    receive=lambda event: None,
    budget=60,
    region="all",
    continuous=True,
    pause=5,
    subdomains=False,
    workers=24,
):
    if type(workers) is not int or workers not in (24, 64, 128):
        raise ValueError("Collector connections: 24, 64 or 128")
    from .catalog import Catalog
    from .updater import active_catalogs

    cycles, checked = 0, 0
    from .discovery_store import DiscoveryJournal

    journal = DiscoveryJournal(root)
    observer = receive

    def persist_event(event):
        if "rule" in event:
            journal.append(event["rule"])
        observer(event)

    receive = persist_event
    try:
        return await _harvest_cycles(
            root,
            catalog,
            progress,
            receive,
            budget,
            region,
            continuous,
            pause,
            subdomains,
            workers,
        )
    finally:
        journal.close()


async def _harvest_cycles(
    root,
    catalog,
    progress,
    receive,
    budget,
    region,
    continuous,
    pause,
    subdomains,
    workers,
):
    from .catalog import Catalog
    from .updater import active_catalogs

    cycles, checked = 0, 0
    while True:
        started = time.monotonic()
        options = {"subdomains": True} if subdomains else {}
        if workers != 24:
            options["workers"] = workers
        result = await harvest(
            root, catalog, progress, receive, budget, region, **options
        )
        finish_harvest(root, result)
        elapsed = time.monotonic() - started
        metrics = HarvestLedger(root)
        try:
            stats = metrics.cycle(result["checked"], elapsed)
        finally:
            metrics.close()
        cycles += 1
        checked += result["checked"]
        receive({"cycle": stats["cycles"], **stats, "warnings": result["warnings"]})
        if not continuous:
            return {
                "persisted": True,
                "cycles": cycles,
                "checked": checked,
                "warnings": result["warnings"],
            }
        catalog = await asyncio.to_thread(
            Catalog,
            active_catalogs(Path(root)),
            Path(root) / "custom-sites.json",
            Path(root) / "discovered-forums.json",
        )
        if catalog.errors:
            raise ValueError("Не удалось перечитать сохранённые каталоги")
        delay = (
            max(1, pause) if result["checked"] or result["rules"] else max(30, pause)
        )
        if not result["checked"] and not result["rules"]:
            progress("No fresh candidates; waiting for source updates")
        else:
            progress(f"{result['checked']} / {elapsed:.1f}s · next in {delay}s")
        await asyncio.sleep(delay)
