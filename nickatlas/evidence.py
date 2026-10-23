import json
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit, urljoin

from .models import canonical


class ProfileEvidence(HTMLParser):
    def __init__(self, osu=False):
        super().__init__(convert_charrefs=True)
        self.osu = osu
        self.profile_data = []
        self.urls = []
        self.names = []
        self.in_title = False
        self.title = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if self.osu and tag == "div" and "data-initial-data" in values:
            try:
                data = json.loads(values["data-initial-data"])
                if (
                    isinstance(data, dict)
                    and isinstance(data.get("user"), dict)
                    and "current_mode" in data
                ):
                    self.profile_data.append(data["user"])
            except (ValueError, TypeError, RecursionError):
                pass
        if tag == "title":
            self.in_title = True
        if tag == "link" and "canonical" in (values.get("rel") or "").split():
            self.urls.append(values.get("href") or "")
        if tag == "meta":
            key = values.get("property") or values.get("name", "")
            if key in ("og:url", "twitter:url"):
                self.urls.append(values.get("content") or "")
            if key in ("profile:username", "username"):
                self.names.append(values.get("content") or "")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data[:2000])


def json_identity(obj, account, depth=0):
    if depth > 4:
        return False
    if isinstance(obj, dict):
        actual = obj.get("username", obj.get("login", obj.get("screen_name")))
        identifier = obj.get("id", obj.get("uid", obj.get("id_str")))
        valid_id = (
            type(identifier) is int
            and identifier > 0
            or isinstance(identifier, str)
            and 1 <= len(identifier.strip()) <= 128
            and identifier.strip() not in ("0", "-1", "null", "None")
        )
        if (
            isinstance(actual, str)
            and actual.casefold() == account.casefold()
            and valid_id
        ):
            return True
        return any(
            json_identity(value, account, depth + 1)
            for key, value in list(obj.items())[:40]
            if key
            in ("user", "data", "users", "person", "account", "profile", "person_view")
        )
    if isinstance(obj, list):
        return any(json_identity(value, account, depth + 1) for value in obj[:10])
    return False


def structured_identity(account, body, profile):
    from .fediverse import webfinger_profile

    if webfinger_profile(account, body, profile):
        return True
    try:
        if json_identity(json.loads(body), account):
            return True
    except (ValueError, RecursionError):
        pass
    if urlsplit(profile).hostname == "osu.ppy.sh":
        parser = ProfileEvidence(osu=True)
        try:
            parser.feed(body[: 1024 * 1024])
        except (ValueError, AssertionError, RecursionError):
            return False
        return any(json_identity(data, account) for data in parser.profile_data)
    return False


def identity_evidence(rule, account, body, profile):
    if structured_identity(account, body, profile):
        return True
    if any(
        ("{username}" in marker or "{account}" in marker)
        and marker.replace("{username}", account).replace("{account}", account) in body
        for marker in rule.present
    ):
        return True
    parser = ProfileEvidence()
    try:
        parser.feed(body[: 256 * 1024])
    except (ValueError, AssertionError, RecursionError):
        return False
    if any(value.casefold() == account.casefold() for value in parser.names):
        return True
    same_url = False
    for url in parser.urls:
        try:
            if (
                url
                and canonical(unquote(urljoin(profile, url))).casefold()
                == canonical(unquote(profile)).casefold()
            ):
                same_url = True
        except ValueError:
            continue
    title = "".join(parser.title)
    nickname = re.search(r"(?<![\w])" + re.escape(account) + r"(?![\w])", title, re.I)
    return bool(same_url and nickname)
