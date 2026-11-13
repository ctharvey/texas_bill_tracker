"""The bill drawer: how it opens and closes, what the header and sections show, and its links and watch button."""

import json
import re

from playwright.sync_api import expect

DRAWER = "#detail-drawer"


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
    expect(page.locator(DRAWER)).to_be_hidden()
    card(page, "HB110").locator("a.bill-number").click()
    expect(page.locator(DRAWER)).to_be_visible()
    expect(page.locator(".drawer-number")).to_have_text("90R / HB 110")
    assert page.url.endswith("#all?query=HB110&bill=HB110")  # the address bar describes filters and the open bill
    assert page.evaluate("document.body.style.overflow") == "hidden"  # the page behind does not scroll


def test_opens_from_empty_space_on_a_card(device):
    page = open_from_list(device)
    card(page, "HB110").click(position={"x": 3, "y": 3})
    expect(page.locator(".drawer-number")).to_have_text("90R / HB 110")


def test_opens_from_a_link_with_the_bill_in_the_hash(device):
    page = device.open("#all?bill=HB110")
    expect(page.locator(DRAWER)).to_be_visible()
    expect(page.locator(".drawer-number")).to_have_text("90R / HB 110")
    expect(page.locator(f"{DRAWER} h2")).to_have_text("Relating to the minimum wage.")


def test_unknown_bill_in_the_hash_opens_no_drawer(device):
    page = device.open("#all?bill=HB1")  # not in the snapshot
    expect(page.locator(DRAWER)).to_be_hidden()


def test_header_pills_title_and_caption(device):
    page = device.open("#all?bill=HB110")
    drawer = page.locator(DRAWER)
    pills = drawer.locator(".drawer-pills").first
    expect(pills.locator(".chamber-pill")).to_have_text("House")
    expect(pills.locator(".status-pill")).to_have_text("Filed")
    expect(pills.locator(".party-pill")).to_have_text("Democratic author")
    expect(drawer.locator("h2")).to_have_text("Relating to the minimum wage.")
    expect(drawer.locator(".drawer-caption")).to_have_text("Relating to the minimum wage.")
    meta = drawer.locator(".drawer-meta-grid")
    expect(meta).to_contain_text("Nov 9, 2026")  # filed on
    expect(meta).to_contain_text("No hearing yet")  # hearing status


def test_luna_block_for_a_reviewed_bill(device):
    page = device.open("#all?bill=HB110")
    luna = page.locator(f"{DRAWER} .luna-block")
    expect(luna.locator("h3")).to_have_text("Full-text review by Luna")
    expect(luna).to_contain_text("Reviewed Nov 12, 2026 · introduced text")
    expect(luna).to_contain_text("would require employers")  # the review's summary
    expect(luna.locator("h4")).to_have_text("Locations")
    expect(luna.locator("li")).to_contain_text("Statewide")


def test_authors_and_sponsors_lists_with_counts(device):
    page = device.open("#all?bill=HB110")
    section = page.locator(f"{DRAWER} section", has=page.locator("h3", has_text="Authors & sponsors"))
    expect(section.locator("h4")).to_have_text(["Authors (1)", "Coauthors (0)", "Sponsors (0)", "Cosponsors (0)"])
    author = section.locator("ul.member-list li")
    expect(author).to_have_count(1)
    expect(author).to_contain_text("Ana-María Rodríguez Ramos")
    expect(author).to_contain_text("Democratic · HD 102")
    expect(author.locator("a.text-link").first).to_have_attribute("href", "#member?code=A3735")
    expect(author.locator("a.member-official")).to_have_attribute("target", "_blank")
    expect(section.get_by_text("None listed in the source snapshot")).to_have_count(3)


def test_agency_section_when_no_agency_is_tagged(device):
    page = device.open("#all?bill=HB110")
    drawer = page.locator(DRAWER)
    expect(drawer.locator("h3", has_text="Potentially affected agencies (0)")).to_have_count(1)
    expect(drawer).to_contain_text("No agency has been tagged yet.")


def test_agency_list_for_a_bill_with_an_agency(device):
    page = device.open("#all?bill=HB147")
    drawer = page.locator(DRAWER)
    expect(drawer.locator("h3", has_text="Potentially affected agencies (1)")).to_have_count(1)
    rows = drawer.locator(".agency-row")
    expect(rows).to_have_count(1)
    expect(rows.first.locator("strong")).to_have_text("Health and Human Services Commission")
    expect(rows.first).to_contain_text("administration of the grant program")
    expect(rows.first.locator(".confidence")).to_have_text("Luna · direct")


def test_official_links_and_ai_readable_link(device):
    page = device.open("#all?bill=HB110")
    drawer = page.locator(DRAWER)
    history = "https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&Bill=HB110"
    expect(drawer.get_by_role("link", name="Read official bill ↗")).to_have_attribute("href", history)
    expect(drawer.get_by_role("link", name="Texas Legislature Online ↗")).to_have_attribute("href", history)
    expect(drawer.get_by_role("link", name="AI-readable version ↗")).to_have_attribute(
        "href", "https://agent.bills.ctharvey.me/bills/HB110.md")
    for name in ("Read official bill ↗", "Texas Legislature Online ↗", "AI-readable version ↗"):
        link = drawer.get_by_role("link", name=name)
        expect(link).to_have_attribute("target", "_blank")
        expect(link).to_have_attribute("rel", "noopener noreferrer")


def test_rss_link_points_at_the_bills_feed(device):
    page = device.open("#all?bill=HB110")
    rss = page.locator(f"{DRAWER} a", has_text="RSS feed")
    expect(rss).to_have_attribute("href", "./live/feeds/HB110.xml")
    assert page.evaluate("document.querySelector('#detail-drawer a[href$=\"HB110.xml\"]').href").endswith(
        "/live/feeds/HB110.xml")


def test_watch_button_toggles_and_saves(device):
    page = device.open("#all?bill=HB110")
    watch = page.locator(f"{DRAWER} [data-watch]")
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


def test_focus_moves_to_the_close_button(device):
    page = device.open("#all?bill=HB110")
    expect(page.locator("#drawer-close")).to_be_focused()


def test_close_button_closes_and_restores_the_hash(device):
    page = open_from_list(device)
    before = page.url
    card(page, "HB110").locator("a.bill-number").click()
    expect(page.locator(DRAWER)).to_be_visible()
    assert "bill=HB110" in page.url
    page.locator("#drawer-close").click()
    expect(page.locator(DRAWER)).to_be_hidden()
    expect(page.locator("#drawer-scrim")).to_be_hidden()
    expect(page).to_have_url(before)  # the history entry the bill added is stepped back over
    assert page.evaluate("document.body.style.overflow") == ""


def test_close_from_a_direct_link_keeps_the_page_and_drops_the_bill(device):
    page = device.open("#all?bill=HB110")
    page.locator("#drawer-close").click()
    expect(page.locator(DRAWER)).to_be_hidden()
    assert "bill=" not in page.url
    assert page.url.split("#", 1)[1].startswith("all")


def test_escape_closes_the_drawer(device):
    page = open_from_list(device)
    card(page, "HB110").locator("a.bill-number").click()
    expect(page.locator(DRAWER)).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(DRAWER)).to_be_hidden()
    assert "bill=" not in page.url


def test_scrim_click_closes_the_drawer_where_the_scrim_is_reachable(device, viewport):
    page = device.open("#all?bill=HB110")
    expect(page.locator("#drawer-scrim")).to_be_visible()
    width = page.evaluate("document.querySelector('#detail-drawer').getBoundingClientRect().width")
    if viewport == "phone":
        # The drawer takes the whole screen, so there is no scrim to tap; Back or the x close it.
        assert width == page.viewport_size["width"]
        return
    assert width < page.viewport_size["width"]
    page.locator("#drawer-scrim").click(position={"x": 10, "y": 10})
    expect(page.locator(DRAWER)).to_be_hidden()
    expect(page.locator("#drawer-scrim")).to_be_hidden()


def test_browser_back_closes_the_drawer_and_restores_the_previous_hash(device):
    page = open_from_list(device)
    before = page.url
    card(page, "HB110").locator("a.bill-number").click()
    expect(page.locator(DRAWER)).to_be_visible()
    page.go_back()
    expect(page).to_have_url(before)
    expect(page.locator(DRAWER)).to_be_hidden()
    expect(page.locator("#bill-search")).to_have_value("HB110")  # the list behind it is as it was left
