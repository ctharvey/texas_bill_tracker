"""Method, saving, data and agencies pages: headings, the promises people rely on, and the agency index."""

import re

from playwright.sync_api import expect


def test_method_page(device):
    page = device.open("#method")
    expect(page.locator("#page-title")).to_contain_text("The scoring method.")
    expect(page.locator(".section-head h2")).to_have_text("Verified facts first. Forecasts second.")
    cards = page.locator(".method-card")
    expect(cards).to_have_count(6)
    assert [c.locator("h3").inner_text() for c in cards.all()] == [
        "What is affected", "Who filed it", "Chance of a hearing", "Likelihood of passage",
        "What changes over time", "Known limitations"]
    expect(page.locator(".info-callout")).to_contain_text("A filed bill is not a viable bill by default.")
    expect(cards.nth(3)).to_contain_text("No passage probabilities are currently claimed.")


def test_saving_page_headings(device):
    page = device.open("#saving")
    expect(page.locator("#page-title")).to_contain_text("Save your work.")
    heads = page.locator(".section-head h2").all_inner_texts()
    assert heads == ["Saving and sharing your info", "What is stored, and where"]
    expect(page.locator(".info-callout").first).to_contain_text("There are no logins on this site.")
    cards = page.locator(".method-card")
    expect(cards).to_have_count(9)
    titles = [c.locator("h3").inner_text() for c in cards.all()]
    assert titles == ["Your watchlist", "Remembered filters", "Links to any view", "Share links",
                      "Export and import a file", "Private sync links", "RSS feeds", "Followed legislators",
                      "Saved searches"]


def test_saving_page_privacy_promises(device):
    page = device.open("#saving")
    card = page.locator(".subpage-card")
    expect(card.locator(".data-field", has_text="Retention")).to_contain_text(
        "A sync link unused for a year is deleted. Deleting it yourself removes it at once")
    text = card.inner_text()
    assert "Deleting it yourself removes it at once" in text
    assert "A sync link unused for a year is deleted" in text
    expect(card.locator(".data-field", has_text="Never collected")).to_contain_text(
        "Names, email addresses, accounts, tracking cookies or analytics")
    expect(card.locator(".data-field", has_text="On this device")).to_contain_text("your sync link if you made one")
    expect(card.locator(".data-field", has_text="Abuse limits")).to_contain_text("never writes addresses down")


def test_saving_page_reports_this_device(device):
    page = device.open("#saving")
    expect(page.locator(".data-field:not(.long)", has_text="This device")).to_contain_text("Not synced · 0 bills watched")
    expect(page.locator(".data-field", has_text="Sync on this site")).to_contain_text("Available")


def test_saving_page_link_to_watchlist(device):
    page = device.open("#saving")
    page.locator('.section-head [data-view="watchlist"]').click()
    expect(page.locator("#page-title")).to_contain_text("Your watchlist.")
    assert page.url.endswith("#watchlist")


def test_data_page(device):
    page = device.open("#data")
    expect(page.locator("#page-title")).to_contain_text("Behind the tracker.")
    expect(page.locator(".section-head h2")).to_have_text("Source, coverage & export")
    field = lambda label: page.locator(".data-field", has_text=label).locator(".data-value")
    expect(field("Legislative session")).to_have_text("90R · 2027")
    expect(field("Snapshot mode")).to_have_text("official-ftp")
    expect(field("Read from")).to_have_text("Live server snapshot")
    loaded = int(field("Loaded records").inner_text())
    assert loaded == int(page.locator("#nav-all").inner_text().replace(",", ""))
    expect(field("Luna reviews")).to_contain_text("bills · updated")
    expect(field("Member roster")).to_contain_text("House")
    expect(page.locator(".info-callout")).to_contain_text("Official source policy:")
    expect(page.locator("#import-trigger")).to_be_visible()
    expect(page.locator("#export-csv")).to_be_visible()
    expect(page.locator('a[href="https://github.com/ctharvey/texas_bill_tracker"]').first).to_be_visible()


def test_agencies_index_lists_agencies_with_counts(device):
    page = device.open("#agencies")
    expect(page.locator("#page-title")).to_contain_text("Follow the agencies.")
    expect(page.locator(".section-head h2")).to_have_text("Texas state agencies")
    cards = page.locator(".agency-card")
    assert cards.count() > 30
    first = cards.first
    expect(first.locator(".agency-code")).to_have_text("HHSC")
    expect(first.locator("strong")).to_have_text("Health and Human Services Commission")
    expect(first.locator(".hits")).to_have_text(re.compile(r"^\d+ bills in snapshot →$"))
    # Sorted by how many bills each agency touches.
    hits = [int(h.split()[0]) for h in page.locator(".agency-card .hits").all_inner_texts()]
    assert hits == sorted(hits, reverse=True)
    assert hits[0] > 0
    expect(page.locator(".agency-card", has_text="Texas Facilities Commission").locator(".hits")).to_have_text(
        "1 bill in snapshot →")
    linked = page.locator(".section-head .subtitle").inner_text()
    assert re.fullmatch(r"\d+ with possible links in this snapshot", linked)


def test_agency_card_opens_the_explorer_filtered_to_that_agency(device):
    page = device.open("#agencies")
    card = page.locator(".agency-card", has_text="Texas Education Agency")
    claimed = int(card.locator(".hits").inner_text().split()[0])
    card.click()
    expect(page.locator("#page-title")).to_contain_text("See what’s moving.")
    assert "agency=tea" in page.url.lower()
    expect(page.locator("#filter-agency")).to_have_value(re.compile("Education Agency"))
    # The explorer shows at least the bills the directory promised (companion-linked bills may add more).
    shown = int(page.locator("#result-count").inner_text().split()[0].replace(",", ""))
    assert shown >= claimed
    assert shown < int(page.locator("#nav-all").inner_text().replace(",", ""))
