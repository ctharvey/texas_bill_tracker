"""Affected-agency combobox in the explorer filter row."""

from playwright.sync_api import expect

from harness import click, reveal

TOTAL = "1384 bills"


def visible_labels(page):
    return [t.strip() for t in page.locator("#agency-options [data-agency-option]:visible").evaluate_all(
        "els => els.map(e => e.dataset.agencyLabel)")]


def numbers(page):
    return page.locator(".bill-card .bill-number").all_inner_texts()


def test_focus_opens_the_full_list(device):
    page = device.open("#all")
    expect(page.locator("#agency-options")).to_be_hidden()
    click(page, "#filter-agency")
    expect(page.locator("#agency-options")).to_be_visible()
    expect(page.locator("#filter-agency")).to_have_attribute("aria-expanded", "true")
    labels = visible_labels(page)
    assert labels[0] == "All affected agencies"
    assert "General Land Office" in labels and "Employees Retirement System of Texas" in labels
    assert len(labels) > 10


def test_typing_narrows_the_options(device):
    page = device.open("#all")
    click(page, "#filter-agency")
    full = visible_labels(page)
    reveal(page, "#filter-agency"); page.fill("#filter-agency", "land")
    labels = visible_labels(page)
    assert labels and len(labels) < len(full)
    assert all("land" in label.lower() for label in labels)
    assert "General Land Office" in labels
    reveal(page, "#filter-agency"); page.fill("#filter-agency", "zzzznope")
    assert visible_labels(page) == []
    expect(page.locator("#agency-no-results")).to_be_visible()
    expect(page.locator("#agency-no-results")).to_have_text("No matching agencies")
    reveal(page, "#filter-agency"); page.fill("#filter-agency", "land")
    expect(page.locator("#agency-no-results")).to_be_hidden()


def test_option_counts_are_shown(device):
    page = device.open("#all")
    click(page, "#filter-agency")
    row = page.locator('[data-agency-option="ers"]')
    expect(row).to_contain_text("Employees Retirement System of Texas")
    expect(row.locator(".agency-option-count")).to_have_text("4")


def test_click_picks_an_agency_and_filters(device):
    page = device.open("#all")
    click(page, "#filter-agency")
    page.locator('[data-agency-option="ers"]').click()
    expect(page.locator("#result-count")).to_have_text("4 bills")
    assert sorted(numbers(page)) == ["HB 234", "HB 430", "HB 690", "SB 108"]
    expect(page.locator("#filter-agency")).to_have_value("Employees Retirement System of Texas")
    expect(page.locator("#agency-options")).to_be_hidden()
    assert page.evaluate("location.hash") == "#all?agency=ers"


def test_keyboard_arrows_and_enter_pick(device):
    page = device.open("#all")
    click(page, "#filter-agency")
    reveal(page, "#filter-agency"); page.fill("#filter-agency", "land")
    page.keyboard.press("ArrowDown")
    active = page.locator("#agency-options .agency-option.active")
    expect(active).to_have_count(1)
    expect(active).to_have_text("General Land Office1")
    active_id = active.get_attribute("id")
    assert active_id
    expect(page.locator("#filter-agency")).to_have_attribute("aria-activedescendant", active_id)
    page.keyboard.press("Enter")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    assert numbers(page) == ["HB 542"]
    expect(page.locator("#filter-agency")).to_have_value("General Land Office")
    expect(page.locator("#agency-options")).to_be_hidden()
    assert page.evaluate("location.hash") == "#all?agency=glo"


def test_arrow_down_moves_through_options_and_up_goes_back(device):
    page = device.open("#all")
    click(page, "#filter-agency")
    page.keyboard.press("ArrowDown")
    first = page.locator("#agency-options .agency-option.active")
    expect(first).to_have_text("All affected agencies")
    page.keyboard.press("ArrowDown")
    expect(page.locator("#agency-options .agency-option.active")).to_have_attribute("data-agency-option", "all-state-agencies")
    page.keyboard.press("ArrowUp")
    expect(page.locator("#agency-options .agency-option.active")).to_have_text("All affected agencies")
    page.keyboard.press("ArrowUp")  # wraps to the last visible option
    labels = visible_labels(page)
    expect(page.locator("#agency-options .agency-option.active")).to_have_attribute("data-agency-label", labels[-1])


def test_enter_without_a_highlight_picks_the_first_match(device):
    page = device.open("#all")
    click(page, "#filter-agency")
    reveal(page, "#filter-agency"); page.fill("#filter-agency", "retirement")
    page.keyboard.press("Enter")
    expect(page.locator("#result-count")).to_have_text("4 bills")
    expect(page.locator("#filter-agency")).to_have_value("Employees Retirement System of Texas")


def test_choosing_all_agencies_clears_the_filter(device):
    page = device.open("#all?agency=ers")
    expect(page.locator("#result-count")).to_have_text("4 bills")
    expect(page.locator("#filter-agency")).to_have_value("Employees Retirement System of Texas")
    click(page, "#filter-agency")
    expect(page.locator('[data-agency-option="ers"]')).to_have_attribute("aria-selected", "true")
    page.locator('[data-agency-option=""]').click()
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    expect(page.locator("#filter-agency")).to_have_value("")
    assert page.evaluate("location.hash") == "#all"


def test_editing_the_text_drops_the_picked_agency(device):
    page = device.open("#all?agency=glo")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    click(page, "#filter-agency")
    page.keyboard.type("x")
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    assert "agency=" not in page.evaluate("location.hash")


def test_escape_closes_and_restores_the_picked_name(device):
    page = device.open("#all?agency=ers")
    click(page, "#filter-agency")
    reveal(page, "#filter-agency"); page.fill("#filter-agency", "zz")
    page.keyboard.press("Escape")
    expect(page.locator("#agency-options")).to_be_hidden()
    expect(page.locator("#filter-agency")).to_have_attribute("aria-expanded", "false")
    # Typing dropped the filter, so with nothing picked the box is empty again.
    expect(page.locator("#filter-agency")).to_have_value("")


def test_escape_with_a_pick_keeps_the_name(device):
    page = device.open("#all?agency=ers")
    click(page, "#filter-agency")
    expect(page.locator("#agency-options")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#agency-options")).to_be_hidden()
    expect(page.locator("#filter-agency")).to_have_value("Employees Retirement System of Texas")
    expect(page.locator("#result-count")).to_have_text("4 bills")
    expect(page.locator("#bill-page")).to_be_hidden()


def test_clicking_elsewhere_hides_the_list(device):
    page = device.open("#all")
    click(page, "#filter-agency")
    expect(page.locator("#agency-options")).to_be_visible()
    page.locator("#page-title").click()
    expect(page.locator("#agency-options")).to_be_hidden()
    expect(page.locator("#result-count")).to_have_text(TOTAL)


def test_tab_away_hides_the_list(device):
    page = device.open("#all")
    click(page, "#filter-agency")
    expect(page.locator("#agency-options")).to_be_visible()
    page.keyboard.press("Tab")
    expect(page.locator("#agency-options")).to_be_hidden()


def test_agency_filter_also_lists_bills_tagged_through_a_companion(device):
    page = device.open("#all")
    click(page, "#filter-agency")
    # The option's badge counts bills tagged with the agency itself ...
    expect(page.locator('[data-agency-option="dshs"] .agency-option-count')).to_have_text("24")
    page.locator('[data-agency-option="dshs"]').click()
    # ... the results add one bill that is listed only because its companion carries the agency.
    expect(page.locator("#result-count")).to_have_text("25 bills")
    via = page.locator(".via-companion")
    expect(via).to_have_count(1)
    expect(via).to_have_text("via companion SB 105")
    assert via.locator("xpath=ancestor::article").get_attribute("data-bill-id") == "HB656"


def test_focus_by_keyboard_opens_the_list(device):
    page = device.open("#all")
    page.focus("#filter-agency")
    expect(page.locator("#agency-options")).to_be_visible()
    expect(page.locator("#filter-agency")).to_have_attribute("aria-expanded", "true")
