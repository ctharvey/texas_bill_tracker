"""Bill explorer (#all): search, filters, sorting, paging, URL hash and remembered filters, watched-only, opening a bill."""

import json
from urllib.parse import parse_qs, unquote

from playwright.sync_api import expect

from harness import click, reveal

TOTAL = "1384 bills"
PREFS_KEY = "tx-bill-atlas-prefs-v1"


def numbers(page, limit=None):
    """Bill numbers of the cards on screen, in order ("HB 110")."""
    found = page.locator(".bill-card .bill-number").all_inner_texts()
    return found[:limit] if limit else found


def hash_of(page):
    return page.evaluate("location.hash")


def hash_params(page):
    h = hash_of(page)
    return parse_qs(h.split("?", 1)[1]) if "?" in h else {}


def count(page):
    return page.locator("#result-count").inner_text()


def pick(page, selector, label):
    reveal(page, selector)
    page.select_option(selector, label=label)


def test_search_filters_results_and_count(device):
    page = device.open("#all")
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    page.fill("#bill-search", "HB110")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    assert numbers(page) == ["HB 110"]
    assert hash_params(page) == {"query": ["HB110"]}
    page.fill("#bill-search", "school")
    expect(page.locator("#result-count")).not_to_have_text(TOTAL)
    expect(page.locator("#result-count")).to_have_text("219 bills")
    page.fill("#bill-search", "")
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    assert hash_of(page) == "#all"


def test_search_with_no_match_shows_empty_state(device):
    page = device.open("#all")
    page.fill("#bill-search", "zzzzqqqq nothing matches this")
    expect(page.locator("#result-count")).to_have_text("0 bills")
    expect(page.locator("#bill-list")).to_contain_text("Nothing matches yet")
    assert numbers(page) == []


def test_search_matches_a_bill_by_its_title_text(device):
    page = device.open("#all")
    page.fill("#bill-search", "minimum wage")
    expect(page.locator("#result-count")).not_to_have_text(TOTAL)
    assert "HB 110" in numbers(page)
    assert "Relating to the minimum wage" in page.locator('.bill-card[data-bill-id="HB110"]').inner_text()


def test_topic_filter(device):
    page = device.open("#all")
    pick(page, "#filter-topic", "Education")
    expect(page.locator("#result-count")).to_have_text("246 bills")
    assert hash_params(page) == {"topic": ["Education"]}
    page.fill("#bill-search", "HB110")
    expect(page.locator("#result-count")).to_have_text("0 bills")  # HB110 is Labor & workforce, not Education
    pick(page, "#filter-topic", "All policy areas")
    expect(page.locator("#result-count")).to_have_text("1 bill")


def test_topic_chip_quick_filter_sets_the_topic(device):
    page = device.open("#all")
    page.locator(".topic-chip", has_text="Education").click()
    expect(page.locator("#result-count")).to_have_text("246 bills")
    expect(page.locator("#filter-topic")).to_have_value("Education")
    expect(page.locator(".topic-chip.selected")).to_have_text("Education")
    page.locator(".topic-chip", has_text="All topics").click()
    expect(page.locator("#result-count")).to_have_text(TOTAL)


def test_chamber_filter(device):
    page = device.open("#all")
    pick(page, "#filter-chamber", "Senate")
    expect(page.locator("#result-count")).to_have_text("319 bills")
    assert all(n.startswith("S") for n in numbers(page))
    pick(page, "#filter-chamber", "House")
    expect(page.locator("#result-count")).to_have_text("1065 bills")
    assert all(n.startswith("H") for n in numbers(page))
    assert hash_params(page) == {"chamber": ["House"]}


def test_stage_filter(device):
    page = device.open("#all")
    pick(page, "#filter-stage", "Referred")
    expect(page.locator("#result-count")).to_have_text("0 bills")
    expect(page.locator("#bill-list")).to_contain_text("Nothing matches yet")
    pick(page, "#filter-stage", "Filed")
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    assert hash_params(page) == {"stage": ["Filed"]}


def test_hearing_status_filter(device):
    page = device.open("#all")
    pick(page, "#filter-outlook", "Heard")
    expect(page.locator("#result-count")).to_have_text("0 bills")
    pick(page, "#filter-outlook", "No hearing yet")
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    assert hash_params(page) == {"outlook": ["No hearing yet"]}


def test_last_action_filter(device):
    page = device.open("#all")
    expect(page.locator("#filter-action option")).to_have_text(["Any last action", "Filed"])
    pick(page, "#filter-action", "Filed")
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    assert hash_params(page) == {"action": ["Filed"]}
    page.locator(".bill-card").first.locator(".action-tag").wait_for()
    assert "Filed" in page.locator(".bill-card .action-tag").first.inner_text()
    pick(page, "#filter-action", "Any last action")
    # A label no bill has matches nothing (the dropdown never offers it, but an address can carry it).
    page.evaluate("location.hash = '#all?action=Other%20action'")
    expect(page.locator("#result-count")).to_have_text("0 bills")


def test_filters_combine(device):
    page = device.open("#all")
    pick(page, "#filter-topic", "Data centers")
    pick(page, "#filter-chamber", "Senate")
    expect(page.locator("#result-count")).to_have_text("6 bills")
    assert sorted(numbers(page)) == sorted(["SB 296", "SB 293", "SB 32", "SB 33", "SB 34", "SB 36"])
    assert all(n.startswith("S") for n in numbers(page))
    assert hash_params(page) == {"topic": ["Data centers"], "chamber": ["Senate"]}


def test_sort_order_changes_the_list(device):
    page = device.open("#all")
    newest = numbers(page, 3)
    assert newest[0] == "HB 1087"
    pick(page, "#sort-order", "Bill number")
    expect(page.locator(".bill-card .bill-number").first).to_have_text("HB 101")
    assert numbers(page, 3) != newest
    assert hash_params(page) == {"sort": ["number"]}
    pick(page, "#sort-order", "Newest filed")
    expect(page.locator(".bill-card .bill-number").first).to_have_text("HB 1087")
    assert numbers(page, 3) == newest
    assert hash_of(page) == "#all"  # the default sort is not written to the address


def test_every_sort_option_is_selectable_and_recorded(device):
    page = device.open("#all")
    keys = {"Newest filed": None, "Latest action": "latest", "Oldest last action": "oldest",
            "Last action stage": "actionstage", "Bill number": "number", "Most agencies": "agencies",
            "Hearing progress": "hearing", "Author influence": "influence"}
    # First cards under each sort in the frozen data. "Oldest last action" and "Hearing progress" tie everywhere
    # in this snapshot (all bills are Filed, No hearing yet, same dates) and fall back to bill number, so they equal "Bill number".
    first = {"Newest filed": ["HB 1087", "HB 1086", "HB 1085"], "Latest action": ["HB 1082", "HB 1083", "HB 1084"],
             "Oldest last action": ["HB 101", "HB 855", "SB 31"], "Last action stage": ["HB 1082", "HB 1083", "HB 1084"],
             "Bill number": ["HB 101", "HB 855", "SB 31"], "Most agencies": ["HB 805", "HB 352", "HB 1018"],
             "Hearing progress": ["HB 101", "HB 855", "SB 31"], "Author influence": ["HB 103", "HB 105", "HB 108"]}
    for label, key in keys.items():
        pick(page, "#sort-order", label)
        expect(page.locator("#sort-order")).to_have_value(label)
        expect(page.locator(".bill-card .bill-number").first).to_have_text(first[label][0])
        assert numbers(page, 3) == first[label], label
        assert page.locator("#result-count").inner_text() == TOTAL
        assert hash_params(page).get("sort") == ([key] if key else None)
    # Most agencies really is ordered by agency links: the top card has the most, and later ones never have more
    pick(page, "#sort-order", "Most agencies")
    expect(page.locator(".bill-card .bill-number").first).to_have_text("HB 805")
    # A card with no agency link shows no count (D5), which reads as 0.
    links = [int(c.locator(".bill-links").inner_text().split()[0]) if c.locator(".bill-links").count() else 0
             for c in page.locator(".bill-card").all()]
    # Only the head is checked: companion bills are pulled next to each other, which reorders later rows.
    assert links[0] == 7 and links[:10] == sorted(links[:10], reverse=True)


def test_filters_are_restored_from_the_hash(device):
    page = device.open("#all?topic=Data%20centers&chamber=Senate&sort=number")
    expect(page.locator("#result-count")).to_have_text("6 bills")
    expect(page.locator("#filter-topic")).to_have_value("Data centers")
    expect(page.locator("#filter-chamber")).to_have_value("Senate")
    expect(page.locator("#sort-order")).to_have_value("Bill number")
    nums = numbers(page)
    assert nums == sorted(nums, key=lambda n: int(n.split()[1]))


def test_search_in_the_hash_fills_the_search_box(device):
    page = device.open("#all?query=HB110")
    expect(page.locator("#bill-search")).to_have_value("HB110")
    expect(page.locator("#result-count")).to_have_text("1 bill")


def test_filter_changes_rewrite_the_address_without_adding_history(device):
    page = device.open("#all")
    before = page.evaluate("history.length")
    pick(page, "#filter-chamber", "Senate")
    pick(page, "#filter-topic", "Education")
    expect(page.locator("#result-count")).not_to_have_text(TOTAL)
    assert hash_params(page) == {"chamber": ["Senate"], "topic": ["Education"]}
    assert page.evaluate("history.length") == before


def test_back_and_forward_move_between_filtered_addresses(device):
    page = device.open("#all")
    page.evaluate("location.hash = '#all?chamber=Senate'")
    expect(page.locator("#result-count")).to_have_text("319 bills")
    page.evaluate("location.hash = '#all?topic=Data%20centers&chamber=House'")
    expect(page.locator("#filter-topic")).to_have_value("Data centers")
    expect(page.locator("#filter-chamber")).to_have_value("House")
    house_dc = count(page)
    assert house_dc not in (TOTAL, "319 bills")
    page.go_back()
    expect(page.locator("#result-count")).to_have_text("319 bills")
    expect(page.locator("#filter-chamber")).to_have_value("Senate")
    expect(page.locator("#filter-topic")).to_have_value("")
    assert hash_params(page) == {"chamber": ["Senate"]}
    page.go_forward()
    expect(page.locator("#filter-topic")).to_have_value("Data centers")
    expect(page.locator("#filter-chamber")).to_have_value("House")
    expect(page.locator("#result-count")).to_have_text(house_dc)


def test_load_more_pages_thirty_at_a_time(device):
    page = device.open("#all")
    more = page.locator("#load-more")
    expect(more).to_be_visible()
    first = page.locator(".bill-card").count()
    assert 30 <= first <= 40  # 30, plus the rest of a companion group that straddles the page edge
    expect(more).to_have_text(f"Load 30 more · showing {first} of 1384")
    more.click()
    expect(page.locator("#load-more")).not_to_have_text(f"Load 30 more · showing {first} of 1384")
    second = page.locator(".bill-card").count()
    assert 60 <= second <= 70  # the visible target is now 60; whole companion groups are never split
    expect(page.locator("#load-more")).to_have_text(f"Load 30 more · showing {second} of 1384")
    # Changing a filter starts paging over at 30
    pick(page, "#filter-chamber", "House")
    expect(page.locator("#result-count")).to_have_text("1065 bills")
    assert page.locator(".bill-card").count() <= 40


def test_no_load_more_when_everything_fits(device):
    page = device.open("#all?query=HB110")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    assert page.locator("#load-more").count() == 0


def test_clear_filters_resets_everything(device):
    page = device.open("#all")
    pick(page, "#filter-topic", "Data centers")
    pick(page, "#filter-chamber", "Senate")
    pick(page, "#sort-order", "Bill number")
    page.fill("#bill-search", "SB")
    expect(page.locator("#result-count")).not_to_have_text(TOTAL)
    page.click("#clear-filters")
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    expect(page.locator("#bill-search")).to_have_value("")
    expect(page.locator("#filter-topic")).to_have_value("")
    expect(page.locator("#filter-chamber")).to_have_value("")
    expect(page.locator("#sort-order")).to_have_value("Newest filed")
    assert hash_of(page) == "#all"
    assert numbers(page, 1) == ["HB 1087"]


def test_only_watched_toggle(device):
    page = device.open("#all?query=HB110")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    page.locator('[data-watch="HB110"]').click()
    expect(page.locator('[data-watch="HB110"]')).to_have_attribute("aria-pressed", "true")
    page.fill("#bill-search", "")
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    click(page, "#watch-filter")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    assert numbers(page) == ["HB 110"]
    assert hash_params(page) == {"onlyWatch": ["1"]}
    click(page, "#watch-filter")
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    assert hash_of(page) == "#all"


def test_only_watched_with_nothing_watched_is_empty(device):
    page = device.open("#all")
    click(page, "#watch-filter")
    expect(page.locator("#result-count")).to_have_text("0 bills")
    expect(page.locator("#bill-list")).to_contain_text("Nothing matches yet")


def test_clicking_a_card_title_opens_the_bill_page_and_back_keeps_the_search(device):
    page = device.open("#all?query=HB110")
    expect(page.locator("#result-count")).to_have_text("1 bill")
    page.locator('.bill-card[data-bill-id="HB110"] .bill-title-link').click()
    expect(page.locator("#bill-page")).to_be_visible()
    expect(page.locator("#bill-page")).to_contain_text("HB 110")
    expect(page.locator("#bill-page")).to_contain_text("minimum wage")
    assert page.url.endswith("#bill?id=HB110")
    page.click("#bill-back")
    expect(page.locator("#bill-page")).to_have_count(0)
    page.wait_for_function("location.hash.startsWith('#all')")
    assert hash_params(page) == {"query": ["HB110"]}


def test_bill_details_button_opens_the_bill_page(device):
    page = device.open("#all?query=HB110")
    page.locator('.bill-card[data-bill-id="HB110"] .bill-open').click()
    expect(page.locator("#bill-page")).to_be_visible()
    assert page.url.endswith("#bill?id=HB110")


def test_bill_address_opens_the_bill_page_on_load(device):
    page = device.open("#bill?id=HB110")
    expect(page.locator("#bill-page")).to_be_visible()
    expect(page.locator("#bill-page")).to_contain_text("minimum wage")


def test_remembered_filters_come_back_on_reload(device):
    page = device.open("#all")
    pick(page, "#filter-chamber", "Senate")
    pick(page, "#filter-topic", "Data centers")
    expect(page.locator("#result-count")).to_have_text("6 bills")
    saved = json.loads(device.storage()[PREFS_KEY])["filters"]
    assert saved["chamber"] == "Senate" and saved["topic"] == "Data centers" and saved["query"] == ""
    # A bare #all in a later visit (a new document in the same browser profile) restores them, and the address shows them again.
    page = device.open("#all", page=device.new_page())
    expect(page.locator("#result-count")).to_have_text("6 bills")
    expect(page.locator("#filter-chamber")).to_have_value("Senate")
    expect(page.locator("#filter-topic")).to_have_value("Data centers")
    assert hash_params(page) == {"topic": ["Data centers"], "chamber": ["Senate"]}


def test_filters_in_the_address_beat_remembered_filters(device):
    page = device.open("#all")
    pick(page, "#filter-chamber", "Senate")
    expect(page.locator("#result-count")).to_have_text("319 bills")
    page = device.open("#all?chamber=House", page=device.new_page())
    expect(page.locator("#result-count")).to_have_text("1065 bills")
    assert json.loads(device.storage()[PREFS_KEY])["filters"]["chamber"] == "House"


def test_clearing_filters_is_remembered_too(device):
    page = device.open("#all?chamber=Senate")
    expect(page.locator("#result-count")).to_have_text("319 bills")
    page.click("#clear-filters")
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    page = device.open("#all", page=device.new_page())
    expect(page.locator("#result-count")).to_have_text(TOTAL)
    expect(page.locator("#filter-chamber")).to_have_value("")


def test_remembered_filters_do_not_leak_into_a_fresh_profile(device_factory):
    first = device_factory()
    page = first.open("#all?chamber=Senate")
    expect(page.locator("#result-count")).to_have_text("319 bills")
    other = device_factory()
    page2 = other.open("#all")
    expect(page2.locator("#result-count")).to_have_text(TOTAL)
    assert page2.evaluate("location.hash") == "#all"
