"""The dashboard (#home): the default view, its search box, your bills since the last visit, and the visit stamp."""

import json

from playwright.sync_api import expect

WATCH_KEY = "tx-bill-atlas-watch-90r"
VISIT_KEY = "tx-bill-atlas-visit-v1"
PREFS_KEY = "tx-bill-atlas-prefs-v1"


def seeded(device_factory, site, items):
    origin = site.base.rstrip("/")
    return device_factory(storage={"cookies": [], "origins": [
        {"origin": origin, "localStorage": [{"name": k, "value": json.dumps(v)} for k, v in items.items()]}]})


def test_a_bare_address_opens_the_dashboard(device):
    page = device.open("")
    expect(page.locator("#home-search")).to_be_visible()
    expect(page.locator("#page-title")).to_contain_text("This session, at a glance.")
    assert page.url.endswith("#home")
    expect(page.locator('.nav-item[data-view="home"]')).to_have_class("nav-item active")


def test_dashboard_search_hands_its_words_to_the_explorer(device):
    page = device.open("#home")
    page.fill("#home-search", "HB110")
    page.locator("#home-search-form button[type=submit]").click()
    expect(page.locator("#bill-search")).to_have_value("HB110")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    assert page.url.endswith("#all?query=HB110")
    page.go_back()
    expect(page.locator("#home-search")).to_be_visible()  # Back returns to the dashboard


def test_old_addresses_still_open_their_pages(device):
    page = device.open("#all")
    expect(page.locator("#bill-search")).to_be_visible()
    page = device.open("#today")
    expect(page.locator("#page-title")).to_contain_text("Today at the Lege.")


def test_your_bills_show_on_a_first_visit(device_factory, site):
    device = seeded(device_factory, site, {WATCH_KEY: ["HB110"]})
    page = device.open("#home")
    yours = page.locator(".home-card").first
    expect(yours.locator("h2")).to_contain_text("Latest on your bills")
    expect(yours.locator('[data-bill-id="HB110"]')).to_have_count(1)


def test_a_new_day_moves_the_visit_stamp_and_loading_leaves_prefs_alone(device_factory, site):
    prefs = {"filters": {"topic": "Labor"}}
    device = seeded(device_factory, site, {VISIT_KEY: {"day": "2020-01-01", "prev": None}, PREFS_KEY: prefs})
    page = device.open("#home")
    expect(page.locator(".home-card h2").first).to_contain_text("Since your last visit, Jan 1")
    stamp = json.loads(device.storage()[VISIT_KEY])
    assert stamp["prev"] == "2020-01-01" and stamp["day"] != "2020-01-01"
    assert json.loads(device.storage()[PREFS_KEY]) == prefs


def test_only_the_dashboard_stamps_a_visit(device):
    device.open("#all")
    device.open("#watchlist")
    assert VISIT_KEY not in device.storage()  # other pages never add a key on load
    device.open("#home")
    assert VISIT_KEY in device.storage()
