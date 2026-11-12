"""Browser E2E fixtures. Opt in with TBA_E2E=1 (CI sets it); the default test run skips this folder.

Every test runs in both serving modes (raw src/ and the deployer-built bundle) at desktop and phone size, with the
clock frozen at the capture time, external hosts stubbed, and any page error or console error failing the test.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

collect_ignore_glob = [] if os.environ.get("TBA_E2E") == "1" else ["test_*.py"]

if os.environ.get("TBA_E2E") == "1":
    from playwright.sync_api import sync_playwright

    import harness

    VIEWPORTS = {"desktop": {"width": 1366, "height": 900}, "phone": {"width": 390, "height": 844}}
    DISCLAIMER_KEY = "tx-bill-atlas-disclaimer-v1"
    # Chrome logs every non-2xx fetch as a console error; replayed 404s for optional files are expected.
    IGNORED_CONSOLE = ("Failed to load resource",)

    @pytest.fixture(scope="session")
    def playwright_instance():
        with sync_playwright() as p:
            yield p

    @pytest.fixture(scope="session")
    def browser(playwright_instance):
        b = harness.launch(playwright_instance)
        yield b
        b.close()

    @pytest.fixture(scope="session", params=harness.MODES)
    def site(request):
        s = harness.Site(request.param)
        yield s
        s.close()

    @pytest.fixture(params=list(VIEWPORTS))
    def viewport(request):
        return request.param

    @pytest.fixture
    def captured_at():
        return datetime.fromisoformat(harness.capture_info()["captured_at"].replace("Z", "+00:00"))

    class Device:
        """One browser profile: its own localStorage, like one person's phone or laptop."""

        def __init__(self, browser, site, viewport, captured_at, accept_disclaimer=True, storage=None):
            self.site = site
            self.errors: list[str] = []
            self.context = browser.new_context(viewport=VIEWPORTS[viewport], locale="en-US",
                                               timezone_id="America/Chicago", storage_state=storage)
            self.context.clock.set_fixed_time(captured_at)
            self.context.route("https://fonts.googleapis.com/**",
                               lambda r: r.fulfill(status=200, body="", content_type="text/css"))
            self.context.route("https://fonts.gstatic.com/**", lambda r: r.fulfill(status=404, body=""))
            self.context.route("https://geocoding.geo.census.gov/**", lambda r: r.abort())
            if accept_disclaimer:
                self.context.add_init_script(f"localStorage.setItem('{DISCLAIMER_KEY}','x');")
            self.page = self.new_page()

        def new_page(self):
            page = self.context.new_page()
            page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: m.type == "error" and not m.text.startswith(IGNORED_CONSOLE)
                    and self.errors.append(f"console.error: {m.text}"))
            return page

        def open(self, hash_="#all", page=None):
            page = page or self.page
            page.goto(self.site.base + hash_, wait_until="networkidle")
            page.wait_for_selector("#dynamic-content *", state="attached", timeout=20000)
            return page

        def storage(self) -> dict:
            return self.page.evaluate("Object.fromEntries(Object.entries(localStorage))")

        def close(self):
            self.context.close()

    @pytest.fixture
    def device_factory(browser, site, viewport, captured_at):
        made = []

        def make(**kwargs):
            d = Device(browser, site, viewport, captured_at, **kwargs)
            made.append(d)
            return d

        yield make
        errors = [e for d in made for e in d.errors]
        for d in made:
            d.close()
        assert not errors, "\n".join(errors)

    @pytest.fixture
    def device(device_factory):
        return device_factory()

    @pytest.fixture
    def fresh_sync(site):
        """An empty sync database and a fresh rate limiter (10 link creations per hour per address) for this test."""
        return site.new_sync_store()
