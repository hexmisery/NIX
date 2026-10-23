import json
import asyncio
import aiohttp
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from .connections import ProfileLinks, clean_link
from .network import safe_url


class Frontier:
    def __init__(self, root):
        self.db = sqlite3.connect(Path(root) / "collector-state.sqlite3", timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS link_domains(base TEXT PRIMARY KEY, origin TEXT NOT NULL, added REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS link_seeds(base TEXT PRIMARY KEY, retry REAL NOT NULL);
        """)

    def enqueue(self, urls, origin):
        source = clean_link(origin, origin)
        if not source:
            return 0
        source_host = urlsplit(source).hostname
        source = urlunsplit(
            (urlsplit(source).scheme, urlsplit(source).netloc, "/", "", "")
        )
        room = max(
            0,
            100000 - self.db.execute("SELECT COUNT(*) FROM link_domains").fetchone()[0],
        )
        rows = {}
        for value in urls:
            if len(rows) >= min(room, 2000):
                break
            link = clean_link(value, origin)
            if not link:
                continue
            p = urlsplit(link)
            if p.hostname == source_host:
                continue
            base = urlunsplit((p.scheme, p.netloc, "", "", ""))
            rows[base] = (base, source, time.time())
        before = self.db.total_changes
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO link_domains VALUES(?,?,?)", rows.values()
            )
        return self.db.total_changes - before

    def bases(self):
        return [
            r[0]
            for r in self.db.execute(
                "SELECT base FROM link_domains ORDER BY added,base LIMIT 100000"
            )
        ]

    def due(self, base):
        retry = self.db.execute(
            "SELECT retry FROM link_seeds WHERE base=?", (base,)
        ).fetchone()
        return not retry or retry[0] <= time.time()

    async def expand(self, net, base, engine, homepage=True):
        safe_url(base)
        retry = self.db.execute(
            "SELECT retry FROM link_seeds WHERE base=?", (base,)
        ).fetchone()
        if retry and retry[0] > time.time():
            return 0
        with self.db:
            self.db.execute(
                "INSERT INTO link_seeds VALUES(?,?) ON CONFLICT(base) DO UPDATE SET retry=excluded.retry",
                (base, time.time() + 6 * 3600),
            )
        added = 0
        if engine == "Mastodon":
            try:
                code, body, final, cut = await net.get(
                    base + "/api/v1/instance/peers", max_body=1024 * 1024
                )
                if (
                    code == 200
                    and not cut
                    and urlsplit(final).hostname == urlsplit(base).hostname
                ):
                    peers = json.loads(body)
                    if isinstance(peers, list):
                        urls = [
                            "https://" + v
                            for v in peers[:20000]
                            if isinstance(v, str)
                            and len(v) <= 253
                            and re.fullmatch(r"[a-zA-Z0-9.-]+", v)
                        ]
                        added += self.enqueue(urls, base)
            except (
                ValueError,
                TypeError,
                OSError,
                asyncio.TimeoutError,
                aiohttp.ClientError,
            ):
                pass
        if homepage:
            try:
                code, body, final, cut = await net.get(base, max_body=262144)
                if code == 200 and urlsplit(final).hostname == urlsplit(base).hostname:
                    parser = ProfileLinks(all_links=True)
                    parser.feed(body)
                    added += self.enqueue((url for url, _ in parser.links), base)
            except (
                ValueError,
                TypeError,
                OSError,
                AssertionError,
                asyncio.TimeoutError,
                aiohttp.ClientError,
            ):
                pass
        return added

    def close(self):
        self.db.close()
