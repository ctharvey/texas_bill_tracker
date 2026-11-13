"""The nav: Browse, Yours and About groups; Today lives on the dashboard; on a phone, a bottom bar with More."""

from playwright.sync_api import expect

BAR = ["Home", "Bill explorer", "Watchlist", "More"]


def test_groups_and_today_leaving_the_nav(device, viewport):
    page = device.open("#home")
    expect(page.locator('.sidebar [data-view="today"]')).to_have_count(0)
    expect(page.locator('.home-card a[data-view="today"]')).to_have_count(1)  # Today is reached from the dashboard
    expect(page.locator(".nav-label")).to_have_text(["BROWSE", "YOURS", "ABOUT"])
    if viewport == "desktop":
        expect(page.locator("#nav-more")).to_be_hidden()
        expect(page.locator(".sidebar [data-view]")).to_have_count(10)


def test_phone_bottom_bar_and_more_sheet(device, viewport):
    page = device.open("#all")
    if viewport != "phone":
        return
    bar = page.locator(".sidebar .nav-item:visible")
    expect(bar).to_have_count(4)
    for item, name in zip(bar.all(), BAR):
        expect(item).to_contain_text(name)
    more = page.locator("#nav-more")
    more.click()
    expect(more).to_have_attribute("aria-expanded", "true")
    expect(page.locator(".sidebar [data-view]:visible")).to_have_count(10)
    page.keyboard.press("Escape")
    expect(more).to_have_attribute("aria-expanded", "false")
    more.click()
    page.locator('.sidebar [data-view="method"]').click()
    expect(page.locator("#page-title")).to_contain_text("The scoring method.")
    expect(more).to_have_attribute("aria-expanded", "false")  # choosing a page closes the sheet


def test_phone_bar_leaves_the_last_card_clickable(device, viewport):
    page = device.open("#all")
    if viewport != "phone":
        return
    last = page.locator("#dynamic-content .bill-card").last
    last.scroll_into_view_if_needed()
    last.locator(".bill-open").click()  # not covered by the fixed bar
    expect(page.locator("#bill-page")).to_be_visible()
