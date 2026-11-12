"""The drawer's bill text: version list, additions and deletions, Luna highlights and their validation."""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

LIVE = Path(__file__).resolve().parent / "fixtures" / "live"
DRAWER = "#detail-drawer"
SHOW = "Show bill text"
NOTE_MISMATCH = "Luna highlights do not match this version of the text."
NOTE_NONE = "Luna highlights appear after the full-text review."
# Observed in the frozen data: highlights exist and match the introduced text for these bills.
HIGHLIGHTED = ["HB110", "HB147", "HB239", "HB448", "HB717", "HB1001", "HB1002", "HB1003"]


def source_marks(bill_id, tag):
    """The text inside every <ins>/<del> pair of the bill's raw markdown, joined, with backslash escapes removed."""
    raw = (LIVE / "text" / bill_id / "I.md").read_text("utf-8")
    return "".join(re.sub(r"\\(.)", r"\1", m) for m in re.findall(rf"<{tag}>(.*?)</{tag}>", raw))


def show_text(device, bill_id):
    page = device.open(f"#all?bill={bill_id}")
    page.locator(f"{DRAWER} button", has_text=SHOW).click()
    expect(page.locator(f"{DRAWER} .bill-text")).to_be_visible()
    return page


def test_before_clicking_nothing_is_loaded_and_the_official_link_is_hidden(device):
    page = device.open("#all?bill=HB717")
    section = page.locator(f"{DRAWER} .bill-text-section")
    expect(section.locator("h3")).to_have_text("Bill text")
    expect(section.get_by_role("button", name=SHOW)).to_be_visible()
    expect(section.locator("select")).to_have_count(0)
    expect(section.locator(".bill-text")).to_have_count(0)
    expect(section.get_by_role("link", name="Read the official text on Texas Legislature Online ↗")).to_be_hidden()


def test_show_bill_text_requests_the_index_then_the_latest_version(device):
    page = device.open("#all?bill=HB717")
    seen = []
    page.on("request", lambda r: seen.append(r.url.split("/live/", 1)[-1]) if "/live/text/" in r.url else None)
    page.locator(f"{DRAWER} button", has_text=SHOW).click()
    expect(page.locator(f"{DRAWER} .bill-text")).to_be_visible()
    assert seen == ["text/HB717/index.json", "text/HB717/I.md"]


def test_version_list_and_official_text_link(device):
    page = show_text(device, "HB717")
    section = page.locator(f"{DRAWER} .bill-text-section")
    expect(section.get_by_role("button", name=SHOW)).to_be_hidden()
    select = section.get_by_label("Bill text version")
    expect(select.locator("option")).to_have_text(["Introduced (I)"])
    expect(select.locator("option:checked")).to_have_text("Introduced (I)")
    link = section.get_by_role("link", name="Read the official text on Texas Legislature Online ↗")
    expect(link).to_be_visible()
    expect(link).to_have_attribute("href", "https://capitol.texas.gov/BillLookup/Text.aspx?LegSess=90R&Bill=HB717")
    expect(link).to_have_attribute("target", "_blank")


def test_text_renders_with_headings_and_escaped_brackets(device):
    page = show_text(device, "HB717")
    body = page.locator(f"{DRAWER} .bill-text .bt-body")
    expect(body.locator("h4").first).to_have_text("HB 717 - Introduced")
    expect(body.locator("h4")).to_have_text(["HB 717 - Introduced", "SECTION 1.", "SECTION 2.", "SECTION 3."])
    expect(body).to_contain_text("(3) \"Qualified county\" is a county that has a population of 200,000 [68,750] or less.")
    expect(body).to_contain_text("This Act takes effect September 1, 2027.")


def test_additions_are_underlined_and_deletions_struck_through(device):
    page = show_text(device, "HB717")
    ins = page.locator(f"{DRAWER} .bill-text .bt-body ins")
    dele = page.locator(f"{DRAWER} .bill-text .bt-body del")
    expect(ins).to_have_text(["200,000", "200,000"])
    expect(dele).to_have_text(["68,750", "68,750"])
    assert ins.first.evaluate("e => getComputedStyle(e).textDecorationLine") == "underline"
    assert dele.first.evaluate("e => getComputedStyle(e).textDecorationLine") == "line-through"
    legend = page.locator(f"{DRAWER} .bt-legend")
    expect(legend).to_contain_text("Underlined = added by the bill · struck through = removed")


@pytest.mark.parametrize("bill_id", ["HB1001", "HB381"])
def test_every_addition_and_deletion_in_the_source_is_rendered(device, bill_id):
    page = show_text(device, bill_id)
    body = f"{DRAWER} .bill-text .bt-body"
    for tag in ("ins", "del"):
        shown = page.evaluate(f"[...document.querySelectorAll('{body} {tag}')].map(e => e.textContent).join('')")
        assert shown == source_marks(bill_id, tag)
        assert shown  # the bill really does have some


@pytest.mark.parametrize("bill_id", HIGHLIGHTED)
def test_highlights_validate_and_are_drawn(device, bill_id):
    page = show_text(device, bill_id)
    root = page.locator(f"{DRAWER} .bill-text")
    expect(root.locator("mark.hl").first).to_be_visible()
    expect(root.locator(".bt-note")).to_have_count(0)
    expect(root.locator(".bt-legend")).to_contain_text("highlight colours show the kind of Luna note")
    expect(root.locator(".bt-chips .bt-chip").first).to_have_attribute("aria-pressed", "true")
    assert NOTE_MISMATCH not in root.inner_text()


def test_bill_without_a_highlights_file_says_they_come_after_the_review(device):
    page = show_text(device, "HB381")
    root = page.locator(f"{DRAWER} .bill-text")
    expect(root.locator(".bt-note")).to_have_text(NOTE_NONE)
    expect(root.locator("mark")).to_have_count(0)
    expect(root.locator(".bt-chips")).to_have_count(0)
    expect(root.locator("ins").first).to_be_visible()  # the text itself is still there


def test_selecting_a_highlight_explains_why_it_is_highlighted(device):
    page = show_text(device, "HB717")
    root = page.locator(f"{DRAWER} .bill-text")
    expect(root.locator(".bt-panel .bt-claim")).to_have_count(0)
    root.locator(".bt-key", has_text="Texas Comptroller of Public Accounts").click()
    claim = root.locator(".bt-panel .bt-claim")
    expect(claim.locator("strong")).to_have_text("Texas Comptroller of Public Accounts")
    expect(claim.locator("small")).to_contain_text("agency")
    expect(claim.locator("p")).not_to_be_empty()
    # Clicking highlighted text in the body shows that passage's notes.
    root.locator('.bt-body mark[data-ids~="major_effects:0"]').first.click()
    # The passage carries both the summary note and the key-effect note; both are listed.
    expect(root.locator(".bt-panel .bt-claim strong").first).to_have_text("Summary")
    expect(root.locator(".bt-panel")).to_contain_text("Expanded county eligibility")


def test_kind_chips_hide_and_show_highlights(device):
    page = show_text(device, "HB717")
    root = page.locator(f"{DRAWER} .bill-text")
    # The passage "(e) " carries only a topic note (policy_tags:1), so hiding Topics switches it off.
    topic_only = root.locator('.bt-body mark[data-ids="policy_tags:1"]').first
    expect(topic_only).to_be_attached()
    assert "hl-off" not in (topic_only.get_attribute("class") or "")
    chip = root.locator(".bt-chip", has_text="Topics")
    chip.click()
    expect(chip).to_have_attribute("aria-pressed", "false")
    expect(topic_only).to_have_class(re.compile(r"\bhl-off\b"))
    chip.click()
    expect(chip).to_have_attribute("aria-pressed", "true")
    assert "hl-off" not in (topic_only.get_attribute("class") or "")


def test_highlights_for_different_text_are_refused(device):
    """Counterexample: the highlight file's hash is for other text, so no highlight may be drawn on this text."""
    def tamper(route):
        data = route.fetch().json()
        data["text_sha256"] = "0" * 64
        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    device.context.route("**/live/luna/highlights/HB717.json", tamper)
    page = show_text(device, "HB717")
    root = page.locator(f"{DRAWER} .bill-text")
    expect(root.locator(".bt-note")).to_have_text(NOTE_MISMATCH)
    expect(root.locator("mark")).to_have_count(0)
    expect(root.locator("ins").first).to_be_visible()


def test_highlights_with_a_range_outside_the_text_do_not_crash_the_text(device):
    """Counterexample: a claim whose range runs past its paragraph is ignored while the rest still shows."""
    def tamper(route):
        data = route.fetch().json()
        data["claims"][0]["ranges"] = [{"p": 9, "start": 0, "end": 99999}]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    device.context.route("**/live/luna/highlights/HB717.json", tamper)
    page = show_text(device, "HB717")
    root = page.locator(f"{DRAWER} .bill-text")
    expect(root.locator(".bt-body")).to_contain_text("This Act takes effect September 1, 2027.")
    expect(root.locator("mark.hl").first).to_be_visible()


def test_text_not_on_the_site_yet_points_to_the_official_page(device):
    device.context.route("**/live/text/HB717/index.json", lambda route: route.fulfill(status=404, body=""))
    page = device.open("#all?bill=HB717")
    page.locator(f"{DRAWER} button", has_text=SHOW).click()
    section = page.locator(f"{DRAWER} .bill-text-section")
    expect(section).to_contain_text("The bill text is not on this site yet; it is added within a few hours of filing.")
    expect(section.get_by_role("link", name="Read the official text on Texas Legislature Online ↗")).to_be_visible()
    expect(section.get_by_role("button", name=SHOW)).to_be_hidden()


def test_a_bad_text_index_reports_it_and_lets_the_reader_retry(device):
    device.context.route("**/live/text/HB717/index.json",
                         lambda route: route.fulfill(status=200, content_type="application/json",
                                                     body=json.dumps({"format": "wrong", "bill_id": "HB717", "versions": []})))
    page = device.open("#all?bill=HB717")
    button = page.locator(f"{DRAWER} button", has_text=SHOW)
    button.click()
    expect(page.locator(f"{DRAWER} .bill-text-section")).to_contain_text(
        "The bill text could not be loaded: The text index is not valid")
    expect(button).to_be_enabled()
