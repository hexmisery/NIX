from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
import asyncio
import aiohttp

from .catalog import SOURCES, parse
from .export import atomic_text
from .network import Network

MAX_CATALOG = 20 * 1024 * 1024


def active_catalogs(root: Path):
    try:
        record = json.loads((root / "catalog-current.json").read_text(encoding="utf-8"))
        name = record["generation"]
        if (
            not isinstance(name, str)
            or len(name) != 32
            or any(c not in "0123456789abcdef" for c in name)
        ):
            return None
        p = root / "catalogs" / name
        return p if p.is_dir() else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


async def update(root: Path, progress=lambda text: None):
    generation = uuid.uuid4().hex
    staging = root / "catalogs" / generation
    staging.mkdir(parents=True, exist_ok=False)
    manifest = {
        "generation": generation,
        "updated": datetime.now(timezone.utc).isoformat(),
        "sources": {},
    }
    async with Network(concurrency=3, timeout=30) as net:
        for name, (repo, branch, relative) in SOURCES.items():
            progress("Обновление: " + name)
            code, text, _, cut = await net.get(
                f"https://api.github.com/repos/{repo}/commits/{branch}",
                max_body=2 * 1024 * 1024,
            )
            if code != 200 or cut:
                raise ValueError(
                    f"{name}: GitHub не вернул версию каталога (HTTP {code})"
                )
            commit = json.loads(text)["sha"]
            if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
                raise ValueError("Некорректная версия источника")
            url = f"https://raw.githubusercontent.com/{repo}/{commit}/{relative}"
            code, text, _, cut = await net.get(url, max_body=MAX_CATALOG)
            if code != 200 or cut:
                raise ValueError(f"{name}: каталог не загружен полностью (HTTP {code})")
            data = json.loads(text)
            rules = parse(name, data)
            if len(rules) < 50:
                raise ValueError(f"{name}: подозрительно маленький каталог")
            atomic_text(staging / (name + ".json"), text)
            manifest["sources"][name] = {
                "commit": commit,
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "rules": len(rules),
            }
    from .discovery import discover_forums
    from .customsites import write_sites, read_sites
    from .models import canonical
    from .paths import assets

    try:
        forums = await discover_forums(progress)
        if not forums:
            raise ValueError("Каталог форумов пуст")
        previous_dir = active_catalogs(root)
        previous_path = (
            previous_dir / "forums.json"
            if previous_dir and (previous_dir / "forums.json").exists()
            else assets() / "catalogs/forums.json"
        )
        merged = {canonical(r.profile): r for r in read_sites(previous_path)}
        merged.update({canonical(r.profile): r for r in forums})
        forums = list(merged.values())
        write_sites(staging / "forums.json", forums)
        manifest["forums"] = {
            "source": "https://discover.discourse.com",
            "entries": len(forums),
            "sha256": hashlib.sha256(
                (staging / "forums.json").read_bytes()
            ).hexdigest(),
        }
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        asyncio.TimeoutError,
        aiohttp.ClientError,
    ):
        previous = active_catalogs(root)
        previous = (
            previous / "forums.json"
            if previous and (previous / "forums.json").exists()
            else assets() / "catalogs/forums.json"
        )
        if previous.exists():
            atomic_text(staging / "forums.json", previous.read_text(encoding="utf-8"))
        manifest["forum_refresh"] = (
            "Previous forum list retained: directory unavailable"
        )
        progress("Каталог форумов недоступен; сохранена предыдущая версия")
    atomic_text(
        staging / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    current = root / "catalog-current.json"
    if current.exists():
        atomic_text(root / "catalog-previous.json", current.read_text(encoding="utf-8"))
    atomic_text(current, json.dumps(manifest))
    return manifest


def rollback(root: Path):
    previous = root / "catalog-previous.json"
    if not previous.exists():
        raise ValueError("Предыдущей версии каталога ещё нет")
    old = json.loads(previous.read_text(encoding="utf-8"))
    probe = root / "catalogs" / str(old.get("generation", ""))
    if (
        len(str(old.get("generation", ""))) != 32
        or any(c not in "0123456789abcdef" for c in str(old.get("generation", "")))
        or not probe.is_dir()
    ):
        raise ValueError("Предыдущая версия недоступна")
    current = root / "catalog-current.json"
    now = current.read_text(encoding="utf-8")
    atomic_text(current, json.dumps(old))
    atomic_text(previous, now)
