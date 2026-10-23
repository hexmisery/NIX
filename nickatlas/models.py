from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import unicodedata
from urllib.parse import quote, urlsplit, urlunsplit

STATUS = {
    "found": "Найден профиль",
    "possible": "Нужна проверка",
    "missing": "Не найден",
    "blocked": "Блокировка",
    "error": "Ошибка",
    "skipped": "Пропущен",
    "rejected": "Отмечен ошибочным",
}


def username(value: str) -> str:
    value = unicodedata.normalize("NFC", value.strip().removeprefix("@"))
    if not 1 <= len(value) <= 64:
        raise ValueError("Ник должен содержать от 1 до 64 символов.")
    if not all(c.isalnum() or c in "._-" for c in value):
        raise ValueError("Допустимы буквы, цифры, точка, дефис и подчёркивание.")
    return value


def substitute(template: str, account: str) -> str:
    return template.replace("{username}", quote(account, safe="")).replace(
        "{account}", quote(account, safe="")
    )


def canonical(url: str) -> str:
    p = urlsplit(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    return urlunsplit((p.scheme.lower(), host, p.path.rstrip("/") or "/", p.query, ""))


@dataclass
class Rule:
    site: str
    profile: str
    probe: str
    source: str
    kind: str = "status_code"
    present: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    exists_code: int = 200
    missing_code: int = 404
    category: str = "other"
    rank: int = 999999999
    known: str = ""
    method: str = "GET"
    disabled: bool = False
    unsupported: str = ""
    engine: str = ""
    json_path: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return hashlib.sha256(canonical(self.profile).encode()).hexdigest()[:20]


@dataclass
class Site:
    rules: list[Rule]

    @property
    def primary(self) -> Rule:
        return self.rules[0]

    @property
    def sources(self) -> str:
        return ", ".join(dict.fromkeys(r.source for r in self.rules))


@dataclass
class Result:
    site: str
    url: str
    source: str
    category: str
    status: str
    reason: str
    checking: bool = False
    verified: bool = False
    elapsed: float = 0
    http: int = 0
    title: str = ""
    links: list[dict] = field(default_factory=list)
    checked: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def data(self):
        return asdict(self)
