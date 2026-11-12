"""Saved searches: save from the explorer, list under Following, rename, delete, reopen, 'new actions' counts."""

import json
import re

from playwright.sync_api import expect

SEARCHES_KEY = "tx-bill-atlas-searches-90r"
TODAY = "2026-11-12"  # the frozen clock (2026-11-12T15:49Z) is this Texas day


def stored(device):
    return json.loads(device.storage().get(SEARCHES_KEY, "[]"))


def seeded_device(device_factory, site, searches):
    origin = site.base.rstrip("/")
    return device_factory(storage={"cookies": [], "origins": [
        {"origin": origin, "localStorage": [{"name": SEARCHES_KEY, "value": json.dumps(searches)}]}]})


def explorer_count(page):
    return int(re.match(r"([\d,]+) bill", page.locator("#result-count").inner_text()).group(1).replace(",", ""))


def test_save_current_search_appears_under_following_with_name_and_count(device):
    page = device.open("#all?query=HB110")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    page.locator("#save-search").click()
    expect(page.locator("#toast")).to_have_text("Saved ““HB110”” · find it under Following")
    saved = stored(device)
    assert len(saved) == 1
    assert saved[0]["name"] == "“HB110”"
    assert saved[0]["filters"] == {"query": "HB110"}
    assert saved[0]["seen"] == TODAY
    expect(page.locator("#nav-follow")).to_have_text("1")

    device.open("#following")
    rows = page.locator(".saved-search")
    expect(rows).to_have_count(1)
    expect(rows.locator(".saved-search-name")).to_have_text("“HB110”")
    expect(rows.locator("p").first).to_have_text("Search “HB110”")
    expect(rows.locator(".saved-search-counts")).to_have_text("1 bill · opened Nov 12")
    expect(page.get_by_role("heading", name="Saved searches")).to_contain_text("1")


def test_count_matches_explorer_for_multi_filter_search(device):
    page = device.open("#all?chamber=Senate&sort=number")
    n = explorer_count(page)
    page.locator("#save-search").click()
    saved = stored(device)
    assert saved[0]["filters"] == {"chamber": "Senate", "sort": "number"}
    assert saved[0]["name"] == "Senate"
    device.open("#following")
    row = page.locator(".saved-search")
    expect(row.locator("p").first).to_have_text("Senate · Sorted by Bill number")
    expect(row.locator(".saved-search-counts strong")).to_have_text(f"{n:,}")


def test_saving_same_filters_twice_is_refused(device):
    page = device.open("#all?query=HB110")
    page.locator("#save-search").click()
    expect(page.locator("#toast")).to_contain_text("Saved ")
    page.locator("#save-search").click()
    expect(page.locator("#toast")).to_have_text("Already saved as ““HB110””")
    assert len(stored(device)) == 1


def test_saved_search_survives_reload(device):
    page = device.open("#all?query=HB110")
    page.locator("#save-search").click()
    page.reload()
    page.wait_for_selector("#dynamic-content *", state="attached")
    expect(page.locator("#nav-follow")).to_have_text("1")
    device.open("#following")
    expect(page.locator(".saved-search-name")).to_have_text("“HB110”")


def test_rename_search(device):
    page = device.open("#all?query=HB110")
    page.locator("#save-search").click()
    device.open("#following")
    page.locator("[data-search-rename]").click()
    box = page.locator('[data-search-rename-form] input[name="name"]')
    expect(box).to_have_value("“HB110”")
    box.fill("Water bill  ")
    box.press("Enter")
    expect(page.locator(".saved-search-name")).to_have_text("Water bill")
    assert [s["name"] for s in stored(device)] == ["Water bill"]
    assert stored(device)[0]["filters"] == {"query": "HB110"}
    # The new name persists.
    page.reload()
    page.wait_for_selector("#dynamic-content *", state="attached")
    expect(page.locator(".saved-search-name")).to_have_text("Water bill")


def test_delete_needs_second_click_then_toasts(device):
    page = device.open("#all?query=HB110")
    page.locator("#save-search").click()
    device.open("#following")
    delete = page.locator("[data-search-delete]")
    delete.click()
    expect(delete).to_have_text("Click again to delete")
    assert len(stored(device)) == 1
    delete.click()
    expect(page.locator("#toast")).to_have_text("Deleted ““HB110””")
    expect(page.locator(".saved-search")).to_have_count(0)
    assert stored(device) == []
    expect(page.locator("#nav-follow")).to_have_text("0")
    expect(page.locator("#dynamic-content")).to_contain_text("then choose Save search to keep it here")


def test_opening_saved_search_restores_filters_and_hash(device_factory, site):
    d = seeded_device(device_factory, site, [{"id": "abcdefgh12", "name": "Senate numbered",
                                              "filters": {"chamber": "Senate", "sort": "number"}, "seen": TODAY}])
    page = d.open("#following")
    link = page.locator(".saved-search-name")
    expect(link).to_have_text("Senate numbered")
    expect(link).to_have_attribute("href", "#all?chamber=Senate&sort=number")
    link.click()
    page.wait_for_function("location.hash === '#all?chamber=Senate&sort=number'")
    expect(page.locator("#filter-chamber")).to_have_value("Senate")
    expect(page.locator("#sort-order")).to_have_value("Bill number")
    expect(page.locator("#page-title")).to_contain_text("See what")
    expect(page.locator("#bill-list .bill-card").first).to_be_visible()
    assert page.eval_on_selector_all("#bill-list .bill-card", "els => els.every(e => /^S/.test(e.dataset.billId))")


def test_new_actions_count_and_opening_marks_seen(device_factory, site):
    # Never opened since 2000: every bill with a dated action counts as new.
    d = seeded_device(device_factory, site, [{"id": "abcdefgh12", "name": "Old", "filters": {"query": "HB110"}, "seen": "2000-01-01"}])
    page = d.open("#following")
    counts = page.locator(".saved-search-counts")
    expect(counts).to_have_text("1 bill · 1 with new actions · opened Jan 1")
    expect(page.locator(".saved-search-new")).to_have_text("1 with new actions")
    page.locator(".saved-search-name").click()
    page.wait_for_function("location.hash.startsWith('#all')")
    # Wait for the explorer to render: navigating on before the hashchange is handled leaves the app on Following.
    expect(page.locator("#page-title")).to_contain_text("See what")
    assert stored(d)[0]["seen"] == TODAY
    d.open("#following")
    expect(page.locator(".saved-search-counts")).to_have_text("1 bill · opened Nov 12")
    expect(page.locator(".saved-search-new")).to_have_count(0)


def test_future_seen_day_means_nothing_new(device_factory, site):
    d = seeded_device(device_factory, site, [{"id": "abcdefgh12", "name": "Fresh", "filters": {"query": "HB110"}, "seen": "2099-01-01"}])
    page = d.open("#following")
    expect(page.locator(".saved-search-counts")).to_have_text("1 bill · opened Jan 1")
    expect(page.locator(".saved-search-new")).to_have_count(0)


def test_search_limit_of_20(device_factory, site):
    searches = [{"id": f"id{i:08d}", "name": f"Search {i}", "filters": {"query": f"HB{i + 1}"}, "seen": TODAY} for i in range(20)]
    d = seeded_device(device_factory, site, searches)
    page = d.open("#all?query=HB110")
    page.locator("#save-search").click()
    expect(page.locator("#toast")).to_have_text("You can save up to 20 searches")
    assert len(stored(d)) == 20


def test_too_long_search_is_refused(device):
    page = device.open("#all?query=" + "a" * 190 + "&topic=" + "b" * 190 + "&agency=" + "c" * 190 + "&stage=" + "d" * 190)
    page.locator("#save-search").click()
    expect(page.locator("#toast")).to_have_text("This search is too long to save; shorten the search words")
    assert stored(device) == []
