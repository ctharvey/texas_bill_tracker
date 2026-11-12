"""Every view renders from the frozen data in both serving modes, and the bundle is the production layout."""

import re

import pytest

VIEWS = {"all": "See what’s moving.", "watchlist": "Your watchlist.", "following": "Following.",
         "today": "Today at the Lege.", "local": "Near you.", "agencies": "Follow the agencies.",
         "review": "Full-text review.", "method": "The scoring method.", "saving": "Save your work.",
         "data": "Behind the tracker."}


@pytest.mark.layout
@pytest.mark.parametrize("view", list(VIEWS))
def test_view_renders(device, view):
    page = device.open(f"#{view}")
    assert page.locator("#dynamic-content").inner_text().strip()
    assert VIEWS[view].lower() in page.locator("#page-title").inner_text().lower()


def test_live_snapshot_is_used_not_the_bundled_fallback(device):
    page = device.open("#data")
    assert "Live server snapshot" in page.locator("#dynamic-content").inner_text()
    count = page.locator("#nav-all").inner_text()
    assert re.fullmatch(r"[\d,]+", count) and int(count.replace(",", "")) >= 1000


def test_bundle_mode_serves_versioned_assets(device, site):
    page = device.open("#all")
    scripts = page.evaluate("[...document.querySelectorAll('script[type=module]')].map(s=>s.getAttribute('src'))")
    if site.mode == "bundle":
        assert scripts == [f"./assets/{site.digest}/app.js"]
    else:
        assert scripts == ["./src/app.js"]
