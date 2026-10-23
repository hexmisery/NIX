from types import SimpleNamespace

import pytest

from tools.check_catalog import check, origins


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,final,expected",
    [
        (200, "https://example.org/", "responding"),
        (200, "https://www.example.org/", "responding"),
        (200, "https://other.example/", "redirected"),
        (403, "https://example.org/", "restricted"),
        (404, "https://example.org/", "http_error"),
    ],
)
async def test_response_categories_do_not_confirm_profiles(code, final, expected):
    class Net:
        async def get(self, url, **kwargs):
            return code, "", final, False

    row = await check(Net(), "https://example.org/")
    assert row["state"] == expected
    assert "verified" not in row


def test_private_and_username_dependent_hosts_are_not_requested():
    catalog = SimpleNamespace(
        sites=[
            SimpleNamespace(primary=SimpleNamespace(profile=profile))
            for profile in (
                "https://example.org/u/{username}",
                "https://{username}.example.org/",
                "http://127.0.0.1/u/{username}",
            )
        ]
    )
    fixed, dynamic, invalid = origins(catalog)
    assert fixed == ["https://example.org/"]
    assert dynamic == ["{username}.example.org"]
    assert invalid == ["http://127.0.0.1/"]
