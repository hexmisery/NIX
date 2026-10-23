import json
from urllib.parse import quote, urlsplit
from .customsites import validate_rule
from .network import safe_url

PATHS = {
    "mastodon": "/@{username}",
    "pixelfed": "/{username}",
    "pleroma": "/users/{username}",
    "akkoma": "/users/{username}",
    "misskey": "/@{username}",
    "sharkey": "/@{username}",
    "firefish": "/@{username}",
    "iceshrimp": "/@{username}",
    "gotosocial": "/@{username}",
    "friendica": "/profile/{username}",
    "hubzilla": "/channel/{username}",
    "lemmy": "/u/{username}",
    "peertube": "/accounts/{username}",
    "mbin": "/u/{username}",
    "kbin": "/u/{username}",
    "wordpress": "/author/{username}",
    "writefreely": "/{username}",
    "goblog": "/{username}",
    "snac": "/{username}",
}


def webfinger_rule(base, software, title="", languages=()):
    host = urlsplit(base).hostname
    if software not in PATHS or not host:
        raise ValueError("Unsupported federation software")
    data = {
        "site": (title or host)[:100],
        "profile": base + PATHS[software],
        "probe": base
        + "/.well-known/webfinger?resource=acct%3A{username}%40"
        + quote(host, safe=""),
        "kind": "webfinger",
        "engine": software,
        "category": "Социальные сети",
        "tags": [
            v
            for v in languages
            if isinstance(v, str) and 1 <= len(v) <= 64 and all(ord(c) >= 32 for c in v)
        ][:32],
    }
    return validate_rule(data)


def webfinger_profile(account, body, profile):
    try:
        data = json.loads(body)
        host = urlsplit(profile).hostname
        if (
            not isinstance(data, dict)
            or not host
            or data.get("subject", "").casefold()
            != ("acct:" + account + "@" + host).casefold()
        ):
            return None
        links = data.get("links", [])
        if not isinstance(links, list):
            return None
        candidates = []
        for rel in ("http://webfinger.net/rel/profile-page", "self"):
            for link in links[:40]:
                if (
                    isinstance(link, dict)
                    and link.get("rel") == rel
                    and isinstance(link.get("href"), str)
                ):
                    href = safe_url(link["href"])
                    parsed = urlsplit(href)
                    if parsed.hostname == host and parsed.path.rstrip("/"):
                        candidates.append(href)
        return candidates[0] if candidates else None
    except (ValueError, TypeError, AttributeError, RecursionError):
        return None


async def inspect_nodeinfo(net, base):
    code, body, final, cut = await net.get(
        base + "/.well-known/nodeinfo", max_body=65536
    )
    if code != 200 or cut or urlsplit(final).hostname != urlsplit(base).hostname:
        return None
    data = json.loads(body)
    links = data.get("links", []) if isinstance(data, dict) else []
    if not isinstance(links, list):
        return None
    allowed = {
        "http://nodeinfo.diaspora.software/ns/schema/2.0",
        "http://nodeinfo.diaspora.software/ns/schema/2.1",
    }
    choices = [
        r
        for r in links[:10]
        if isinstance(r, dict)
        and r.get("rel") in allowed
        and isinstance(r.get("href"), str)
    ]
    for link in sorted(choices, key=lambda r: r["rel"], reverse=True):
        url = safe_url(link["href"])
        if urlsplit(url).hostname != urlsplit(base).hostname or (
            urlsplit(base).scheme == "https" and urlsplit(url).scheme != "https"
        ):
            continue
        code, body, final, cut = await net.get(url, max_body=262144)
        if code != 200 or cut or urlsplit(final).hostname != urlsplit(base).hostname:
            continue
        obj = json.loads(body)
        if not isinstance(obj, dict) or not isinstance(obj.get("software"), dict):
            continue
        software = str(obj["software"].get("name", "")).casefold()
        if (
            software not in PATHS
            or not isinstance(obj.get("protocols"), list)
            or "activitypub" not in obj["protocols"]
        ):
            continue
        meta = obj.get("metadata", {})
        if not isinstance(meta, dict):
            meta = {}
        languages = meta.get("languages", [])
        if not isinstance(languages, list):
            languages = []
        return webfinger_rule(
            base,
            software,
            str(meta.get("nodeName") or urlsplit(base).hostname),
            languages,
        )
    return None
