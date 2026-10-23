import asyncio, json, sys, ipaddress
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nickatlas.fediverse import webfinger_rule, webfinger_profile, inspect_nodeinfo
from nickatlas.engine import check_site
from nickatlas.models import Site
from nickatlas.frontier import Frontier
from nickatlas.connections import clean_link, ProfileLinks
from nickatlas.network import Network


@pytest.mark.asyncio
async def test_webfinger_exact_subject_and_stable_preview_url():
    rule = webfinger_rule("https://example.org", "misskey")
    seen = []

    class Net:
        async def get(self, url, **kw):
            if "acct%3Aadmin%40" in url:
                return (
                    200,
                    json.dumps(
                        {
                            "subject": "acct:admin@example.org",
                            "links": [
                                {"rel": "self", "href": "https://example.org/users/123"}
                            ],
                        }
                    ),
                    url,
                    False,
                )
            return 404, "", url, False

    result = await check_site(Net(), Site([rule]), "admin", preview=seen.append)
    assert result.verified and result.url == "https://example.org/users/123"
    assert seen and all(row.url == result.url for row in seen)
    assert not webfinger_profile(
        "admin", '{"subject":"acct:admin@elsewhere.org","links":[]}', result.url
    )


@pytest.mark.asyncio
async def test_reflecting_webfinger_does_not_confirm_every_name():
    from urllib.parse import parse_qs, urlsplit

    rule = webfinger_rule("https://example.org", "misskey")

    class Net:
        async def get(self, url, **kw):
            resource = parse_qs(urlsplit(url).query)["resource"][0]
            return (
                200,
                json.dumps(
                    {
                        "subject": resource,
                        "links": [
                            {"rel": "self", "href": "https://example.org/users/fake"}
                        ],
                    }
                ),
                url,
                False,
            )

    assert (await check_site(Net(), Site([rule]), "admin")).status == "possible"


@pytest.mark.asyncio
async def test_nodeinfo_only_follows_same_public_host():
    seen = []

    class Net:
        async def get(self, url, **kw):
            seen.append(url)
            if url.endswith("/.well-known/nodeinfo"):
                return (
                    200,
                    json.dumps(
                        {
                            "links": [
                                {
                                    "rel": "http://nodeinfo.diaspora.software/ns/schema/2.1",
                                    "href": "https://example.org/nodeinfo/2.1",
                                }
                            ]
                        }
                    ),
                    url,
                    False,
                )
            return (
                200,
                json.dumps(
                    {
                        "software": {"name": "lemmy", "version": "1"},
                        "protocols": ["activitypub"],
                        "metadata": {"languages": ["ru"]},
                    }
                ),
                url,
                False,
            )

    rule = await inspect_nodeinfo(Net(), "https://example.org")
    assert rule.kind == "webfinger" and rule.tags == ["ru"] and len(seen) == 2

    class Foreign:
        async def get(self, url, **kw):
            assert url.endswith("/.well-known/nodeinfo")
            return (
                200,
                json.dumps(
                    {
                        "links": [
                            {
                                "rel": "http://nodeinfo.diaspora.software/ns/schema/2.1",
                                "href": "https://other.example/nodeinfo",
                            }
                        ]
                    }
                ),
                url,
                False,
            )

    assert await inspect_nodeinfo(Foreign(), "https://example.org") is None


@pytest.mark.parametrize(
    "key",
    [
        "access_token",
        "apiKey",
        "auth[token]",
        "x-amz-signature",
        "client_secret",
        "%2574oken",
        "jwt",
    ],
)
def test_secret_links_never_enter_frontier(tmp_path, key):
    url = "https://other.example/profile?" + key + "=fixture"
    assert clean_link(url, "https://example.org") is None
    queue = Frontier(tmp_path)
    try:
        assert queue.enqueue([url], "https://example.org") == 0
    finally:
        queue.close()


def test_parser_and_frontier_are_bounded_and_deduplicate(tmp_path):
    parser = ProfileLinks(all_links=True)
    parser.feed(
        "".join(
            '<a href="https://n' + str(i) + '.example.org">x</a>' for i in range(2000)
        )
    )
    assert len(parser.links) == 256
    q = Frontier(tmp_path)
    try:
        assert (
            q.enqueue(
                [
                    "https://other.example/path",
                    "https://other.example/second",
                    "http://127.0.0.1/path",
                    "https://user:pass@bad.example/path",
                ],
                "https://source.example/profile",
            )
            == 1
        )
        assert q.bases() == ["https://other.example"]
        assert (
            q.db.execute("SELECT origin FROM link_domains").fetchone()[0]
            == "https://source.example/"
        )
    finally:
        q.close()


@pytest.mark.asyncio
async def test_proxy_request_pins_public_ip_and_preserves_tls_hostname(monkeypatch):
    loop = asyncio.get_running_loop()

    async def resolver(*args, **kw):
        return [(2, 1, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(loop, "getaddrinfo", resolver)

    class Content:
        async def iter_chunked(self, *args):
            yield b"{}"

    class Response:
        status = 200
        headers = {}
        charset = "utf-8"
        content = Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async with Network(proxy="http://127.0.0.1:1") as net:
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            return Response()

        monkeypatch.setattr(net.session, "get", get)
        code, _, url, _ = await net.get("https://example.org/profile")
        target, kwargs = calls[0]
        assert ipaddress.ip_address(
            __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(target).hostname
        ).is_global
        assert (
            kwargs["server_hostname"] == "example.org"
            and kwargs["headers"]["Host"] == "example.org"
        )
        assert url == "https://example.org/profile" and code == 200
        assert net.session.connector.force_close


def test_legacy_failures_retry_once_with_new_detector(tmp_path):
    from nickatlas.harvest_state import HarvestLedger
    import time

    ledger = HarvestLedger(tmp_path)
    try:
        with ledger.db:
            ledger.db.executemany(
                "INSERT INTO checks VALUES(?,?,?,?)",
                [
                    ("https://old.example", time.time(), time.time() + 86400, ""),
                    (
                        "https://known.example",
                        time.time(),
                        time.time() + 86400,
                        "Mastodon",
                    ),
                ],
            )
        assert "https://old.example" not in ledger.recent()
        assert "https://known.example" in ledger.recent()
        ledger.checked("https://old.example", None)
        assert "https://old.example" in ledger.recent()
    finally:
        ledger.close()
