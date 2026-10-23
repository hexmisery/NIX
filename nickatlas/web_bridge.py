import asyncio
from collections import Counter, deque
from dataclasses import replace
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
import webbrowser

from .catalog import Catalog
from .catalog_state import export_catalog, import_catalog, signature
from .connections import connection_rows
from .customsites import preset, read_sites, rule_data, validate_rule, write_sites
from .engine import scan
from .frontier import Frontier
from .regions import PRIORITIES, normalize_scope
from .export import atomic_text, export_results
from .harvest import auto_rules, harvest_loop, save_auto_rules
from .models import canonical, username
from .network import Network, safe_url, ROUTE
from .proxies import ProxyStore, MAX_IMPORT_BYTES
from .harvest_state import HarvestLedger
from .storage import Store
from .updater import active_catalogs, update


class DesktopAPI:
    def __init__(self, root):
        self._root = Path(root)
        self._window = None
        self._ready = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("Desktop engine did not start")
        if self._startup_error:
            raise RuntimeError("Could not open local data") from self._startup_error

    def _serve(self):
        asyncio.set_event_loop(self._loop)
        self._startup_error = None
        try:
            self._store = Store(self._root / "history.sqlite3")
            self._proxies = ProxyStore(self._root)
            self._frontier = Frontier(self._root)
            self._settings = {
                "language": "en",
                "priority": "all",
                "concurrency": 64,
                "harvest_workers": 64,
                "subdomains": True,
                "include_adult": False,
                "source": "",
                "category": "Все категории",
                "auto_update": True,
                "auto_discover": False,
                "glass_opacity": 8,
            }
            try:
                loaded = json.loads(
                    (self._root / "settings.json").read_text(encoding="utf-8")
                )
                if isinstance(loaded, dict):
                    self._settings.update(
                        {k: loaded[k] for k in self._settings if k in loaded}
                    )
            except (OSError, ValueError):
                pass
            try:
                resume = json.loads(
                    (self._root / "collection-session.json").read_text(encoding="utf-8")
                )
                if not isinstance(resume, dict):
                    raise ValueError()
                self._resume_options = {
                    "resume": resume.get("resume") is True,
                    "budget": resume.get("budget", 200)
                    if resume.get("budget", 200) in (20, 60, 100, 200)
                    else 200,
                    "priority": resume.get("priority", "all")
                    if resume.get("priority", "all") in PRIORITIES
                    else "all",
                }
            except (OSError, ValueError):
                self._resume_options = {
                    "resume": False,
                    "budget": 200,
                    "priority": "all",
                }
            self._resume_options["priority"] = normalize_scope(
                self._resume_options["priority"]
            )
            self._settings["priority"] = normalize_scope(self._settings["priority"])
            if self._settings["priority"] not in PRIORITIES:
                self._settings["priority"] = "all"
            if (
                type(self._settings["concurrency"]) is not int
                or not 2 <= self._settings["concurrency"] <= 128
            ):
                self._settings["concurrency"] = 64
            if type(self._settings["harvest_workers"]) is not int or self._settings[
                "harvest_workers"
            ] not in (24, 64, 128):
                self._settings["harvest_workers"] = 64
            self._events = deque(maxlen=4096)
            self._results = {}
            self._account, self._scan_id, self._total = "", None, 0
            self._task, self._kind = None, ""
            self._cancel = threading.Event()
            self._progress, self._error = "", ""
            self._search_started, self._search_finished = 0, 0
            metrics = HarvestLedger(self._root)
            try:
                stats = metrics.stats()
            finally:
                metrics.close()
            self._discovery_added, self._cycles = stats["added"], stats["cycles"]
            self._checked_domains = stats["checked"]
            self._collection_rate = stats.get("per_minute", 0)
            self._reload()
            self._maintenance_task = self._loop.create_task(self._maintenance())
        except Exception as exc:
            self._startup_error = exc
        self._ready.set()
        if not self._startup_error:
            self._loop.run_forever()
            self._maintenance_task.cancel()
            self._loop.run_until_complete(
                asyncio.gather(self._maintenance_task, return_exceptions=True)
            )
            self._store.close()
            self._frontier.close()
        self._loop.close()

    def _call(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(
            timeout=45
        )

    def _reload(self):
        catalog = Catalog(
            active_catalogs(self._root),
            self._root / "custom-sites.json",
            self._root / "discovered-forums.json",
        )
        if catalog.errors:
            raise ValueError("Could not load catalog")
        self._catalog = catalog
        self._saved_keys = set(auto_rules(self._root))
        self._signature = signature(self._root)

    def _busy(self):
        return self._task is not None and not self._task.done()

    async def _maintenance(self):
        await asyncio.sleep(0.7)
        last_resume_attempt = time.time()
        if self._resume_options["resume"] and not self._busy():
            try:
                self._start_discovery(
                    self._resume_options["budget"],
                    self._resume_options["priority"],
                    True,
                )
            except ValueError:
                self._error = "Select a working proxy first"
        last_update = time.time()
        last_discovery = time.time()
        while True:
            await asyncio.sleep(2)
            if self._busy():
                continue
            try:
                self._proxies.route()
            except ValueError:
                self._error = "Select a working proxy first"
                continue
            now = time.time()
            if self._resume_options["resume"] and (
                not self._error or now - last_resume_attempt >= 60
            ):
                last_resume_attempt = now
                self._start_discovery(
                    self._resume_options["budget"],
                    self._resume_options["priority"],
                    True,
                )
                continue
            if self._settings.get("auto_update") and now - last_update >= 7 * 86400:
                last_update = now

                async def refresh():
                    await update(
                        self._root, lambda x: setattr(self, "_progress", str(x))
                    )
                    self._reload()

                self._launch("update", refresh)
            elif (
                self._settings.get("auto_discover") and now - last_discovery >= 6 * 3600
            ):
                last_discovery = now

                async def discover_once():
                    await harvest_loop(
                        self._root,
                        self._catalog,
                        budget=60,
                        region="all",
                        continuous=False,
                        subdomains=bool(self._settings.get("subdomains")),
                        workers=self._settings["harvest_workers"],
                    )
                    self._reload()

                self._launch("discovery", discover_once)

    def _ensure_idle(self):
        if self._busy():
            raise ValueError("Stop the current job first")

    def _state(self):
        counts = Counter(
            "checking" if r.checking else r.status for r in self._results.values()
        )
        return {
            "busy": self._busy(),
            "job": self._kind if self._busy() else "",
            "account": self._account,
            "total": self._total,
            "checked": sum(not r.checking for r in self._results.values()),
            "counts": dict(counts),
            "sites": len(self._catalog.sites),
            "progress": self._progress,
            "error": self._error,
            "added": self._discovery_added,
            "cycles": self._cycles,
            "search_rate": round(
                sum(not r.checking for r in self._results.values())
                * 60
                / max(
                    1,
                    (self._search_finished or time.monotonic()) - self._search_started,
                )
            )
            if self._search_started
            else 0,
            "per_minute": self._collection_rate,
            "connection": self._proxies.mode,
            "saved_sites": len(self._saved_keys),
            "checked_domains": self._checked_domains,
        }

    def bootstrap(self):
        async def run():
            return {
                "state": self._state(),
                "settings": self._settings,
                "collection": dict(self._resume_options),
                "history": self._history(),
                "version": "0.11.1",
                "sources": sorted({r.source for r in self._catalog.rules}),
                "categories": sorted({r.category for r in self._catalog.rules}),
            }

        return self._call(run())

    def poll(self):
        async def run():
            try:
                if not self._busy() and signature(self._root) != self._signature:
                    self._reload()
            except (OSError, ValueError):
                self._error = "Could not refresh local catalog"
            events = list(self._events)
            self._events.clear()
            return {"state": self._state(), "events": events}

        return self._call(run())

    def _history(self):
        return [
            {"id": x[0], "account": x[1], "started": x[2], "total": x[3], "state": x[4]}
            for x in self._store.history()
        ]

    def history(self):
        async def run():
            return self._history()

        return self._call(run())

    def _launch(self, kind, work):
        self._ensure_idle()
        route = self._proxies.route() if kind != "proxies" else None
        self._kind, self._error, self._progress = kind, "", ""
        self._cancel.clear()

        async def wrapper():
            token = ROUTE.set(route)
            try:
                await work()
            except asyncio.CancelledError:
                self._progress = "Stopped"
            except Exception as exc:
                self._error = "Could not finish job: " + type(exc).__name__
            finally:
                ROUTE.reset(token)
                self._events.append({"type": "done", "job": kind})

        self._task = asyncio.create_task(wrapper())
        return self._state()

    def search(self, account, full=False, priority="all", connections=None):
        async def run():
            self._ensure_idle()
            self._proxies.route()
            account_clean = username(account)
            if type(full) is not bool or priority not in PRIORITIES:
                raise ValueError("Invalid search options")
            if signature(self._root) != self._signature:
                self._reload()
            settings = dict(self._settings)
            if connections is not None:
                if type(connections) is not int or not 2 <= connections <= 128:
                    raise ValueError("Connections: 2–128")
                settings["concurrency"] = connections
            settings["priority"] = priority
            atomic_text(self._root / "settings.json", json.dumps(settings))
            self._settings = settings
            sites = self._catalog.select(
                full,
                settings.get("category", "Все категории"),
                bool(settings.get("include_adult")),
                str(settings.get("source", "")),
                priority,
            )
            self._account, self._results, self._total = account_clean, {}, len(sites)
            self._search_started, self._search_finished = time.monotonic(), 0
            self._scan_id = self._store.begin(account_clean, len(sites))
            self._events.clear()

            def receive(result):
                self._results[result.url] = result
                if not result.checking:
                    self._store.append(self._scan_id, [result])
                    if result.status == "found":
                        self._frontier.enqueue(
                            (
                                link["url"]
                                for link in result.links
                                if isinstance(link, dict)
                                and isinstance(link.get("url"), str)
                            ),
                            result.url,
                        )
                self._events.append({"type": "result", "result": result.data()})

            async def work():
                try:
                    await scan(
                        sites,
                        account_clean,
                        receive,
                        self._cancel,
                        concurrency=max(
                            2, min(128, int(settings.get("concurrency", 64)))
                        ),
                        verify=True,
                        preview=receive,
                    )
                    self._progress = "Stopped" if self._cancel.is_set() else "Finished"
                    self._store.finish(
                        self._scan_id,
                        "cancelled" if self._cancel.is_set() else "complete",
                    )
                except BaseException:
                    self._store.finish(
                        self._scan_id, "cancelled" if self._cancel.is_set() else "error"
                    )
                    raise
                finally:
                    self._search_finished = time.monotonic()
                    pending = [
                        replace(
                            r,
                            checking=False,
                            status="possible",
                            verified=False,
                            reason="Verification interrupted",
                        )
                        for r in self._results.values()
                        if r.checking
                    ]
                    for result in pending:
                        receive(result)

            return self._launch("search", work)

        return self._call(run())

    def stop(self):
        return self._call(self._stop(True))

    async def _stop(self, user_request):
        if user_request:
            self._save_collection(False)
        self._cancel.set()
        if self._busy():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        return self._state()

    def results(self):
        async def run():
            return [
                r.data()
                | {
                    "annotation": dict(
                        zip(
                            ("favorite", "rejected", "note"),
                            self._store.annotation(self._account, r.url),
                        )
                    )
                }
                for r in self._results.values()
            ]

        return self._call(run())

    def new_search(self):
        async def run():
            self._ensure_idle()
            self._results, self._account, self._scan_id, self._total = {}, "", None, 0
            self._search_started, self._search_finished = 0, 0
            self._progress, self._error = "", ""
            self._events.clear()
            return self._state()

        return self._call(run())

    def load_history(self, scan_id):
        async def run():
            self._ensure_idle()
            record = next((x for x in self._history() if x["id"] == scan_id), None)
            if record is None:
                raise ValueError("Unknown search")
            self._scan_id, self._account, self._total = (
                record["id"],
                record["account"],
                record["total"],
            )
            self._search_started, self._search_finished = 0, 0
            rows = self._store.results(scan_id)
            self._results = {
                r.url: replace(r, status="possible", reason="Recheck required")
                if r.status == "found" and not r.verified
                else r
                for r in rows
            }
            self._progress, self._error = "Saved", ""
            return {
                "state": self._state(),
                "results": [r.data() for r in self._results.values()],
            }

        return self._call(run())

    def delete_history(self, scan_id):
        async def run():
            self._ensure_idle()
            if type(scan_id) is not int:
                raise ValueError("Invalid search")
            self._store.delete(scan_id)
            return self._history()

        return self._call(run())

    def annotate(self, url, favorite, rejected, note):
        async def run():
            if (
                url not in self._results
                or type(favorite) is not bool
                or type(rejected) is not bool
                or not isinstance(note, str)
            ):
                raise ValueError("Invalid note")
            self._store.annotate(self._account, url, favorite, rejected, note)
            return True

        return self._call(run())

    def annotation(self, url):
        async def run():
            if url not in self._results:
                raise ValueError("Unknown profile")
            return dict(
                zip(
                    ("favorite", "rejected", "note"),
                    self._store.annotation(self._account, url),
                )
            )

        return self._call(run())

    def links(self):
        async def run():
            return connection_rows(list(self._results.values()))

        return self._call(run())

    def sites(self, query="", offset=0, custom=False):
        async def run():
            if (
                not isinstance(query, str)
                or len(query) > 200
                or type(offset) is not int
                or offset < 0
            ):
                raise ValueError("Invalid filter")
            health = self._store.host_health()
            rows = [
                s
                for s in self._catalog.sites
                if query.casefold()
                in (s.primary.site + s.primary.profile + s.sources).casefold()
                and (not custom or any(r.source == "Свои сайты" for r in s.rules))
            ]
            return {
                "total": len(rows),
                "rows": [
                    rule_data(s.primary)
                    | {
                        "source": s.sources,
                        "health": health.get(
                            urlsplit(s.primary.profile).hostname, "Unchecked"
                        ),
                    }
                    for s in rows[offset : offset + 100]
                ],
            }

        return self._call(run())

    def save_site(self, data):
        async def run():
            self._ensure_idle()
            rule = validate_rule(data)
            current = {
                canonical(r.profile): r
                for r in read_sites(self._root / "custom-sites.json")
            }
            current[canonical(rule.profile)] = rule
            write_sites(self._root / "custom-sites.json", list(current.values()))
            self._reload()
            return self._state()

        return self._call(run())

    def remove_site(self, profile):
        async def run():
            self._ensure_idle()
            rules = read_sites(self._root / "custom-sites.json")
            write_sites(
                self._root / "custom-sites.json",
                [r for r in rules if r.profile != profile],
            )
            self._reload()
            return self._state()

        return self._call(run())

    def site_preset(self, platform, base, name):
        return preset(platform, base, name)

    def _save_collection(self, enabled, budget=None, priority=None):
        data = dict(self._resume_options)
        data["resume"] = bool(enabled)
        if budget is not None:
            data["budget"] = budget
        if priority is not None:
            data["priority"] = priority
        atomic_text(self._root / "collection-session.json", json.dumps(data))
        self._resume_options = data

    def discover(self, budget=200, priority="all", continuous=True, workers=None):
        async def run():
            return self._start_discovery(budget, priority, continuous, workers)

        return self._call(run())

    def _start_discovery(self, budget, priority, continuous, workers=None):
        settings = dict(self._settings)
        workers = self._settings["harvest_workers"] if workers is None else workers
        if type(workers) is not int or workers not in (24, 64, 128):
            raise ValueError("Invalid collector speed")
        if (
            type(budget) is not int
            or budget not in (20, 60, 100, 200)
            or priority not in PRIORITIES
            or type(continuous) is not bool
        ):
            raise ValueError("Invalid discovery options")
        self._ensure_idle()
        self._proxies.route()
        self._settings["harvest_workers"] = workers
        atomic_text(self._root / "settings.json", json.dumps(self._settings))
        self._save_collection(continuous, budget, priority)
        self._collection_rate = 0
        partial, known = {}, {canonical(s.primary.profile) for s in self._catalog.sites}

        def receive(event):
            if "cycle" in event:
                self._cycles = event["cycle"]
                self._collection_rate = event.get("per_minute", 0)
                self._checked_domains = event.get("checked", self._checked_domains)
                self._discovery_added = event.get("added", self._discovery_added)
                partial.clear()
                self._reload()
            elif event.get("progress"):
                self._checked_domains = event["checked"]
            elif "rule" in event:
                rule = event["rule"]
                key = canonical(rule.profile)
                partial[key] = rule
                self._saved_keys.add(key)
                if key not in known:
                    known.add(key)
                    self._discovery_added += 1
                self._events.append(
                    {"type": "discovery", "site": rule.site, "url": rule.profile}
                )

        async def work():
            try:
                await harvest_loop(
                    self._root,
                    self._catalog,
                    lambda x: setattr(self, "_progress", str(x)),
                    receive,
                    budget,
                    priority,
                    continuous,
                    subdomains=bool(settings.get("subdomains", True)),
                    workers=workers,
                )
            finally:
                if partial:
                    save_auto_rules(self._root, list(partial.values()))
                self._reload()
                if not continuous:
                    self._save_collection(False)

        return self._launch("discovery", work)

    def update_catalogs(self):
        async def run():
            async def work():
                await update(self._root, lambda x: setattr(self, "_progress", str(x)))
                self._reload()
                self._progress = "Updated"

            return self._launch("update", work)

        return self._call(run())

    def check_sites(self):
        async def run():
            async def work():
                urls = list(
                    {
                        urlsplit(s.primary.profile)
                        ._replace(path="", query="", fragment="")
                        .geturl()
                        for s in self._catalog.sites
                        if "{" not in urlsplit(s.primary.profile).netloc
                    }
                )
                queue = asyncio.Queue()
                for url in urls:
                    queue.put_nowait(url)
                checked = 0
                async with Network(concurrency=24, timeout=6) as net:

                    async def worker():
                        nonlocal checked
                        while not queue.empty():
                            url = queue.get_nowait()
                            try:
                                code, _, _, _ = await net.get(url, max_body=16384)
                                state = (
                                    "Blocked"
                                    if code in (401, 403, 407, 429, 451, 999)
                                    else "Reachable"
                                    if code
                                    else "Unreachable"
                                )
                            except Exception:
                                state = "Unreachable"
                            self._store.set_health(
                                "host:" + urlsplit(url).hostname, state, ""
                            )
                            checked += 1
                            self._progress = f"{checked:,} / {len(urls):,}"

                    await asyncio.gather(*(worker() for _ in range(min(24, len(urls)))))

            return self._launch("health", work)

        return self._call(run())

    def save_settings(self, settings):
        async def run():
            if not isinstance(settings, dict) or set(settings) - set(self._settings):
                raise ValueError("Invalid settings")
            merged = self._settings | settings
            if (
                merged["language"] not in ("en", "ru")
                or merged["priority"] not in PRIORITIES
            ):
                raise ValueError("Invalid language or region")
            if (
                type(merged["concurrency"]) is not int
                or not 2 <= merged["concurrency"] <= 128
            ):
                raise ValueError("Connections: 2–128")
            if type(merged["harvest_workers"]) is not int or merged[
                "harvest_workers"
            ] not in (24, 64, 128):
                raise ValueError("Invalid collector speed")
            if (
                type(merged["glass_opacity"]) is not int
                or not 0 <= merged["glass_opacity"] <= 65
            ):
                raise ValueError("Invalid transparency")
            if merged["source"] not in {
                "",
                *(r.source for r in self._catalog.rules),
            } or merged["category"] not in {
                "Все категории",
                *(r.category for r in self._catalog.rules),
            }:
                raise ValueError("Invalid source or category")
            for key in ("include_adult", "subdomains", "auto_update", "auto_discover"):
                if type(merged[key]) is not bool:
                    raise ValueError("Invalid option")

            try:
                old = json.loads(
                    (self._root / "settings.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                old = {}
            atomic_text(
                self._root / "settings.json",
                json.dumps((old if isinstance(old, dict) else {}) | merged),
            )
            self._settings = merged
            return merged

        return self._call(run())

    def open_url(self, url):
        safe_url(url)
        webbrowser.open(url)
        return True

    def proxies(self):
        async def run():
            return self._proxies.public()

        return self._call(run())

    def import_proxies(self, text=None):
        if text is None:
            if self._window is None:
                return None
            import webview

            files = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=False,
                file_types=("Proxy lists (*.txt;*.csv)",),
            )
            if not files:
                return None
            path = Path(files[0])
            if path.stat().st_size > MAX_IMPORT_BYTES:
                raise ValueError("Proxy list exceeds 32 MB")
            text = path.read_text(encoding="utf-8-sig")

        async def run():
            self._ensure_idle()
            return self._proxies.add(text) | {"data": self._proxies.public()}

        return self._call(run())

    def configure_proxy(self, mode, selected=""):
        async def run():
            self._ensure_idle()
            self._proxies.configure(mode, selected)
            if self._error == "Select a working proxy first":
                self._error = ""
            return self._proxies.public()

        return self._call(run())

    def remove_proxy(self, key):
        async def run():
            self._ensure_idle()
            self._proxies.remove(key)
            return self._proxies.public()

        return self._call(run())

    def check_proxies(self):
        async def run():
            async def work():
                checked = 0

                def receive(row):
                    nonlocal checked
                    checked += 1
                    self._events.append({"type": "proxy", "row": row})
                    self._progress = f"{checked} / {len(self._proxies.rows)}"

                await self._proxies.check(receive)

            return self._launch("proxies", work)

        return self._call(run())

    def transfer(self, action):
        import webview

        if (
            action not in ("import", "catalog", "json", "csv", "html")
            or not self._window
        ):
            raise ValueError("Invalid export")
        suffix = "zip" if action in ("import", "catalog") else action
        selected = self._window.create_file_dialog(
            webview.FileDialog.OPEN if action == "import" else webview.FileDialog.SAVE,
            save_filename="NIX-catalog.zip"
            if suffix == "zip"
            else "NIX-results." + suffix,
            file_types=(f"NIX (*.{suffix})",),
        )
        if not selected:
            return None
        path = Path(selected[0])

        async def run():
            self._ensure_idle()
            if action == "import":
                count = import_catalog(self._root, path)
                self._reload()
                return {"count": count}
            if action == "catalog":
                return {"count": export_catalog(self._root, path)}
            if path.suffix.lower() != "." + suffix:
                path = path.with_suffix("." + suffix)
            export_results(path, self._account, list(self._results.values()))
            return {"count": len(self._results)}

        return self._call(run())

    def window_control(self, action):
        if self._window:
            if action == "minimize":
                self._window.minimize()
            elif action == "maximize":
                self._window.toggle_fullscreen()
            elif action == "close":
                self._window.destroy()
        return True

    def _shutdown(self):
        async def close():
            self._maintenance_task.cancel()
            await asyncio.gather(self._maintenance_task, return_exceptions=True)
            await self._stop(False)

        try:
            self._call(close())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=10)
