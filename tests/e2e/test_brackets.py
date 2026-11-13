"""Population limits on the bill page: which places meet each population test, what changed, and no index."""

import re

from playwright.sync_api import expect


def brackets(device, bill):
    page = device.open(f"#bill?id={bill}")
    box = page.locator("#drawer-brackets")
    expect(box).to_be_visible()
    expect(box.locator("h3")).to_have_text("Population limits")
    return page, box


def item(box, text):
    return box.locator(".bracket-list > li").filter(has_text=text)


def test_between_range_threshold_change_shows_was_line_and_newly_covered(device):
    _, box = brackets(device, "HB717")
    li = item(box, "between 10,000 and 200,000")
    expect(li).to_have_count(1)
    expect(li.locator("strong")).to_have_text("Counties with a population between 10,000 and 200,000")
    expect(li).to_contain_text("threshold changed")
    expect(li).to_contain_text("Section 2")
    expect(li.locator(".bracket-was")).to_contain_text("Was between 10,000 and 68,750 (110 counties).")
    was = li.locator(".bracket-was").inner_text()
    assert re.search(r"Newly meets the test: \w+ County, .+ and \d+ more\.", was)
    # The range test is not worded "of between ...".
    assert "population of between" not in li.inner_text()
    # The open-ended threshold in the same bill is its own row.
    other = item(box, "200,000 or less")
    expect(other.locator("strong")).to_have_text("Counties with a population of 200,000 or less")
    expect(other.locator(".bracket-was")).to_contain_text("Was 68,750 or less (202 counties)")
    # Counties near the line are flagged.
    expect(li).to_contain_text("Close to the line: Ochiltree County (10,015)")


def test_count_covers_more_places_after_the_change(device):
    _, box = brackets(device, "HB717")
    li = item(box, "between 10,000 and 200,000")
    now = int(re.search(r"(\d+) counties meet this test", li.inner_text()).group(1))
    was = int(re.search(r"\((\d+) counties\)", li.locator(".bracket-was").inner_text()).group(1))
    assert now > was, "raising the ceiling covers more counties"


def test_quoted_existing_limits_are_folded_until_opened(device):
    _, box = brackets(device, "HB717")
    fold = box.locator("details.law-more").filter(has_text="Limits already in the law this bill quotes (1)")
    expect(fold).to_have_count(1)
    expect(fold).not_to_have_attribute("open", "")
    expect(fold.locator(".bracket-list")).to_be_hidden()
    fold.locator("summary").click()
    expect(fold.locator(".bracket-list li")).to_contain_text("Counties with a population of less than 10,000")
    expect(fold.locator(".bracket-list")).to_be_visible()


def test_struck_limits_and_unread_note(device):
    _, box = brackets(device, "HB303")
    expect(box).to_contain_text("This bill adds no new population limits.")
    expect(box.locator("summary", has_text="Limits already in the law this bill quotes (2)")).to_be_visible()
    expect(box.locator("summary", has_text="Limits this bill strikes (1)")).to_be_visible()
    expect(box).to_contain_text("1 population limit in this bill could not be read; see the bill text.")


def test_neighboring_place_note(device):
    _, box = brackets(device, "HB448")
    li = item(box, "3.3 million")
    expect(li).to_have_count(1)
    expect(li).to_contain_text("new in this bill")
    expect(li.locator(".bracket-related")).to_have_text("Describes a neighboring place, not the place this covers.")
    expect(li).to_contain_text("1 county meets this test: Harris County")
    assert "threshold changed" not in li.inner_text()


def test_dropped_places_and_extra_conditions(device):
    _, box = brackets(device, "HB239")
    county = item(box, "250,000 or more")
    expect(county.locator("strong")).to_have_text("Counties with a population of 250,000 or more")
    expect(county.locator(".bracket-was")).to_contain_text("Was more than 500,000 (12 counties). Newly meets the test:")
    # More than 12 names fold behind "and N more".
    expect(county.locator("details summary")).to_have_text(re.compile(r"^and \d+ more$"))
    city = item(box, "Cities with a population of 25,000 or more")
    expect(city.locator(".bracket-was")).to_contain_text("Was 10,000 or more (236 cities). No longer meets it: 117 cities.")
    expect(city).to_contain_text("The bill adds other conditions here, so fewer places may qualify")
    expect(city).to_contain_text("Close to the line: Corsicana (25,109)")


def test_county_and_city_limits_in_one_bill(device):
    _, box = brackets(device, "HB381")
    heads = box.locator(".bracket-list > li > strong").all_inner_texts()
    assert heads == ["Counties with a population of more than 500,000",
                     "Counties with a population of less than 500,000",
                     "Cities with a population of less than 500,000"]
    expect(item(box, "more than 500,000")).to_contain_text("12 counties meet this test: Harris County")
    expect(item(box, "Cities with a population of less than 500,000")).to_contain_text("cities meet this test.")
    for li in box.locator(".bracket-list > li").all():
        assert "new in this bill" in li.inner_text()


def test_unreadable_limits_are_counted_in_plural(device):
    _, box = brackets(device, "HB1079")
    expect(box).to_contain_text("13 population limits in this bill could not be read")
    expect(box.locator("summary", has_text="Limits already in the law this bill quotes (64)")).to_be_visible()
    expect(item(box, "more than 2.1 million").locator(".bracket-related")).to_contain_text("Describes a neighboring place")


def test_bill_without_population_limits_has_no_section(device):
    page = device.open("#bill?id=HB110")
    expect(page.locator("#bill-page")).to_be_visible()
    expect(page.locator("#drawer-statutes")).to_be_visible()  # the page finished loading its optional sections
    expect(page.locator("#drawer-brackets")).to_be_hidden()


def test_without_the_index_the_section_is_hidden_and_nothing_errors(device):
    device.context.route("**/live/brackets/index.json", lambda r: r.fulfill(status=404, body=""))
    page = device.open("#bill?id=HB717")
    expect(page.locator("#drawer-statutes")).to_be_visible()
    expect(page.locator("#bill-page")).to_be_visible()
    expect(page.locator("#drawer-brackets")).to_be_hidden()
    assert page.locator("#drawer-brackets").inner_text().strip() == ""
    # The rest of the page still works.
    expect(page.locator("#bill-page h2")).to_be_visible()
    page.locator("#bill-back").click()
    expect(page.locator("#bill-page")).to_have_count(0)
