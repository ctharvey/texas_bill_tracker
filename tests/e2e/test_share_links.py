"""Share links: what 'Copy share link' puts on the clipboard, and what a stranger sees when opening it."""

import json
import re

from playwright.sync_api import expect

WATCH_KEY = "tx-bill-atlas-watch-90r"


def allow_clipboard(device):
    device.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=device.site.base.rstrip("/"))


def clipboard(page):
    return page.evaluate("navigator.clipboard.readText()")


def star(page, bill_id):
    return page.locator(f'#bill-list .bill-card[data-bill-id="{bill_id}"] [data-watch]')


def build_rich_profile(device):
    """HB110 + HB1001 watched, one legislator followed, one saved search: the share link must carry only the bills."""
    page = device.open("#all?query=HB110")
    star(page, "HB110").click()
    page.goto(device.site.base + "#all?query=HB1001")
    star(page, "HB1001").click()
    device.open("#member?code=A2150")
    page.locator("button.follow-button").click()
    expect(page.locator("#toast")).to_contain_text("Following")
    device.open("#all?query=HB717")
    page.locator("#save-search").click()
    expect(page.locator("#toast")).to_contain_text("Saved ")
    return page


def test_copy_share_link_text_and_toast(device):
    allow_clipboard(device)
    page = build_rich_profile(device)
    device.open("#watchlist")
    page.locator("#share-watch").click()
    expect(page.locator("#toast")).to_have_text("Share link copied")
    link = clipboard(page)
    assert link == device.site.base + "#all?list=HB110,HB1001"


def test_share_link_never_carries_follows_searches_or_sync_keys(device, fresh_sync):
    allow_clipboard(device)
    page = build_rich_profile(device)
    device.open("#watchlist")
    expect(page.locator("#sync-create")).to_be_enabled()
    page.locator("#sync-create").click()
    expect(page.locator("#toast")).to_have_text("Sync link created. Copy the edit link to your other devices.")
    page.locator("#sync-copy-edit").click()
    expect(page.locator("#toast")).to_have_text("Edit link copied")
    edit_link = clipboard(page)
    edit_key = re.search(r"sync=([A-Za-z0-9_-]{22})$", edit_link).group(1)
    page.locator("#sync-copy-view").click()
    expect(page.locator("#toast")).to_have_text("View-only link copied")
    view_key = re.search(r"sync=([A-Za-z0-9_-]{22})$", clipboard(page)).group(1)
    assert view_key != edit_key

    page.locator("#share-watch").click()
    expect(page.locator("#toast")).to_have_text("Share link copied")
    link = clipboard(page)
    assert link == device.site.base + "#all?list=HB110,HB1001"
    for secret in ("A2150", "follow", "search", "sync", "HB717", "HB717".lower(), edit_key, view_key, "edit"):
        assert secret not in link, secret
    # The address bar never shows the edit key either.
    assert edit_key not in page.url


def test_stranger_opens_share_link_sees_banner_and_only_those_bills(device_factory, site):
    stranger = device_factory()
    page = stranger.open("#all?list=HB110,HB1001")
    banner = page.locator(".shared-banner")
    expect(banner).to_contain_text("Shared list · 2 bills.")
    expect(banner).to_contain_text("Opened from a link; your own watchlist is unchanged.")
    expect(page.locator("#result-count")).to_have_text("2 bills")
    ids = sorted(page.eval_on_selector_all("#bill-list .bill-card", "els => els.map(e => e.dataset.billId)"))
    assert ids == ["HB1001", "HB110"]
    # Read-only: nothing lands in the stranger's own watchlist or saved searches, and 'Save search' is not offered.
    expect(page.locator("#nav-watch")).to_have_text("0")
    expect(page.locator("#save-search")).to_have_count(0)
    assert json.loads(stranger.storage().get(WATCH_KEY, "[]")) == []
    # The link stays in the address bar.
    assert page.url.endswith("#all?list=HB110,HB1001")


def test_share_link_ignores_invalid_bill_numbers_and_duplicates(device_factory):
    page = device_factory().open("#all?list=hb110,NOPE,HB110,HB%201001,HB0")
    expect(page.locator(".shared-banner")).to_contain_text("Shared list · 2 bills.")
    expect(page.locator("#result-count")).to_have_text("2 bills")


def test_one_bill_share_banner_uses_singular(device_factory):
    page = device_factory().open("#all?list=HB110")
    expect(page.locator(".shared-banner")).to_contain_text("Shared list · 1 bill.")
    expect(page.locator("#result-count")).to_have_text("1 bill")


def test_adopt_shared_list_adds_to_own_watchlist(device_factory):
    stranger = device_factory()
    page = stranger.open("#all?query=HB717")
    star(page, "HB717").click()
    page.goto(stranger.site.base + "#all?list=HB110,HB1001")
    page.reload()
    page.wait_for_selector(".shared-banner")
    expect(page.locator("#nav-watch")).to_have_text("1")
    page.locator("#shared-add").click()
    expect(page.locator("#toast")).to_have_text("Added 2 bills to your watchlist")
    expect(page.locator("#nav-watch")).to_have_text("3")
    assert sorted(json.loads(stranger.storage()[WATCH_KEY])) == ["HB1001", "HB110", "HB717"]
    # Adding the same list again adds nothing.
    page.locator("#shared-add").click()
    expect(page.locator("#toast")).to_have_text("Added 0 bills to your watchlist")
    assert len(json.loads(stranger.storage()[WATCH_KEY])) == 3


def test_show_all_bills_leaves_the_shared_list(device_factory):
    page = device_factory().open("#all?list=HB110,HB1001")
    expect(page.locator("#result-count")).to_have_text("2 bills")
    page.locator("#shared-close").click()
    expect(page.locator(".shared-banner")).to_have_count(0)
    count = int(page.locator("#result-count").inner_text().split()[0].replace(",", ""))
    assert count > 100
    expect(page.locator("#save-search")).to_have_count(1)


def test_copy_view_link_copies_current_url_with_filters(device):
    allow_clipboard(device)
    page = device.open("#all?query=HB110&chamber=House")
    page.locator("#copy-view-link").click()
    expect(page.locator("#toast")).to_have_text("Link to this view copied")
    assert clipboard(page) == device.site.base + "#all?query=HB110&chamber=House"


def test_clipboard_blocked_falls_back_to_showing_the_link(device):
    # No clipboard permission granted: the toast shows the link itself so it can be copied by hand.
    page = device.open("#all?query=HB110")
    star(page, "HB110").click()
    device.open("#watchlist")
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: () => Promise.reject(new Error('no'))}})")
    page.locator("#share-watch").click()
    expect(page.locator("#toast")).to_have_text(f"Copy failed. Share link: {device.site.base}#all?list=HB110")
