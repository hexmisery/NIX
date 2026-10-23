import json
from pathlib import Path
import sqlite3

from .customsites import rule_data, validate_rule
from .models import canonical


class DiscoveryJournal:
    def __init__(self, root):
        path = Path(root) / "discovery-journal.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sites(profile TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        self.db.commit()

    def append(self, rule):
        data = rule_data(rule)
        validate_rule(data)
        with self.db:
            self.db.execute(
                "INSERT INTO sites VALUES(?,?) ON CONFLICT(profile) DO UPDATE SET data=excluded.data",
                (canonical(rule.profile), json.dumps(data, ensure_ascii=False)),
            )

    def close(self):
        self.db.close()


def journal_rules(root):
    path = Path(root) / "discovery-journal.sqlite3"
    if not path.exists():
        return []
    if path.is_symlink() or path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("Invalid discovery journal")
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            count = db.execute("SELECT count(*) FROM sites").fetchone()[0]
            if count > 1024000:
                raise ValueError("Discovery journal limit exceeded")
            return [
                validate_rule(json.loads(row[0]))
                for row in db.execute("SELECT data FROM sites")
            ]
        finally:
            db.close()
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        raise ValueError("Could not read discovery journal") from exc
