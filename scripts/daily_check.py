"""Daily read-only sweep of Texas Bill Atlas's public systems.

Every check is a GET (or an FTP listing) against a public address; nothing is written anywhere. Prints one line per
check and exits 1 when any check fails, so a scheduler can alert on it.

    python scripts/daily_check.py            # all checks
    python scripts/daily_check.py --no-ci    # skip the GitHub Actions checks (needs the gh CLI)
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

SITES = ("https://billatlas.org/", "https://bills.ctharvey.me/")
AGENT = "https://agent.billatlas.org/"
FTP_HOUSE = "ftp://ftp.legis.state.tx.us/bills/90R/billhistory/house_bills/"
REPO = "ctharvey/texas_bill_tracker"
UA = "texas-bill-atlas-daily-check/1"

# Hours before a feed counts as stale: bills refresh hourly (:17), Luna's status as it works, members daily (09:47).
MAX_AGE_HOURS = {"bills": 3, "members": 30, "luna": 12}
CI_MAX_AGE_HOURS = 30  # The nightly run is at 08:00 UTC.
CERT_MIN_DAYS = 14


def parse_time(text):
    """ISO time (with Z or an offset) to an aware UTC datetime, or None."""
    if not isinstance(text, str) or not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def age_hours(text, now):
    t = parse_time(text)
    return None if t is None else max(0.0, (now - t).total_seconds() / 3600)


def freshness(name, stamp, now, limit):
    """(ok, detail) for a feed's timestamp."""
    hours = age_hours(stamp, now)
    if hours is None:
        return False, f"{name}: no readable timestamp ({stamp!r})"
    return hours <= limit, f"{name}: {hours:.1f} h old (limit {limit} h)"


def asset_digest(html):
    """The build digest in the page's app.js path (assets/<digest>/app.js), or None for an unbundled page."""
    m = re.search(r"assets/([0-9a-f]{8,})/app\.js", html or "")
    return m[1] if m else None


def highest_bill(listing_names):
    """Highest bill number among FTP history file names like 'HB 1178.xml'."""
    nums = [int(m[1]) for n in listing_names if (m := re.fullmatch(r"[A-Z]+ ?0*(\d+)\.xml", n.strip()))]
    return max(nums) if nums else None


def snapshot_highest(bills, prefix="HB"):
    nums = [int(b["id"][len(prefix):]) for b in bills
            if isinstance(b, dict) and re.fullmatch(prefix + r"\d+", str(b.get("id", "")))]
    return max(nums) if nums else None


def ci_verdict(runs, event, now):
    """(ok, detail) for the newest main-branch run of `event` in `gh run list --json` output."""
    mine = [r for r in runs if r.get("event") == event and r.get("headBranch") == "main"]
    if not mine:
        return False, f"no {event} run on main found"
    r = max(mine, key=lambda r: r.get("createdAt", ""))
    hours = age_hours(r.get("createdAt"), now)
    when = f"{hours:.0f} h ago" if hours is not None else "unknown time"
    if r.get("status") != "completed":
        return True, f"{event} run {r.get('headSha', '')[:7]} still {r.get('status')} ({when})"
    ok = r.get("conclusion") == "success"
    if event == "schedule" and hours is not None and hours > CI_MAX_AGE_HOURS:
        return False, f"newest nightly run is {when}"
    return ok, f"{event} run {r.get('headSha', '')[:7]}: {r.get('conclusion')} ({when})"


# --- Network ----------------------------------------------------------------------------------------------------

def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def get_json(url):
    status, _, body = get(url)
    return status, json.loads(body)


def ftp_names(url):
    _, _, body = get(url, timeout=60)
    return [line.split(None, 3)[-1] for line in body.decode("latin-1").splitlines() if line.strip()]


def cert_days(host, now):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=15) as sock, ctx.wrap_socket(sock, server_hostname=host) as tls:
        end = datetime.strptime(tls.getpeercert()["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    return (end - now).days


# --- Checks -----------------------------------------------------------------------------------------------------

def run_checks(include_ci=True):
    now = datetime.now(timezone.utc)
    results = []

    def check(name, fn):
        try:
            ok, detail = fn()
        except Exception as e:  # A check that cannot run is a failure, reported with its reason.
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append((name, ok, detail))
        return ok

    digests = {}
    for site in SITES:
        def home(site=site):
            status, _, body = get(site)
            digest = asset_digest(body.decode("utf-8", "replace"))
            digests[site] = digest
            if status != 200 or not digest:
                return False, f"HTTP {status}, build {digest}"
            status, _, js = get(f"{site}assets/{digest}/app.js")
            return status == 200 and len(js) > 1000, f"HTTP 200, build {digest}, app.js {len(js)} bytes"
        check(f"site {site}", home)
    check("both sites on the same build", lambda: (len(set(digests.values())) == 1 and None not in digests.values(),
                                                   ", ".join(f"{s}: {d}" for s, d in digests.items())))

    snapshot = {}
    def bills():
        status, data = get_json(SITES[0] + "live/bills.json")
        snapshot.update(data)
        n = len(data.get("bills") or [])
        ok, detail = freshness("bills.json", data.get("generated_at"), now, MAX_AGE_HOURS["bills"])
        return ok and n > 0 and data.get("data_mode") == "official-ftp", f"{detail}, {n} bills, mode {data.get('data_mode')}"
    check("bill data fresh", bills)

    def ftp_parity():
        folders = [n for n in ftp_names(FTP_HOUSE) if n.startswith("HB")]
        highest = None
        for folder in sorted(folders, reverse=True):  # Newest range first; empty future ranges list nothing.
            highest = highest_bill(ftp_names(FTP_HOUSE + folder + "/"))
            if highest:
                break
        ours = snapshot_highest(snapshot.get("bills") or [])
        return ours is not None and highest is not None and ours >= highest, f"official FTP HB {highest}, Atlas HB {ours}"
    check("bill data matches the Legislature's FTP", ftp_parity)

    def members():
        _, data = get_json(SITES[0] + "live/members.json")
        n = len(data.get("members") or {})
        ok, detail = freshness("members.json", data.get("generated_at"), now, MAX_AGE_HOURS["members"])
        return ok and data.get("format") == "texas-bill-members-v1" and n >= 150, f"{detail}, {n} members"
    check("member roster fresh", members)

    def luna():
        _, data = get_json(SITES[0] + "live/luna/status.json")
        ok, detail = freshness("luna status", data.get("updated_at"), now, MAX_AGE_HOURS["luna"])
        state = "running" if data.get("running") else "idle"
        return ok, f"{detail}, {state}, {len(data.get('reviewed') or [])} reviewed"
    check("Luna review status fresh", luna)

    for site in SITES:
        check(f"sync API {site}", lambda site=site: (lambda r: (r[0] == 200 and r[1].get("ok") is True, f"HTTP {r[0]} {r[1]}"))(
            get_json(site + "api/sync/health")))

    def agent():
        for path in ("index.html", "sitemap.xml", "robots.txt"):
            status, _, body = get(AGENT + path)
            if status != 200 or not body:
                return False, f"{path}: HTTP {status}"
        status, data = get_json(AGENT + "search.json?q=teacher")
        n = data.get("total")
        fresh, detail = freshness("search data", data.get("data_as_of"), now, MAX_AGE_HOURS["bills"] + 1)
        return status == 200 and bool(n) and fresh, f"index, sitemap, robots OK; search 'teacher': {n} results; {detail}"
    check("agent edition and search", agent)

    for host in ("billatlas.org", "bills.ctharvey.me", "agent.billatlas.org"):
        check(f"TLS certificate {host}", lambda host=host: (lambda d: (d >= CERT_MIN_DAYS, f"{d} days left"))(cert_days(host, now)))

    if include_ci:
        runs = []
        def load_runs():
            out = subprocess.run(["gh", "run", "list", "-R", REPO, "-w", "tests.yml", "-L", "30", "--json",
                                  "event,headBranch,headSha,status,conclusion,createdAt"],
                                 capture_output=True, text=True, timeout=60, check=True).stdout
            runs.extend(json.loads(out))
            return True, f"{len(runs)} recent runs"
        if check("GitHub Actions reachable", load_runs):
            check("nightly tests (E2E)", lambda: ci_verdict(runs, "schedule", now))
            check("tests on the last push to main", lambda: ci_verdict(runs, "push", now))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-ci", action="store_true", help="skip the GitHub Actions checks")
    args = parser.parse_args(argv)
    results = run_checks(include_ci=not args.no_ci)
    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - failed} passed, {failed} failed ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
