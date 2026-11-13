"""The search page (#all) says what search looks at, runs its examples on click, and says why each result matched."""

from playwright.sync_api import expect


def test_what_search_looks_at_lists_the_fields_and_its_examples_run(device):
    page = device.open("#all")
    help_ = page.locator(".search-help")
    help_.locator("summary").click()
    expect(help_).to_contain_text("affected group")
    expect(help_).to_contain_text("Luna search term")
    help_.locator('[data-search-example="HB 110"]').click()
    expect(page.locator("#bill-search")).to_have_value("HB 110")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    assert page.url.endswith("#all?query=HB%20110")


def test_each_result_says_why_it_matched(device):
    page = device.open("#all?query=HB110")
    expect(page.locator('article[data-bill-id="HB110"] .match-reason')).to_have_text("Matched: bill number")
    page = device.open('#all?query=%22minimum%20wage%22')
    expect(page.locator(".bill-card .match-reason").first).to_contain_text("minimum wage")


def test_no_reason_line_without_a_search(device):
    page = device.open("#all")
    expect(page.locator(".bill-card").first).to_be_visible()
    expect(page.locator(".match-reason")).to_have_count(0)
