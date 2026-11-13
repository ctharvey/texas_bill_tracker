"""Drawer stage sections (Luna changes, hearing witnesses, fiscal note check).

The frozen production data has none of them yet, so each must be absent and quiet; routes that supply a valid
payload show the sections do appear when production starts publishing them.
"""

import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

LIVE = Path(__file__).resolve().parent / "fixtures" / "live"
DRAWER = "#bill-page"
BILLS = ["HB110", "HB147", "HB239", "HB381", "HB448", "HB717", "HB1001", "HB1002", "HB1003"]
STAGE_HEADINGS = ["What changed", "Hearing", "Fiscal note check"]


def per_bill_urls(bill_id):
    return [f"text/{bill_id}/index.json", f"luna/changes/{bill_id}.json", f"history/{bill_id}/witnesses-H.json",
            f"history/{bill_id}/witnesses-S.json", f"luna/fiscal/{bill_id}.json", f"luna/highlights/{bill_id}.json"]


def open_recording(device, bill_id):
    """Open the bill's drawer from a cold page, recording every /live/ response (path -> status) and any warning."""
    page = device.page
    responses, warnings = {}, []
    device.requests = []
    page.on("request", lambda r: device.requests.append(r.url.split("/live/", 1)[1]) if "/live/" in r.url else None)
    page.on("response", lambda r: responses.__setitem__(r.url.split("/live/", 1)[1], r.status) if "/live/" in r.url else None)
    page.on("console", lambda m: warnings.append(m.text) if m.type == "warning" else None)
    device.open(f"#bill?id={bill_id}")
    expect(page.locator("#bill-page-title")).to_be_visible()
    # The stage fetches run after the drawer opens; wait until all six per-bill requests have answered.
    expected = per_bill_urls(bill_id)
    for _ in range(100):
        if all(u in responses for u in expected):
            break
        page.wait_for_timeout(100)
    return page, responses, warnings


@pytest.mark.parametrize("bill_id", BILLS)
def test_no_stage_sections_are_shown_and_the_expected_requests_are_made(device, bill_id):
    page, responses, warnings = open_recording(device, bill_id)
    drawer = page.locator(DRAWER)
    expect(drawer.locator(".stage-section")).to_have_count(0)
    for heading in STAGE_HEADINGS:
        expect(drawer.get_by_role("heading", name=heading, exact=True)).to_have_count(0)
    # Exactly the six per-bill files were asked for: text index and highlights exist; the stage files are 404.
    per_bill = {u: s for u, s in responses.items() if f"/{bill_id}" in u or u.endswith(f"/{bill_id}.json")}
    assert sorted(per_bill) == sorted(u for u in per_bill if u in per_bill_urls(bill_id))
    assert set(per_bill_urls(bill_id)) <= set(per_bill)
    for url in per_bill_urls(bill_id):
        expected_status = 200 if url.startswith("text/") or url.startswith("luna/highlights/") else 404
        if url == f"luna/highlights/{bill_id}.json" and not (LIVE / url).is_file():
            expected_status = 404  # HB381 has no highlights yet
        assert per_bill[url] == expected_status, (url, per_bill[url])
    assert not [w for w in warnings if "hidden" in w], warnings  # nothing was rejected as malformed


def test_each_stage_file_is_requested_once_per_opening(device):
    page, responses, _ = open_recording(device, "HB110")
    counts = [u for u in device.requests if u.startswith(("luna/changes", "luna/fiscal", "history/"))]
    assert sorted(counts) == sorted(["luna/changes/HB110.json", "luna/fiscal/HB110.json",
                                     "history/HB110/witnesses-H.json", "history/HB110/witnesses-S.json"])


def test_opening_another_bill_asks_for_that_bills_files(device):
    page, _, _ = open_recording(device, "HB110")
    seen = []
    page.on("request", lambda r: seen.append(r.url.split("/live/", 1)[1]) if "/live/" in r.url else None)
    page.locator(f"{DRAWER} button.companion-open").click()  # HB 972
    expect(page.locator(".drawer-number")).to_have_text("90R / HB 972")
    for _ in range(100):
        if "luna/fiscal/HB972.json" in seen:
            break
        page.wait_for_timeout(100)
    for url in ["luna/changes/HB972.json", "history/HB972/witnesses-H.json", "history/HB972/witnesses-S.json",
                "luna/fiscal/HB972.json"]:
        assert url in seen
    assert not [u for u in seen if "HB110" in u]
    expect(page.locator(f"{DRAWER} .stage-section")).to_have_count(0)


def test_hearing_section_appears_when_witness_data_exists(device):
    """Control for the absent-section tests: the same drawer does show a hearing once a valid payload is published."""
    payload = {"format": "texas-bill-witnesses-v1", "chamber": "H", "committee": "Labor & Employment",
               "hearing": "Hearing of Mar 3", "witnesses": [
                   {"name": "Pat Doe", "organization": "Texas Workers Union", "position": "for", "testified": True},
                   {"name": "Sam Roe", "position": "against", "testified": False}]}
    device.context.route("**/live/history/HB110/witnesses-H.json", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(payload)))
    page = device.open("#bill?id=HB110")
    hearing = page.locator(f"{DRAWER} .stage-hearing")
    expect(hearing.locator("h3")).to_have_text("Hearing")
    expect(hearing).to_contain_text("House · Labor & Employment")
    expect(hearing).to_contain_text("1 for · 1 against · 0 on")
    expect(hearing).to_contain_text("1 testified, 1 registered without testifying")
    expect(hearing).to_contain_text("Pat Doe — Texas Workers Union")
    expect(hearing).to_contain_text("Registered, not testifying (1)")


def test_changes_section_appears_only_for_changes_that_match_the_current_text(device):
    index = json.loads((LIVE / "text" / "HB110" / "index.json").read_text("utf-8"))
    newest = index["versions"][-1]
    good = {"format": "texas-bill-luna-changes-v1", "bill_id": "HB110", "from_version": newest["code"],
            "to_version": newest["code"], "text_sha256": newest["sha256"],
            "changes": [{"kind": "added", "label": "New wage floor", "explanation": "Sets the floor at $15."}]}
    stale = dict(good, text_sha256="f" * 64)
    served = {"body": good}
    device.context.route("**/live/luna/changes/HB110.json", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(served["body"])))
    page = device.open("#bill?id=HB110")
    changes = page.locator(f"{DRAWER} .stage-changes")
    expect(changes.locator("h3")).to_have_text("What changed")
    expect(changes).to_contain_text("New wage floor")
    expect(changes).to_contain_text("Sets the floor at $15.")
    # The same payload made for other text (hash differs) is refused.
    served["body"] = stale
    page.reload(wait_until="networkidle")
    expect(page.locator("#bill-page-title")).to_be_visible()
    for _ in range(10):
        page.wait_for_timeout(100)
    expect(page.locator(f"{DRAWER} .stage-changes")).to_have_count(0)
