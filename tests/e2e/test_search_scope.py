"""The Bills / Laws buttons above the explorer search: both on shows both, one on shows only that kind, the last one on
stays on, and the choice rides in the address and the remembered explorer prefs. The law heading search files are
stubbed (the fixtures have no live/law)."""

import json
import re

from playwright.sync_api import expect

MANIFEST = {"format": "texas-bill-law-search-v1", "prefixes": {"min": 2, "wag": 2, "thi": 60}}
SHARDS = {
    "min": [["LA 62", "MINIMUM WAGE"], ["LA 62.051", "MINIMUM WAGE"]],
    "wag": [["LA 62", "MINIMUM WAGE"], ["LA 62.051", "MINIMUM WAGE"]],
    "thi": [[f"PE 46.{i:02d}", f"THING NUMBER {i}"] for i in range(10, 70)],
}


def stub_law_search(device):
    def fulfill(route):
        name = route.request.url.rsplit("/", 1)[-1].split("?")[0]
        if name == "index.json":
            return route.fulfill(status=200, body=json.dumps(MANIFEST), content_type="application/json")
        prefix = name.removesuffix(".json")
        if prefix in SHARDS:
            return route.fulfill(status=200, body=json.dumps(SHARDS[prefix]), content_type="application/json")
        return route.fulfill(status=404, body="")
    device.context.route("**/live/law/search/*", fulfill)


def button(page, kind):
    return page.locator(f'[data-search-scope="{kind}"]')


def test_both_is_the_default_and_shows_bills_and_law_headings(device):
    stub_law_search(device)
    page = device.open("#all")
    expect(button(page, "bills")).to_have_attribute("aria-pressed", "true")
    expect(button(page, "laws")).to_have_attribute("aria-pressed", "true")
    page.fill("#bill-search", "minimum wage")
    expect(page.locator(".law-heading-hint")).to_be_visible()
    expect(page.locator("#bill-list .bill-card").first).to_be_visible()
    expect(page.locator("#result-count")).to_have_text(re.compile(r"^\d+ bills?$"))
    assert "scope=" not in page.url


def test_laws_only_lists_laws_hides_bill_controls_and_survives_a_reload(device):
    stub_law_search(device)
    page = device.open("#all")
    page.fill("#bill-search", "minimum wage")
    button(page, "bills").click()
    expect(button(page, "bills")).to_have_attribute("aria-pressed", "false")
    expect(button(page, "laws")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#result-count")).to_have_text("2 laws")
    items = page.locator("#bill-list .law-result-list li")
    expect(items).to_have_count(2)
    expect(page.locator("#bill-list .bill-card")).to_have_count(0)
    expect(items.first.locator("a")).to_have_attribute("href", re.compile(r"/law/LA/62$"))
    for hidden in (".search-help", ".filter-bar", ".topic-strip", "#active-filters", "#sort-order", "#export-csv"):
        expect(page.locator(hidden)).to_be_hidden()
    expect(page.locator("#bill-search")).to_have_attribute("aria-label", "Search Texas law")
    expect(page.locator("#bill-search")).to_have_value("minimum wage")
    assert "scope=laws" in page.url

    button(page, "laws").click()  # The last one on stays on.
    expect(button(page, "laws")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#result-count")).to_have_text("2 laws")

    page.reload(wait_until="networkidle")
    expect(button(page, "bills")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#bill-list .law-result-list li")).to_have_count(2)
    assert json.loads(device.storage()["tx-bill-atlas-prefs-v1"])["scope"] == "laws"

    page = device.open("#all")  # The next visit, no scope in the address: the remembered one.
    expect(button(page, "laws")).to_have_attribute("aria-pressed", "true")
    expect(button(page, "bills")).to_have_attribute("aria-pressed", "false")

    button(page, "bills").click()  # Back to Both: the bill controls return.
    expect(page.locator(".filter-bar")).to_be_visible()
    expect(page.locator("#bill-list .bill-card").first).to_be_visible()
    assert "scope=" not in page.url


def test_laws_only_lists_an_exact_key_no_bill_changes_and_pages_long_lists(device):
    stub_law_search(device)
    page = device.open("/explorer?scope=laws&query=PE%201.01")
    expect(page.locator("#result-count")).to_have_text("1 law")
    expect(page.locator("#bill-list .law-result-list a")).to_have_attribute("href", re.compile(r"/law/PE/1\.01$"))
    page.fill("#bill-search", "thing")
    expect(page.locator("#result-count")).to_have_text("60 laws")
    expect(page.locator("#bill-list .law-result-list li")).to_have_count(50)
    page.locator("#law-more").click()
    expect(page.locator("#bill-list .law-result-list li")).to_have_count(60)
    expect(page.locator("#law-more")).to_have_count(0)
    page.fill("#bill-search", "")
    expect(page.locator(".law-results-intro")).to_contain_text("Search Texas law by words")


def test_bills_only_drops_the_heading_list_and_keeps_the_section_callout(device):
    stub_law_search(device)
    page = device.open("#all")
    button(page, "laws").click()
    expect(button(page, "laws")).to_have_attribute("aria-pressed", "false")
    assert "scope=bills" in page.url
    page.fill("#bill-search", "minimum wage")
    expect(page.locator("#bill-list .bill-card").first).to_be_visible()
    expect(page.locator(".law-heading-hint")).to_have_count(0)
    page.fill("#bill-search", "62.051")
    expect(page.locator(".statute-hint a")).to_have_text("Labor Code § 62.051")


def test_no_buttons_on_the_watchlist(device):
    page = device.open("#watchlist")
    expect(page.locator("#bill-search")).to_be_attached()
    expect(page.locator(".search-scope")).to_have_count(0)
