"""Review progress page: the run card and passes, Luna's full-text review counts, the live worker list, the
one-bill lookup, recent reviews, the problem groups, and the 60 second refresh."""

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
    # Only the problem groups are listed, all closed: no wall of reviewed or not-started bills.
    groups = page.locator(".review-group")
    titles = [g.locator("summary strong").inner_text() for g in groups.all()]
    assert titles == ["Follow-up questions queued", "Waiting for bill text"]
    assert [g.evaluate("d=>d.open") for g in groups.all()] == [False, False]
    expect(page.locator("details.review-group", has_text="Waiting for bill text").locator("summary span")).to_have_text(
        f"{c['Waiting for bill text']:,}")
    # Idle: the run card says when the next run starts; the full review pass counts bills not started.
    run = page.locator(".review-run")
    expect(run.locator(".review-run-state strong")).to_have_text("Idle")
    expect(run.locator(".review-run-state span")).to_contain_text("Next run about")
    expect(run.locator(".review-pass")).to_have_count(4)
    expect(run.locator(".review-pass").first.locator(".pass-count strong")).to_have_text(f"{c['Not started']:,}")


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


def test_lookup_says_one_bills_state_and_opens_it(device):
    page = device.open("#review")
    result = page.locator("#review-lookup-result")
    page.fill("#review-lookup", "water")
    expect(result).to_contain_text("Type a bill number")
    page.fill("#review-lookup", "hb 99999")
    expect(result).to_contain_text("HB99999: Not a bill in this session")
    page.fill("#review-lookup", "h.b. 1011")
    expect(result.locator('.review-chip[data-open="HB1011"]')).to_have_count(1)
    expect(result.locator(".review-lookup-state")).to_contain_text("Reviewed")
    page.press("#review-lookup", "Enter")
    expect(page.locator("#bill-page .drawer-number")).to_have_text("90R / HB 1011")


def test_recent_reviews_are_newest_first(device):
    page = device.open("#review")
    rows = page.locator(".review-recent .today-row")
    assert 0 < rows.count() <= 20
    expect(rows.first).to_contain_text("Reviewed")


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
    page.fill("#review-lookup", "HB1021")
    expect(page.locator("#review-lookup-result .review-lookup-state")).to_have_text("Being reviewed now")
    # Failures list the stage; a retry bill counts as reviewed but is queued for follow-up questions.
    failed = page.locator(".review-group", has_text="Failed").first
    expect(failed.locator('[data-open="HB1031"]')).to_have_attribute("title", re.compile("extract failed"))
    expect(page.locator(".review-headline")).to_contain_text("1 of them have follow-up questions queued")
    expect(page.locator(".review-group", has_text="Follow-up questions queued").locator("summary span")).to_have_text("1")
    expect(page.locator("#nav-review")).to_have_text(str(c["Reviewed"]))


def test_run_card_names_the_pass_and_counts_each(device):
    def make(base, _n):
        base.update(running=True, updated_at="2026-11-12T15:48:00Z", run_started_at="2026-11-12T15:35:00Z",
                    **{"pass": "topics", "passes": {"entities": {"due": 0, "checked": 212},
                                                    "topics": {"due": 506, "checked": 40}}})
        return base
    serve_status(device, make)
    device.context.clock.install(time="2026-11-12T15:49:00Z")
    page = device.open("#review")
    run = page.locator(".review-run")
    expect(run.locator(".review-run-state strong")).to_have_text("Working on: Topics and scope votes")
    expect(run.locator(".review-run-state span")).to_contain_text("14 of 55 minutes used")
    now = run.locator(".review-pass.now")
    expect(now).to_have_count(1)
    expect(now).to_have_attribute("aria-current", "step")
    expect(now.locator(".pass-count")).to_contain_text("506")
    expect(now.locator(".pass-checked")).to_have_text("40 done this run")
    expect(run.locator(".review-pass.clear")).to_contain_text("Agencies")  # nothing left
    expect(run.locator(".review-pass").last.locator(".pass-count")).to_contain_text("counted after the next run")


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


def test_refresh_every_minute_keeps_open_groups_and_the_lookup(device):
    def make(base, n):
        if n > 1:
            base.update(updated_at="2026-11-12T15:50:00Z", running=True, in_progress=["HB1021"], current="HB1021")
            base["reviewed"] = [x for x in base["reviewed"] if x != "HB1021"]
        return base
    calls = serve_status(device, make)
    page = run_clock(device)
    before = len(calls)
    before_counts = counts(page)
    # The reader opens one group and is typing a bill number.
    page.locator(".review-group", has_text="Waiting for bill text").locator("summary").click()
    state = [g.evaluate("d=>d.open") for g in page.locator(".review-group").all()]
    assert state == [False, True]
    page.fill("#review-lookup", "HB1021")
    with page.expect_request(re.compile(r"/live/luna/status\.json")):
        page.clock.run_for(61000)
    expect(page.locator(".section-head .subtitle")).to_contain_text("Reviewing now")
    assert len(calls) > before
    assert counts(page)["Reviewing now"] == 1
    assert counts(page)["Reviewed"] == before_counts["Reviewed"] - 1
    assert [g.evaluate("d=>d.open") for g in page.locator(".review-group").all()] == state
    expect(page.locator("#review-lookup")).to_have_value("HB1021")
    expect(page.locator("#review-lookup")).to_be_focused()
    expect(page.locator("#review-lookup-result .review-lookup-state")).to_have_text("Being reviewed now")


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
