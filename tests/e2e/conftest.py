"""Browser E2E fixtures. Opt in with TBA_E2E=1 (CI sets it); the default test run skips this folder.

Every test runs in both serving modes (raw src/ and the deployer-built bundle) with the clock frozen at the capture
time, external hosts stubbed, and any page error or console error failing the test.

Viewports: a test runs at desktop and phone size when it takes the `viewport` fixture (it checks phone behavior) or is
marked `@pytest.mark.layout`; every other test runs at desktop only. CI runs the full matrix in shards:
TBA_E2E_VIEWPORTS=desktop|phone runs every test at that one size, =all at both; TBA_E2E_MODE=src|bundle picks one mode.

Fast check per move commit (the full matrix runs in CI):
  TBA_E2E=1 python -m pytest -q tests/e2e/test_smoke.py tests/e2e/test_stored_data.py tests/e2e/test_sync.py       tests/e2e/test_<moved feature>.py

Locally use at most `-n 3`: each xdist worker keeps its own Chrome, and `-n 8` used up a 32 GB desktop's free RAM. Outside
CI the run stops itself when free RAM falls under TBA_E2E_MIN_FREE_GB (default 6).

Local check (about 470 runs): TBA_E2E=1 TBA_E2E_QUICK=1 python -m pytest -q -n 2 tests/e2e
  Bundle mode only, except the smoke and CSP modules in both modes (they check that the page's code loads either way).
Full matrix off the desktop: python tests/e2e/run_remote.py <commit> (ubuntu-server, Playwright's Docker image).
"""

import inspect
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

collect_ignore_glob = [] if os.environ.get("TBA_E2E") == "1" else ["test_*.py"]


def pytest_configure(config):
    config.addinivalue_line("markers", "layout: run at phone size too (layout or phone-only behavior)")


def pytest_generate_tests(metafunc):
    if "viewport" not in metafunc.fixturenames:
        return
    forced = os.environ.get("TBA_E2E_VIEWPORTS")
    if forced in ("desktop", "phone"):
        sizes = [forced]
    elif (forced == "all" or metafunc.definition.get_closest_marker("layout")
          or "viewport" in inspect.signature(metafunc.function).parameters):
        sizes = ["desktop", "phone"]
    else:
        sizes = ["desktop"]
    metafunc.parametrize("viewport", sizes, indirect=True)


# Modules that still run in both serving modes under TBA_E2E_QUICK=1.
QUICK_BOTH_MODES = {"test_smoke.py", "test_csp.py"}


def pytest_collection_modifyitems(config, items):
    if os.environ.get("TBA_E2E_QUICK") != "1":
        return
    keep, drop = [], []
    for item in items:
        mode = getattr(item, "callspec", None) and item.callspec.params.get("site")
        (drop if mode == "src" and item.path.name not in QUICK_BOTH_MODES else keep).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


def _free_gb():
    """Available RAM in GB, or None when it cannot be read (no psutil and no /proc/meminfo)."""
    try:
        import psutil
        return psutil.virtual_memory().available / 2**30
    except ImportError:
        pass
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 2**20
    except OSError:
        pass
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    # Local only: a desktop run that eats the free RAM leaves the machine unresponsive. CI runners are disposable.
    if os.environ.get("CI") == "true":
        return
    floor = float(os.environ.get("TBA_E2E_MIN_FREE_GB", "6"))
    free = _free_gb()
    if free is not None and free < floor:
        # Stop the way -x does (pytest.exit inside an xdist worker is an INTERNALERROR); this test errors with the reason.
        message = f"E2E stopped: {free:.1f} GB RAM free, under TBA_E2E_MIN_FREE_GB={floor:g}. Use a lower -n."
        item.session.shouldstop = message
        pytest.fail(message, pytrace=False)

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

    @pytest.fixture(scope="session", params=[m for m in harness.MODES if os.environ.get("TBA_E2E_MODE", m) == m])
    def site(request):
        s = harness.Site(request.param)
        yield s
        s.close()

    @pytest.fixture
    def viewport(request):
        return request.param

    @pytest.fixture
    def captured_at():
        return datetime.fromisoformat(harness.capture_info()["captured_at"].replace("Z", "+00:00"))

    class Device:
        """One browser profile: its own localStorage, like one person's phone or laptop."""

        def __init__(self, browser, site, viewport, captured_at, accept_disclaimer=True, storage=None, enforce_csp=False):
            self.site = site
            self.errors: list[str] = []
            # Playwright's string predicates (wait_for_function) evaluate code in the page, which the site's CSP
            # refuses like eval; test_csp.py keeps the policy enforced for the site itself.
            self.context = browser.new_context(viewport=VIEWPORTS[viewport], locale="en-US",
                                               timezone_id="America/Chicago", storage_state=storage,
                                               bypass_csp=not enforce_csp)
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
            page.on("requestfailed", self._code_failed)
            return page

        def _code_failed(self, request):
            # The page's own code failing to load leaves the app unstarted, and Chrome reports it only as an ignored
            # "Failed to load resource" console line; name the file instead of waiting out a 20 s selector timeout.
            if request.url.startswith(self.site.base + ("src/", "assets/")[self.site.mode == "bundle"]):
                self.errors.append(f"requestfailed: {request.url} {request.failure}")

        def open(self, hash_="#all", page=None):
            page = page or self.page
            page.goto(self.site.base + hash_.lstrip("/"), wait_until="networkidle")  # "#all?.." or a path ("/today")
            failed = [e for e in self.errors if e.startswith("requestfailed: ")]
            assert not failed, "the page's own code failed to load:\n" + "\n".join(failed)
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

    @pytest.fixture(scope="session")
    def site_pages(site):
        """The data run's static pages (live/share) for this site, built once (harness.build_site_pages)."""
        return harness.build_site_pages(site)

    @pytest.fixture
    def fresh_sync(site):
        """An empty sync database and a fresh rate limiter (10 link creations per hour per address) for this test."""
        return site.new_sync_store()
