"""D6: agency, party, hearing, last action and watched-only sit behind More filters; set filters show as chips that
remove one filter each; Copy link, Save search and Export share one Share / save menu."""

from playwright.sync_api import expect

TOTAL = "1384 bills"


def test_more_filters_is_closed_until_opened_and_counts_what_it_holds(device):
    page = device.open("#all")
    expect(page.locator("#filter-topic")).to_be_visible()
    expect(page.locator("#filter-chamber")).to_be_visible()
    expect(page.locator("#filter-stage")).to_be_visible()
    expect(page.locator("#filter-agency")).to_be_hidden()
    page.locator("#more-filters > summary").click()
    expect(page.locator("#filter-agency")).to_be_visible()
    page.select_option("#filter-outlook", label="Heard")
    expect(page.locator("#more-count")).to_have_text(" · 1")
    # A redraw (watched-only redraws the whole explorer) keeps it open.
    page.click("#watch-filter")
    expect(page.locator("#more-filters")).to_have_attribute("open", "")
    expect(page.locator("#more-count")).to_have_text(" · 2")


def test_an_address_with_a_hidden_filter_opens_more_filters(device):
    page = device.open("#all?agency=ers")
    expect(page.locator("#more-filters")).to_have_attribute("open", "")
    expect(page.locator("#filter-agency")).to_be_visible()


def test_chips_name_each_filter_and_remove_one_at_a_time(device):
    page = device.open("#all?chamber=Senate&topic=Education")
    chips = page.locator("#active-filters .filter-chip")
    expect(chips).to_have_count(2)
    expect(chips.nth(0)).to_contain_text("Policy area: Education")
    expect(chips.nth(1)).to_contain_text("Senate")
    page.locator('[data-clear-filter="chamber"]').click()
    expect(chips).to_have_count(1)
    expect(page.locator("#filter-chamber")).to_have_value("")
    expect(page.locator("#filter-topic")).to_have_value("Education")
    page.click("#clear-filters")
    expect(chips).to_have_count(0)
    expect(page.locator("#result-count")).to_have_text(TOTAL)


def test_no_chips_without_filters(device):
    page = device.open("#all")
    expect(page.locator("#active-filters .filter-chip")).to_have_count(0)
    expect(page.locator("#clear-filters")).to_have_count(0)


def test_share_menu_holds_the_three_actions_and_closes_on_an_outside_click(device):
    page = device.open("#all")
    expect(page.locator("#save-search")).to_be_hidden()
    page.locator("#share-menu > summary").click()
    for selector in ("#copy-view-link", "#save-search", "#export-csv"):
        expect(page.locator(selector)).to_be_visible()
    page.locator("#page-title").click()
    expect(page.locator("#share-menu")).not_to_have_attribute("open", "")
