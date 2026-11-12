"""Statute tracking: the drawer list, the section page and its side-by-side compare, section search, and no index."""

import re

from playwright.sync_api import expect

SECTION = "#statute?law=LA&sec=62.051"


def drawer_statutes(device, bill="HB110"):
    page = device.open(f"#all?bill={bill}")
    return page, page.locator("#drawer-statutes")


def open_section(device):
    page = device.open(SECTION)
    page.wait_for_selector(".law-compare-wrap")
    return page


def pick_texts(page):
    return [page.locator(f"[data-law-side={s}]").evaluate("e=>e.options[e.selectedIndex].text") for s in ("left", "right")]


def test_drawer_lists_the_sections_the_bill_changes(device):
    page, box = drawer_statutes(device)
    expect(box).to_be_visible()
    expect(box.locator("h3")).to_have_text("Laws this bill changes (2)")
    items = box.locator(".law-list li")
    expect(items).to_have_count(2)
    first = items.filter(has_text="62.051")
    expect(first).to_contain_text("Labor Code")
    expect(first).to_contain_text("Minimum Wage")
    expect(first).to_contain_text("amends")
    expect(first).to_contain_text("7 other bills")
    expect(items.filter(has_text="62.151")).to_contain_text("repeals")
    # Only the contested amendment is called out in the intro.
    expect(box).to_contain_text("1 is also amended by other bills")


def test_drawer_link_opens_the_section_page(device):
    page, box = drawer_statutes(device)
    box.locator("a", has_text="62.051").click()
    page.wait_for_selector(".law-compare-wrap")
    assert page.url.endswith(SECTION)
    expect(page.locator("#page-title")).to_contain_text("One section of law")
    head = page.locator(".section-head").first
    expect(head).to_contain_text("Labor Code § 62.051")
    expect(head).to_contain_text("Minimum Wage")


def test_section_page_groups_bills_with_identical_wording(device):
    page = open_section(device)
    versions = page.locator(".law-version")
    expect(versions).to_have_count(4)
    same = versions.filter(has_text="same wording")
    expect(same).to_have_count(1)
    text = same.inner_text()
    for number in ("HB 110", "HB 132", "HB 856", "HB 972", "HB 1051"):
        assert number in text
    for number in ("HB 246", "SB 253", "SB 295"):
        expect(versions.filter(has_text=number)).to_have_count(1)
    # Every version of this section offers a comparison; each row names the bill's current stage.
    expect(page.locator("[data-law-compare]")).to_have_count(4)
    expect(versions.first.locator(".law-status").first).to_have_text("Filed")
    expect(page.locator(".today-group h3").first).to_contain_text("Bills that amend this section")


def test_side_by_side_defaults_to_current_law_against_a_version(device):
    page = open_section(device)
    left, right = pick_texts(page)
    assert left.startswith("Current law, as quoted in HB 110")
    assert right.startswith("HB 110 = HB 132 = HB 856 = HB 972 = HB 1051 · amended")
    legend = page.locator(".law-legend").inner_text()
    assert re.search(r"\d+ of \d+ parts? differs?", legend)
    expect(page.locator(".law-compare .law-row:not(.law-head)").first).to_be_visible()
    assert page.locator(".law-row mark").count() > 0, "changed words are highlighted"


def test_compare_button_puts_that_version_on_the_right(device):
    page = open_section(device)
    page.locator("[data-law-compare]").nth(1).click()
    expect(page.locator("[data-law-side=right]")).to_have_value("HB246")
    expect(page.locator("[data-law-side=left]")).to_have_value("law")
    assert pick_texts(page)[1].startswith("HB 246 · amended")


def test_bill_against_bill_compare(device):
    page = open_section(device)
    page.locator("[data-law-compare]").nth(1).click()  # right = HB 246
    left = page.locator("[data-law-side=left]")
    options = left.locator("option").all_inner_texts()
    other = next(o for o in options if o.startswith("SB 253"))
    left.select_option(label=other)
    assert pick_texts(page)[0].startswith("SB 253")
    assert pick_texts(page)[1].startswith("HB 246")
    legend = page.locator(".law-legend")
    expect(legend).to_contain_text("parts differ")
    expect(legend).not_to_contain_text("Pick two different versions")
    # Same bill on both sides asks for two different versions.
    page.locator("[data-law-side=right]").select_option(label=other)
    expect(legend).to_contain_text("Pick two different versions")


def test_phone_column_toggle(device, viewport):
    page = open_section(device)
    toggle = page.locator("[data-law-show=right]")
    if viewport == "desktop":
        expect(toggle).to_be_hidden()  # both columns always fit
        return
    both = page.locator("[data-law-show=both]")
    expect(both).to_have_attribute("aria-pressed", "true")
    row = page.locator(".law-row:not(.law-head)").first

    def visible_cells():
        return row.locator(".law-cell").evaluate_all("c=>c.filter(x=>getComputedStyle(x).display!=='none').map(x=>x.dataset.name)")

    assert len(visible_cells()) == 2
    toggle.click()
    expect(page.locator(".law-compare")).to_have_attribute("data-show", "right")
    expect(toggle).to_have_attribute("aria-pressed", "true")
    assert len(visible_cells()) == 1
    page.locator("[data-law-show=left]").click()
    expect(page.locator(".law-compare")).to_have_attribute("data-show", "left")
    shown_left = visible_cells()
    page.locator("[data-law-show=right]").click()
    assert visible_cells() != shown_left, "left and right show different columns"
    both.click()
    assert len(visible_cells()) == 2


def test_bill_opened_from_the_section_page_keeps_the_section_in_the_address(device):
    page = open_section(device)
    page.locator(".law-version a.bill-number").first.click()
    expect(page.locator("#detail-drawer")).to_be_visible()
    assert "bill=" in page.url and "statute" in page.url and "sec=62.051" in page.url
    page.keyboard.press("Escape")
    expect(page.locator("#detail-drawer")).to_be_hidden()
    assert "bill=" not in page.url and page.url.endswith(SECTION)


def test_section_search_finds_every_bill_that_changes_it(device):
    page = open_section(device)
    on_page = {n.replace(" ", "") for n in page.locator(".law-version a.bill-number").all_inner_texts()}
    assert len(on_page) == 8
    page.locator("[data-view=all]").first.click()
    page.fill("#bill-search", "62.051")
    hint = page.locator(".statute-hint")
    expect(hint).to_be_visible()
    expect(hint.locator("a")).to_have_text("Labor Code § 62.051")
    expect(hint.locator("a")).to_have_attribute("href", re.compile(r"statute\?law=LA&sec=62\.051"))
    listed = page.locator("#bill-list")
    for bill in on_page:
        expect(listed.locator(f'[data-bill-id="{bill}"]')).to_have_count(1)
    expect(page.locator("#result-count")).to_have_text(re.compile(r"^\d+ bills$"))
    hint.locator("a").click()
    page.wait_for_selector(".law-compare-wrap")
    assert page.url.endswith(SECTION)


def test_section_search_by_code_name(device):
    page = device.open("#all")
    page.fill("#bill-search", "Labor Code 62.051")
    expect(page.locator(".statute-hint a")).to_have_text("Labor Code § 62.051")


def test_unknown_section_says_no_bill_changes_it(device):
    page = device.open("#statute?law=ED&sec=99.999")
    callout = page.locator(".info-callout").first
    expect(callout).to_contain_text("No bill in this snapshot changes")
    expect(callout.locator("a")).to_have_attribute("href", re.compile(r"statutes\.capitol\.texas\.gov"))


def test_malformed_section_address_is_refused(device):
    page = device.open("#statute?law=ED&sec=../x")
    expect(page.locator(".info-callout").first).to_contain_text("does not name a section of Texas law")


def test_without_the_index_nothing_breaks(device):
    device.context.route("**/live/statutes/index.json", lambda r: r.fulfill(status=404, body=""))
    page = device.open("#all?bill=HB110")
    expect(page.locator("#detail-drawer")).to_be_visible()
    expect(page.locator("#drawer-statutes")).to_be_hidden()
    assert page.locator("#drawer-statutes").inner_text().strip() == ""
    page.keyboard.press("Escape")
    page.fill("#bill-search", "62.051")
    expect(page.locator(".statute-hint")).to_have_count(0)
    page.goto(device.site.base + SECTION)
    expect(page.locator(".info-callout").first).to_contain_text("not available right now")
    expect(page.locator(".law-compare-wrap")).to_have_count(0)
