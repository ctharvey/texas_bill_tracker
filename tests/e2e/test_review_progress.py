"""Review progress page: Luna's full-text review counts, groups, the live worker list, and the 60 second refresh."""

import json
import re

from playwright.sync_api import expect

STATUS_URL = "**/live/luna/status.json"
BASE_UPDATED = "2026-11-12T15:40:29Z"


def num(text):
    return int(text.replace(",", ""))


def counts(page):
    """{'Reviewed': 1295, ...} from the legend under the progress bar."""
    out = {}
    for box in page.locator(".review-count").all():
        label = box.locator("span").last.inner_text().split(" · ")[0]
        out[label] = num(box.locator("strong").inner_text())
    return out


def total_bills(page):
    return num(re.search(r"of ([\d,]+) bills reviewed", page.locator(".review-headline").inner_text()).group(1))


def serve_status(device, make):
    """Answer live/luna/status.json with make(base_status, call_number); records how often it was asked."""
    calls = []

    def handle(route):
        response = route.fetch()
        base = response.json()
        calls.append(1)
        route.fulfill(response=response, body=json.dumps(make(base, len(calls))), headers={**response.headers, "content-length": ""})
    device.context.route(STATUS_URL, handle)
    return calls


def test_progress_page_shows_counts_and_groups(device):
    page = device.open("#review")
    expect(page.locator("#page-title")).to_contain_text("Full-text review.")
    expect(page.locator(".section-head h2")).to_have_text("Review progress")
    expect(page.locator(".section-head .subtitle")).to_have_text(
        "Idle until the next hourly run · last update Nov 12, 2026, 9:40 AM CT")
    c = counts(page)
    total = total_bills(page)
    # Every bill is in exactly one state, and none are being worked on right now.
    assert c.keys() == {"Reviewed", "Waiting for bill text", "Not started"}
    assert sum(c.values()) == total
    headline = page.locator(".review-headline").inner_text()
    assert f"{c['Reviewed']:,} of {total:,} bills reviewed" in headline
    pct = round(c["Reviewed"] / total * 1000) / 10
    assert f"({pct:g}%)" in headline
    expect(page.locator(".review-now")).to_have_count(0)
    # The bar says the same thing to a screen reader.
    label = page.locator(".review-bar").get_attribute("aria-label")
    assert f"{c['Reviewed']} reviewed" in label and f"of {total}" in label
    # Groups: only Reviewed starts open; its count matches the legend.
    groups = page.locator(".review-group")
    titles = [g.locator("summary strong").inner_text() for g in groups.all()]
    assert titles == ["Reviewed", "Follow-up questions queued", "Waiting for bill text", "Not started"]
    opened = [g.evaluate("d=>d.open") for g in groups.all()]
    assert opened == [True, False, False, False]
    expect(groups.first.locator("summary span")).to_have_text(f"{c['Reviewed']:,}")
    expect(groups.first.locator(".review-chip")).to_have_count(c["Reviewed"])
    expect(page.locator("details.review-group", has_text="Waiting for bill text").locator("summary span")).to_have_text(
        f"{c['Waiting for bill text']:,}")


def test_nav_count_matches_reviewed(device):
    page = device.open("#review")
    nav = num(page.locator("#nav-review").inner_text())
    assert nav == counts(page)["Reviewed"]
    # The same number is on every page, not just this one.
    page = device.open("#all")
    assert num(page.locator("#nav-review").inner_text()) == nav


def test_audit_spot_check_line(device):
    page = device.open("#review")
    expect(page.locator(".review-audit")).to_have_text(
        "Spot check: 23 reviews re-checked independently · 14 agreed · 7 with minor issues · 2 with major issues")


def test_chips_open_the_bill_and_tagged_chips_are_marked(device):
    page = device.open("#review")
    chip = page.locator(".review-group").first.locator('.review-chip[data-open="HB1011"]')
    expect(chip).to_have_count(1)
    chip.click()
    expect(page.locator("#bill-page .drawer-number")).to_have_text("90R / HB 1011")
    page.locator("#bill-back").click()
    tagged = page.locator(".review-group").first.locator(".review-chip.tagged")
    untagged = page.locator(".review-group").first.locator(".review-chip:not(.tagged)")
    assert tagged.count() > 0 and untagged.count() > 0
    expect(tagged.first).to_have_attribute("title", re.compile("Luna tags published"))
    expect(untagged.first).to_have_attribute("title", re.compile("no verified tags published"))


def test_workers_in_progress_failures_and_follow_ups(device):
    def make(base, _n):
        base.update(running=True, updated_at="2026-11-12T15:48:00Z", waiting_until=None, current="HB1021",
                    in_progress=["HB1021", "HB1022"], upcoming=["HB1023", "HB1024"], retry=["HB1030"])
        base["reviewed"] = [x for x in base["reviewed"] if x not in ("HB1021", "HB1022")]
        base["failed"]["HB1031"] = "extract"
        base["reviewed"] = [x for x in base["reviewed"] if x != "HB1031"]
        return base
    serve_status(device, make)
    page = device.open("#review")
    expect(page.locator(".section-head .subtitle")).to_have_text("Reviewing now · updated Nov 12, 2026, 9:48 AM CT")
    c = counts(page)
    assert c["Reviewing now"] == 2 and c["Failed"] == 1
    assert sum(c.values()) == total_bills(page)
    now = page.locator(".review-now")
    expect(now).to_be_visible()
    assert now.locator(".review-chip").all_inner_texts() == ["HB1021", "HB1022", "HB1023", "HB1024"]
    expect(now.locator("small").first).to_have_text("Reviewing now")
    expect(now.locator("small").nth(1)).to_have_text("Up next")
    # A bill held by a worker is not also counted as reviewed.
    expect(page.locator(".review-group").first.locator('[data-open="HB1021"]')).to_have_count(0)
    # Failures list the stage; a retry bill counts as reviewed but is queued for follow-up questions.
    failed = page.locator(".review-group", has_text="Failed").first
    expect(failed.locator('[data-open="HB1031"]')).to_have_attribute("title", re.compile("extract failed"))
    expect(page.locator(".review-headline")).to_contain_text("1 of them have follow-up questions queued")
    expect(page.locator(".review-group", has_text="Follow-up questions queued").locator("summary span")).to_have_text("1")
    expect(page.locator("#nav-review")).to_have_text(str(c["Reviewed"]))


def test_stale_worker_is_flagged(device):
    def make(base, _n):
        base.update(running=True, updated_at="2026-11-12T13:00:00Z", in_progress=["HB1021"], current="HB1021")
        return base
    serve_status(device, make)
    page = device.open("#review")
    expect(page.locator(".section-head .subtitle")).to_contain_text("may have stopped")
    expect(page.locator(".review-now")).to_have_count(0)


def test_status_unavailable_falls_back_to_published_tags(device):
    device.context.route(STATUS_URL, lambda r: r.fulfill(status=404, body=""))
    page = device.open("#review")
    expect(page.locator(".section-head .subtitle")).to_have_text(
        "Live worker status is unavailable, so bills with published Luna tags are counted as reviewed.")
    c = counts(page)
    assert 0 < c["Reviewed"] < total_bills(page)
    assert num(page.locator("#nav-review").inner_text()) == c["Reviewed"]


def run_clock(device, page_url_hash="#review"):
    """A running fake clock from the capture time, so timers can be fast-forwarded."""
    device.context.clock.install(time="2026-11-12T15:49:00Z")
    return device.open(page_url_hash)


def test_refresh_every_minute_keeps_open_groups_open(device):
    def make(base, n):
        if n > 1:
            base.update(updated_at="2026-11-12T15:50:00Z", running=True, in_progress=["HB1021"], current="HB1021")
            base["reviewed"] = [x for x in base["reviewed"] if x != "HB1021"]
        return base
    calls = serve_status(device, make)
    page = run_clock(device)
    before = len(calls)
    before_counts = counts(page)
    # The reader opens one group and closes another.
    page.locator(".review-group", has_text="Waiting for bill text").locator("summary").click()
    page.locator(".review-group", has_text="Reviewed").first.locator("summary").click()
    state = [g.evaluate("d=>d.open") for g in page.locator(".review-group").all()]
    assert state == [False, False, True, False]
    with page.expect_request(re.compile(r"/live/luna/status\.json")):
        page.clock.run_for(61000)
    expect(page.locator(".section-head .subtitle")).to_contain_text("Reviewing now")
    assert len(calls) > before
    assert counts(page)["Reviewing now"] == 1
    assert counts(page)["Reviewed"] == before_counts["Reviewed"] - 1
    assert [g.evaluate("d=>d.open") for g in page.locator(".review-group").all()] == state


def test_refresh_without_news_does_not_redraw(device):
    calls = serve_status(device, lambda base, n: base)
    page = run_clock(device)
    page.evaluate("document.querySelector('.review-headline').dataset.mark='kept'")
    before = len(calls)
    with page.expect_response(re.compile(r"/live/luna/status\.json")):
        page.clock.run_for(61000)
    assert len(calls) > before
    expect(page.locator(".review-headline")).to_have_attribute("data-mark", "kept")


def test_other_views_do_not_poll(device):
    calls = serve_status(device, lambda base, n: base)
    page = run_clock(device, "#all")
    before = len(calls)
    page.clock.run_for(180000)
    page.wait_for_timeout(250)
    assert len(calls) == before
