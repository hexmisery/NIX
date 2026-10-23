import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

from .customsites import MAX_FILE, decode_document, read_sites, rule_data, write_sites
from .models import canonical

MAX_ARCHIVE = 256 * 1024 * 1024
LOCAL_NAME = re.compile(
    r"(?:custom-sites\.json|discovered-forums\.json|auto-sites/[0-9]{4}\.json)\Z"
)


def local_files(root):
    root = Path(root)
    paths = [root / "custom-sites.json", root / "discovered-forums.json"]
    paths.extend(sorted((root / "auto-sites").glob("[0-9][0-9][0-9][0-9].json"))[:512])
    return [p for p in paths if p.is_file() and not p.is_symlink()]


def signature(root):
    root = Path(root)
    paths = local_files(root) + [
        root / "catalog-current.json",
        root / "discovery-journal.sqlite3",
        root / "discovery-journal.sqlite3-wal",
    ]
    return tuple(
        (str(p.relative_to(root)), p.stat().st_mtime_ns, p.stat().st_size)
        for p in paths
        if p.exists()
    )


def export_catalog(root, target):
    root, target = Path(root), Path(target)
    if (root / "discovery-journal.sqlite3").exists():
        from .harvest import save_auto_rules

        save_auto_rules(root, [])
    files = local_files(root)
    if sum(p.stat().st_size for p in files) > MAX_ARCHIVE:
        raise ValueError("Catalog exceeds 256 MB")

    documents = [(p.relative_to(root).as_posix(), read_sites(p)) for p in files]
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".nix-catalog-", suffix=".zip", dir=target.parent
    )
    os.close(fd)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(
                "manifest.json", json.dumps({"format": "nix-catalog", "version": 1})
            )
            for name, rules in documents:
                archive.writestr(
                    name,
                    json.dumps(
                        {
                            "format": "nix-sites",
                            "version": 1,
                            "sites": [rule_data(r) for r in rules],
                        },
                        ensure_ascii=False,
                    ),
                )
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return sum(len(rules) for _, rules in documents)


def import_catalog(root, source):
    root, source = Path(root), Path(source)
    if source.stat().st_size > MAX_ARCHIVE:
        raise ValueError("Archive exceeds 256 MB")
    incoming = {}
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            names = [i.filename for i in entries]
            if (
                len(entries) > 515
                or len(names) != len(set(names))
                or "manifest.json" not in names
            ):
                raise ValueError("Invalid catalog archive")
            if sum(i.file_size for i in entries) > MAX_ARCHIVE:
                raise ValueError("Expanded catalog exceeds 256 MB")
            for info in entries:
                if info.file_size > MAX_FILE or info.flag_bits & 1:
                    raise ValueError("Invalid catalog entry")
                if info.filename != "manifest.json" and not LOCAL_NAME.fullmatch(
                    info.filename
                ):
                    raise ValueError("Unexpected catalog entry")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest != {"format": "nix-catalog", "version": 1}:
                raise ValueError("Unsupported catalog archive")
            for info in entries:
                if info.filename != "manifest.json":
                    incoming[info.filename] = decode_document(
                        json.loads(archive.read(info))
                    )
    except (
        zipfile.BadZipFile,
        UnicodeError,
        RecursionError,
        KeyError,
        RuntimeError,
    ) as exc:
        raise ValueError("Invalid catalog archive") from exc

    existing_auto = {}
    for p in local_files(root):
        if p.parent.name == "auto-sites":
            existing_auto.update((canonical(r.profile), r) for r in read_sites(p))
    added, documents = 0, {}
    imported_auto = {}
    for name, rules in incoming.items():
        if name.startswith("auto-sites/"):
            imported_auto.update((canonical(r.profile), r) for r in rules)
            continue
        existing = {canonical(r.profile): r for r in read_sites(root / name)}
        merged = {canonical(r.profile): r for r in rules}
        added += len(merged.keys() - existing.keys())
        merged.update(existing)
        documents[name] = list(merged.values())
    added += len(imported_auto.keys() - existing_auto.keys())
    imported_auto.update(existing_auto)
    auto = list(imported_auto.values())
    if len(auto) > 1024000:
        raise ValueError("Auto catalog limit exceeded")
    documents.update(
        (f"auto-sites/{i // 2000:04d}.json", auto[i : i + 2000])
        for i in range(0, len(auto), 2000)
    )

    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nix-import-") as staging:
        previous = {}
        for name, rules in documents.items():
            staged = Path(staging) / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            write_sites(staged, rules)
            dest = root / name
            if dest.is_symlink() or dest.parent.is_symlink():
                raise ValueError("Catalog symlinks are unsupported")
            previous[name] = dest.read_bytes() if dest.exists() else None
        committed = []
        try:
            from .export import atomic_text

            for name in documents:
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                atomic_text(dest, (Path(staging) / name).read_text(encoding="utf-8"))
                committed.append(name)
        except OSError:
            for name in committed:
                if previous[name] is None:
                    (root / name).unlink(missing_ok=True)
                else:
                    atomic_text(root / name, previous[name].decode("utf-8-sig"))
            raise
    return added
