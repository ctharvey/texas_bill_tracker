"""E2E harness: serve the site as raw src/ or as the production bundle, with frozen live/ data and a real sync service.

The bundle is built by the repository's own deployer code (deploy_static.versioned_assets), so a module the
deployer would not publish 404s here exactly as it would in production.
"""

import json
import shutil
import sys
import tempfile
import threading
import types
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


def release_files() -> tuple[str, ...]:
    """The files the deployer publishes, by its own rule."""
    lister = getattr(deploy_static, "release_files", None)
    return tuple(lister(REPO)) if lister else deploy_static.FILES


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
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(self._handler(), directory=str(self.root)))
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
                    self.send_error(405)
                elif path.startswith("/live/"):
                    self.serve_live(path[len("/live/"):])
                else:
                    super().do_GET()

            def serve_live(self, rel):
                entry = site.recorded.get(rel)
                file = LIVE / rel
                if entry is None:
                    site.misses.append(rel)
                if not entry or entry["status"] != 200 or not file.is_file():
                    self.send_error(404)
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
