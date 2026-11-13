"""D2-B: on a wide screen a card body opens a short preview beside the results; on a phone it opens the bill page."""

import re

import pytest
from playwright.sync_api import expect


def cards(page):
    first = page.locator("#bill-list article.bill-card").first
    first.wait_for()
    return page.locator("#bill-list article.bill-card")


def open_wide(device):
    page = device.open("#all")
    if page.viewport_size["width"] < 1200:
        pytest.skip("the preview is for wide screens; phones open the bill page")
    return page


def test_preview_shows_the_bill_beside_the_results_and_marks_its_card(device):
    page = open_wide(device)
    first = cards(page).nth(0)
    bill = first.get_attribute("data-bill-id")
    first.locator(".bill-filed").click()
    preview = page.locator("#bill-preview")
    expect(preview).to_be_visible()
    expect(preview.locator("#preview-title")).to_be_focused()
    expect(preview.locator("#preview-title")).to_have_text(first.locator(".bill-title").inner_text())
    expect(first).to_have_class(re.compile(r"\bpreviewed\b"))
    expect(preview.locator(".preview-step span")).to_contain_text("1 of ")
    expect(preview.locator('[data-preview-step="-1"]')).to_be_disabled()
    assert "#bill?" not in page.url and bill not in page.url, "the preview is not an address"


def test_next_and_previous_step_through_the_shown_cards(device):
    page = open_wide(device)
    first, second = cards(page).nth(0), cards(page).nth(1)
    first.locator(".bill-filed").click()
    page.locator('#bill-preview [data-preview-step="1"]').click()
    expect(page.locator("#preview-title")).to_have_text(second.locator(".bill-title").inner_text())
    expect(page.locator(".bill-card.previewed")).to_have_count(1)
    expect(second).to_have_class(re.compile(r"\bpreviewed\b"))
    page.locator('#bill-preview [data-preview-step="-1"]').click()
    expect(page.locator("#preview-title")).to_have_text(first.locator(".bill-title").inner_text())


def test_escape_and_close_hide_the_preview_and_return_focus_to_the_card(device):
    page = open_wide(device)
    first = cards(page).nth(0)
    first.locator(".bill-filed").click()
    expect(page.locator("#bill-preview")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#bill-preview")).to_be_hidden()
    expect(first.locator(".bill-title-link")).to_be_focused()
    expect(page.locator(".bill-card.previewed")).to_have_count(0)
    first.locator(".bill-filed").click()
    page.locator("#preview-close").click()
    expect(page.locator("#bill-preview")).to_be_hidden()


def test_watch_in_the_preview_updates_the_card_and_open_goes_to_the_page(device):
    page = open_wide(device)
    first = cards(page).nth(0)
    bill = first.get_attribute("data-bill-id")
    first.locator(".bill-filed").click()
    page.locator(f'#bill-preview [data-watch="{bill}"]').click()
    expect(page.locator(f'#bill-preview [data-watch="{bill}"]')).to_have_attribute("aria-pressed", "true")
    expect(first.locator(".watch-button")).to_have_attribute("aria-pressed", "true")
    page.locator("#bill-preview [data-open]").click()
    expect(page.locator("#bill-page")).to_be_visible()
    assert page.url.endswith(f"#bill?id={bill}")
    page.locator("#bill-back").click()
    expect(page.locator("#bill-list article.bill-card").first).to_be_visible()
    expect(page.locator("#bill-preview")).to_be_hidden()


def test_a_phone_opens_the_bill_page_not_the_preview(device):
    page = device.open("#all")
    if page.viewport_size["width"] >= 1200:
        pytest.skip("phones only")
    first = cards(page).nth(0)
    bill = first.get_attribute("data-bill-id")
    first.locator(".bill-filed").click()
    expect(page.locator("#bill-page")).to_be_visible()
    assert page.url.endswith(f"#bill?id={bill}")
