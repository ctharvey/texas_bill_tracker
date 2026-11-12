"""Record the frozen live/ data the E2E suite replays (run deliberately, never inside a move commit).

Serves this checkout locally and walks every view and drawer while live/ requests go to production through the
browser's network stack (Cloudflare refuses urllib). Every response the page asks for is saved under fixtures/live/
and listed in fixtures/capture.json with its status and hash; 404s are recorded too, so replay answers the same.

  python tests/e2e/capture_fixtures.py [--brackets PATH]

--brackets: a locally built live/brackets/index.json used when production has none yet (recorded as such).
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

PROD = "https://bills.ctharvey.me/"
# Bills the suite opens by name: statute, bracket, related-place and range examples from the feature work.
BILLS = ["HB1", "HB110", "HB147", "HB239", "HB381", "HB448", "HB717"]
VIEWS = ["all", "watchlist", "following", "today", "local", "agencies", "review", "method", "saving", "data"]
WANT = {"changes": 2, "fiscal": 2, "highlights": 3}  # Reviewed bills to find for each optional per-bill file.


def keep_miss(rel: str, bills: list[str]) -> bool:
    name = rel.rsplit("/", 1)[-1].split(".", 1)[0]
    return not rel.startswith(("luna/changes/", "luna/fiscal/", "luna/highlights/")) or name in bills


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brackets", type=Path)
    args = parser.parse_args()
    staging = harness.FIXTURES / "live.new"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    files: dict[str, dict] = {}
    site = harness.Site("src")

    def record(route):
        rel = route.request.url.split("/live/", 1)[1].split("?", 1)[0]
        response = route.fetch(url=PROD + "live/" + rel)
        body = response.body()
        if rel not in files:
            entry = {"status": response.status, "origin": "production"}
            if response.status == 200:
                (staging / rel).parent.mkdir(parents=True, exist_ok=True)
                (staging / rel).write_bytes(body)
                entry |= {"type": response.headers.get("content-type", "").split(";")[0],
                          "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            files[rel] = entry
        route.fulfill(response=response, body=body)

    try:
        with sync_playwright() as p:
            browser = harness.launch(p)
            ctx = browser.new_context(viewport={"width": 1366, "height": 900})
            ctx.route("**/live/**", record)
            ctx.route("https://fonts.googleapis.com/**", lambda r: r.fulfill(status=200, body="", content_type="text/css"))
            ctx.route("https://fonts.gstatic.com/**", lambda r: r.fulfill(status=404, body=""))
            ctx.add_init_script("localStorage.setItem('tx-bill-atlas-disclaimer-v1','x');")
            page = ctx.new_page()
            page.goto(site.base + "#all", wait_until="networkidle")
            reviewed = page.evaluate("fetch('./live/luna/tags.json').then(r=>r.json()).then(t=>Object.keys(t.bills||{}))")
            found = {kind: [] for kind in WANT}
            for bill in reviewed:
                for kind, need in WANT.items():
                    if len(found[kind]) < need:
                        url = f"./live/luna/{kind}/{bill}.json"
                        if page.evaluate(f"fetch('{url}').then(r=>r.ok)"):
                            found[kind].append(bill)
                if all(len(found[k]) >= n for k, n in WANT.items()):
                    break
            bills = list(dict.fromkeys(BILLS + [b for kind in found.values() for b in kind]))
            print("bills:", bills, "| found:", found)
            for view in VIEWS:
                page.goto(site.base + f"#{view}", wait_until="networkidle")
            statute_pages, member_pages = [], []
            for bill in bills:
                page.goto(site.base + f"#all?bill={bill}", wait_until="networkidle")
                page.wait_for_timeout(500)
                statute_pages += page.eval_on_selector_all("#drawer-statutes a[href^='#statute']", "a=>a.map(x=>x.getAttribute('href'))")[:2]
                member_pages += page.eval_on_selector_all("#detail-drawer a[href^='#member']", "a=>a.map(x=>x.getAttribute('href'))")[:1]
                show = page.locator(".bill-text-section button", has_text="Show bill text")
                if show.count():
                    # networkidle returns before the click's fetches start; wait for the text itself.
                    with page.expect_response(lambda r: r.url.endswith(".md"), timeout=20000):
                        show.click()
                    select = page.locator(".bill-text-section select")
                    for i in range(select.locator("option").count() if select.count() else 0):
                        code = select.locator("option").nth(i).inner_text().rsplit("(", 1)[-1].rstrip(")")
                        if files.get(f"text/{bill}/{code}.md"):
                            continue
                        with page.expect_response(lambda r, c=code: r.url.endswith(f"/{c}.md"), timeout=20000):
                            select.select_option(index=i)
            for href in list(dict.fromkeys(statute_pages + member_pages)):
                page.goto(site.base + href, wait_until="networkidle")
                page.wait_for_timeout(300)
            browser.close()
    finally:
        site.close()

    if args.brackets and files.get("brackets/index.json", {}).get("status") != 200:
        body = args.brackets.read_bytes()
        (staging / "brackets").mkdir(exist_ok=True)
        (staging / "brackets" / "index.json").write_bytes(body)
        files["brackets/index.json"] = {"status": 200, "origin": f"local build ({args.brackets.name})",
                                        "type": "application/json", "bytes": len(body),
                                        "sha256": hashlib.sha256(body).hexdigest()}
    # Probe misses for bills the suite never opens are noise; any other unrecorded path replays as 404 anyway.
    files = {rel: e for rel, e in files.items() if e["status"] == 200 or keep_miss(rel, bills)}
    commit = subprocess.run(["git", "-C", str(harness.REPO), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    shutil.rmtree(harness.LIVE, ignore_errors=True)
    staging.rename(harness.LIVE)
    harness.CAPTURE.write_text(json.dumps({
        "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": PROD, "commit": commit, "bills": bills,
        "files": dict(sorted(files.items()))}, indent=1) + "\n", "utf-8")
    total = sum(e.get("bytes", 0) for e in files.values())
    print(f"captured {len(files)} paths ({sum(e['status'] == 200 for e in files.values())} files, {total} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
