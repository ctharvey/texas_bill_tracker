"""Create the stored-data fixtures that test_stored_data.py loads (run deliberately; tests never call this).

  python tests/e2e/make_stored_fixtures.py

WHEN TO RE-RUN: almost never. These files pin what a person's browser and files looked like when the app was last
known to read them correctly (the base commit of the refactor). The point is that the refactored code must still load
them unchanged, so regenerating them with refactored code defeats the purpose. Re-run only on purpose, from a build
whose saved-data format you intend to be the new reference, and review the diff of fixtures/stored/ by hand.

It drives the CURRENT app (raw src/, frozen live/ data, the real sync service on a temp database) with Playwright like a
person would: accepts the disclaimer, stars bills, follows legislators, saves and renames searches, leaves filters
set, picks "Use my location" with a mocked position, creates a private sync link, exports the saved-data file. Then
writes fixtures/stored/:

  local_storage.json   every localStorage key/value exactly as the app wrote it
  profile-file.json    the "Export file" download (watchlist + follows + saved searches)
  watchlist-file.json  the older watchlist-only file format, produced by the app's own prefs.js watchlistFile (the UI
                       no longer offers a watchlist-only export, but import still accepts the old files)
  sync.sqlite3         the sync service database holding this list (taken with the sqlite3 backup API)
  stored.json          what each fixture should show (and which keys the sync link uses; test database only)

Every value is made up for this fixture; no production data or keys are involved.
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

OUT = harness.FIXTURES / "stored"
WATCH = ["HB110", "HB1001", "HB239", "HB717", "HB448"]  # Order matters: it is the stored order.
FOLLOW = ["A4395", "A2150", "A4805"]  # Member codes from the frozen roster (live/members.json).
AUSTIN = {"latitude": 30.2672, "longitude": -97.7431, "accuracy": 20}


def main() -> int:
    captured_at = datetime.fromisoformat(harness.capture_info()["captured_at"].replace("Z", "+00:00"))
    site = harness.Site("src")
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as p:
        browser = harness.launch(p)
        ctx = browser.new_context(viewport={"width": 1366, "height": 900}, locale="en-US", timezone_id="America/Chicago",
                                  geolocation=AUSTIN, permissions=["geolocation"], accept_downloads=True)
        ctx.clock.set_fixed_time(captured_at)
        ctx.route("https://fonts.googleapis.com/**", lambda r: r.fulfill(status=200, body="", content_type="text/css"))
        ctx.route("https://fonts.gstatic.com/**", lambda r: r.fulfill(status=404, body=""))
        ctx.route("https://geocoding.geo.census.gov/**", lambda r: r.abort())
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))

        def go(hash_):
            page.goto(site.base + hash_, wait_until="networkidle")
            page.wait_for_selector("#dynamic-content *", state="attached", timeout=20000)

        # Disclaimer: dismissed by the person, so the app writes its own flag value.
        go("#all")
        expect(page.locator("#disclaimer")).to_have_attribute("open", "")
        page.click("#disclaimer-ok")
        page.wait_for_function("localStorage.getItem('tx-bill-atlas-disclaimer-v1')")

        # Watchlist: star bills from their drawers, in order.
        for bill in WATCH:
            go(f"#bill?id={bill}")
            page.locator(f"#bill-page [data-watch='{bill}']").first.click()
            page.wait_for_function(f"JSON.parse(localStorage.getItem('tx-bill-atlas-watch-90r')||'[]').includes('{bill}')")

        # Follows: from each legislator's own page.
        for code in FOLLOW:
            go(f"#member?code={code}")
            page.locator(f"[data-follow='{code}']").first.click()
            page.wait_for_function(f"JSON.parse(localStorage.getItem('tx-bill-atlas-follow-90r')||'[]').includes('{code}')")

        # Saved searches: one plain, one renamed.
        go("#all")
        page.select_option("#filter-chamber", label="House")
        harness.click(page, "#save-search")
        page.fill("#bill-search", "water")
        harness.click(page, "#save-search")
        page.wait_for_function("JSON.parse(localStorage.getItem('tx-bill-atlas-searches-90r')||'[]').length===2")
        go("#following")
        page.locator("[data-search-rename]").nth(1).click()
        page.fill("[data-search-rename-form] input[name=name]", "Water bills I track")
        page.press("[data-search-rename-form] input[name=name]", "Enter")
        expect(page.locator(".saved-search-name", has_text="Water bills I track")).to_be_visible()

        # Remembered filters (left set when the person leaves the explorer): chamber Senate and search words.
        go("#all")
        page.select_option("#filter-chamber", label="Senate")
        page.fill("#bill-search", "school")
        harness.click(page, "#copy-view-link")  # persistState writes the remembered filters.
        page.wait_for_function("localStorage.getItem('tx-bill-atlas-prefs-v1')")

        # Near you: "Use my location" with a mocked position.
        go("#local")
        page.click("#near-locate")
        expect(page.locator(".near-summary")).to_be_visible(timeout=20000)

        # Sync link, created last so the server holds everything above.
        go("#watchlist")
        harness.reveal(page, "#sync-create")
        page.click("#sync-create")
        harness.reveal(page, "#sync-copy-edit")
        expect(page.locator("#sync-copy-edit")).to_be_visible()
        page.wait_for_function("localStorage.getItem('tx-bill-atlas-sync-v1')")

        # The profile file, exactly as the UI downloads it.
        with page.expect_download() as dl:
            harness.reveal(page, "#export-watch")
            page.click("#export-watch")
        profile_name = dl.value.suggested_filename
        dl.value.save_as(OUT / "profile-file.json")

        # The older watchlist-only file, from the app's own module (no UI button for it any more).
        legacy = page.evaluate("""async (ids) => { const m = await import('./src/prefs.js'); return m.watchlistFile(ids); }""",
                               WATCH)
        (OUT / "watchlist-file.json").write_text(legacy + "\n", "utf-8")

        # What the pages show, recorded for the tests to compare against.
        storage = page.evaluate("Object.fromEntries(Object.entries(localStorage))")
        (OUT / "local_storage.json").write_text(json.dumps(storage, indent=2, sort_keys=True) + "\n", "utf-8")
        go("#local")
        expect(page.locator(".near-summary")).to_be_visible(timeout=20000)
        near_text = page.locator(".near-summary strong").inner_text()
        nav ={"watch": page.locator("#nav-watch").inner_text(), "follow": page.locator("#nav-follow").inner_text()}
        go("#following")
        searches_shown = [{"name": e.locator(".saved-search-name").inner_text(),
                           "counts": e.locator(".saved-search-counts").inner_text()}
                          for e in page.locator(".saved-search").all()]
        followed_names = [e.inner_text().split("\n")[0].strip() for e in page.locator(".followed-member").all()]
        ctx.close()
        browser.close()
    if errors:
        print("page errors:", errors)
        return 1

    sync_state = json.loads(storage["tx-bill-atlas-sync-v1"])
    stored = {
        "note": "Test data only. Describes what a person's saved state looked like when these fixtures were made.",
        "captured_at": harness.capture_info()["captured_at"],
        "storage_keys": sorted(storage),
        "watch": json.loads(storage["tx-bill-atlas-watch-90r"]),
        "follows": json.loads(storage["tx-bill-atlas-follow-90r"]),
        "followed_names_shown": followed_names,
        "searches": json.loads(storage["tx-bill-atlas-searches-90r"]),
        "searches_shown": searches_shown,
        "remembered_filters": json.loads(storage["tx-bill-atlas-prefs-v1"])["filters"],
        "near": json.loads(storage["texas-bill-atlas-near-you-v1"]),
        "near_summary_text": near_text,
        "nav_counts": nav,
        "profile_download_name": profile_name,
        "sync": {"edit_key": sync_state["key"], "view_key": sync_state["viewKey"], "version": sync_state["version"],
                 "note": "These keys exist only in fixtures/stored/sync.sqlite3, a throwaway test database."},
    }
    (OUT / "stored.json").write_text(json.dumps(stored, indent=2) + "\n", "utf-8")

    # A consistent single-file copy of the sync database the service wrote (backup API, not a file copy).
    target = OUT / "sync.sqlite3"
    target.unlink(missing_ok=True)
    source, dest = sqlite3.connect(str(site.sync_db)), sqlite3.connect(str(target))
    with dest:
        source.backup(dest)
    dest.execute("PRAGMA journal_mode=DELETE")
    dest.close()
    source.close()
    site.close()
    for leftover in OUT.glob("sync.sqlite3-*"):
        leftover.unlink()
    print(f"wrote {OUT}")
    print(json.dumps({k: stored[k] for k in ("watch", "follows", "searches_shown", "near_summary_text", "nav_counts")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
