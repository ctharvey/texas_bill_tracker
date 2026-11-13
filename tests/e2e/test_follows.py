"""Following legislators: the follow button, the #nav-follow count, the Following view, persistence and the RSS link."""

import json
from pathlib import Path

from playwright.sync_api import expect

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "live"
BILLS = json.loads((FIXTURES / "bills.json").read_text(encoding="utf-8"))["bills"]

FOLLOW_KEY = "tx-bill-atlas-follow-90r"
LANDGRAF = "A3040"   # Rep. Brooks Landgraf, authors 29 captured bills
SPARKS = "A1375"     # Sen. Kevin Sparks, authors 2 captured bills
MENENDEZ = "A1110"
NEAR_KEY = "texas-bill-atlas-near-you-v1"

ODESSA = {"latitude": 31.8457, "longitude": -102.3676}   # House 81 (Landgraf), Senate 31 (Sparks)


def stored_follows(device):
    raw = device.storage().get(FOLLOW_KEY)
    return None if raw is None else json.loads(raw)


def authored_numbers(name, chamber):
    return [b["number"] for b in BILLS if name in b["authors"] and b["chamber"] == chamber]


def followed_chips(page):
    return [c.inner_text().replace("\n", " ").strip() for c in page.locator(".followed-member").all()]


def test_follow_from_member_page_persists_and_lists_bills(device):
    page = device.open(f"#member?code={LANDGRAF}")
    button = page.locator(".member-profile [data-follow]")
    expect(button).to_have_text("+ Follow")
    expect(button).to_have_attribute("aria-pressed", "false")
    assert stored_follows(device) is None
    expect(page.locator("#nav-follow")).to_have_text("0")

    button.click()
    expect(button).to_have_text("✓ Following")
    expect(button).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#toast")).to_have_text("Following Rep. Brooks Landgraf · their bills are under Following")
    expect(page.locator("#nav-follow")).to_have_text("1")
    assert device.storage()[FOLLOW_KEY] == '["A3040"]'

    # Survives a reload: the button, the count and the Following view all come back from this device's storage.
    page.reload(wait_until="networkidle")
    expect(page.locator(".member-profile [data-follow]")).to_have_text("✓ Following")
    expect(page.locator("#nav-follow")).to_have_text("1")

    page = device.open("#following")
    section = page.locator(".followed-section", has_text="Followed legislators")
    expect(section.locator("h3")).to_have_text("Followed legislators 1")
    assert followed_chips(page) == ["Rep. Brooks Landgraf RSS Unfollow"]
    expect(page.locator(".followed-member a.member-name")).to_have_attribute("href", f"#member?code={LANDGRAF}")
    expected = authored_numbers("Landgraf", "House")
    rows = section.locator(".today-row")
    expect(rows).to_have_count(len(expected))
    assert sorted(t.strip() for t in rows.locator(".bill-number").all_inner_texts()) == sorted(expected)
    # Each row names who it is followed through and in what role.
    expect(rows.first.locator(".today-action")).to_have_text("Rep. Landgraf · Author")


def test_member_rss_link_points_at_the_member_feed(device):
    device.open(f"#member?code={LANDGRAF}")
    link = device.page.locator(".member-profile").get_by_role("link", name="RSS feed")
    expect(link).to_have_attribute("href", f"./live/feeds/members/{LANDGRAF}.xml")
    expect(link).to_have_attribute("target", "_blank")
    device.page.locator(".member-profile [data-follow]").click()
    page = device.open("#following")
    expect(page.locator(".followed-member").get_by_role("link", name="RSS")).to_have_attribute(
        "href", f"./live/feeds/members/{LANDGRAF}.xml")


def test_unfollow_from_member_page_and_from_following_view(device):
    page = device.open(f"#member?code={LANDGRAF}")
    button = page.locator(".member-profile [data-follow]")
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")
    button.click()
    expect(button).to_have_text("+ Follow")
    expect(page.locator("#toast")).to_have_text("Unfollowed Rep. Brooks Landgraf")
    expect(page.locator("#nav-follow")).to_have_text("0")
    assert device.storage()[FOLLOW_KEY] == "[]"

    button.click()
    expect(page.locator("#nav-follow")).to_have_text("1")
    page = device.open("#following")
    page.get_by_role("button", name="Unfollow Rep. Brooks Landgraf").click()
    # Unfollowing on the Following view itself: the toast carries no pointer to the Following view.
    expect(page.locator("#toast")).to_have_text("Unfollowed Rep. Brooks Landgraf")
    expect(page.locator(".followed-member")).to_have_count(0)
    expect(page.locator("#dynamic-content")).to_contain_text(
        "Follow a legislator from their member page or from Near you to see every bill they file or sign onto here.")
    expect(page.locator("#nav-follow")).to_have_text("0")
    assert device.storage()[FOLLOW_KEY] == "[]"


def test_follow_from_near_you_result_lists_both_legislators_bills(device):
    device.context.grant_permissions(["geolocation"])
    device.context.set_geolocation(ODESSA)
    page = device.open("#local")
    page.locator("#near-locate:not([disabled])").click()
    cards = page.locator(".near-member")
    expect(cards).to_have_count(2)
    expect(cards.nth(0)).to_contain_text("Rep. Brooks Landgraf")
    expect(cards.nth(1)).to_contain_text("Sen. Kevin Sparks")

    house_btn, senate_btn = cards.nth(0).locator("[data-follow]"), cards.nth(1).locator("[data-follow]")
    expect(house_btn).to_have_text("+ Follow")
    senate_btn.click()
    expect(cards.nth(1).locator("[data-follow]")).to_have_text("✓ Following")
    expect(cards.nth(0).locator("[data-follow]")).to_have_text("+ Follow")
    cards.nth(0).locator("[data-follow]").click()
    expect(cards.nth(0).locator("[data-follow]")).to_have_text("✓ Following")
    expect(page.locator("#nav-follow")).to_have_text("2")
    # Stored in the order they were followed.
    assert json.loads(device.storage()[FOLLOW_KEY]) == [SPARKS, LANDGRAF]

    page = device.open("#following")
    assert followed_chips(page) == ["Sen. Kevin Sparks RSS Unfollow", "Rep. Brooks Landgraf RSS Unfollow"]
    section = page.locator(".followed-section", has_text="Followed legislators")
    expect(section.locator("h3")).to_have_text("Followed legislators 2")
    expected = authored_numbers("Landgraf", "House") + authored_numbers("Sparks", "Senate")
    rows = section.locator(".today-row")
    expect(rows).to_have_count(min(30, len(expected)))
    expect(page.locator("#follow-more")).to_have_text(f"Show 30 more · showing 30 of {len(expected)}")
    page.locator("#follow-more").click()
    expect(rows).to_have_count(len(expected))
    assert sorted(t.strip() for t in rows.locator(".bill-number").all_inner_texts()) == sorted(expected)
    expect(page.locator("#follow-more")).to_have_count(0)


def test_stored_follows_are_cleaned_on_load(device):
    """Invalid codes and repeats are dropped when the list is read; a well-formed code unknown to the roster still
    counts in the badge but has no chip or bills."""
    device.open("#all")
    device.page.evaluate("k => localStorage.setItem(k, JSON.stringify(['A3040','nonsense','A3040','a1','A1110','A9999']))",
                         FOLLOW_KEY)
    page = device.open("#following")
    page.reload(wait_until="networkidle")
    expect(page.locator("#nav-follow")).to_have_text("3")
    expect(page.locator(".followed-section", has_text="Followed legislators").locator("h3")).to_have_text(
        "Followed legislators 2")
    assert followed_chips(page) == ["Rep. Brooks Landgraf RSS Unfollow", "Sen. José Menéndez RSS Unfollow"]
    # Writing a change re-saves the cleaned list.
    page.get_by_role("button", name="Unfollow Rep. Brooks Landgraf").click()
    assert json.loads(device.storage()[FOLLOW_KEY]) == [MENENDEZ, "A9999"]


def test_followed_legislator_with_no_bills_says_so(device):
    device.open("#member?code=A4875")   # Rep. Garibay: no captured bills
    device.page.locator(".member-profile [data-follow]").click()
    page = device.open("#following")
    expect(page.locator(".followed-member")).to_have_count(1)
    expect(page.locator("#dynamic-content")).to_contain_text("No bills by the legislators you follow in this snapshot yet.")


def test_drawer_author_offers_a_member_link_but_no_follow_button(device):
    page = device.open("#bill?id=HB717")
    drawer = page.locator("#bill-page")
    expect(drawer.locator("a.member-name", has_text="Landgraf")).to_have_attribute("href", f"#member?code={LANDGRAF}")
    expect(drawer.locator("[data-follow]")).to_have_count(0)
