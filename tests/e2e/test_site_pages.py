"""SEO chunk 5: member, topic, agency, about, home and today pages arrive as the data run's static HTML (live/share,
served for the path as the gateway serves it when the file exists) and the app takes each one over in place: the
static marker goes, the address stays (or gets the member's right slug), and the app's canonical is the page's own."""

import html
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

SITE = "https://billatlas.org"
CANONICAL = re.compile(r'<link rel="canonical" href="https://billatlas\.org([^"]*)"')
VIEW = re.compile(r'data-static-view="([^"]+)"')
TITLE = re.compile(r"<title>([^<]+)</title>")

# (address, static file, static view, the app's #page-title). None: the title comes from the static page's own
# <title>, so the test checks that the static page and the app name the same member, topic or agency.
PAGES = [
    ("/member/A1110/jose-menendez", "member/A1110.html", "member:A1110", None),
    ("/topic/education", "topic/education.html", "topic:education", None),
    ("/agency/tea", "agency/tea.html", "agency:tea", None),
    ("/about/method", "about/method.html", "about:method", "How the atlas works."),
    ("/about/saving", "about/saving.html", "about:saving", "Save your work."),
    ("/about/data", "about/data.html", "about:data", "Behind the tracker."),
    ("/", "home.html", "page:home", "This session, at a glance."),
    ("/today", "today.html", "page:today", "Today at the Lege."),
]


def serve_static(device, path, body):
    """Answer the document request for `path` with the static page; returns the list of paths it answered."""
    served = []

    def handle(route):
        if route.request.resource_type != "document":
            route.continue_()
            return
        served.append(urlsplit(route.request.url).path)
        route.fulfill(status=200, body=body, content_type="text/html; charset=utf-8")

    device.context.route(lambda url: urlsplit(url).path == path, handle)
    return served


def name_in(page_title):
    """'Education: Texas bills · Texas Bill Atlas' -> 'Education'; 'Sen. Jose Menendez · Texas Bill Atlas' -> as is."""
    return html.unescape(page_title).split(" · ")[0].split(": ")[0]


@pytest.mark.parametrize("path,file,view,title", PAGES, ids=[p[1] for p in PAGES])
def test_static_page_is_taken_over_in_place(device, site_pages, path, file, view, title):
    static = (site_pages / file).read_text("utf-8")
    assert VIEW.search(static).group(1) == view
    assert CANONICAL.search(static).group(1) == path
    title = title or name_in(TITLE.search(static).group(1))
    served = serve_static(device, path, static)
    page = device.open(path)
    assert served == [path]  # the page the browser got was the static one
    expect(page.locator("#dynamic-content[data-static-view]")).to_have_count(0)
    expect(page.locator("#page-title")).to_contain_text(title)
    assert urlsplit(page.url).path == path  # no redirect
    expect(page.locator('link[rel="canonical"]')).to_have_attribute("href", SITE + path)
    expect(page.locator('meta[name="robots"][content*="noindex"]')).to_have_count(0)


def test_member_page_with_a_wrong_slug_gets_the_right_address(device, site_pages):
    static = (site_pages / "member/A1110.html").read_text("utf-8")
    served = serve_static(device, "/member/A1110/x", static)  # the gateway serves the page for any slug
    page = device.open("/member/A1110/x")
    assert served == ["/member/A1110/x"]
    expect(page.locator("#dynamic-content[data-static-view]")).to_have_count(0)
    expect(page).to_have_url(re.compile(r"/member/A1110/jose-menendez$"))
    expect(page.locator('link[rel="canonical"]')).to_have_attribute("href", f"{SITE}/member/A1110/jose-menendez")


def test_topic_and_agency_pages_list_their_bills(device, site_pages):
    rows = "#dynamic-content .today-group a.bill-number[data-open]"
    for path, file in (("/topic/education", "topic/education.html"), ("/agency/tea", "agency/tea.html")):
        static = (site_pages / file).read_text("utf-8")
        listed = set(re.findall(r'href="/bill/([A-Z]+[0-9]+)"', static))
        assert 0 < len(listed) <= 100  # the static list's cap
        serve_static(device, path, static)
        page = device.open(path)
        expect(page.locator("#dynamic-content[data-static-view]")).to_have_count(0)
        shown = page.locator(rows).evaluate_all("links => links.map(a => a.dataset.open)")
        # The app shows 30 at a time. Both lists are newest first, so the app's first rows are among the static page's.
        assert set(shown) <= listed, sorted(set(shown) - listed)[:5]
        total = int(re.match(r"(\d+) bills? in this snapshot", page.locator("#dynamic-content .near-hint").first.inner_text()).group(1))
        assert len(shown) == min(30, total)
        if total > 30:
            page.locator("[data-group-more]").click()
            expect(page.locator(rows)).to_have_count(min(60, total))


def test_unknown_topic_and_agency_say_so(device):
    page = device.open("/topic/no-such-topic")  # no static file: the gateway serves the app
    expect(page.locator("#page-title")).to_contain_text("Topic not found")
    page = device.open("/agency/no-such-agency")
    expect(page.locator("#page-title")).to_contain_text("Agency not found")
