from collections import Counter
import json
from pathlib import Path
from urllib.parse import urlsplit

from .models import Rule, Site, canonical
from .paths import assets

SOURCES = {
    "nexfil": ("thewhiteh4t/nexfil", "main", "src/nexfil/url_store.json"),
    "socialanalyzer": ("qeeqbox/social-analyzer", "main", "data/sites.json"),
    "whatsmyname": ("WebBreacher/WhatsMyName", "main", "wmn-data.json"),
    "sherlock": (
        "sherlock-project/sherlock",
        "master",
        "sherlock_project/resources/data.json",
    ),
    "maigret": ("soxoj/maigret", "main", "maigret/resources/data.json"),
}


def strings(value):
    if isinstance(value, str):
        return [value] if value else []
    return [str(x) for x in value if x] if isinstance(value, list) else []


def normalize(template):
    return (
        str(template or "")
        .replace("{}", "{username}")
        .replace("{account}", "{username}")
    )


def profile_ok(template):
    try:
        p = urlsplit(template)
        return (
            p.scheme in ("https", "http")
            and bool(p.hostname)
            and "{username}" in template
        )
    except ValueError:
        return False


def parse(name, data):
    rules = []
    if name == "nexfil":
        if not isinstance(data, list):
            raise ValueError("Некорректный каталог NExfil")
        for entry in data:
            profile = normalize(entry.get("url"))
            method = entry.get("test")
            rules.append(
                Rule(
                    urlsplit(profile).hostname or profile,
                    profile,
                    profile,
                    "NExfil",
                    kind="message"
                    if method == "string"
                    else "response_url"
                    if method == "url"
                    else "status_code",
                    absent=strings(entry.get("data")) if method == "string" else [],
                    unsupported=""
                    if method in (None, "string", "url", "subdomain")
                    else "Нужен отдельный адаптер NExfil",
                )
            )
    elif name == "socialanalyzer":
        if not isinstance(data.get("websites_entries"), list):
            raise ValueError("Некорректный каталог Social Analyzer")
        shared = {
            x["name"]: x.get("detections", [])
            for x in data.get("shared_detections", [])
        }
        for entry in data["websites_entries"]:
            profile = normalize(entry.get("url"))
            detections = []
            for d in entry.get("detections", []):
                detections.extend(
                    shared.get(d.get("name"), []) if d.get("type") == "shared" else [d]
                )
            normal = [
                d
                for d in detections
                if d.get("type") == "normal"
                and d.get("string")
                and "temp_fix_" not in d["string"]
            ]
            rules.append(
                Rule(
                    urlsplit(profile).hostname or profile,
                    profile,
                    profile,
                    "Social Analyzer",
                    "message",
                    present=[d["string"] for d in normal if d.get("return") == "true"],
                    absent=[d["string"] for d in normal if d.get("return") == "false"],
                    rank=int(entry.get("global_rank") or 999999999),
                    tags=strings(entry.get("country"))
                    + strings(entry.get("country_code")),
                    category="adult"
                    if entry.get("nsfw") == "true"
                    else str(entry.get("type", "other")).split(" > ")[0],
                    unsupported=""
                    if normal
                    else "Требуется браузер или особый метод проверки",
                )
            )
    elif name == "whatsmyname":
        if not isinstance(data.get("sites"), list):
            raise ValueError("Некорректный каталог WhatsMyName")
        for s in data["sites"]:
            profile = normalize(s.get("uri_pretty") or s.get("uri_check"))
            rules.append(
                Rule(
                    str(s.get("name", "")),
                    profile,
                    normalize(s.get("uri_check")),
                    "WhatsMyName / Blackbird",
                    "message",
                    strings(s.get("e_string")),
                    strings(s.get("m_string")),
                    int(s.get("e_code", 200)),
                    int(s.get("m_code", 404)),
                    str(s.get("cat", "other")),
                    known=next(iter(s.get("known", [])), ""),
                    method="POST" if s.get("post_body") else "GET",
                    disabled=s.get("valid") is False,
                )
            )
    elif name == "sherlock":
        if len(data) < 10:
            raise ValueError("Неполный каталог Sherlock")
        for title, s in data.items():
            if not isinstance(s, dict) or "url" not in s:
                continue
            rules.append(
                Rule(
                    title,
                    normalize(s["url"]),
                    normalize(s.get("urlProbe") or s["url"]),
                    "Sherlock",
                    s.get("errorType", "status_code"),
                    absent=strings(s.get("errorMsg")),
                    known=s.get("username_claimed", ""),
                    category="adult" if s.get("isNSFW") else "other",
                )
            )
    elif name == "maigret":
        if not isinstance(data.get("sites"), dict) or not isinstance(
            data.get("engines"), dict
        ):
            raise ValueError("Некорректный каталог Maigret")
        for title, raw in data["sites"].items():
            base = data["engines"].get(raw.get("engine"), {}).get("site", {})
            s = {**base, **raw}

            def expand(value):
                value = normalize(value)
                for k in ("urlMain", "urlSubpath"):
                    value = value.replace("{" + k + "}", str(s.get(k, "")))
                return value

            rules.append(
                Rule(
                    title,
                    expand(s.get("url")),
                    expand(s.get("urlProbe") or s.get("url")),
                    "Maigret",
                    s.get("checkType", "status_code"),
                    strings(s.get("presenseStrs")),
                    strings(s.get("absenceStrs")),
                    category="Форумы"
                    if s.get("engine")
                    in (
                        "XenForo",
                        "phpBB/Search",
                        "phpBB",
                        "phpBB2/Search",
                        "vBulletin",
                        "Discourse",
                        "DiscourseJson",
                        "Flarum",
                        "Vanilla",
                        "bbPress",
                        "BuddyPress",
                        "NodeBB",
                    )
                    else next(iter(s.get("tags", [])), "other"),
                    tags=list(s.get("tags", [])),
                    engine=s.get("engine") or "",
                    rank=int(s.get("alexaRank") or 999999999),
                    known=str(s.get("usernameClaimed", "")),
                    method=s.get("requestMethod", "GET"),
                    disabled=bool(s.get("disabled")),
                    unsupported="Специальный ID или приблизительный поиск"
                    if s.get("type", "username") != "username" or s.get("similarSearch")
                    else "",
                )
            )
    else:
        raise ValueError("Неизвестный источник каталога")
    for r in rules:
        if (
            not profile_ok(r.profile)
            or not r.site
            or "{" in r.probe.replace("{username}", "")
        ):
            r.unsupported = "Нет ссылки на профиль или нужен особый адаптер"
        if r.method != "GET":
            r.unsupported = "Требуется POST-адаптер; автоматическая проверка отключена"
        if r.kind not in ("message", "status_code", "response_url"):
            r.unsupported = "Неизвестный метод проверки"
    return rules


class Catalog:
    def __init__(
        self,
        cache: Path | None = None,
        custom_path: Path | None = None,
        discovered_path: Path | None = None,
    ):
        self.rules = []
        self.errors = []
        for name in SOURCES:
            path = cache / (name + ".json") if cache else None
            try:
                if not path or not path.exists():
                    path = assets() / "catalogs" / (name + ".json")
                self.rules.extend(
                    parse(name, json.loads(path.read_text(encoding="utf-8")))
                )
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.errors.append(f"{name}: {type(exc).__name__}")
        from .customsites import read_sites

        forum_path = (
            cache / "forums.json"
            if cache and (cache / "forums.json").exists()
            else assets() / "catalogs" / "forums.json"
        )
        extra_paths = [
            (forum_path, "Discourse Discover"),
            (discovered_path, "Discourse Discover"),
            (custom_path, "Свои сайты"),
        ]
        extra_paths.append((assets() / "catalogs/mastodon.json", "Mastodon Directory"))
        extra_paths.append((assets() / "catalogs/verified.json", "Автосбор"))
        extra_paths.extend(
            (p, "Community Directory")
            for p in sorted((assets() / "catalogs").glob("community-*.json"))
        )
        for prefix, label in (("collected", "Collected sites"), ("fedidb", "FediDB")):
            extra_paths.extend(
                (p, label)
                for p in sorted((assets() / "catalogs").glob(prefix + "-*.json"))
            )
        if custom_path:
            extra_paths.extend(
                (p, "Автосбор")
                for p in sorted((custom_path.parent / "auto-sites").glob("*.json"))[
                    :512
                ]
            )
        for path, source in extra_paths:
            if path:
                try:
                    extra = read_sites(path)
                    for rule in extra:
                        rule.source = source
                    self.rules.extend(extra)
                except (OSError, ValueError, TypeError) as exc:
                    self.errors.append(f"{source}: {type(exc).__name__}")
        if custom_path:
            from .discovery_store import journal_rules

            try:
                for rule in journal_rules(custom_path.parent.resolve()):
                    rule.source = "Автосбор"
                    self.rules.append(rule)
            except (OSError, ValueError) as exc:
                self.errors.append(f"Discovery journal: {type(exc).__name__}")
        if custom_path:
            from .harvest_state import cached_metadata

            metadata_tags = {
                canonical(r.profile): r.tags
                for r in cached_metadata(custom_path.parent)
            }
            for rule in self.rules:
                rule.tags = sorted(
                    set(rule.tags) | set(metadata_tags.get(canonical(rule.profile), ()))
                )[:32]
        forums = {
            canonical(r.profile): r
            for r in self.rules
            if r.source == "Discourse Discover"
        }
        self.rules = [r for r in self.rules if r.source != "Discourse Discover"] + list(
            forums.values()
        )
        custom_disabled = {
            canonical(r.profile)
            for r in self.rules
            if r.source == "Свои сайты" and r.disabled
        }
        groups = {}
        self.omitted = Counter()
        for rule in self.rules:
            if (
                rule.disabled
                or rule.unsupported
                or canonical(rule.profile) in custom_disabled
            ):
                self.omitted["disabled" if rule.disabled else "unsupported"] += 1
                continue
            groups.setdefault(canonical(rule.profile), []).append(rule)
        self.sites = []
        for rules in groups.values():
            rules.sort(
                key=lambda r: (
                    r.source != "Свои сайты",
                    r.kind not in ("json_user", "webfinger"),
                    not bool(r.present),
                    r.source != "WhatsMyName / Blackbird",
                    r.rank,
                )
            )
            self.sites.append(Site(rules))
        self.sites.sort(
            key=lambda s: (
                s.primary.source != "Свои сайты",
                min(r.rank for r in s.rules),
                s.primary.site.casefold(),
            )
        )

    def select(
        self,
        full=False,
        category="Все категории",
        include_adult=False,
        source="",
        priority="all",
    ):
        sites = [
            s
            for s in self.sites
            if category == "Все категории"
            or any(r.category == category for r in s.rules)
        ]
        if not include_adult:
            sites = [
                s
                for s in sites
                if not any(
                    any(
                        x in (r.category + " " + " ".join(r.tags)).lower()
                        for x in ("porn", "nsfw", "adult")
                    )
                    for r in s.rules
                )
            ]
        if source:
            sites = [
                Site([r for r in s.rules if source in r.source])
                for s in sites
                if any(source in r.source for r in s.rules)
            ]
        from .regions import SCOPES, matches_scope

        if priority in SCOPES and priority != "all":
            sites = [
                s
                for s in sites
                if matches_scope(
                    s.primary.profile,
                    [tag for r in s.rules for tag in r.tags],
                    priority,
                )
            ]
        if priority != "all":
            from .regions import regional_order

            tags = {
                s.primary.profile: [tag for r in s.rules for tag in r.tags]
                for s in sites
            }
            positions = {
                url: i
                for i, url in enumerate(
                    regional_order(tags, tags, priority, preserve_order=True)
                )
            }
            sites.sort(key=lambda site: positions[site.primary.profile])
        return sites if full else sites[:100]
