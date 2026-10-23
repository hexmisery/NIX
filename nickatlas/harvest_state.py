from pathlib import Path
import sqlite3
import json
import time
from urllib.parse import urlsplit


class HarvestLedger:
    def __init__(self, root):
        self.db = sqlite3.connect(Path(root) / "collector-state.sqlite3", timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS checks(base TEXT PRIMARY KEY, checked REAL NOT NULL, retry REAL NOT NULL, engine TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS check_revisions(base TEXT PRIMARY KEY, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS pending(base TEXT PRIMARY KEY, hint TEXT NOT NULL, added REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS totals(name TEXT PRIMARY KEY, value INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS metadata(base TEXT PRIMARY KEY, data TEXT NOT NULL, checked REAL NOT NULL, retry REAL NOT NULL);
        """)

    def recent(self):
        return {
            row[0]
            for row in self.db.execute(
                "SELECT c.base FROM checks c LEFT JOIN check_revisions r ON r.base=c.base WHERE c.retry>? AND (c.engine<>'' OR COALESCE(r.revision,1)>=2)",
                (time.time(),),
            )
        }

    def increment(self, name, count=1):
        self.db.execute(
            "INSERT INTO totals VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value",
            (name, count),
        )

    def checked(self, base, rule):
        now = time.time()
        with self.db:
            self.db.execute(
                "INSERT INTO checks VALUES(?,?,?,?) ON CONFLICT(base) DO UPDATE SET checked=excluded.checked,retry=excluded.retry,engine=excluded.engine",
                (
                    base,
                    now,
                    now + (7 * 86400 if rule else 86400),
                    rule.engine if rule else "",
                ),
            )
            self.db.execute(
                "INSERT INTO check_revisions VALUES(?,2) ON CONFLICT(base) DO UPDATE SET revision=2",
                (base,),
            )
            self.db.execute("DELETE FROM pending WHERE base=?", (base,))
            self.increment("checked")

    def added(self):
        with self.db:
            self.increment("added")

    def cycle(self, checked=None, elapsed=None):
        with self.db:
            self.increment("cycles")
            if checked is not None and elapsed is not None:
                self.db.executemany(
                    "INSERT INTO totals VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                    [
                        ("last_batch_size", int(checked)),
                        ("last_batch_ms", round(elapsed * 1000)),
                    ],
                )
        return self.stats()

    def stats(self):
        values = dict(self.db.execute("SELECT name,value FROM totals"))
        return (
            (
                {
                    "per_minute": round(
                        values.get("last_batch_size", 0)
                        * 60000
                        / values["last_batch_ms"]
                    )
                }
                if values.get("last_batch_ms")
                else {}
            )
            | {key: values.get(key, 0) for key in ("checked", "added", "cycles")}
            | {"queued": self.db.execute("SELECT COUNT(*) FROM pending").fetchone()[0]}
        )

    def enqueue_subdomains(self, bases, recent, adapted):
        if self.db.execute("SELECT COUNT(*) FROM pending").fetchone()[0] >= 50000:
            return
        rows = []
        for base, hint in bases:
            if hint == "Mastodon":
                continue
            host = urlsplit(base).hostname
            if not host or host.split(".")[0] in (
                "forum",
                "forums",
                "community",
                "social",
            ):
                continue
            for prefix in ("forum", "community", "social"):
                candidate = f"https://{prefix}.{host}"
                if (
                    candidate not in recent
                    and urlsplit(candidate).hostname not in adapted
                ):
                    rows.append(
                        (
                            candidate,
                            "Mastodon" if prefix == "social" else "Discourse",
                            time.time(),
                        )
                    )
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO pending VALUES(?,?,?)", rows[:1000]
            )

    def pending(self, limit, recent, adapted, scope="all"):
        from .regions import matches_scope

        if limit <= 0:
            return []
        rows = self.db.execute("SELECT base,hint FROM pending ORDER BY added,base")
        selected = []
        for base, hint in rows:
            if (
                base not in recent
                and urlsplit(base).hostname not in adapted
                and matches_scope(base, (), scope)
            ):
                selected.append((base, hint))
                if len(selected) >= limit:
                    break
        return selected

    def metadata_recent(self):
        return {
            row[0]
            for row in self.db.execute(
                "SELECT base FROM metadata WHERE retry>?", (time.time(),)
            )
        }

    def record_metadata(self, base, rule):
        from .customsites import rule_data

        now = time.time()
        data = json.dumps(rule_data(rule), ensure_ascii=True) if rule else ""
        with self.db:
            self.db.execute(
                "INSERT INTO metadata VALUES(?,?,?,?) ON CONFLICT(base) DO UPDATE SET data=excluded.data,checked=excluded.checked,retry=excluded.retry",
                (base, data, now, now + (6 * 3600 if rule else 3600)),
            )

    def close(self):
        self.db.close()


def candidates(pools, offsets, adapted, ledger, budget, subdomains, scope="all"):
    recent = ledger.recent()
    roots, seen, state = [], set(), dict(offsets)
    limit = budget - max(1, budget // 10) if subdomains else budget
    positions = {}
    remaining = {}
    for name, pool, hint in pools:
        positions[name] = offsets.get(name, 0) % len(pool) if pool else 0
        remaining[name] = len(pool)
    while len(roots) < limit and any(remaining.values()):
        for name, pool, hint in pools:
            while remaining[name]:
                position = positions[name]
                base = pool[position]
                positions[name] = (position + 1) % len(pool)
                remaining[name] -= 1
                if base in recent or base in seen or urlsplit(base).hostname in adapted:
                    continue
                seen.add(base)
                roots.append((base, hint))
                break
            if len(roots) >= limit:
                break
    for name, _, _ in pools:
        state[name] = positions[name]
    if subdomains:
        ledger.enqueue_subdomains(roots, recent, adapted)
    extra = (
        ledger.pending(budget - len(roots), recent, adapted, scope)
        if subdomains
        else []
    )
    return roots + extra, state


def cached_metadata(root):
    from .customsites import validate_rule

    path = Path(root) / "collector-state.sqlite3"
    if not path.exists():
        return []
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
        ).fetchone():
            return []
        rules = []
        for (data,) in db.execute(
            "SELECT data FROM metadata WHERE data<>'' AND retry>? LIMIT 100000",
            (time.time(),),
        ):
            try:
                rules.append(validate_rule(json.loads(data)))
            except (ValueError, TypeError):
                continue
        return rules
    finally:
        db.close()
