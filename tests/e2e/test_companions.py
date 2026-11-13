"""Companion and related-bill blocks on the bill page, and the one button that watches a whole companion group."""

import json

from playwright.sync_api import expect

DRAWER = "#bill-page"
WATCH_KEY = "tx-bill-atlas-watch-90r"


def companion_section(page):
    return page.locator(f"{DRAWER} .companion-section")


def watched(device):
    return sorted(json.loads(device.storage().get(WATCH_KEY, "[]")))


def test_bill_without_companions_has_no_companion_block(device):
    page = device.open("#bill?id=HB147")
    expect(page.locator(f"{DRAWER} h2")).to_be_visible()
    expect(companion_section(page)).to_have_count(0)


def test_companion_row_shows_number_chamber_relation_author_title_and_last_action(device):
    page = device.open("#bill?id=HB110")
    section = companion_section(page)
    expect(section.locator("h3")).to_have_text("Companion bill (1)")
    row = section.locator(".companion-row")
    expect(row).to_have_count(1)
    expect(row.locator("button.companion-open")).to_have_text("HB 972")
    expect(row.locator(".chamber-pill")).to_have_text("House")
    expect(row).to_contain_text("duplicate · by Simmons")
    expect(row.locator("p")).to_have_text("Relating to the minimum wage.")
    expect(row.locator(".action-tag")).to_contain_text("Filed")


def test_companion_link_opens_the_other_bill(device):
    page = device.open("#bill?id=HB110")
    companion_section(page).locator("button.companion-open").click()
    expect(page.locator(".drawer-number")).to_have_text("90R / HB 972")
    assert page.url.endswith("#bill?id=HB972")
    # ... and that bill lists HB 110 back, even though it does not carry HB 110 in its own record.
    expect(companion_section(page).locator("button.companion-open", has_text="HB 110")).to_have_count(1)


def test_a_bill_with_several_companions_lists_them_all_with_a_group_button(device):
    page = device.open("#bill?id=HB972")
    section = companion_section(page)
    expect(section.locator("h3")).to_have_text("Companion bills (4)")
    expect(section.locator("button.companion-open")).to_have_text(["HB 110", "HB 132", "HB 856", "HB 1051"])
    expect(section.locator(".companion-watch")).to_have_text("☆ Watch all 5")


def test_companion_listed_only_from_the_other_side_shows_the_senate_bill(device):
    # HB 1059 lists SB 164 as its companion; SB 164's own record lists none, yet its page shows HB 1059.
    page = device.open("#bill?id=SB164")
    row = companion_section(page).locator(".companion-row")
    expect(row).to_have_count(1)
    expect(row.locator("button.companion-open")).to_have_text("HB 1059")
    expect(row).to_contain_text("identical")
    expect(page.locator(f"{DRAWER} .drawer-pills .chamber-pill").first).to_have_text("Senate")


def test_group_watch_button_watches_every_bill_then_unwatches_all(device):
    page = device.open("#bill?id=HB110")
    button = companion_section(page).locator(".companion-watch")
    expect(button).to_have_text("☆ Watch all 2")
    expect(button).to_have_attribute("aria-pressed", "false")
    button.click()
    expect(button).to_have_text("★ Watching all 2")
    expect(button).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#toast")).to_have_text("Watching HB 110, HB 972")
    assert watched(device) == ["HB110", "HB972"]
    expect(page.locator("#nav-watch")).to_have_text("2")
    # The page's own watch button reflects it too.
    expect(page.locator(f"{DRAWER} [data-watch]")).to_have_text("★ Remove from watchlist")
    button.click()
    expect(button).to_have_text("☆ Watch all 2")
    expect(page.locator("#toast")).to_have_text("Removed HB 110, HB 972 from your watchlist")
    assert watched(device) == []


def test_group_button_counts_those_already_watched(device):
    page = device.open("#bill?id=HB110")
    page.locator(f"{DRAWER} [data-watch]").click()  # watch only HB 110
    button = companion_section(page).locator(".companion-watch")
    expect(button).to_have_text("☆ Watch all 2 (1 watched)")
    button.click()
    expect(button).to_have_text("★ Watching all 2")
    assert watched(device) == ["HB110", "HB972"]


def test_related_bills_block_links_to_each_related_bill(device):
    page = device.open("#bill?id=HB110")
    section = page.locator(f"{DRAWER} .related-section")
    expect(section.locator("h3")).to_have_text("Related bills")
    chips = section.locator("button.review-chip")
    expect(chips).to_have_text(["HB1051", "HB856", "SB295", "HB246", "HB132"])
    expect(section).to_contain_text("computed automatically")
    chips.nth(2).click()
    expect(page.locator(".drawer-number")).to_have_text("90R / SB 295")
    assert page.url.endswith("#bill?id=SB295")
    expect(page.locator(f"{DRAWER} .drawer-pills .chamber-pill").first).to_have_text("Senate")


def test_bill_with_a_single_related_entry(device):
    page = device.open("#bill?id=HB381")
    chips = page.locator(f"{DRAWER} .related-section button.review-chip")
    expect(chips).to_have_text(["HB1032"])
