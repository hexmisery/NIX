from dataclasses import asdict
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit

from .export import atomic_text
from .models import Rule, canonical, substitute, username
from .network import safe_url

MAX_SITES = 2000
MAX_FILE = 4 * 1024 * 1024
FIELDS = {
    "site",
    "profile",
    "probe",
    "kind",
    "present",
    "absent",
    "exists_code",
    "missing_code",
    "category",
    "known",
    "disabled",
    "json_path",
    "engine",
    "tags",
}
PRESETS = {
    "Discourse": ("/u/{username}", "/u/{username}.json", "user", "Discourse"),
    "Mastodon": (
        "/@{username}",
        "/api/v1/accounts/lookup?acct={username}",
        "",
        "Mastodon",
    ),
    "Gitea": ("/{username}", "/api/v1/users/{username}", "", "Gitea"),
}


def validate_rule(data):
    if not isinstance(data, dict):
        raise ValueError("Сайт должен быть объектом JSON")
    if set(data) - FIELDS:
        raise ValueError("Неизвестные поля: " + ", ".join(sorted(set(data) - FIELDS)))
    title = data.get("site", "")
    if (
        not isinstance(title, str)
        or not 1 <= len(title.strip()) <= 100
        or any(ord(c) < 32 for c in title)
    ):
        raise ValueError("Название: от 1 до 100 символов без переносов")
    profile = data.get("profile", "")
    probe = data.get("probe") or profile
    for value in (profile, probe):
        if (
            not isinstance(value, str)
            or len(value) > 2000
            or value.count("{username}") != 1
        ):
            raise ValueError("В ссылке нужен ровно один {username}")
        if re.search(r"[{}]", value.replace("{username}", "")):
            raise ValueError("Неизвестный шаблон в ссылке")
        checked_url = substitute(value, "nixcheck")
        safe_url(checked_url)
        from .connections import sensitive_query_key

        parsed = urlsplit(checked_url)
        if parsed.fragment:
            raise ValueError("Фрагменты после # в шаблоне не поддерживаются")
        if any(
            sensitive_query_key(k)
            for k, _ in parse_qsl(parsed.query, max_num_fields=50)
        ):
            raise ValueError("Секретные параметры в URL не поддерживаются")
    kind = data.get("kind", "message")
    if kind not in ("message", "status_code", "json_user", "webfinger"):
        raise ValueError("Неподдерживаемый метод проверки")
    markers = {}
    for name in ("present", "absent"):
        values = data.get(name, [])
        if (
            not isinstance(values, list)
            or len(values) > 12
            or any(not isinstance(v, str) or not 1 <= len(v) <= 500 for v in values)
        ):
            raise ValueError("Маркеры: максимум 12 строк, до 500 символов каждая")
        markers[name] = values
    if kind == "message" and not (markers["present"] or markers["absent"]):
        raise ValueError(
            "Для проверки содержимого нужен положительный или отрицательный маркер"
        )
    codes = {}
    for name, default in (("exists_code", 200), ("missing_code", 404)):
        value = data.get(name, default)
        if type(value) is not int or not 100 <= value <= 599:
            raise ValueError("HTTP-код должен быть числом от 100 до 599")
        codes[name] = value
    category = data.get("category", "Свои сайты")
    known = data.get("known", "")
    if known:
        username(known)
    engine = data.get("engine", "")
    json_path = data.get("json_path", "")
    if not isinstance(category, str) or not 1 <= len(category) <= 60:
        raise ValueError("Категория должна быть строкой до 60 символов")
    if not isinstance(known, str) or len(known) > 64:
        raise ValueError("Слишком длинный контрольный ник")
    if not isinstance(engine, str) or len(engine) > 40:
        raise ValueError("Некорректный тип сайта")
    if not isinstance(json_path, str) or not re.fullmatch(
        r"(?:[A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z_][A-Za-z0-9_]*){0,5}|", json_path
    ):
        raise ValueError("Путь к объекту JSON: например user")
    if type(data.get("disabled", False)) is not bool:
        raise ValueError("Поле disabled должно быть true или false")
    tags = data.get("tags", [])
    if (
        not isinstance(tags, list)
        or len(tags) > 32
        or any(
            not isinstance(tag, str)
            or not 1 <= len(tag) <= 64
            or any(ord(c) < 32 for c in tag)
            for tag in tags
        )
    ):
        raise ValueError("Invalid site language tags")
    return Rule(
        title.strip(),
        profile,
        probe,
        "Свои сайты",
        kind,
        present=markers["present"],
        absent=markers["absent"],
        **codes,
        category=category,
        known=known,
        disabled=data.get("disabled", False),
        json_path=json_path,
        engine=engine,
        tags=list(tags),
    )


def rule_data(rule):
    data = asdict(rule)
    return {k: data[k] for k in FIELDS}


def decode_document(data):
    if (
        not isinstance(data, dict)
        or data.get("format") != "nix-sites"
        or data.get("version") != 1
    ):
        raise ValueError("Нужен файл каталога NIX версии 1")
    sites = data.get("sites")
    if not isinstance(sites, list) or len(sites) > MAX_SITES:
        raise ValueError(f"Каталог должен содержать до {MAX_SITES} сайтов")
    rules = [validate_rule(item) for item in sites]
    if len({canonical(r.profile) for r in rules}) != len(rules):
        raise ValueError("В файле повторяются адреса профилей")
    return rules


def read_sites(path):
    path = Path(path)
    if not path.exists():
        return []
    if path.stat().st_size > MAX_FILE:
        raise ValueError("Файл каталога превышает 4 МБ")
    try:
        return decode_document(json.loads(path.read_text(encoding="utf-8-sig")))
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        raise ValueError("Некорректный JSON или кодировка файла") from None


def write_sites(path, rules):
    if len(rules) > MAX_SITES:
        raise ValueError("В своём каталоге допускается до 2000 сайтов")
    data = {"format": "nix-sites", "version": 1, "sites": [rule_data(r) for r in rules]}
    decode_document(data)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text.encode("utf-8")) > MAX_FILE:
        raise ValueError("Каталог превышает 4 МБ")
    atomic_text(Path(path), text)


def preset(name, base, title):
    base = base.strip().rstrip("/")
    safe_url(base)
    p = urlsplit(base)
    if p.query or p.fragment:
        raise ValueError("Укажи адрес форума без параметров и фрагментов")
    profile, probe, json_path, engine = PRESETS[name]
    return {
        "site": title,
        "profile": base + profile,
        "probe": base + probe,
        "kind": "json_user",
        "json_path": json_path,
        "engine": engine,
        "category": "Форумы"
        if name == "Discourse"
        else "Разработка"
        if name == "Gitea"
        else "Социальные сети",
    }
