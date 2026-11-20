"""Law search usability: plurals, named laws, chapter citations, best matches first with the search words marked, the
Changed by bills filter in Laws mode, and See all from the law list above the bills. The law heading search files are
stubbed (the fixtures have no live/law); the fixture statute index has bills changing LA 62.051, none LA 62.201."""

import json
import re

from playwright.sync_api import expect

MANIFEST = {"format": "texas-bill-law-search-v1", "prefixes": {"min": 3, "wag": 3, "thi": 60}}
WAGE = [["LA 62.201", "MINIMUM WAGES FOR SEASONAL WORKERS"], ["LA 62", "MINIMUM WAGE"], ["LA 62.051", "MINIMUM WAGE"]]
SHARDS = {
    "min": WAGE,
    "wag": WAGE,
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


def laws(page):
    return page.locator("#bill-list .law-result-list li")


def test_a_plural_finds_the_singular_best_match_first_with_the_words_marked(device):
    stub_law_search(device)
    page = device.open("/explorer?scope=laws&query=minimum%20wages")
    expect(page.locator("#result-count")).to_have_text("3 laws")
    # The heading that is the search comes first (the chapter before its section), the longer heading last.
    expect(laws(page).first.locator("a")).to_have_attribute("href", re.compile(r"/law/LA/62$"))
    expect(laws(page).last.locator("a")).to_have_attribute("href", re.compile(r"/law/LA/62\.201$"))
    expect(laws(page).first.locator("mark.law-match")).to_have_text(["Minimum", "Wage"])


def test_changed_by_bills_keeps_only_laws_a_bill_changes(device):
    stub_law_search(device)
    page = device.open("/explorer?scope=laws&query=minimum%20wage")
    expect(page.locator("#result-count")).to_have_text("3 laws")
    toggle = page.locator("#law-changed")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    toggle.click()
    expect(page.locator("#law-changed")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#result-count")).to_have_text("2 laws")  # LA 62.051 and its chapter, not LA 62.201.
    expect(page.locator("#result-note")).to_contain_text("changed by bills")
    expect(laws(page).locator("a[href$='/law/LA/62.201']")).to_have_count(0)
    page.locator("#law-changed").click()
    expect(page.locator("#result-count")).to_have_text("3 laws")


def test_a_named_law_and_a_chapter_citation_open_the_law(device):
    stub_law_search(device)
    page = device.open("/explorer?scope=laws")
    page.fill("#bill-search", "Public Information Act")
    expect(laws(page).first.locator("a")).to_have_attribute("href", re.compile(r"/law/GV/552$"))
    page.fill("#bill-search", "Tex. Penal Code ch. 46")
    expect(page.locator("#result-count")).to_have_text("1 law")
    expect(laws(page).locator("a")).to_have_attribute("href", re.compile(r"/law/PE/46$"))
    page.fill("#bill-search", "Tex. Penal Code 46.02")
    expect(laws(page).locator("a")).to_have_attribute("href", re.compile(r"/law/PE/46\.02$"))


def test_see_all_moves_from_the_law_list_above_the_bills_to_the_laws_view(device):
    stub_law_search(device)
    page = device.open("#all")
    page.fill("#bill-search", "thing")
    hint = page.locator(".law-heading-hint")
    expect(hint.locator("li")).to_have_count(5)
    see_all = page.locator("#law-see-all")
    expect(see_all).to_contain_text("See all 60 laws")
    see_all.click()
    expect(page.locator('[data-search-scope="bills"]')).to_have_attribute("aria-pressed", "false")
    expect(page.locator('[data-search-scope="laws"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#result-count")).to_have_text("60 laws")
    expect(page.locator("#bill-search")).to_have_value("thing")
    assert "scope=laws" in page.url
