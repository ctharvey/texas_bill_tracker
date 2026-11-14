"""The site's Content-Security-Policy stays enforced here (every other test bypasses it for Playwright's own helpers):
using the main views must trip no violation. Any violation also logs a console error, which fails the test."""

from harness import click

VIEWS = ("#home", "#all", "#following", "#near", "#data", "#watchlist")
LISTEN = ("window.__csp = [];"
          "document.addEventListener('securitypolicyviolation', e => window.__csp.push("
          "e.violatedDirective + ' ' + (e.blockedURI || '(inline)')));")


def test_main_views_run_under_the_policy(device_factory):
    device = device_factory(enforce_csp=True)
    device.context.add_init_script(LISTEN)
    page = device.new_page()
    for view in VIEWS:
        device.open(view, page=page)
        assert page.evaluate("window.__csp") == [], view
    device.open("#all?query=water", page=page)
    page.locator("#bill-list a, #bill-list button").first.click()
    click(page, "#warbler-dot")
    page.wait_for_timeout(300)
    assert page.evaluate("window.__csp") == []
