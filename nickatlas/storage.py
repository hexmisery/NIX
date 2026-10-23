import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .models import Result


class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS scans(
                id INTEGER PRIMARY KEY, username TEXT NOT NULL, started TEXT NOT NULL,
                total INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'running'
            );
            CREATE TABLE IF NOT EXISTS results(
                scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
                url TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(scan_id, url)
            );
            CREATE TABLE IF NOT EXISTS annotations(
                username TEXT NOT NULL, url TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
                rejected INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(username, url)
            );
            CREATE TABLE IF NOT EXISTS health(
                key TEXT PRIMARY KEY, checked TEXT NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL
            );
        """)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("UPDATE scans SET state='interrupted' WHERE state='running'")
        self.db.commit()

    def begin(self, account, total):
        c = self.db.execute(
            "INSERT INTO scans(username,started,total) VALUES(?,?,?)",
            (account, datetime.now(timezone.utc).isoformat(), total),
        )
        self.db.commit()
        return c.lastrowid

    def append(self, scan_id, results):
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO results VALUES(?,?,?)",
                [
                    (scan_id, r.url, json.dumps(r.data(), ensure_ascii=False))
                    for r in results
                ],
            )
            for r in results:
                host = urlsplit(r.url).hostname
                if not host:
                    continue
                status = (
                    "Blocked"
                    if r.http in (401, 403, 407, 429, 451, 999)
                    else "Reachable"
                    if r.http
                    else "Unreachable"
                )
                self.db.execute(
                    "INSERT OR REPLACE INTO health VALUES(?,?,?,?)",
                    ("host:" + host, r.checked, status, str(r.http)),
                )

    def host_health(self):
        return {
            key[5:]: state
            for key, state in self.db.execute(
                "SELECT key,state FROM health WHERE substr(key,1,5)='host:'"
            )
        }

    def finish(self, scan_id, state):
        with self.db:
            self.db.execute("UPDATE scans SET state=? WHERE id=?", (state, scan_id))

    def history(self):
        return self.db.execute(
            "SELECT id,username,started,total,state FROM scans ORDER BY id DESC LIMIT 100"
        ).fetchall()

    def results(self, scan_id):
        rows = [
            Result(**json.loads(x[0]))
            for x in self.db.execute(
                "SELECT data FROM results WHERE scan_id=? ORDER BY rowid", (scan_id,)
            )
        ]
        for row in rows:
            if row.checking:
                row.checking, row.verified, row.status, row.reason = (
                    False,
                    False,
                    "possible",
                    "Verification interrupted",
                )
        return rows

    def annotation(self, account, url):
        row = self.db.execute(
            "SELECT favorite,rejected,note FROM annotations WHERE username=? AND url=?",
            (account, url),
        ).fetchone()
        return row or (0, 0, "")

    def annotate(self, account, url, favorite, rejected, note):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO annotations VALUES(?,?,?,?,?)",
                (account, url, int(favorite), int(rejected), note[:10000]),
            )

    def set_health(self, key, state, reason):
        with self.db:
            self.db.execute(
                "INSERT INTO health VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET checked=excluded.checked, reason=excluded.reason, state=CASE WHEN excluded.state='unknown' AND health.state='quarantine' THEN health.state ELSE excluded.state END",
                (key, datetime.now(timezone.utc).isoformat(), state, reason),
            )

    def quarantined(self):
        return {
            x[0]
            for x in self.db.execute("SELECT key FROM health WHERE state='quarantine'")
        }

    def delete(self, scan_id):
        with self.db:
            self.db.execute("DELETE FROM scans WHERE id=?", (scan_id,))

    def close(self):
        self.db.close()
