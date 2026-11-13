"""Bill search box (#bill-search): what a query matches, odd input, the address bar, and search beside other controls.

Counts are for the captured fixture (1384 bills).
"""

import re

import pytest
from playwright.sync_api import expect

TOTAL = "1384 bills"
COUNT = re.compile(r"^\d+ bills?$")


def numbers(page, limit=None):
    found = page.locator(".bill-card .bill-number").all_inner_texts()
    return found[:limit] if limit else found


def count(page) -> int:
    return int(page.locator("#result-count").inner_text().split()[0])


def search(page, query):
    """Type a query and wait until the app has recorded it in the address (which happens after it renders)."""
    page.fill("#bill-search", query)
    page.wait_for_function(
        "q => (new URLSearchParams(location.hash.split('?')[1] || '').get('query') || '') === q", arg=query)


def count_for(page, query) -> int:
    search(page, query)
    expect(page.locator("#result-count")).to_have_text(COUNT)
    return count(page)


def expect_count(page, text):
    expect(page.locator("#result-count")).to_have_text(text)


# ---- Bill numbers ----

@pytest.mark.parametrize("typed", ["HB110", "hb110", "HB 110", "hb 110", "H.B. 110", "H.B. No. 110", "House Bill 110",
                                   "house bill no. 110", "HB\u200b110", "\ufeffHB 110", "  HB110  ", "\uff28\uff22\uff11\uff11\uff10"])
def test_a_bill_number_is_found_however_it_is_written(device, typed):
    page = device.open("#all")
    search(page, typed)
    expect_count(page, "1 bill")
    assert numbers(page) == ["HB 110"]


def test_a_partial_bill_number_finds_every_bill_that_starts_with_it(device):
    page = device.open("#all")
    search(page, "HB 108")
    expect_count(page, "9 bills")
    assert all(n.startswith("HB 108") for n in numbers(page))


def test_a_bare_number_finds_that_number_in_both_chambers(device):
    page = device.open("#all")
    search(page, "110")
    expect_count(page, "2 bills")
    assert sorted(numbers(page)) == ["HB 110", "SB 110"]
    search(page, "1087")
    expect_count(page, "1 bill")
    assert numbers(page) == ["HB 1087"]


def test_a_resolution_is_found_by_its_long_name(device):
    page = device.open("#all")
    search(page, "House Resolution 18")
    assert "HR 18" in numbers(page)
    assert all(n.startswith("HR 18") for n in numbers(page))


def test_a_bill_number_with_leading_zeros_is_found(device):
    page = device.open("#all")
    search(page, "HB0110")
    expect(page.locator(".bill-card .bill-number")).to_have_text(["HB 110"])


# ---- Words ----

@pytest.mark.parametrize("typed", ["minimum wage", "MINIMUM WAGE", "Minimum Wage", "minimum   wage", "  minimum wage  ",
                                   "Relating to the minimum wage", "wage minimum", "mini\u00admum wage"])
def test_a_phrase_matches_whatever_its_case_or_spacing(device, typed):
    page = device.open("#all")
    search(page, typed)
    expect_count(page, "9 bills")
    assert "HB 110" in numbers(page)


def test_a_plural_finds_the_same_bills_as_its_singular(device):
    page = device.open("#all")
    search(page, "wage")
    expect_count(page, "17 bills")
    search(page, "wages")
    expect_count(page, "17 bills")
    search(page, "school")
    expect_count(page, "219 bills")
    search(page, "schools")
    expect_count(page, "219 bills")


def test_double_quotes_keep_words_together_and_in_order(device):
    page = device.open("#all")
    search(page, '"minimum wage"')
    expect_count(page, "8 bills")
    search(page, '"minimum wage."')
    expect_count(page, "8 bills")
    search(page, '"school district"')
    expect_count(page, "148 bills")
    search(page, '"district school"')
    expect_count(page, "0 bills")
    search(page, '"school district" tax')
    expect(page.locator("#result-count")).not_to_have_text("0 bills")
    assert 0 < count(page) < 148


def test_an_ampersand_matches_with_or_without_spaces(device):
    page = device.open("#all")
    assert count_for(page, "A & M") == count_for(page, "A&M") == 4


def test_search_finds_a_bill_by_its_authors_party(device):
    page = device.open("#all")
    republican = count_for(page, '"Republican author"')
    democratic = count_for(page, '"Democratic author"')
    assert republican > 0 and democratic > 0 and republican + democratic <= 1384
    expect(page.locator(".bill-card").first).to_contain_text("Democratic author")


def test_search_finds_a_bill_by_the_date_on_its_card(device):
    page = device.open("#all")
    assert 0 < count_for(page, '"Nov 9"') < 1384
    expect(page.locator(".bill-card").first).to_contain_text("Nov 9")


def test_a_longer_query_never_finds_more(device):
    page = device.open("#all")
    previous = None
    for typed in ["s", "sc", "sch", "scho", "schoo", "school", "school ", "school d", "school district"]:
        search(page, typed)
        expect(page.locator("#result-count")).to_have_text(COUNT)
        now = count(page)
        assert previous is None or now <= previous, typed
        previous = now
    assert previous == 150


def test_search_finds_a_bill_by_its_author(device):
    page = device.open("#all")
    search(page, "Little")
    expect_count(page, "7 bills")
    expect(page.locator(".bill-card").first).to_contain_text("By Little")
    search(page, "Cook, Molly")
    expect_count(page, "25 bills")
    search(page, "Bell, Keith")
    expect_count(page, "2 bills")
    assert sorted(numbers(page)) == ["HB 927", "HB 951"]


def test_search_finds_an_accented_name_typed_with_its_accent(device):
    page = device.open("#all")
    search(page, "Men\u00e9ndez")
    expect_count(page, "80 bills")
    search(page, "men\u00e9ndez")
    expect_count(page, "80 bills")
    search(page, "Anch\u00eda")
    expect_count(page, "13 bills")


@pytest.mark.parametrize("plain, accented", [("Menendez", "Men\u00e9ndez"), ("Anchia", "Anch\u00eda")])
def test_search_finds_an_accented_name_typed_without_its_accent(device, plain, accented):
    page = device.open("#all")
    assert count_for(page, plain) == count_for(page, accented) > 0


def test_search_finds_a_member_by_first_name_then_last(device):
    page = device.open("#all")
    assert count_for(page, "Molly Cook") == count_for(page, "Cook, Molly") > 0


def test_search_finds_the_same_bills_whatever_the_word_order(device):
    page = device.open("#all")
    assert count_for(page, "district school") == count_for(page, "school district") > 0


def test_search_finds_a_bill_by_agency_and_topic_names(device):
    page = device.open("#all")
    search(page, "Texas Education Agency")
    expect_count(page, "82 bills")
    search(page, '"Texas Education Agency"')
    expect_count(page, "72 bills")
    search(page, "Data centers")
    expect_count(page, "25 bills")
    search(page, '"data center"')
    expect_count(page, "22 bills")


def test_search_finds_a_bill_by_official_subject_and_by_impact(device):
    page = device.open("#all")
    search(page, "Labor--Wages")
    expect(page.locator('.bill-card[data-bill-id="HB110"]')).to_be_visible()
    search(page, "MINIMUM WAGE")  # an official subject heading, matched whatever its case
    expect(page.locator('.bill-card[data-bill-id="HB110"]')).to_be_visible()
    search(page, "Eligibility expansion")
    expect(page.locator("#result-count")).not_to_have_text("0 bills")
    assert count(page) < 1384



def test_search_finds_a_bill_by_the_groups_luna_says_it_affects(device):
    # "cemetery plot owners" is an affected group in SB215's Luna review and appears in no other searchable field.
    page = device.open("#all")
    search(page, '"cemetery plot owners"')
    expect_count(page, "1 bill")
    expect(page.locator('.bill-card[data-bill-id="SB215"]')).to_be_visible()

def test_search_reads_the_last_action_line(device):
    page = device.open("#all")
    search(page, '"H Filed"')
    expect_count(page, "1065 bills")  # every House bill in the fixture is at "H Filed"
    page.select_option("#filter-chamber", label="Senate")
    expect_count(page, "0 bills")
    page.select_option("#filter-chamber", label="House")
    expect_count(page, "1065 bills")
    search(page, '"11/09/2026 H Filed"')
    expect(page.locator("#result-count")).not_to_have_text("1065 bills")
    assert 0 < count(page) < 1065


@pytest.mark.parametrize("typed", ["62.051", "Labor Code 62.051", "Sec. 62.051"])
def test_a_law_section_finds_the_bills_that_change_it(device, typed):
    page = device.open("#all")
    search(page, typed)
    expect_count(page, "8 bills")
    assert "HB 110" in numbers(page)


def test_an_ampersand_is_searched_as_typed(device):
    page = device.open("#all")
    search(page, "A&M")
    expect_count(page, "4 bills")
    assert sorted(numbers(page)) == ["HB 1015", "HB 452", "HB 920", "SB 72"]


def test_an_apostrophe_and_a_hyphen_are_searched_as_typed(device):
    page = device.open("#all")
    search(page, "children's")
    expect_count(page, "7 bills")
    search(page, "work-related")
    expect_count(page, "2 bills")
    # HB 297 matches on its affected group "Purchasers of qualifying tools and work-related items".
    assert sorted(numbers(page)) == ["HB 297", "HB 497"]


def test_a_curly_apostrophe_matches_like_a_straight_one(device):
    page = device.open("#all")
    assert count_for(page, "children\u2019s") == count_for(page, "children's") > 0


# ---- Empty and odd input ----

@pytest.mark.parametrize("typed", ["   ", "\u200b", "\ufeff \u00ad"])
def test_a_query_of_only_blank_characters_shows_every_bill(device, typed):
    page = device.open("#all")
    search(page, "HB110")
    expect_count(page, "1 bill")
    search(page, typed)
    expect_count(page, TOTAL)


def test_a_query_is_plain_text_not_a_pattern(device):
    page = device.open("#all")
    search(page, ".*")
    expect_count(page, "0 bills")
    search(page, "(")
    expect_count(page, "28 bills")
    search(page, "wage|school")
    expect_count(page, "0 bills")


ODD = ["<img src=x onerror=alert(1)>", '"><img src=x onerror="window.__xss=1">', "'><svg onload='window.__xss=1'>", "<script>window.__xss=1</script>", "\\", "(", "[", "%20", "%", "#", "?", "=", "&",
       "a+b", "50%", '"', "'", "`${1}`", "../../etc", "\U0001F920 rodeo", "x" * 150]


@pytest.mark.parametrize("typed", ODD)
def test_odd_input_is_safe_and_survives_the_address_bar(device, typed):
    page = device.open("#all")
    search(page, typed)
    expect(page.locator("#result-count")).to_have_text(COUNT)
    shown = page.locator("#result-count").inner_text()
    # The same address in a new tab gives the same box and the same results.
    again = device.open(page.evaluate("location.hash"), page=device.new_page())
    expect(again.locator("#bill-search")).to_have_value(typed)
    expect(again.locator("#result-count")).to_have_text(shown)
    # Nothing typed, or read back from the address, is ever turned into markup.
    for tab in (page, again):
        assert tab.locator("img[src='x'], svg[onload]").count() == 0
        assert tab.evaluate("window.__xss") is None


def test_a_very_long_query_finds_nothing_and_is_cut_in_the_address(device):
    page = device.open("#all")
    page.fill("#bill-search", "x" * 250)
    expect_count(page, "0 bills")
    expect(page.locator("#bill-list")).to_contain_text("Nothing matches yet")
    # Only the first 200 characters are searched, kept in the address and remembered.
    page.wait_for_function("(new URLSearchParams(location.hash.split('?')[1]).get('query') || '').length === 200")
    expect(page.locator("#bill-search")).to_have_attribute("maxlength", "200")
    again = device.open("#all", page=device.new_page())
    assert again.input_value("#bill-search") == "x" * 200
    again = device.open("#all?query=" + "x" * 250, page=device.new_page())
    assert len(again.input_value("#bill-search")) == 200


# ---- Typing ----

def test_results_update_on_every_keystroke_and_the_box_keeps_focus(device):
    page = device.open("#all")
    box = page.locator("#bill-search")
    box.click()
    box.press_sequentially("minimum wage")
    expect_count(page, "9 bills")
    expect(box).to_be_focused()
    expect(box).to_have_value("minimum wage")
    for _ in range(5):
        box.press("Backspace")
    expect_count(page, "27 bills")  # "minimum"
    expect(box).to_be_focused()


def test_pressing_enter_keeps_the_results(device):
    page = device.open("#all")
    search(page, "minimum wage")
    page.locator("#bill-search").press("Enter")
    expect_count(page, "9 bills")
    expect(page.locator("#bill-search")).to_have_value("minimum wage")
    expect(page.locator("#bill-page")).to_be_hidden()


# ---- Address bar and memory ----

def test_a_query_in_the_address_is_decoded_into_the_box(device):
    page = device.open("#all?query=A%26M")
    expect(page.locator("#bill-search")).to_have_value("A&M")
    expect_count(page, "4 bills")
    page = device.open("#all?query=minimum+wage")
    expect(page.locator("#bill-search")).to_have_value("minimum wage")
    expect_count(page, "9 bills")


def test_changing_the_address_changes_the_search(device):
    page = device.open("#all")
    page.evaluate("location.hash = '#all?query=wage'")
    expect(page.locator("#bill-search")).to_have_value("wage")
    expect_count(page, "17 bills")
    page.evaluate("location.hash = '#all?query=minimum%20wage'")
    expect_count(page, "9 bills")
    page.go_back()
    expect(page.locator("#bill-search")).to_have_value("wage")
    expect_count(page, "17 bills")


def test_typing_does_not_add_history_entries(device):
    page = device.open("#all")
    before = page.evaluate("history.length")
    page.locator("#bill-search").press_sequentially("wage")
    expect_count(page, "17 bills")
    assert page.evaluate("history.length") == before


def test_the_last_query_is_remembered_on_the_next_visit(device):
    page = device.open("#all")
    search(page, "wage")
    expect_count(page, "17 bills")
    page = device.open("#all")
    expect(page.locator("#bill-search")).to_have_value("wage")
    expect_count(page, "17 bills")


# ---- Search beside other controls ----

def test_search_and_chamber_filter_split_the_results_exactly(device):
    page = device.open("#all")
    search(page, "school")
    expect_count(page, "219 bills")
    page.select_option("#filter-chamber", label="House")
    expect(page.locator("#result-count")).not_to_have_text("219 bills")
    house = count(page)
    page.select_option("#filter-chamber", label="Senate")
    expect(page.locator("#result-count")).not_to_have_text(f"{house} bills")
    senate = count(page)
    assert house > 0 and senate > 0 and house + senate == 219
    expect(page.locator("#bill-search")).to_have_value("school")


def test_search_narrows_a_topic_filter(device):
    page = device.open("#all?topic=Data%20centers")
    expect(page.locator("#result-count")).to_have_text(COUNT)
    topic_only = count(page)
    search(page, "water")
    expect(page.locator("#result-count")).not_to_have_text(f"{topic_only} bills")
    assert 0 < count(page) < topic_only
    expect(page.locator("#filter-topic")).to_have_value("Data centers")


def test_search_results_follow_the_chosen_sort(device):
    page = device.open("#all")
    search(page, "HB 108")
    expect_count(page, "9 bills")
    newest = [int(n.split()[1]) for n in numbers(page)]
    assert newest == sorted(newest, reverse=True)
    page.select_option("#sort-order", label="Bill number")
    expect(page.locator(".bill-card .bill-number").first).to_have_text(f"HB {min(newest)}")
    by_number = [int(n.split()[1]) for n in numbers(page)]
    assert by_number == sorted(newest)
    expect(page.locator("#bill-search")).to_have_value("HB 108")


def test_search_results_page_thirty_at_a_time(device):
    page = device.open("#all")
    search(page, "school")
    more = page.locator("#load-more")
    expect(more).to_contain_text("of 219")
    first = page.locator(".bill-card").count()
    assert 30 <= first <= 40
    more.click()
    expect(page.locator("#load-more")).not_to_have_text(f"Load 30 more \u00b7 showing {first} of 219")
    assert page.locator(".bill-card").count() > first
    # A new query starts the paging over.
    search(page, "school district")
    expect_count(page, "150 bills")
    assert page.locator(".bill-card").count() <= 40
    search(page, "minimum wage")
    expect_count(page, "9 bills")
    assert page.locator("#load-more").count() == 0


def test_opening_and_closing_a_bill_keeps_the_search(device):
    page = device.open("#all")
    search(page, "minimum wage")
    page.locator('.bill-card[data-bill-id="HB110"] .bill-number').click()
    expect(page.locator("#bill-page")).to_be_visible()
    assert page.evaluate("location.hash") == "#bill?id=HB110"
    page.locator("#bill-back").click()
    expect(page.locator("#bill-page")).to_have_count(0)
    assert "query=minimum%20wage" in page.evaluate("location.hash")
    expect(page.locator("#bill-search")).to_have_value("minimum wage")
    expect_count(page, "9 bills")


def test_clear_filters_empties_the_search(device):
    page = device.open("#all")
    search(page, "minimum wage")
    expect_count(page, "9 bills")
    page.click("#clear-filters")
    expect_count(page, TOTAL)
    expect(page.locator("#bill-search")).to_have_value("")
    assert page.evaluate("location.hash") == "#all"


def test_the_watchlist_has_its_own_search(device):
    page = device.open("#all")
    for bill in ("HB110", "HB1087"):
        search(page, bill)
        expect_count(page, "1 bill")
        page.locator(f'[data-watch="{bill}"]').first.click()
        expect(page.locator(f'[data-watch="{bill}"]').first).to_have_attribute("aria-pressed", "true")
    page = device.open("#watchlist")
    expect_count(page, "2 bills")
    expect(page.locator("#bill-search")).to_have_value("")  # the explorer's query does not follow you here
    search(page, "minimum wage")
    expect_count(page, "1 bill")
    # An unwatched companion bill may be listed beside it for context; only the watched card counts.
    assert page.locator("#bill-list .bill-card:not(.unwatched-companion) .bill-number").all_inner_texts() == ["HB 110"]
    assert page.evaluate("location.hash") == "#watchlist?query=minimum%20wage"
    search(page, "school")  # matches many bills, none of them watched
    expect_count(page, "0 bills")
    # The explorer still has its own last query.
    page = device.open("#all")
    expect(page.locator("#bill-search")).to_have_value("HB1087")


def test_search_works_at_phone_size(device, viewport):
    page = device.open("#all")
    box = page.locator("#bill-search")
    expect(box).to_be_visible()
    search(page, "minimum wage")
    expect_count(page, "9 bills")
    expect(page.locator('.bill-card[data-bill-id="HB110"]')).to_be_visible()
    search(page, "zzzzqqqq")
    expect_count(page, "0 bills")
    expect(page.locator("#bill-list")).to_contain_text("Nothing matches yet")
