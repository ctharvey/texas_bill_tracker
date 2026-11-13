"""Watchlist: star from a card and from the bill page, nav count, the Watchlist view, persistence, file export/import."""

import json

from playwright.sync_api import expect

WATCH_KEY = "tx-bill-atlas-watch-90r"


def watched_cards(page):
    """Cards for watched bills (unwatched companions shown for context are excluded)."""
    return page.locator("#bill-list .bill-card:not(.unwatched-companion)")


def card_ids(page):
    return sorted(page.eval_on_selector_all("#bill-list .bill-card:not(.unwatched-companion)",
                                            "els => els.map(e => e.dataset.billId)"))


def star(page, bill_id):
    return page.locator(f'#bill-list .bill-card[data-bill-id="{bill_id}"] [data-watch]')


def test_star_from_card_updates_nav_count_toast_and_storage(device):
    page = device.open("#all?query=HB110")
    expect(page.locator("#nav-watch")).to_have_text("0")
    expect(star(page, "HB110")).to_have_attribute("aria-pressed", "false")
    star(page, "HB110").click()
    expect(page.locator("#toast")).to_have_text("HB110 added to your watchlist")
    expect(star(page, "HB110")).to_have_attribute("aria-pressed", "true")
    expect(star(page, "HB110")).to_have_text("★")
    expect(page.locator("#nav-watch")).to_have_text("1")
    assert json.loads(device.storage()[WATCH_KEY]) == ["HB110"]

    star(page, "HB110").click()
    expect(page.locator("#toast")).to_have_text("HB110 removed from your watchlist")
    expect(star(page, "HB110")).to_have_text("☆")
    expect(page.locator("#nav-watch")).to_have_text("0")
    assert json.loads(device.storage()[WATCH_KEY]) == []


def test_star_from_the_bill_page(device):
    page = device.open("#bill?id=HB110")
    drawer = page.locator("#bill-page")
    expect(drawer).to_be_visible()
    btn = drawer.locator("[data-watch]")
    expect(btn).to_have_text("☆ Follow this bill")
    btn.click()
    expect(page.locator("#toast")).to_have_text("HB110 added to your watchlist")
    expect(drawer.locator("[data-watch]")).to_have_text("★ Remove from watchlist")
    expect(page.locator("#nav-watch")).to_have_text("1")
    assert json.loads(device.storage()[WATCH_KEY]) == ["HB110"]
    drawer.locator("[data-watch]").click()
    expect(drawer.locator("[data-watch]")).to_have_text("☆ Follow this bill")
    expect(page.locator("#nav-watch")).to_have_text("0")
    assert json.loads(device.storage()[WATCH_KEY]) == []


def test_watchlist_view_lists_exactly_watched_bills_and_survives_reload(device):
    page = device.open("#all?query=HB110")
    star(page, "HB110").click()
    page.goto(device.site.base + "#all?query=HB1001")
    expect(star(page, "HB1001")).to_be_visible()
    star(page, "HB1001").click()
    expect(page.locator("#nav-watch")).to_have_text("2")
    assert json.loads(device.storage()[WATCH_KEY]) == ["HB110", "HB1001"]

    device.open("#watchlist")
    expect(page.locator("#page-title")).to_contain_text("Your watchlist")
    expect(page.locator("#result-count")).to_have_text("2 bills")
    assert card_ids(page) == ["HB1001", "HB110"]

    # Reload: the list is read back from localStorage.
    device.open("#watchlist")
    expect(page.locator("#nav-watch")).to_have_text("2")
    expect(page.locator("#result-count")).to_have_text("2 bills")
    assert card_ids(page) == ["HB1001", "HB110"]

    # Unstarring in the Watchlist view removes the card from it.
    star(page, "HB110").click()
    expect(page.locator("#result-count")).to_have_text("1 bill")
    assert card_ids(page) == ["HB1001"]


def test_empty_watchlist_shows_hint_and_disabled_share(device):
    page = device.open("#watchlist")
    expect(page.locator("#result-count")).to_have_text("0 bills")
    expect(page.locator("#bill-list")).to_contain_text("Star bills from the explorer to follow them here.")
    expect(page.locator("#share-watch")).to_be_disabled()
    expect(page.locator("#export-watch")).to_be_disabled()


def test_export_file_is_download_of_watchlist(device):
    page = device.open("#all?query=HB110")
    star(page, "HB110").click()
    device.open("#watchlist")
    with page.expect_download() as dl:
        page.locator("#export-watch").click()
    download = dl.value
    assert download.suggested_filename == "texas-bill-atlas-saved.json"
    data = json.loads(open(download.path(), encoding="utf-8").read())
    assert data["format"] == "texas-bill-atlas-profile-v1"
    assert data["lists"] == [{"id": "main", "name": "Watchlist", "bills": ["HB110"]}]
    expect(page.locator("#toast")).to_have_text("Watchlist, followed legislators and saved searches exported")


def test_import_watchlist_json_file_adds_bills(device, tmp_path):
    f = tmp_path / "list.json"
    f.write_text(json.dumps({"format": "texas-bill-atlas-watchlist-v1", "bills": ["HB110", "HB1001", "HB9999999"]}))
    page = device.open("#watchlist")
    page.set_input_files("#import-watch-file", str(f))
    expect(page.locator("#toast")).to_have_text("Added 2 of 2 bills")
    expect(page.locator("#nav-watch")).to_have_text("2")
    assert json.loads(device.storage()[WATCH_KEY]) == ["HB110", "HB1001"]
    assert card_ids(page) == ["HB1001", "HB110"]


def test_import_plain_text_and_is_additive_and_deduplicated(device, tmp_path):
    page = device.open("#all?query=HB110")
    star(page, "HB110").click()
    device.open("#watchlist")
    f = tmp_path / "list.txt"
    f.write_text("please watch HB 110, hb1001 and HB1001")
    page.set_input_files("#import-watch-file", str(f))
    expect(page.locator("#toast")).to_have_text("Added 1 of 2 bills")
    assert json.loads(device.storage()[WATCH_KEY]) == ["HB110", "HB1001"]


def test_import_file_without_bills_fails_and_changes_nothing(device, tmp_path):
    f = tmp_path / "bad.txt"
    f.write_text("nothing to see here")
    page = device.open("#watchlist")
    page.set_input_files("#import-watch-file", str(f))
    expect(page.locator("#toast")).to_have_text("Import failed: No Texas bill numbers found")
    expect(page.locator("#nav-watch")).to_have_text("0")
    assert WATCH_KEY not in device.storage() or json.loads(device.storage()[WATCH_KEY]) == []
