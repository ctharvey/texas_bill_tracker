"""Rebuild tests/e2e/fixtures/agent/pages.json: the agent edition's page lists (topics, agencies, about, home and
today, SEO chunk 5) for the captured snapshot, as scripts/build_agent.mjs writes them on the server.

Usage: python tests/e2e/make_site_pages.py

Needs node. The E2E run itself does not: the Playwright container has no node, so the file is kept in the repository
and harness.build_site_pages() feeds it to build_feeds.py, which writes the static pages the tests serve.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE = REPO / "tests" / "e2e" / "fixtures" / "live"
TARGET = REPO / "tests" / "e2e" / "fixtures" / "agent" / "pages.json"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "agent"
        subprocess.run(["node", "scripts/build_agent.mjs", "--snapshot", str(LIVE / "bills.json"),
                        "--tags", str(LIVE / "luna" / "tags.json"), "--members", str(LIVE / "members.json"),
                        "--status", str(LIVE / "luna" / "status.json"), "--out", str(out)],
                       cwd=REPO, check=True, capture_output=True)
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / "data" / "pages.json", TARGET)
    print(f"wrote {TARGET.relative_to(REPO)} ({TARGET.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
