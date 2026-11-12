"""Profile file: one download carrying watchlist, follows and saved searches, and importing it on another device."""

import json

from playwright.sync_api import expect

WATCH_KEY = "tx-bill-atlas-watch-90r"
FOLLOW_KEY = "tx-bill-atlas-follow-90r"
SEARCHES_KEY = "tx-bill-atlas-searches-90r"


def star(page, bill_id):
    return page.locator(f'#bill-list .bill-card[data-bill-id="{bill_id}"] [data-watch]')


def build_rich_profile(device):
    page = device.open("#all?query=HB110")
    star(page, "HB110").click()
    page.goto(device.site.base + "#all?query=HB1001")
    star(page, "HB1001").click()
    device.open("#member?code=A2150")
    page.locator("button.follow-button").click()
    expect(page.locator("#toast")).to_contain_text("Following")
    device.open("#all?query=HB717&chamber=House")
    page.locator("#save-search").click()
    expect(page.locator("#toast")).to_contain_text("Saved ")
    return page


def export_profile(device):
    page = device.open("#watchlist")
    with page.expect_download() as dl:
        page.locator("#export-watch").click()
    download = dl.value
    assert download.suggested_filename == "texas-bill-atlas-saved.json"
    return json.loads(open(download.path(), encoding="utf-8").read())


def test_export_carries_watchlist_follows_and_saved_searches(device):
    build_rich_profile(device)
    data = export_profile(device)
    assert set(data) == {"format", "session", "exported_at", "lists", "follows", "searches"}
    assert data["format"] == "texas-bill-atlas-profile-v1"
    assert data["session"] == "90R"
    assert data["exported_at"].startswith("2026-11-12T15:49:")  # the frozen clock
    assert data["lists"] == [{"id": "main", "name": "Watchlist", "bills": ["HB110", "HB1001"]}]
    assert data["follows"] == ["A2150"]
    assert len(data["searches"]) == 1
    search = data["searches"][0]
    assert set(search) == {"id", "name", "filters", "seen"}
    assert search["filters"] == {"query": "HB717", "chamber": "House"}
    assert search["name"] == "“HB717” · House"
    assert search["seen"] == "2026-11-12"
    # What is in the file is what the browser stores.
    stored = device.storage()
    assert json.loads(stored[SEARCHES_KEY]) == data["searches"]
    assert json.loads(stored[FOLLOW_KEY]) == data["follows"]
    assert json.loads(stored[WATCH_KEY]) == data["lists"][0]["bills"]


def test_export_excludes_device_only_things(device):
    page = build_rich_profile(device)
    page.evaluate("localStorage.setItem('tx-bill-atlas-near-v1', JSON.stringify({house:'5'}))")
    text = json.dumps(export_profile(device))
    for leftover in ("near", "prefs", "sync", "editKey", "viewKey"):
        assert leftover not in text, leftover


def test_export_with_only_follows_is_allowed(device):
    page = device.open("#member?code=A2150")
    page.locator("button.follow-button").click()
    expect(page.locator("#toast")).to_contain_text("Following")
    page = device.open("#watchlist")
    expect(page.locator("#export-watch")).to_be_enabled()
    expect(page.locator("#share-watch")).to_be_disabled()
    data = export_profile(device)
    assert data["lists"][0]["bills"] == [] and data["follows"] == ["A2150"] and data["searches"] == []


def test_import_profile_into_fresh_device_restores_everything(device_factory, tmp_path):
    first = device_factory()
    build_rich_profile(first)
    f = tmp_path / "profile.json"
    f.write_text(json.dumps(export_profile(first)), encoding="utf-8")

    second = device_factory()
    page = second.open("#watchlist")
    expect(page.locator("#nav-watch")).to_have_text("0")
    page.set_input_files("#import-watch-file", str(f))
    expect(page.locator("#toast")).to_have_text("Added 2 of 2 bills, 1 of 1 legislators, 1 of 1 saved searches")
    expect(page.locator("#nav-watch")).to_have_text("2")
    expect(page.locator("#nav-follow")).to_have_text("2")  # one legislator + one saved search
    expect(page.locator("#result-count")).to_have_text("2 bills")
    assert json.loads(second.storage()[WATCH_KEY]) == ["HB110", "HB1001"]

    page = second.open("#following")
    expect(page.locator(".saved-search-name")).to_have_text("“HB717” · House")
    expect(page.locator(".saved-search p").first).to_have_text("Search “HB717” · House")
    expect(page.locator(".followed-member")).to_have_count(1)
    expect(page.locator(".followed-member")).to_contain_text("Rep. Rafael Anchía")
    assert json.loads(second.storage()[SEARCHES_KEY]) == json.loads(first.storage()[SEARCHES_KEY])

    # Importing again only adds: nothing new the second time.
    page = second.open("#watchlist")
    page.set_input_files("#import-watch-file", str(f))
    expect(page.locator("#toast")).to_have_text("Added 0 of 2 bills, 0 of 1 legislators, 0 of 1 saved searches")
    assert json.loads(second.storage()[FOLLOW_KEY]) == ["A2150"]
    assert len(json.loads(second.storage()[SEARCHES_KEY])) == 1


def test_import_merges_into_existing_profile(device_factory, tmp_path):
    first = device_factory()
    build_rich_profile(first)
    f = tmp_path / "profile.json"
    f.write_text(json.dumps(export_profile(first)), encoding="utf-8")

    second = device_factory()
    page = second.open("#all?query=HB717")
    star(page, "HB717").click()
    page = second.open("#watchlist")
    page.set_input_files("#import-watch-file", str(f))
    expect(page.locator("#toast")).to_have_text("Added 2 of 2 bills, 1 of 1 legislators, 1 of 1 saved searches")
    assert json.loads(second.storage()[WATCH_KEY]) == ["HB717", "HB110", "HB1001"]
    expect(page.locator("#nav-watch")).to_have_text("3")


def test_empty_profile_file_is_rejected(device, tmp_path):
    f = tmp_path / "empty.json"
    f.write_text(json.dumps({"format": "texas-bill-atlas-profile-v1", "lists": [{"id": "main", "name": "Watchlist", "bills": []}],
                             "follows": [], "searches": []}))
    page = device.open("#watchlist")
    page.set_input_files("#import-watch-file", str(f))
    expect(page.locator("#toast")).to_have_text("Import failed: This file has no bills or legislators (or saved searches)")
    expect(page.locator("#nav-watch")).to_have_text("0")


def test_profile_import_drops_invalid_entries(device, tmp_path):
    f = tmp_path / "messy.json"
    f.write_text(json.dumps({"format": "texas-bill-atlas-profile-v1",
                             "lists": [{"id": "main", "name": "Watchlist", "bills": ["HB110", "nonsense"]}],
                             "follows": ["A2150", "bogus"],
                             "searches": [{"id": "bad id", "name": "x", "filters": {}},
                                          {"id": "goodid1234", "name": "Kept", "filters": {"query": "HB110", "evil": "x"}, "seen": "nope"}]}))
    page = device.open("#watchlist")
    page.set_input_files("#import-watch-file", str(f))
    expect(page.locator("#toast")).to_have_text("Added 1 of 1 bills, 1 of 1 legislators, 1 of 1 saved searches")
    saved = json.loads(device.storage()[SEARCHES_KEY])
    assert saved == [{"id": "goodid1234", "name": "Kept", "filters": {"query": "HB110"}, "seen": None}]
    assert json.loads(device.storage()[FOLLOW_KEY]) == ["A2150"]
