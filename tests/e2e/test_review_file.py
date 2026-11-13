"""Opening a private review file from the drawer: the rendered review, and the errors for files that do not fit."""

import json

from playwright.sync_api import expect

DRAWER = "#bill-page"
PAGE_TEXT = "The employer shall pay each employee at least fifteen dollars an hour."
QUOTE = "at least fifteen dollars"
NOT_YET = "A reviewed full-text analysis is not yet available. Review files open only in this browser session."


def bundle(bill_id="HB110", **override):
    start = PAGE_TEXT.index(QUOTE)
    data = {
        "format": "texas-bill-review-v1", "bill_id": bill_id, "status": "ready_for_review",
        "document": {"bill_id": bill_id, "session": "90R", "version": "introduced", "pages": [PAGE_TEXT, "Second page."],
                     "text_hash": "abc", "source_url": "https://tcss.legis.texas.gov/x"},
        "result": {"bill_id": bill_id, "summary": {"text": "Sets a wage floor for employees."},
                   "policy_tags": [{"tag": "Labor & workforce", "text": "Changes what employers must pay.",
                                    "impact": "high"}]},
        "validation": {"errors": [], "verified_citations": [
            {"claim": "policy_tags:0", "status": "resolved",
             "parts": [{"page": 1, "start": start, "end": start + len(QUOTE), "quote": QUOTE}]}]},
        "pending_questions": [{"question": "Is tipped work covered?", "reason": "Not stated"}],
    }
    data.update(override)
    return data


def upload(page, name, payload):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    page.locator(f"{DRAWER} input[type=file]").set_input_files(
        {"name": name, "mimeType": "application/json", "buffer": body})


def test_drawer_offers_a_review_file_button_and_says_none_is_loaded(device):
    page = device.open("#bill?id=HB110")
    section = page.locator(f"{DRAWER} section.drawer-section", has=page.locator("h3", has_text="Full text & highlighted evidence"))
    expect(section.get_by_role("button", name="Open a review file")).to_be_visible()
    expect(section).to_contain_text(NOT_YET)


def test_the_button_opens_the_file_chooser_for_json(device):
    page = device.open("#bill?id=HB110")
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="Open a review file").click()
    assert chooser.value.page == page
    assert page.locator(f"{DRAWER} input[type=file]").get_attribute("accept") == ".json,application/json"


def test_valid_review_for_the_open_bill_is_rendered(device):
    page = device.open("#bill?id=HB110")
    upload(page, "review.json", bundle())
    expect(page.locator("#toast")).to_have_text("Private review opened")
    review = page.locator(f"{DRAWER} .bill-review")
    expect(review.locator(".review-status")).to_have_text("Private import · ready for review · introduced text · 2 PDF pages")
    expect(review.locator(".review-summary")).to_have_text("Sets a wage floor for employees.")
    expect(review.locator("details summary").first).to_have_text("1 open review questions")
    expect(review.locator(".review-highlight")).to_have_text([QUOTE])
    # The first highlight is explained straight away, with its source page.
    explanation = review.locator(".review-explanation")
    expect(explanation).to_contain_text("Why highlighted · PDF page 1")
    expect(explanation.locator("h4")).to_have_text("Policy tag: Labor & workforce · high")
    expect(explanation).to_contain_text("Changes what employers must pay.")
    expect(page.get_by_text(NOT_YET)).to_have_count(0)
    # Both pages of the source text are there.
    expect(review.locator(".review-page summary")).to_have_text(["PDF page 1", "PDF page 2"])
    expect(review.locator(".review-source").first).to_contain_text(PAGE_TEXT.replace(QUOTE, "").split()[0])


def test_clicking_a_highlight_shows_why_it_is_highlighted(device):
    page = device.open("#bill?id=HB110")
    upload(page, "review.json", bundle())
    review = page.locator(f"{DRAWER} .bill-review")
    review.locator(".review-highlight").click()
    expect(review.locator(".review-explanation blockquote")).to_have_text(QUOTE)


def test_review_stays_for_this_session_but_not_across_a_reload(device):
    page = device.open("#bill?id=HB110")
    upload(page, "review.json", bundle())
    expect(page.locator(f"{DRAWER} .bill-review")).to_be_visible()
    # Close and reopen the same bill: still there. Reload: gone, "only in this browser session".
    page.locator("#bill-back").click()
    page.locator("#bill-search").fill("HB110")
    page.locator('article[data-bill-id="HB110"] a.bill-number').click()
    expect(page.locator(f"{DRAWER} .bill-review")).to_be_visible()
    page.reload(wait_until="networkidle")
    expect(page.locator(f"{DRAWER} .bill-review")).to_have_count(0)
    expect(page.locator(DRAWER)).to_contain_text(NOT_YET)


def test_review_for_another_bill_is_refused(device):
    page = device.open("#bill?id=HB110")
    upload(page, "other.json", bundle("HB147"))
    expect(page.locator("#toast")).to_have_text("Review could not be opened: This review belongs to HB147")
    expect(page.locator(f"{DRAWER} .bill-review")).to_have_count(0)
    expect(page.locator(DRAWER)).to_contain_text(NOT_YET)


def test_file_that_is_not_json_is_refused(device):
    page = device.open("#bill?id=HB110")
    upload(page, "notes.json", b"this is not json {")
    expect(page.locator("#toast")).to_contain_text("Review could not be opened: ")
    expect(page.locator("#toast")).not_to_contain_text("Private review opened")
    expect(page.locator(f"{DRAWER} .bill-review")).to_have_count(0)


def test_json_that_is_not_a_review_is_refused(device):
    page = device.open("#bill?id=HB110")
    upload(page, "other.json", {"hello": "world"})
    expect(page.locator("#toast")).to_have_text(
        "Review could not be opened: This file is not a complete Texas bill review")
    expect(page.locator(f"{DRAWER} .bill-review")).to_have_count(0)


def test_review_whose_excerpt_does_not_match_its_text_is_refused(device):
    bad = bundle()
    bad["validation"]["verified_citations"][0]["parts"][0]["quote"] = "something the page never said"
    page = device.open("#bill?id=HB110")
    upload(page, "bad.json", bad)
    expect(page.locator("#toast")).to_have_text(
        "Review could not be opened: A highlighted excerpt does not match the supplied source text")
    expect(page.locator(f"{DRAWER} .bill-review")).to_have_count(0)


def test_file_over_fifteen_megabytes_is_refused(device):
    page = device.open("#bill?id=HB110")
    upload(page, "huge.json", b" " * (15 * 1024 * 1024 + 1))
    expect(page.locator("#toast")).to_have_text("Review could not be opened: Select a file smaller than 15 MB")


def test_a_refused_file_does_not_replace_a_review_already_open(device):
    page = device.open("#bill?id=HB110")
    upload(page, "review.json", bundle())
    expect(page.locator(f"{DRAWER} .bill-review .review-summary")).to_be_visible()
    upload(page, "other.json", bundle("HB147"))
    expect(page.locator("#toast")).to_have_text("Review could not be opened: This review belongs to HB147")
    expect(page.locator(f"{DRAWER} .bill-review .review-summary")).to_have_text("Sets a wage floor for employees.")
