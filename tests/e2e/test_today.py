"""Today at the Lege: the day's bills by topic and action type, with the clock frozen at the capture (Nov 12, 2026).

The frozen snapshot has six bills filed today. The topic-overflow and paging controls need more rows than that, so
those tests replay the same bills file with extra bills moved onto today.
"""

import json
import re

from playwright.sync_api import expect

TODAY = "2026-11-12"


def replay_bills(device, edit):
    """Serve live/bills.json with `edit(bills_list)` applied; everything else stays the frozen capture."""
    def handle(route):
        response = route.fetch()
        data = response.json()
        edit(data["bills"])
        route.fulfill(response=response, body=json.dumps(data), headers={**response.headers, "content-length": ""})
    device.context.route("**/live/bills.json", handle)


def move_to_today(bills, count):
    moved = 0
    for b in bills:
        if moved >= count:
            break
        b.update(actions=["Filed"], action_dates=[TODAY], last_action_date=TODAY, last_action=f"11/12/2026 H Filed")
        moved += 1


def chips(page):
    return page.locator(".today-topics .topic-chip").all_inner_texts()


def test_today_lists_the_days_bills(device):
    page = device.open("#today")
    expect(page.locator("#page-title")).to_contain_text("Today at the Lege.")
    expect(page.locator(".section-overline")).to_have_text("TODAY")
    expect(page.locator(".section-head h2")).to_have_text("Nov 12, 2026")
    expect(page.locator(".section-head .subtitle")).to_have_text("6 bills with recorded action")
    expect(page.locator(".today-note")).to_contain_text("The 90th Legislature convenes in January 2027")
    expect(page.locator(".today-note")).not_to_contain_text("No recorded activity today")
    rows = page.locator(".today-row")
    expect(rows).to_have_count(6)
    numbers = [r.replace("\n", " ") for r in page.locator(".today-row .bill-number").all_inner_texts()]
    assert numbers == [f"HB {n}" for n in range(1082, 1088)]
    group = page.locator(".today-group h3")
    expect(group).to_have_count(1)
    expect(group).to_have_text(re.compile(r"^Filed\s+6$"))
    expect(rows.first).to_contain_text("virtual currency kiosks")
    expect(rows.first.locator(".today-action")).to_have_text("Filed")


def test_topic_chips_count_the_days_bills_and_filter(device):
    page = device.open("#today")
    assert chips(page) == ["All · 6", "Criminal justice · 2", "Public safety · 1"]
    expect(page.locator(".today-topics .selected")).to_have_text("All · 6")
    # Sorted by count, then name; the counts agree with what the rows are tagged with.
    tagged = page.locator(".today-row").evaluate_all(
        "rows=>rows.filter(r=>r.innerText.includes('Criminal justice')).length")
    assert tagged == 2
    page.locator(".topic-chip", has_text="Criminal justice").click()
    expect(page.locator(".today-row")).to_have_count(2)
    expect(page.locator(".section-head .subtitle")).to_have_text("2 bills with recorded action")
    selected = page.locator(".today-topics .selected")
    expect(selected).to_have_text("Criminal justice · 2")
    expect(selected).to_have_attribute("aria-pressed", "true")
    for text in page.locator(".today-row").all_inner_texts():
        assert "Criminal justice" in text
    # The chip row still offers every topic of the day, and All brings the rest back.
    assert chips(page) == ["All · 6", "Criminal justice · 2", "Public safety · 1"]
    page.locator(".topic-chip", has_text="All ·").click()
    expect(page.locator(".today-row")).to_have_count(6)
    expect(page.locator(".section-head .subtitle")).to_have_text("6 bills with recorded action")


def test_single_bill_subtitle_is_singular(device):
    page = device.open("#today")
    page.locator(".topic-chip", has_text="Public safety").click()
    expect(page.locator(".section-head .subtitle")).to_have_text("1 bill with recorded action")


def test_small_day_has_no_paging_or_overflow_controls(device):
    page = device.open("#today")
    expect(page.locator("#today-more")).to_have_count(0)
    expect(page.locator("#today-topics-toggle")).to_have_count(0)


def test_row_links_open_the_bill_drawer(device):
    page = device.open("#today")
    page.locator(".today-row .bill-number", has_text="HB 1083").click()
    drawer = page.locator("#detail-drawer")
    expect(drawer).to_be_visible()
    expect(drawer.locator(".drawer-number")).to_have_text("90R / HB 1083")
    assert page.url.endswith("#today?bill=HB1083")
    page.keyboard.press("Escape")
    expect(drawer).to_be_hidden()
    assert page.url.endswith("#today")
    page.locator(".today-row .bill-title-link", has_text="wrongfully imprisoned").click()
    expect(drawer.locator(".drawer-number")).to_have_text("90R / HB 1083")


def test_clicking_a_row_body_opens_its_drawer(device):
    page = device.open("#today")
    page.locator(".today-row", has_text="HB 1085").locator(".today-action").click()
    expect(page.locator("#detail-drawer .drawer-number")).to_have_text("90R / HB 1085")


def test_quiet_day_falls_back_to_the_most_recent_activity(device):
    def quiet(bills):
        for b in bills:
            if b.get("last_action_date") == TODAY:
                b.update(action_dates=["2026-11-10"], last_action_date="2026-11-10", last_action="11/10/2026 H Filed")
    replay_bills(device, quiet)
    page = device.open("#today")
    expect(page.locator(".section-overline")).to_have_text("MOST RECENT ACTIVITY")
    head = page.locator(".section-head h2").inner_text()
    assert head != "Nov 12, 2026" and re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}, 2026", head)
    note = page.locator(".today-note")
    expect(note).to_contain_text("No recorded activity today; showing " + head)
    assert page.locator(".today-row").count() > 0


def test_topic_overflow_toggle_and_paging(device):
    replay_bills(device, lambda bills: move_to_today(bills, 260))
    page = device.open("#today")
    first = chips(page)
    toggle = page.locator("#today-topics-toggle")
    expect(toggle).to_be_visible()
    match = re.fullmatch(r"\+(\d+) more topics", toggle.inner_text())
    assert match, toggle.inner_text()
    hidden = int(match.group(1))
    assert len(first) == 1 + 12, "All plus the 12 largest topics"
    counts = [int(c.rsplit("· ", 1)[1]) for c in first[1:]]
    assert counts == sorted(counts, reverse=True)
    toggle.click()
    everything = chips(page)
    assert len(everything) == len(first) + hidden
    expect(page.locator("#today-topics-toggle")).to_have_text("Show fewer")
    page.locator("#today-topics-toggle").click()
    assert chips(page) == first
    # A selected topic stays listed even when it is one of the overflow topics.
    toggle.click()
    last_topic = chips(page)[-1]
    page.locator(".topic-chip", has_text=last_topic).click()
    page.locator("#today-topics-toggle").click()
    assert last_topic in chips(page)
    assert re.fullmatch(r"\+\d+ more topics", page.locator("#today-topics-toggle").inner_text()) or \
        page.locator("#today-topics-toggle").inner_text() == "Show fewer"


def test_show_100_more_reveals_the_next_page(device):
    replay_bills(device, lambda bills: move_to_today(bills, 260))
    page = device.open("#today")
    total = int(re.match(r"(\d+) bills", page.locator(".section-head .subtitle").inner_text()).group(1))
    assert total >= 260
    more = page.locator("#today-more")
    expect(more).to_have_text(f"Show 100 more · showing 100 of {total}")
    expect(page.locator(".today-row")).to_have_count(100)
    more.click()
    expect(page.locator(".today-row")).to_have_count(200)
    expect(page.locator("#today-more")).to_have_text(f"Show 100 more · showing 200 of {total}")
    page.locator("#today-more").click()
    expect(page.locator(".today-row")).to_have_count(total)
    expect(page.locator("#today-more")).to_have_count(0)
    # Choosing a topic starts a fresh page of 100.
    page.locator(".topic-chip:not(.selected)").nth(1).click()
    assert page.locator(".today-row").count() <= 100
