"""Code pages (#24): /law lists the codes, /law/<CODE> every chapter with the ones bills change marked, and a chapter
opens its own page. The law copy's index is stubbed (the fixtures have no live/law); the fixture statute index has bills
changing sections in Labor Code chapter 62 and none in chapter 63, so 62 is marked and 63 is not."""

import json
import re

from playwright.sync_api import expect

LAW = {"format": "texas-bill-law-v1", "codes": {
    "LA": {"name": "Labor Code", "headings": {"62": "CHAPTER 62. MINIMUM WAGE", "63": "CHAPTER 63. AN UNCHANGED CHAPTER",
                                              "62.v2": "CHAPTER 62. A SECOND VERSION"}},
    "PE": {"name": "Penal Code", "headings": {"2": "CHAPTER 2. BURDEN OF PROOF"}},  # No fixture bill changes PE 2.
}}


def stub_law_index(device):
    device.context.route("**/live/law/index.json",
                         lambda route: route.fulfill(status=200, body=json.dumps(LAW), content_type="application/json"))


def test_the_code_index_lists_the_codes_and_opens_one(device):
    stub_law_index(device)
    page = device.open("/law")
    codes = page.locator("#law-codes li")
    expect(codes).to_have_count(2)
    expect(codes.first).to_contain_text("Labor Code: 2 chapters, 1 changed by bills")
    expect(codes.last).to_have_text("Penal Code: 1 chapter")
    codes.first.locator("a").click()
    expect(page).to_have_url(re.compile(r"/law/LA$"))
    expect(page.locator("#page-title")).to_have_text("Texas Labor Code")
    expect(page).to_have_title(re.compile(r"^Texas Labor Code: every chapter"))


def test_a_code_lists_every_chapter_and_marks_the_ones_bills_change(device):
    stub_law_index(device)
    page = device.open("/law/LA")
    chapters = page.locator("#law-chapters li")
    expect(chapters).to_have_count(2)
    expect(chapters.first).to_contain_text("Chapter 62: Minimum Wage")
    expect(chapters.first.locator("strong")).to_have_text(re.compile(r"^\(\d+ bills? changes? it\)$"))
    expect(chapters.last).to_have_text("Chapter 63: An Unchanged Chapter")
    expect(page.locator("link[rel=canonical]")).to_have_attribute("href", "https://billatlas.org/law/LA")
    chapters.first.locator("a").click()
    expect(page).to_have_url(re.compile(r"/law/LA/62$"))


CN_LAW = {"format": "texas-bill-law-v1", "codes": {
    "CN": {"name": "The Texas Constitution", "headings": {"8": "ARTICLE 8. TAXATION AND REVENUE"}},
    "LA": LAW["codes"]["LA"],
}}
TAIL = " and the bills in the 90th Legislature that would change it."


def test_law_page_subtitles_name_what_the_page_shows(device):
    device.context.route("**/live/law/index.json",
                         lambda route: route.fulfill(status=200, body=json.dumps(CN_LAW), content_type="application/json"))
    page = device.open("/law/CN")
    expect(page.locator("#page-subtitle")).to_have_text(
        "Every article of the Texas Constitution, and the ones bills in the 90th Legislature would change.")
    content = page.locator("#dynamic-content")
    expect(content).to_contain_text("Bills are matched to articles automatically")
    expect(content).not_to_contain_text("TEXAS CODE")
    page.locator("#law-chapters li a").first.click()
    expect(page).to_have_url(re.compile(r"/law/CN/8$"))
    expect(page.locator("#page-subtitle")).to_have_text("An article of the Texas Constitution" + TAIL)
    page = device.open("/law/CN/8/1-b")
    expect(page.locator("#page-subtitle")).to_have_text("A section of the Texas Constitution" + TAIL)
    page = device.open("/law/LA/62")
    expect(page.locator("#page-subtitle")).to_have_text("A chapter of Texas law" + TAIL)
    page = device.open("/law/LA")
    expect(page.locator("#dynamic-content")).to_contain_text("Bills are matched to chapters automatically")
    expect(page.locator("#page-subtitle")).to_have_text(
        "Every chapter of a Texas code, and the ones bills in the 90th Legislature would change.")


def test_an_unknown_code_says_so(device):
    stub_law_index(device)
    page = device.open("/law/ZZ")
    expect(page.locator("#dynamic-content")).to_contain_text("No Texas code this site follows matches ZZ")
