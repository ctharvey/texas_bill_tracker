"""Disclaimer and privacy dialogs: first-visit disclaimer, remembered acceptance, footer links."""

import re

from playwright.sync_api import expect

KEY = "tx-bill-atlas-disclaimer-v1"


def test_disclaimer_shows_on_first_visit_and_is_remembered(device_factory):
    device = device_factory(accept_disclaimer=False)
    page = device.open("#all")
    dialog = page.locator("#disclaimer")
    expect(dialog).to_be_visible()
    expect(dialog.locator("h2")).to_have_text("Before you use Texas Bill Atlas")
    expect(dialog).to_contain_text("An independent, open-source project.")
    expect(dialog).to_contain_text("Not advice.")
    assert KEY not in device.storage(), "nothing is stored until it is accepted"
    page.locator("#disclaimer-ok").click()
    expect(dialog).to_be_hidden()
    # The app stores it in the dialog's 'close' event, which fires a task after the dialog hides.
    page.wait_for_function(f"localStorage.getItem('{KEY}') !== null")
    stored = device.storage()[KEY]
    assert re.match(r"\d{4}-\d{2}-\d{2}T", stored), "the acceptance is stored as a timestamp"
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#dynamic-content *", state="attached")
    expect(page.locator("#disclaimer")).to_be_hidden()
    # A second tab on the same profile does not ask again either.
    other = device.new_page()
    device.open("#all", page=other)
    expect(other.locator("#disclaimer")).to_be_hidden()


def test_escape_also_counts_as_seen(device_factory):
    device = device_factory(accept_disclaimer=False)
    page = device.open("#all")
    expect(page.locator("#disclaimer")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#disclaimer")).to_be_hidden()
    page.wait_for_function(f"localStorage.getItem('{KEY}') !== null")  # written in the 'close' event, a task later
    assert KEY in device.storage()


def test_disclaimer_blocks_the_page_behind_it(device_factory):
    device = device_factory(accept_disclaimer=False)
    page = device.open("#all")
    expect(page.locator("#disclaimer")).to_be_visible()
    assert page.evaluate("document.querySelector('#disclaimer').matches(':modal')")
    assert page.evaluate("document.activeElement.id") == "disclaimer-ok"


def test_no_disclaimer_when_already_accepted(device):
    page = device.open("#all")
    expect(page.locator("#disclaimer")).to_be_hidden()
    assert KEY in device.storage()


def test_disclaimer_link_reopens_it(device):
    page = device.open("#all")
    page.locator("#disclaimer-open").click()
    dialog = page.locator("#disclaimer")
    expect(dialog).to_be_visible()
    expect(dialog.locator("h2")).to_have_text("Before you use Texas Bill Atlas")
    expect(dialog.locator('a[href="https://capitol.texas.gov/"]')).to_be_visible()
    page.locator("#disclaimer-ok").click()
    expect(dialog).to_be_hidden()
    # And it can be reopened again.
    page.locator("#disclaimer-open").click()
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()


def test_privacy_link_opens_the_policy_and_it_closes(device):
    page = device.open("#all")
    expect(page.locator("#privacy")).to_be_hidden()
    page.locator("#privacy-open").click()
    dialog = page.locator("#privacy")
    expect(dialog).to_be_visible()
    expect(dialog.locator("h2")).to_have_text("Privacy Policy")
    expect(dialog).to_contain_text("We do not require registration, names, email addresses")
    headings = dialog.locator("h3").all_inner_texts()
    assert headings == ["Information we collect", "Analytics and security", "Watchlists and saved preferences",
                        "Technical data", "Third-party services", "Changes", "Questions"]
    dialog.get_by_role("button", name="Close").click()
    expect(dialog).to_be_hidden()
    page.locator("#privacy-open").click()
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    # Reading the privacy policy is not accepting the disclaimer's separate record, and nothing breaks the page.
    expect(page.locator("#disclaimer")).to_be_hidden()


def test_privacy_link_works_while_the_disclaimer_has_not_been_accepted_yet(device_factory):
    device = device_factory(accept_disclaimer=False)
    page = device.open("#all")
    page.locator("#disclaimer-ok").click()
    page.locator("#privacy-open").click()
    expect(page.locator("#privacy")).to_be_visible()
    expect(page.locator("#disclaimer")).to_be_hidden()
