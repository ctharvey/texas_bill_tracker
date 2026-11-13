"""Data & imports (#data) and the explorer's CSV export; importing CSV and JSON files."""

import csv
import io
import json

from playwright.sync_api import expect

from harness import click, reveal

HEADER = ["id", "title", "author", "chamber", "status", "filed_at", "hearing_progress", "policy_areas", "agencies",
          "agency_relationships", "official_url", "authors", "author_count", "coauthors", "coauthor_count", "sponsors",
          "sponsor_count", "cosponsors", "cosponsor_count"]


def download_csv(page, button="#export-csv"):
    with page.expect_download() as info:
        click(page, button)
    dl = info.value
    text = open(dl.path(), encoding="utf-8-sig").read()
    return dl.suggested_filename, list(csv.DictReader(io.StringIO(text)))


def card_ids(page):
    return [t.replace(" ", "") for t in page.locator(".bill-card .bill-number").all_inner_texts()]


def upload(page, name, content, mime):
    page.set_input_files("#import-file", files=[{"name": name, "mimeType": mime, "buffer": content.encode("utf-8")}])


def test_export_matches_the_visible_filtered_bills(device):
    page = device.open("#all?agency=ers")
    expect(page.locator("#result-count")).to_have_text("4 bills")
    name, rows = download_csv(page)
    assert name == "texas-90R-bills.csv"
    assert list(rows[0].keys()) == HEADER
    assert [r["id"] for r in rows] == card_ids(page)  # same bills, same order as the screen
    assert len(rows) == 4
    for row in rows:
        card = page.locator(f'.bill-card[data-bill-id="{row["id"]}"]')
        assert card.locator(".bill-title-link").inner_text() == row["title"]
        assert row["chamber"] == card.locator(".chamber-pill").first.inner_text()
        assert row["status"] == card.locator(".status-pill").inner_text()
        assert row["official_url"].endswith(f"Bill={row['id']}")
        assert "Employees Retirement System of Texas" in row["agencies"].split("|")


def test_export_file_has_a_byte_order_mark_and_crlf_rows(device):
    page = device.open("#all?query=HB110")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    with page.expect_download() as info:
        click(page, "#export-csv")
    raw = open(info.value.path(), "rb").read()
    assert raw.startswith(b"\xef\xbb\xbfid,title,author,")
    assert raw.count(b"\r\n") == 1 and not raw.endswith(b"\r\n")


def test_export_follows_the_filter_not_the_whole_list(device):
    page = device.open("#all?topic=Data%20centers&chamber=Senate")
    expect(page.locator("#result-count")).to_have_text("6 bills")
    _, rows = download_csv(page)
    assert len(rows) == 6
    assert all(r["chamber"] == "Senate" and "Data centers" in r["policy_areas"].split("|") for r in rows)
    assert sorted(r["id"] for r in rows) == sorted(card_ids(page))


def test_export_of_a_search_has_the_one_matching_row(device):
    page = device.open("#all?query=HB110")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    _, rows = download_csv(page)
    assert len(rows) == 1
    assert rows[0]["id"] == "HB110" and rows[0]["title"] == "Relating to the minimum wage."
    assert rows[0]["policy_areas"] == "Labor & workforce"
    assert rows[0]["hearing_progress"] == "No hearing yet" and rows[0]["status"] == "Filed"


def test_export_with_no_matches_is_just_the_header(device):
    page = device.open("#all?stage=Referred")
    expect(page.locator("#result-count")).to_have_text("0 bills")
    _, rows = download_csv(page)
    assert rows == []


def test_data_view_exports_everything_loaded(device):
    page = device.open("#data")
    expect(page.locator("#dynamic-content")).to_contain_text("Loaded records")
    name, rows = download_csv(page)
    assert name == "texas-90R-bills.csv"
    assert len(rows) == 1384
    assert len({r["id"] for r in rows}) == 1384
    assert {"HB110", "HB1001"} <= {r["id"] for r in rows}


def test_data_view_export_uses_the_remembered_filters(device):
    device.open("#all?agency=ers")
    page = device.open("#data", page=device.new_page())  # a new document, as on a later visit
    expect(page.locator("#dynamic-content")).to_contain_text("Loaded records")
    _, rows = download_csv(page)
    assert sorted(r["id"] for r in rows) == ["HB234", "HB430", "HB690", "SB108"]


def test_export_then_import_round_trips_the_rows(device):
    page = device.open("#all?topic=Data%20centers&chamber=Senate")
    expect(page.locator("#result-count")).to_have_text("6 bills")
    with page.expect_download() as info:
        click(page, "#export-csv")
    exported = open(info.value.path(), encoding="utf-8").read()
    expected = sorted(card_ids(page))
    page.goto(device.site.base + "#data", wait_until="networkidle")
    page.locator("#dynamic-content").wait_for()
    page.set_input_files("#import-file", files=[{"name": "back.csv", "mimeType": "text/csv", "buffer": exported.encode("utf-8")}])
    expect(page.locator("#toast")).to_have_text("Imported 6 bills")
    expect(page.locator("#result-count")).to_have_text("6 bills")
    assert sorted(card_ids(page)) == expected


CSV_IMPORT = (
    "id,title,author,chamber,status,filed_at,policy_areas,agencies\r\n"
    'HB9001,"Relating to ""quoted"", comma text",Jane Roe,House,Filed,2026-11-01,Taxes|Education,\r\n'
    "SB9002,Relating to hats,John Doe,Senate,Filed,2026-11-02,Healthcare,\r\n"
    "'=SUM(1+1),Not a bill number,Nobody,House,Filed,2026-11-02,Taxes,\r\n"
    "HB9003,'=Formula title,Ann Poe,House,Filed,2026-11-03,Elections,\r\n"
)


def test_import_csv_replaces_the_list_and_says_so(device):
    page = device.open("#data")
    upload(page, "my-bills.csv", CSV_IMPORT, "text/csv")
    expect(page.locator("#toast")).to_have_text("Imported 3 bills")  # the row without a bill number is skipped
    expect(page.locator("#page-title")).to_contain_text("See what")
    expect(page.locator("#result-count")).to_have_text("3 bills")
    assert sorted(card_ids(page)) == ["HB9001", "HB9003", "SB9002"]
    assert page.evaluate("location.hash") == "#all"
    card = page.locator('.bill-card[data-bill-id="HB9001"]')
    expect(card.locator(".bill-title-link")).to_have_text('Relating to "quoted", comma text')
    expect(card.locator(".chamber-pill").first).to_have_text("House")
    expect(card).to_contain_text("Jane Roe")
    # A leading apostrophe added to defuse spreadsheet formulas is removed again.
    expect(page.locator('.bill-card[data-bill-id="HB9003"] .bill-title-link')).to_have_text("=Formula title")
    expect(page.locator("#results-bottom")).to_contain_text("Local file: my-bills.csv")


def test_imported_data_is_described_in_the_data_view(device):
    page = device.open("#data")
    upload(page, "my-bills.csv", CSV_IMPORT, "text/csv")
    expect(page.locator("#result-count")).to_have_text("3 bills")
    page.evaluate("location.hash = '#data'")
    body = page.locator("#dynamic-content")
    expect(body).to_contain_text("local import")
    expect(body).to_contain_text("User import")
    expect(body.locator(".data-field", has_text="Loaded records").locator(".data-value")).to_have_text("3")
    expect(body).to_contain_text("Local file: my-bills.csv")


def test_import_json_array(device):
    page = device.open("#data")
    data = [{"id": "HB9100", "title": "Relating to roads", "author": "Sam Lee", "status": "Filed", "filed_at": "2026-11-05"},
            {"number": "sb 9101", "description": "Relating to rivers"}, {"id": "bogus"}]
    upload(page, "bills.json", json.dumps(data), "application/json")
    expect(page.locator("#toast")).to_have_text("Imported 2 bills")
    expect(page.locator("#result-count")).to_have_text("2 bills")
    assert sorted(card_ids(page)) == ["HB9100", "SB9101"]
    expect(page.locator('.bill-card[data-bill-id="SB9101"] .bill-title-link')).to_have_text("Relating to rivers")


def test_import_json_object_with_bills_key(device):
    page = device.open("#data")
    upload(page, "export.json", json.dumps({"bills": [{"id": "HB9200", "title": "Relating to lakes"}]}), "application/json")
    expect(page.locator("#toast")).to_have_text("Imported 1 bills")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    assert card_ids(page) == ["HB9200"]


def test_import_clears_existing_filters(device):
    device.open("#all?chamber=Senate&topic=Data%20centers")  # remembered, so #data starts with these filters
    page = device.open("#data", page=device.new_page())
    upload(page, "my-bills.csv", CSV_IMPORT, "text/csv")
    expect(page.locator("#result-count")).to_have_text("3 bills")
    expect(page.locator("#filter-topic")).to_have_value("")
    expect(page.locator("#filter-chamber")).to_have_value("")


def test_import_rejects_bad_files_and_keeps_the_current_data(device):
    page = device.open("#data")
    upload(page, "broken.json", "{not json", "application/json")
    expect(page.locator("#toast")).to_contain_text("Import failed:")
    upload(page, "nothing.json", json.dumps({"hello": "world"}), "application/json")
    expect(page.locator("#toast")).to_have_text("Import failed: Expected an array of bills or an object with a bills array")
    upload(page, "novalid.csv", "id,title\r\nXX1,nope\r\n", "text/csv")
    expect(page.locator("#toast")).to_have_text("Import failed: No valid Texas bill numbers found")
    expect(page.locator("#dynamic-content")).to_contain_text("Live server snapshot")
    expect(page.locator(".data-field", has_text="Loaded records").locator(".data-value")).to_have_text("1384")


def test_import_button_opens_the_file_chooser(device):
    page = device.open("#data")
    with page.expect_file_chooser() as info:
        page.click("#import-trigger")
    chooser = info.value
    assert chooser.is_multiple() is False
