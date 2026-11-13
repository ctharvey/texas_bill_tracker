"""The bill page (#bill?id=): how it opens, old bill links, Back to results, what the header and sections show, and
its links and watch button."""

import json

from playwright.sync_api import expect

PAGE = "#bill-page"


def card(page, bill_id):
    return page.locator(f'article[data-bill-id="{bill_id}"]')


def open_from_list(device, bill_id="HB110"):
    """Search for the bill in the explorer so its card is on screen, as a person would."""
    page = device.open("#all")
    page.fill("#bill-search", bill_id)
    expect(card(page, bill_id)).to_have_count(1)
    return page


def test_opens_from_the_bill_number_on_a_card(device):
    page = open_from_list(device)
    expect(page.locator(PAGE)).to_have_count(0)
    card(page, "HB110").locator("a.bill-number").click()
    expect(page.locator(PAGE)).to_be_visible()
    expect(page.locator(".drawer-number")).to_have_text("90R / HB 110")
    assert page.url.endswith("#bill?id=HB110")  # a bill link is a link to the bill, not to a list
    expect(card(page, "HB110")).to_have_count(0)  # the page replaces the list
    expect(page.locator(".page-heading")).to_be_hidden()  # the bill's own header takes its place


def test_bill_number_link_is_the_bill_address(device):
    page = open_from_list(device)
    expect(card(page, "HB110").locator("a.bill-number")).to_have_attribute("href", "#bill?id=HB110")


def test_opens_from_empty_space_on_a_card(device):
    page = open_from_list(device)
    card(page, "HB110").click(position={"x": 3, "y": 3})
    if page.viewport_size["width"] >= 1200:
        # Wide screens preview first (test_bill_preview.py); Open bill goes on to the page.
        expect(page.locator("#bill-preview .bill-number")).to_have_text("HB 110")
        page.locator("#bill-preview .preview-actions [data-open]").click()
    expect(page.locator(".drawer-number")).to_have_text("90R / HB 110")


def test_opens_from_its_address(device):
    page = device.open("#bill?id=HB110")
    expect(page.locator(PAGE)).to_be_visible()
    expect(page.locator(".drawer-number")).to_have_text("90R / HB 110")
    expect(page.locator("#bill-page-title")).to_have_text("Relating to the minimum wage.")


def test_old_bill_link_redirects_to_the_bill_page(device):
    # RSS items, agent docs and saved links carry `#<view>?…&bill=`; they open the page without adding a history entry.
    page = device.open("#all?topic=Labor&bill=HB110")
    expect(page.locator(".drawer-number")).to_have_text("90R / HB 110")
    assert page.url.endswith("#bill?id=HB110")
    page.locator("#bill-back").click()
    expect(page.locator(PAGE)).to_have_count(0)
    assert page.url.endswith("#all?topic=Labor")  # Back to results goes to the list the link named


def test_unknown_bill_shows_a_not_found_page(device):
    page = device.open("#bill?id=HB1")  # not in the snapshot
    expect(page.locator(PAGE)).to_contain_text("HB1 is not in this snapshot")
    expect(page.locator(".drawer-number")).to_have_count(0)


def test_header_pills_title_and_caption(device):
    page = device.open("#bill?id=HB110")
    bill = page.locator(PAGE)
    pills = bill.locator(".drawer-pills").first
    expect(pills.locator(".chamber-pill")).to_have_text("House")
    expect(pills.locator(".status-pill")).to_have_text("Filed")
    expect(pills.locator(".party-pill")).to_have_text("Democratic author")
    expect(bill.locator("#bill-page-title")).to_have_text("Relating to the minimum wage.")
    expect(bill.locator(".drawer-caption")).to_have_text("Relating to the minimum wage.")
    meta = bill.locator(".drawer-meta-grid")
    expect(meta).to_contain_text("Nov 9, 2026")  # filed on
    expect(meta).to_contain_text("No hearing yet")  # hearing status


def test_luna_block_for_a_reviewed_bill(device):
    page = device.open("#bill?id=HB110")
    luna = page.locator(f"{PAGE} .luna-block")
    expect(luna.locator("h3")).to_have_text("Full-text review by Luna")
    expect(luna).to_contain_text("Reviewed Nov 12, 2026 · introduced text")
    expect(luna).to_contain_text("would require employers")  # the review's summary
    expect(luna.locator("h4")).to_have_text("Locations")
    expect(luna.locator("li")).to_contain_text("Statewide")


def test_authors_and_sponsors_lists_with_counts(device):
    page = device.open("#bill?id=HB110")
    section = page.locator(f"{PAGE} section", has=page.locator("h3", has_text="Authors & sponsors"))
    expect(section.locator("h4")).to_have_text(["Authors (1)", "Coauthors (0)", "Sponsors (0)", "Cosponsors (0)"])
    author = section.locator("ul.member-list li")
    expect(author).to_have_count(1)
    expect(author).to_contain_text("Ana-María Rodríguez Ramos")
    expect(author).to_contain_text("Democratic · HD 102")
    expect(author.locator("a.text-link").first).to_have_attribute("href", "#member?code=A3735")
    expect(author.locator("a.member-official")).to_have_attribute("target", "_blank")
    expect(section.get_by_text("None listed in the source snapshot")).to_have_count(3)


def test_agency_section_when_no_agency_is_tagged(device):
    page = device.open("#bill?id=HB110")
    bill = page.locator(PAGE)
    expect(bill.locator("h3", has_text="Potentially affected agencies (0)")).to_have_count(1)
    expect(bill).to_contain_text("No agency has been tagged yet.")


def test_agency_list_for_a_bill_with_an_agency(device):
    page = device.open("#bill?id=HB147")
    bill = page.locator(PAGE)
    expect(bill.locator("h3", has_text="Potentially affected agencies (1)")).to_have_count(1)
    rows = bill.locator(".agency-row")
    expect(rows).to_have_count(1)
    expect(rows.first.locator("strong")).to_have_text("Health and Human Services Commission")
    expect(rows.first).to_contain_text("administration of the grant program")
    expect(rows.first.locator(".confidence")).to_have_text("Luna · direct")


def test_official_links_and_ai_readable_link(device):
    page = device.open("#bill?id=HB110")
    bill = page.locator(PAGE)
    history = "https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&Bill=HB110"
    expect(bill.get_by_role("link", name="Read official bill ↗")).to_have_attribute("href", history)
    expect(bill.get_by_role("link", name="Texas Legislature Online ↗")).to_have_attribute("href", history)
    expect(bill.get_by_role("link", name="AI-readable version ↗")).to_have_attribute(
        "href", "https://agent.bills.ctharvey.me/bills/HB110.md")
    for name in ("Read official bill ↗", "Texas Legislature Online ↗", "AI-readable version ↗"):
        link = bill.get_by_role("link", name=name)
        expect(link).to_have_attribute("target", "_blank")
        expect(link).to_have_attribute("rel", "noopener noreferrer")


def test_rss_link_points_at_the_bills_feed(device):
    page = device.open("#bill?id=HB110")
    rss = page.locator(f"{PAGE} a", has_text="RSS feed")
    expect(rss).to_have_attribute("href", "./live/feeds/HB110.xml")
    assert page.evaluate("document.querySelector('#bill-page a[href$=\"HB110.xml\"]').href").endswith(
        "/live/feeds/HB110.xml")


def test_watch_button_toggles_and_saves(device):
    page = device.open("#bill?id=HB110")
    watch = page.locator(f"{PAGE} [data-watch]")
    expect(watch).to_have_text("☆ Follow this bill")
    watch.click()
    expect(watch).to_have_text("★ Remove from watchlist")
    expect(page.locator("#toast")).to_have_text("HB110 added to your watchlist")
    assert json.loads(device.storage()["tx-bill-atlas-watch-90r"]) == ["HB110"]
    expect(page.locator("#nav-watch")).to_have_text("1")
    watch.click()
    expect(watch).to_have_text("☆ Follow this bill")
    expect(page.locator("#toast")).to_have_text("HB110 removed from your watchlist")
    expect(page.locator("#nav-watch")).to_have_text("0")
    assert json.loads(device.storage()["tx-bill-atlas-watch-90r"]) == []


def test_focus_moves_to_the_bill_title(device):
    page = device.open("#bill?id=HB110")
    expect(page.locator("#bill-page-title")).to_be_focused()


def test_back_to_results_restores_the_list(device):
    page = open_from_list(device)
    before = page.url
    card(page, "HB110").locator("a.bill-number").click()
    expect(page.locator(PAGE)).to_be_visible()
    page.locator("#bill-back").click()
    expect(page.locator(PAGE)).to_have_count(0)
    expect(page).to_have_url(before)
    expect(page.locator("#bill-search")).to_have_value("HB110")
    expect(card(page, "HB110")).to_have_count(1)


def test_back_to_results_from_a_first_page_goes_to_the_explorer(device):
    page = device.open("#bill?id=HB110")
    page.locator("#bill-back").click()
    expect(page.locator(PAGE)).to_have_count(0)
    assert page.url.split("#", 1)[1].startswith("all")


def test_browser_back_returns_to_the_list_as_it_was_left(device):
    page = open_from_list(device)
    before = page.url
    card(page, "HB110").locator("a.bill-number").click()
    expect(page.locator(PAGE)).to_be_visible()
    page.go_back()
    expect(page).to_have_url(before)
    expect(page.locator(PAGE)).to_have_count(0)
    expect(page.locator("#bill-search")).to_have_value("HB110")  # the list is as it was left


def test_back_restores_how_many_results_were_showing_and_the_scroll_position(device):
    page = device.open("#all")
    page.locator("#load-more").click()
    expect(page.locator("#dynamic-content .bill-card")).to_have_count(60)
    target = page.locator("#dynamic-content .bill-card").nth(40)
    target.scroll_into_view_if_needed()
    page.evaluate("window.scrollBy({top: 100, behavior: 'instant'})")
    y = page.evaluate("Math.round(scrollY)")
    target.locator(".bill-open").click()
    expect(page.locator(PAGE)).to_be_visible()
    assert page.evaluate("scrollY") == 0  # a bill page starts at its top
    page.locator("#bill-back").click()
    expect(page.locator("#dynamic-content .bill-card")).to_have_count(60)
    assert abs(page.evaluate("Math.round(scrollY)") - y) <= 1
    # The browser's Back does the same.
    target.locator(".bill-open").click()
    expect(page.locator(PAGE)).to_be_visible()
    page.go_back()
    expect(page.locator("#dynamic-content .bill-card")).to_have_count(60)
    assert abs(page.evaluate("Math.round(scrollY)") - y) <= 1


def test_moving_from_bill_to_bill_keeps_where_back_to_results_goes(device):
    page = open_from_list(device)
    before = page.url
    card(page, "HB110").locator("a.bill-number").click()
    expect(page.locator(PAGE)).to_be_visible()
    page.evaluate("location.hash = '#bill?id=HB147'")
    expect(page.locator(".drawer-number")).to_have_text("90R / HB 147")
    page.locator("#bill-back").click()
    expect(page).to_have_url(before)
