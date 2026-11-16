"""Daily read-only sweep of Texas Bill Atlas's public systems.

Every check is a GET (or an FTP listing) against a public address; nothing is written anywhere. Prints one line per
check and exits 1 when any check fails, so a scheduler can alert on it.

    python scripts/daily_check.py            # all checks
    python scripts/daily_check.py --no-ci    # skip the GitHub Actions checks (needs the gh CLI)
    python scripts/daily_check.py --sample 0 # spot-check every bill from the newest filing day, not 8
"""
from __future__ import annotations

import argparse
import html
import json
import random
import re
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

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


def asset_digest(page):
    """The build digest in the page's app.js path (assets/<digest>/app.js), or None for an unbundled page."""
    m = re.search(r"assets/([0-9a-f]{8,})/app\.js", page or "")
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


PLACEHOLDER = "is not currently available"  # TLC's stand-in page until a version's HTML is posted (the PDF may be).


def official_record(xml):
    """Caption, authors and last action from a TLO bill history XML file."""
    def text(tag):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S)
        return html.unescape(m[1].strip()) if m else ""
    return {"caption": text("caption"), "authors": [a.strip() for a in text("authors").split("|") if a.strip()],
            "last_action": text("lastaction")}


def bill_findings(bill, official, members, tag, luna_failed, text_state, agent_ok, search_ok, agent_behind=False,
                  text_is_new=False):
    """What one bill got, as [(level, message)] with level 'ok', 'warn' (expected wait) or 'fail'.

    official: official_record() of its TLO history, or None; members: the roster's members map; tag: its Luna entry or
    None; luna_failed: Luna's recorded failure reason or None; text_state: 'ok', 'placeholder' or 'none';
    agent_behind: the agent edition was built from data older than this bill's snapshot (it rebuilds hourly);
    text_is_new: its text file is newer than the snapshot, so the data run has not passed it on yet."""
    out = []
    chamber = "house" if str(bill.get("id", "")).startswith("H") else "senate"
    if official is None:
        out.append(("fail", "no official history record"))
    else:
        if official["caption"] != bill.get("caption"):
            out.append(("fail", "caption differs from the official record"))
        if official["authors"] != list(bill.get("authors") or []):
            out.append(("fail", f"authors {bill.get('authors')} vs official {official['authors']}"))
        if official["last_action"] and official["last_action"] != bill.get("last_action"):
            out.append(("warn", "official record has a newer action than the snapshot"))
    if not bill.get("caption") or not bill.get("authors"):
        out.append(("fail", "missing caption or author"))
    unknown = [a for a in bill.get("authors") or [] if f"{chamber}|{a}" not in members]
    if unknown:
        out.append(("fail", f"author not in the member roster: {', '.join(unknown)}"))
    if not bill.get("subjects"):
        out.append(("warn", "no official subjects yet"))
    if text_state == "none":
        out.append(("warn", "no bill text posted yet, so no Luna review yet"))
    elif text_state == "placeholder":
        out.append(("warn", "official HTML text is a placeholder (PDF only), so Luna waits"))
    if tag:
        if not tag.get("summary") or not tag.get("policy_tags"):
            out.append(("fail", "Luna review has no summary or policy tags"))
    elif text_state == "ok" and luna_failed and text_is_new:
        out.append(("warn", "text was posted after the last data run; the next run passes it to Luna"))
    elif text_state == "ok":
        out.append(("fail", f"text is posted but Luna failed: {luna_failed}") if luna_failed
                   else ("warn", "text is posted; Luna has not reviewed it yet"))
    level = "warn" if agent_behind else "fail"  # A bill newer than the agent edition's last build is not in it yet.
    if not agent_ok:
        out.append((level, "no agent edition page" + (" yet (not rebuilt since it arrived)" if agent_behind else "")))
    if not search_ok:
        out.append((level, "search by bill number does not find it" + (" yet" if agent_behind else "")))
    return out


def verdict(findings):
    """(ok, detail) for check(): ok is True, None (warnings only) or False."""
    fails = [m for level, m in findings if level == "fail"]
    warns = [m for level, m in findings if level == "warn"]
    if fails:
        return False, "; ".join(fails + warns)
    return (None, "; ".join(warns)) if warns else (True, "data, official match, roster, Luna, agent page, search")


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

def ftp_time(line):
    """UTC time of an FTP listing line ('11-16-26  03:32PM  13580 HB01184I.htm'). The server lists Texas time; this
    assumes CST, so in daylight time it reads an hour late, which only makes text look newer."""
    m = re.match(r"(\d\d-\d\d-\d\d)\s+(\d\d:\d\d[AP]M)", line.strip())
    if not m:
        return None
    local = datetime.strptime(f"{m[1]} {m[2]}", "%m-%d-%y %I:%M%p")
    return local.replace(tzinfo=timezone.utc) + timedelta(hours=6)


_listings = {}


def text_state(bill):
    """('ok' | 'placeholder' | 'none', posted time or None) for a bill's newest posted text version."""
    versions = bill.get("text_versions") or []
    if not versions or not versions[-1].get("html"):
        return "none", None
    url = versions[-1]["html"]
    _, _, body = get(url, timeout=60)
    folder, name = url.rsplit("/", 1)
    if folder not in _listings:
        _listings[folder] = get(folder + "/", timeout=60)[2].decode("latin-1").splitlines()
    line = next((l for l in _listings[folder] if l.lower().endswith(name.lower())), "")
    return ("placeholder" if PLACEHOLDER in body.decode("latin-1") else "ok"), ftp_time(line)


def spot_check_bills(check, snapshot, sample, now):
    """Spot checks of bills from the newest filing day: each one against everything the pipeline should give it."""
    bills = snapshot.get("bills") or []
    if not bills:
        return check("spot checks of new bills", lambda: (False, "no snapshot to sample"))
    day = max(str(b.get("filed_at", ""))[:10] for b in bills)
    newest = [b for b in bills if str(b.get("filed_at", "")).startswith(day)]
    picked = sorted(random.sample(newest, min(sample, len(newest))) if sample else newest, key=lambda b: b["id"])
    members = get_json(SITES[0] + "live/members.json")[1].get("members") or {}
    tags = get_json(SITES[0] + "live/luna/tags.json")[1].get("bills") or {}
    status = get_json(SITES[0] + "live/luna/status.json")[1]
    failed = status.get("failed") or {}
    check(f"bills filed {day}", lambda: (True, f"{len(newest)} bills; checking {', '.join(b['id'] for b in picked)}"))
    for bill in picked:
        def one(bill=bill):
            official = None
            if bill.get("source_path"):
                url = "ftp://ftp.legis.state.tx.us" + bill["source_path"].replace(" ", "%20")
                official = official_record(get(url, timeout=60)[2].decode("utf-8-sig", "replace"))
            try:
                status_code, _, page = get(f"{AGENT}bills/{bill['id']}.md")
                agent_ok = status_code == 200 and page.decode("utf-8", "replace").startswith(f"# {bill.get('number')}")
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                agent_ok = False
            found = get_json(f"{AGENT}search.json?q={urllib.parse.quote(bill.get('number') or bill['id'])}")[1]
            search_ok = any(r.get("id") == bill["id"] for r in (found.get("results") or [])[:3])
            built, ours = parse_time(found.get("data_as_of")), parse_time(snapshot.get("generated_at"))
            behind = bool(built and ours and built < ours)
            state, posted = text_state(bill)
            new_text = bool(posted and ours and posted > ours)
            return verdict(bill_findings(bill, official, members, tags.get(bill["id"]), failed.get(bill["id"]),
                                         state, agent_ok, search_ok, agent_behind=behind, text_is_new=new_text))
        check(f"  {bill['id']}", one)

    # Bills Luna still cannot read days after filing: TLC's HTML placeholder (PDF only), or a real download failure.
    def stuck():
        by_id = {b["id"]: b for b in bills}
        old = sorted((i for i, why in failed.items() if why == "download" and i in by_id
                      and age_hours(str(by_id[i].get("filed_at")) + "T00:00:00Z", now) > 72),
                     key=lambda i: (len(i), i))
        other = {i: why for i, why in failed.items() if why != "download"}
        detail = f"{len(old)} bills over 3 days without readable text" + (f": {', '.join(old)}" if old else "")
        detail += f"; other Luna failures: {other}" if other else ""
        return (None if old or other else True), detail
    check("bills Luna cannot review", stuck)


def run_checks(include_ci=True, sample=8):
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

    spot_check_bills(check, snapshot, sample, now)

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
    parser.add_argument("--sample", type=int, default=8, help="new bills to spot-check (0 = all of that day)")
    args = parser.parse_args(argv)
    results = run_checks(include_ci=not args.no_ci, sample=args.sample)
    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'WARN' if ok is None else 'FAIL'}  {name:<{width}}  {detail}")
    failed = sum(1 for _, ok, _ in results if ok is False)
    warned = sum(1 for _, ok, _ in results if ok is None)
    print(f"\n{len(results) - failed - warned} passed, {warned} warnings, {failed} failed "
          f"({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
