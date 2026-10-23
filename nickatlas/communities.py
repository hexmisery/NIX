from html.parser import HTMLParser
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from .customsites import preset, validate_rule
from .export import atomic_text

DIRECTORY = "https://betterdiscourse.app/forums/"


class DirectoryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entries, self.active, self.url, self.title, self.bold = (
            [],
            False,
            "",
            [],
            False,
        )

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li" and "data-name" in attrs:
            self.active, self.url, self.title = True, "", []
        if self.active and tag == "a" and not self.url:
            self.url = attrs.get("href", "")
        if self.active and tag == "b":
            self.bold = True

    def handle_data(self, data):
        if self.bold:
            self.title.append(data)

    def handle_endtag(self, tag):
        if tag == "b":
            self.bold = False
        if tag == "li" and self.active:
            if self.url:
                self.entries.append({"url": self.url, "title": "".join(self.title)})
            self.active = False


def community_rules(entries):
    rules, seen = [], set()
    for item in entries[:10000]:
        try:
            host = urlsplit(item["url"]).hostname
            if not host or host in seen:
                continue
            rule = validate_rule(
                preset("Discourse", item["url"], (item.get("title") or host)[:100])
            )
            rule.source = "Community Directory"
            rules.append(rule)
            seen.add(host)
        except (ValueError, TypeError, KeyError):
            continue
    return rules


async def directory_rules(net, root):
    path = Path(root) / "community-feed.json"
    old = None
    try:
        if path.stat().st_size < 4 * 1024 * 1024:
            old = json.loads(path.read_text(encoding="utf-8"))
            if 0 <= time.time() - old["updated"] < 6 * 3600:
                return community_rules(old["entries"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        code, body, _, cut = await net.get(DIRECTORY, max_body=6 * 1024 * 1024)
        if code != 200 or cut:
            raise ValueError("Community directory unavailable")
        parser = DirectoryParser()
        parser.feed(body)
        rules = community_rules(parser.entries)
        if len(rules) < 50:
            raise ValueError("Community directory incomplete")
        atomic_text(
            path, json.dumps({"updated": time.time(), "entries": parser.entries})
        )
        return rules
    except Exception:
        if isinstance(old, dict) and isinstance(old.get("entries"), list):
            return community_rules(old["entries"])
        raise
