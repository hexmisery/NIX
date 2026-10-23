import html
import re
from html.parser import HTMLParser
import json
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit, unquote

from .models import canonical
from .network import safe_url

SENSITIVE = {
    "token",
    "access_token",
    "api_key",
    "key",
    "secret",
    "auth",
    "password",
    "code",
    "session",
    "sid",
    "authorization",
    "bearer",
    "jwt",
    "client_secret",
    "refresh_token",
    "id_token",
    "otp",
    "signature",
    "sig",
}


def sensitive_query_key(key):
    decoded = str(key)
    for _ in range(2):
        decoded = unquote(decoded)
    pieces = re.split(r"[^a-z0-9_]+", decoded.casefold())
    aliases = {
        "apikey",
        "accesstoken",
        "refreshtoken",
        "clientsecret",
        "sessionid",
        "idtoken",
    }
    return decoded.casefold() in SENSITIVE or any(
        p in SENSITIVE or p.replace("_", "") in aliases for p in pieces
    )


def clean_link(raw, base):
    if not isinstance(raw, str) or len(raw) > 2000:
        return None
    raw = html.unescape(raw.strip())
    if raw.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    if not raw.startswith(("http://", "https://", "/", "//")):
        raw = "https://" + raw
    try:
        url = urljoin(base, raw)
        safe_url(url)
        p = urlsplit(url)
        query = parse_qsl(p.query, keep_blank_values=True, max_num_fields=50)
        if len(p.path) > 1000:
            return None
        if any(sensitive_query_key(k) for k, _ in query):
            return None
        query = [
            (k, v)
            for k, v in query
            if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")
        ]
        return urlunsplit((p.scheme, p.netloc, p.path or "/", urlencode(query), ""))
    except (ValueError, TypeError):
        return None


class ProfileLinks(HTMLParser):
    def __init__(self, all_links=False):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.all_links = all_links
        self.jsonld = False
        self.script = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if (
            len(self.links) < 256
            and tag == "a"
            and attr.get("href")
            and (self.all_links or "me" in attr.get("rel", "").lower().split())
        ):
            self.links.append(
                (attr["href"], "Ссылка в описании" if self.all_links else "HTML rel=me")
            )
        if tag == "script" and attr.get("type", "").lower() == "application/ld+json":
            self.jsonld = True
            self.script = []

    def handle_data(self, text):
        if self.jsonld and sum(map(len, self.script)) < 65536:
            self.script.append(text[: max(0, 65536 - sum(map(len, self.script)))])

    def handle_endtag(self, tag):
        if tag == "script" and self.jsonld:
            self.jsonld = False
            try:
                self.visit(json.loads("".join(self.script)))
            except (ValueError, RecursionError):
                pass

    def visit(self, obj, depth=0):
        if depth > 5:
            return
        if isinstance(obj, list):
            for item in obj[:30]:
                self.visit(item, depth + 1)
        elif isinstance(obj, dict):
            kind = obj.get("@type", "")
            if kind == "Person" or isinstance(kind, list) and "Person" in kind:
                values = obj.get("sameAs", [])
                for value in (
                    [values]
                    if isinstance(values, str)
                    else values
                    if isinstance(values, list)
                    else []
                )[:20]:
                    if isinstance(value, str) and len(self.links) < 256:
                        self.links.append((value, "JSON-LD Person.sameAs"))
            for key in ("@graph", "mainEntity"):
                if key in obj:
                    self.visit(obj[key], depth + 1)


def extract_links(body, base):
    parser = ProfileLinks()
    try:
        parser.feed(body[: 1024 * 1024])
    except (ValueError, RecursionError, AssertionError):
        pass
    try:
        obj = json.loads(body)
        user = obj.get("user", obj) if isinstance(obj, dict) else {}
        if isinstance(user, dict):
            for key in ("website", "blog"):
                if user.get(key):
                    parser.links.append((user[key], "Поле профиля: " + key))
            for field in (
                user.get("fields", [])[:20]
                if isinstance(user.get("fields"), list)
                else []
            ):
                if isinstance(field, dict) and isinstance(field.get("value"), str):
                    fields_parser = ProfileLinks(all_links=True)
                    fields_parser.feed(field["value"][:10000])
                    parser.links.extend(
                        (url, "Поле профиля: " + str(field.get("name", ""))[:50])
                        for url, _ in fields_parser.links
                    )
            for key in ("bio_cooked", "bio_html", "note"):
                bio = user.get(key)
                if isinstance(bio, str):
                    bio_parser = ProfileLinks(all_links=True)
                    bio_parser.feed(bio[:50000])
                    parser.links.extend(bio_parser.links)
    except (ValueError, TypeError, RecursionError, AssertionError):
        pass
    result, seen = [], set()
    for raw, evidence in parser.links:
        link = clean_link(raw, base)
        if not link or canonical(link) == canonical(base):
            continue
        key = canonical(link)
        if key not in seen:
            seen.add(key)
            result.append({"url": link, "evidence": evidence})
        if len(result) >= 20:
            break
    return result


def connection_rows(results):
    by_url = {canonical(r.url): r for r in results if r.status == "found"}
    rows = []
    for source in results:
        if source.status not in ("found", "possible"):
            continue
        for link in source.links:
            if not isinstance(link, dict) or not clean_link(
                link.get("url"), source.url
            ):
                continue
            target = by_url.get(canonical(link["url"]))
            reciprocal = bool(
                target
                and any(
                    canonical(back.get("url", "")) == canonical(source.url)
                    for back in target.links
                    if isinstance(back, dict)
                )
            )
            rows.append(
                {
                    "source": source.url,
                    "target": link["url"],
                    "site": source.site,
                    "evidence": link.get("evidence", "Ссылка на странице"),
                    "matched": bool(target),
                    "reciprocal": reciprocal,
                    "source_status": source.status,
                }
            )
    shared = {}
    for row in rows:
        shared.setdefault(canonical(row["target"]), set()).add(row["source"])
    for row in rows:
        row["shared_count"] = len(shared[canonical(row["target"])])
    return rows[:2000]
