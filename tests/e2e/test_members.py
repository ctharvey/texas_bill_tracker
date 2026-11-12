"""Member pages (#member?code=...): profile, tenure tag, bills by role, links from a bill, and the not-found fallbacks."""

import json
import re
from pathlib import Path

from playwright.sync_api import expect

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "live"
BILLS = json.loads((FIXTURES / "bills.json").read_text(encoding="utf-8"))["bills"]

LANDGRAF = "A3040"   # Rep. Brooks Landgraf, House 81, 12 years
MENENDEZ = "A1110"   # Sen. Jose Menendez, Senate 26, 26 years
GARIBAY = "A4875"    # Rep. Montserrat Garibay, House 49, new member


def authored(name, chamber):
    """Bill numbers the snapshot lists as authored by a legislator of this chamber (read straight from the raw data).
    The frozen snapshot has no coauthors, sponsors or cosponsors on any bill."""
    return [b["number"] for b in BILLS if name in b["authors"] and b["chamber"] == chamber]


def section_titles(page):
    return [re.sub(r"\s+", " ", h.inner_text()).strip() for h in page.locator("#dynamic-content .today-group h3").all()]


def test_house_member_profile(device):
    page = device.open(f"#member?code={LANDGRAF}")
    expect(page.locator("#dynamic-content h2")).to_have_text("Rep. Brooks Landgraf")
    expect(page.locator("#page-title")).to_contain_text("Every bill they")
    profile = page.locator(".member-profile")
    expect(profile).to_contain_text("Texas House · District 81")
    expect(profile).to_contain_text("Republican · HD 81 · 12 years served · since 2015")
    expect(profile.locator(".tenure-pill")).to_have_text("Senior")
    expect(profile).to_contain_text("12 years in the House")
    expect(profile).to_contain_text("Ector County, Loving County, Ward County, Winkler County")
    expect(profile.get_by_role("link", name="Texas Legislature Online")).to_have_attribute(
        "href", "https://capitol.texas.gov/Members/MemberInfo.aspx?Leg=90&Chamber=H&Code=A3040")
    expect(profile.get_by_role("link", name="Legislative Reference Library")).to_have_attribute(
        "href", re.compile(r"^https://lrl\.texas\.gov/legeLeaders/members/memberDisplay\.cfm\?memberID=\d+$"))
    expect(profile.locator(".follow-button")).to_have_text("+ Follow")
    expect(profile.get_by_role("link", name="RSS feed")).to_have_attribute("href", f"./live/feeds/members/{LANDGRAF}.xml")


def test_house_member_bill_list_matches_authored_bills(device):
    expected = authored("Landgraf", "House")
    assert len(expected) == 29
    page = device.open(f"#member?code={LANDGRAF}")
    # Only the Author role has bills in this snapshot, so it is the only section.
    assert section_titles(page) == ["Author 29"]
    expect(page.locator("#dynamic-content")).to_contain_text("29 bills in this snapshot.")
    expect(page.locator("#dynamic-content")).to_contain_text(
        "Representatives author and coauthor House bills and sponsor Senate bills that reach the House.")
    rows = page.locator(".today-group .today-row")
    expect(rows).to_have_count(29)
    shown = [r.locator(".bill-number").first.inner_text().strip() for r in rows.all()]
    assert sorted(shown) == sorted(expected)
    assert "HB 717" in shown
    assert page.locator("#dynamic-content .today-group h3:text-matches('Coauthor|Sponsor|Cosponsor')").count() == 0


def test_senate_member_page_pages_through_a_long_list(device):
    expected = authored("Menéndez", "Senate")
    assert len(expected) == 80
    page = device.open(f"#member?code={MENENDEZ}")
    expect(page.locator("#dynamic-content h2")).to_have_text("Sen. José Menéndez")
    profile = page.locator(".member-profile")
    expect(profile).to_contain_text("Texas Senate · District 26")
    expect(profile).to_contain_text("Democratic · SD 26 · 26 years served · since 2001")
    expect(profile.locator(".tenure-pill")).to_have_text("Senior")
    expect(page.locator("#dynamic-content")).to_contain_text("80 bills in this snapshot.")
    expect(page.locator("#dynamic-content")).to_contain_text(
        "Senators author and coauthor Senate bills and sponsor House bills that reach the Senate.")
    assert section_titles(page) == ["Author 80"]
    rows = page.locator(".today-group .today-row")
    expect(rows).to_have_count(30)
    more = page.locator("[data-member-more='Author']")
    expect(more).to_have_text("Show 30 more · showing 30 of 80")
    more.click()
    expect(rows).to_have_count(60)
    page.locator("[data-member-more='Author']").click()
    expect(rows).to_have_count(80)
    expect(page.locator("[data-member-more]")).to_have_count(0)


def test_new_member_shows_newcomer_tag(device):
    page = device.open(f"#member?code={GARIBAY}")
    profile = page.locator(".member-profile")
    expect(page.locator("#dynamic-content h2")).to_have_text("Rep. Montserrat Garibay")
    expect(profile.locator(".tenure-pill")).to_have_text("Newcomer")
    expect(profile).to_contain_text("Democratic (2026 ballot, unofficial) · HD 49 · member-elect; no prior service on record")
    expect(profile).to_contain_text("New to the House")
    expect(profile).to_contain_text("Texas House · District 49")
    expect(page.locator("#dynamic-content")).to_contain_text("No bills by this member in this snapshot yet.")
    assert section_titles(page) == []


def test_drawer_author_links_to_member_page(device):
    page = device.open("#all?bill=HB717")
    link = page.locator("#detail-drawer a.member-name", has_text="Landgraf")
    expect(link).to_have_attribute("href", f"#member?code={LANDGRAF}")
    link.click()
    expect(page.locator("#dynamic-content h2")).to_have_text("Rep. Brooks Landgraf")
    assert page.evaluate("location.hash") == f"#member?code={LANDGRAF}"
    expect(page.locator("#dynamic-content .today-row").first).to_be_visible()
    # The member page lists the bill we came from.
    assert "HB 717" in [t.strip() for t in page.locator("#dynamic-content .bill-number").all_inner_texts()]


def test_well_formed_unknown_code_says_member_not_found(device):
    page = device.open("#member?code=A9999")
    expect(page.locator("#dynamic-content h2")).to_have_text("Member not found")
    expect(page.locator("#dynamic-content .info-callout")).to_contain_text(
        "No member of the 90th Legislature has the code A9999.")
    expect(page.locator("#dynamic-content .info-callout").get_by_role("link", name="Near you")).to_have_attribute(
        "href", "#local")


def test_malformed_or_missing_code_falls_back_the_same_way(device):
    page = device.open("#member?code=not-a-code")
    expect(page.locator("#dynamic-content h2")).to_have_text("Member not found")
    expect(page.locator("#dynamic-content .info-callout")).to_contain_text(
        "No member of the 90th Legislature has the code in this address.")
    page = device.open("#member")
    expect(page.locator("#dynamic-content h2")).to_have_text("Member not found")
    expect(page.locator("#dynamic-content .info-callout")).to_contain_text("has the code in this address.")
