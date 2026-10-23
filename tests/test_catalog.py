from urllib.parse import urlsplit

from nickatlas.catalog import Catalog
from nickatlas.models import canonical


def test_bundled_catalog_is_valid_and_deduplicated():
    catalog = Catalog()
    assert not catalog.errors
    profiles = [canonical(site.primary.profile) for site in catalog.sites]
    assert len(profiles) == len(set(profiles))
    assert len(profiles) >= 20_000
    domains = {
        urlsplit(profile.replace("{username}", "admin")).hostname for profile in profiles
    }
    assert len(domains) >= 20_000


def test_adult_sites_are_excluded_by_default():
    catalog = Catalog()
    safe = catalog.select(full=True)
    adult = catalog.select(full=True, include_adult=True)
    assert len(safe) < len(adult)
    assert all(
        not any(
            marker in (rule.category + " " + " ".join(rule.tags)).lower()
            for rule in site.rules
            for marker in ("porn", "nsfw", "adult")
        )
        for site in safe
    )
