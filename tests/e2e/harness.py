"""E2E harness: serve the site as raw src/ or as the production bundle, with frozen live/ data and a real sync service.

The bundle is built by the repository's own deployer code (deploy_static.versioned_assets), so a module the
deployer would not publish 404s here exactly as it would in production.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import warnings
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
LIVE = FIXTURES / "live"
CAPTURE = FIXTURES / "capture.json"
sys.path.insert(0, str(REPO / "scripts"))
sys.modules.setdefault("fcntl", types.ModuleType("fcntl"))  # deploy_static locks with fcntl on Linux; unused here.
import deploy_static  # noqa: E402
import sync_service as svc  # noqa: E402

MODES = ("src", "bundle")
# The app's paths (/today, /bill/HB5, /law/PE/46, ...), from the route list the deploy publishes (public/routes.json).
APP_PATHS = [re.compile(route["match"]) for route in json.loads((REPO / "public" / "routes.json").read_text(encoding="utf-8"))["routes"]]


def release_files() -> tuple[str, ...]:
    """The files the deployer publishes, by its own rule, from the tracked files (the deployer lists the commit's tree).

    A new file that is not yet added to git is left out, as a deploy of the commit would leave it out."""
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout
    return deploy_static.release_files(name for name in tracked.decode().split("\0") if name)


def build_bundle(target: Path) -> str:
    """Lay out a release the way deploy_static.main does: published files plus assets/<digest>/ and rewritten page."""
    bundle = {name: (REPO / name).read_bytes() for name in release_files()}
    digest, versioned = deploy_static.versioned_assets(bundle)
    bundle.update(versioned)
    for name, content in bundle.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return digest


def launch(playwright):
    """Playwright's own Chromium (CI installs it); this desktop falls back to the system Chrome."""
    try:
        return playwright.chromium.launch()
    except Exception as error:  # Missing or mismatched browser build.
        if "Executable doesn't exist" not in str(error):
            raise
        return playwright.chromium.launch(channel="chrome")


def capture_info() -> dict:
    return json.loads(CAPTURE.read_text("utf-8")) if CAPTURE.is_file() else {"files": {}}


def build_site_pages(site) -> Path:
    """The static pages the data run writes into live/share (member, topic, agency, about, home, today, bill, law),
    built by scripts/build_feeds.py from the captured snapshot, the committed agent page lists
    (fixtures/agent/pages.json, see make_site_pages.py) and a shell made from the index.html this site serves, as the
    deployer makes current/shell.html. Returns the share folder."""
    live = site.tmp / "pages" / "live"
    live.mkdir(parents=True)
    for name in ("bills.json", "members.json", "luna", "text"):
        source = LIVE / name
        if source.is_dir():
            shutil.copytree(source, live / name)
        elif source.is_file():
            shutil.copyfile(source, live / name)
    agent = live / "agent" / "data"
    agent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "agent" / "pages.json", agent / "pages.json")
    shell = site.tmp / "pages" / "shell.html"
    shell.write_bytes(deploy_static.shell_page((site.root / "index.html").read_bytes()))
    done = subprocess.run([sys.executable, "scripts/build_feeds.py", "--snapshot", str(live / "bills.json"),
                           "--out", str(site.tmp / "pages" / "feeds"), "--statutes", str(site.tmp / "pages" / "statutes"),
                           "--today", capture_info()["captured_at"][:10], "--no-indexnow", "--shell", str(shell)],
                          cwd=REPO, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]
    return live / "share"


class _Server(ThreadingHTTPServer):
    # A page load opens about 50 module requests at once. The default listen backlog (5) refused some of them under
    # parallel runs (ECONNREFUSED), and a refused module leaves the app unstarted: a 20 s selector timeout.
    request_queue_size = 128


class Site:
    """One running site. `misses` lists live/ paths the page asked for that the capture does not hold."""

    def __init__(self, mode: str):
        assert mode in MODES, mode
        self.mode = mode
        self.tmp = Path(tempfile.mkdtemp(prefix=f"tba-e2e-{mode}-"))
        if mode == "src":
            self.root = REPO
        else:
            self.root = self.tmp / "release"
            self.digest = build_bundle(self.root)
        self.recorded = capture_info()["files"]
        self.misses: list[str] = []
        self.server = _Server(("127.0.0.1", 0), partial(self._handler(), directory=str(self.root)))
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}/"
        self.new_sync_store()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def new_sync_store(self, db: Path | None = None) -> Path:
        """A fresh (or given) sync database; tests never see production rows."""
        db = db or Path(tempfile.mkdtemp(dir=self.tmp)) / "sync.sqlite3"
        self.sync_db = db
        self.app = svc.App(svc.Store(db), svc.Snapshot(LIVE / "bills.json"), allowed_origins=(self.base.rstrip("/"),))
        self.api = svc.make_handler(self.app)
        return db

    def _handler(self):
        site = self

        class Handler(SimpleHTTPRequestHandler):
            # Keep-alive. Under HTTP/1.0 each of a page's ~42 requests was a new loopback connection; a full run left
            # 20,000+ sockets in TIME_WAIT and Windows refused new ones (net::ERR_NO_BUFFER_SPACE), so a module failed
            # to load and the app never started. Every response here sends Content-Length.
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def end_headers(self):
                self.send_header("Cache-Control", "no-store")
                super().end_headers()

            def route(self, method):
                path = self.path.split("?", 1)[0]
                if path.startswith("/api/sync"):
                    site.api.dispatch(self, method)
                elif method != "GET":
                    self.close_connection = True  # The request body is left unread; never reuse this connection.
                    self.send_error(405)
                elif path.startswith("/live/"):
                    self.serve_live(path[len("/live/"):])
                elif path != "/" and any(match.fullmatch(path) for match in APP_PATHS):
                    self.path = "/index.html"  # As the gateway serves the app at every path in the route list.
                    super().do_GET()
                else:
                    super().do_GET()

            def serve_live(self, rel):
                entry = site.recorded.get(rel)
                file = LIVE / rel
                if entry is None:
                    site.misses.append(rel)
                if not entry or entry["status"] != 200 or not file.is_file():
                    # Empty, like the tests' own route stubs: an unread error body can hold a fetch open until its
                    # timeout, and networkidle with it (the app releases bodies itself since 499cff3).
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", entry.get("type") or self.guess_type(str(file)))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self): self.route("GET")
            def do_POST(self): self.route("POST")
            def do_PUT(self): self.route("PUT")
            def do_DELETE(self): self.route("DELETE")

        return Handler

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)


# The explorer keeps some controls in closed menus (More filters; Share / save). A test that is about the control,
# not the menu, opens the menu holding it first. test_filters_menus.py tests the menus themselves.
def reveal(page, selector, timeout=5000):
    """Open the closed menu holding `selector`. Does nothing if it never appears (a test may expect it absent)."""
    try:
        page.locator(selector).first.wait_for(state="attached", timeout=timeout)
    except Exception:
        return
    # A menu can still be open here with its close pending (the Share / save menu closes on a timer after one of its
    # buttons is used), so opening only "if closed now" can lose the race. Re-open while the menu keeps closing.
    for _ in range(3):
        before = page.evaluate("s => { const el = document.querySelector(s); const d = el?.closest('details:not([open])');"
                               " if (d) { d.querySelector('summary').click(); return 'opened'; }"
                               " return el?.closest('details') ? 'open' : 'none'; }", selector)
        if before == "none":
            return
        try:
            page.locator(selector).first.wait_for(state="visible", timeout=1000)
            return
        except Exception:
            closed = page.evaluate("s => !!document.querySelector(s)?.closest('details:not([open])')", selector)
            if not closed:
                return  # hidden for some other reason; leave it to the test
            if before == "open":
                warnings.warn(f"reveal({selector!r}): its menu was open, then closed before use; re-opened it")


def click(page, selector, **kwargs):
    reveal(page, selector)
    page.click(selector, **kwargs)
