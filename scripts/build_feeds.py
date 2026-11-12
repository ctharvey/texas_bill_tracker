"""Build one RSS feed per bill, and one per legislator, from the live snapshot, so people can follow bills and
legislators without an account.

Stateless: item identity comes from (bill, date, action text), so readers see only new actions. A feed file
is rewritten only when its content changes. Standard library only (the data unit extracts it via git show).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from xml.sax.saxutils import escape

BILL_ID = re.compile(r"(HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9]\d{0,4}")
SITE = "https://bills.ctharvey.me/"


def rfc822(day: str | None) -> str | None:
    try:
        moment = dt.datetime.fromisoformat(str(day)[:10]).replace(hour=12, tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None
    return moment.strftime("%a, %d %b %Y %H:%M:%S +0000")


def bill_items(bill: dict) -> list[dict]:
    actions = [a for a in bill.get("actions") or [] if isinstance(a, str) and a.strip()]
    dates = bill.get("action_dates") if isinstance(bill.get("action_dates"), list) else []
    if len(dates) != len(actions):
        # Older snapshots: only the most recent action has a known date.
        dates = [None] * (len(actions) - 1) + [bill.get("last_action_date")] if actions else []
    seen, items = {}, []
    for text, day in zip(actions, dates):
        base = f"{bill['id']}|{day or ''}|{text}"
        seen[base] = seen.get(base, 0) + 1  # The same text can recur on one day; keep each distinct.
        digest = hashlib.sha256(f"{base}|{seen[base]}".encode("utf-8")).hexdigest()[:16]
        items.append({"bill": bill["id"], "text": text, "date": day, "guid": f"{bill['id']}-{digest}",
                      "caption": bill.get("caption") or bill.get("title") or ""})
    items.reverse()  # Newest first.
    return items


def review_items(bill: dict, review: dict | None) -> list[dict]:
    """One item per published Luna full-text review; a re-review (new reviewed_at or text version) is a new item."""
    if not isinstance(review, dict) or not review.get("reviewed_at"):
        return []
    stamp, version = str(review["reviewed_at"]), str(review.get("text_version") or "")
    digest = hashlib.sha256(f"{bill['id']}|review|{stamp}|{version}".encode("utf-8")).hexdigest()[:16]
    topics = [t.get("tag") if isinstance(t, dict) else t for t in review.get("policy_tags") or []]
    summary = str(review.get("summary") or "").strip()
    detail = " ".join(filter(None, [summary, f"Topics: {', '.join(str(t) for t in topics if t)}." if topics else "",
                                    "Automated tags from the bill's full text; confirm on Texas Legislature Online."]))
    return [{"bill": bill["id"], "text": f"Full-text review published{f' ({version} text)' if version else ''}",
             "date": stamp[:10], "guid": f"{bill['id']}-review-{digest}", "caption": detail}]


def load_reviews(path: Path | None) -> dict:
    """Published Luna tags keyed by bill id; missing or malformed files mean no review items, never an error."""
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("format") != "texas-bill-luna-tags-v1" or not isinstance(data.get("bills"), dict):
        return {}
    return {k: v for k, v in data["bills"].items() if isinstance(v, dict)}


def all_items(bill: dict, review: dict | None = None) -> list[dict]:
    items = bill_items(bill) + review_items(bill, review)
    items.sort(key=lambda i: i["date"] or "", reverse=True)  # Stable: same-day actions keep their order.
    return items


def render_rss(title: str, link: str, description: str, items: list[dict], site: str = SITE) -> str:
    newest =max(items, key=lambda i: i["date"] or "", default=None)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0">', "<channel>",
             f"<title>{escape(title)}</title>", f"<link>{escape(link)}</link>",
             f"<description>{escape(description)}</description>", "<language>en-us</language>",
             "<ttl>60</ttl>"]
    if newest and rfc822(newest["date"]):
        lines.append(f"<lastBuildDate>{rfc822(newest['date'])}</lastBuildDate>")
    for item in items:
        lines += ["<item>", f"<title>{escape(item['bill'] + ': ' + item['text'])}</title>",
                  f"<link>{escape(site + '#all?bill=' + item['bill'])}</link>",
                  f"<description>{escape(item['caption'])}</description>",
                  f'<guid isPermaLink="false">{escape(item["guid"])}</guid>']
        if rfc822(item["date"]):
            lines.append(f"<pubDate>{rfc822(item['date'])}</pubDate>")
        lines.append("</item>")
    lines += ["</channel>", "</rss>", ""]
    return "\n".join(lines)


def bill_feed(bill: dict, site: str = SITE, review: dict | None = None) -> str:
    return render_rss(f"{bill['id']} · Texas Bill Atlas", f"{site}#all?bill={bill['id']}",
                      (bill.get("caption") or bill.get("title") or "")[:500]
                      + " Unofficial; confirm on Texas Legislature Online.", all_items(bill, review), site)


MEMBER_CODE = re.compile(r"A\d{3,5}")
# Same join as the site (taxonomy.attachMembers): authors and coauthors serve in the bill's chamber, sponsors and
# cosponsors in the other one, matched by the roster's "<chamber>|<display name>" key.
ROLES = (("authors", "Author", "origin"), ("coauthors", "Coauthor", "origin"),
         ("sponsors", "Sponsor", "other"), ("cosponsors", "Cosponsor", "other"))
MEMBER_FEED_ITEMS = 200


def load_roster(path: Path | None) -> dict:
    """Roster entries keyed by "<chamber>|<name>"; a missing or malformed file means no member feeds, never an error."""
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    members = data.get("members") if isinstance(data, dict) else None
    return {k: v for k, v in members.items() if isinstance(v, dict)} if isinstance(members, dict) else {}


def names(value) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return [s.strip() for s in re.split(r"[;,]", value) if s.strip()] if isinstance(value, str) else []


def member_roles(bill: dict, roster: dict) -> dict[str, str]:
    """Member code -> first role (author before coauthor before sponsor before cosponsor) on this bill."""
    origin = "house" if str(bill.get("id", "")).upper().startswith("H") else "senate"
    other = "senate" if origin == "house" else "house"
    found: dict[str, str] = {}
    for key, role, side in ROLES:
        chamber = origin if side == "origin" else other
        for name in names(bill.get(key)):
            member = roster.get(f"{chamber}|{name}")
            code = member.get("code") if member else None
            if isinstance(code, str) and member.get("chamber") == chamber:
                found.setdefault(code, role)
    return found


def member_title(member: dict) -> str:
    return f"{'Rep.' if member.get('chamber') == 'house' else 'Sen.'} {member.get('full_name') or member.get('display_name')}"


def member_feed(member: dict, bills: list[tuple[dict, str]], site: str = SITE, reviews: dict | None = None) -> str:
    """Every action on the bills a legislator filed or signed onto, newest first, capped at MEMBER_FEED_ITEMS."""
    reviews = reviews or {}
    title = member_title(member)
    items = []
    for bill, role in bills:
        for item in all_items(bill, reviews.get(bill["id"])):
            items.append({**item, "caption": f"{title} · {role}. {item['caption']}"})
    items.sort(key=lambda i: i["date"] or "", reverse=True)
    return render_rss(f"{title} · Texas Bill Atlas", f"{site}#member?code={member['code']}",
                      f"Actions on bills {title} filed or signed onto in the 90th Legislature. "
                      "Unofficial; confirm on Texas Legislature Online.", items[:MEMBER_FEED_ITEMS], site)


def write_member_feeds(snapshot: dict, roster: dict, out_dir: Path, site: str = SITE,
                       reviews: dict | None = None) -> tuple[int, int]:
    """One feed per coded roster member (empty when they have no bills yet, so a feed link never breaks)."""
    by_code = {m["code"]: m for m in roster.values() if MEMBER_CODE.fullmatch(str(m.get("code", "")))}
    if not by_code:
        return 0, 0
    bills: dict[str, list] = {code: [] for code in by_code}
    for bill in snapshot.get("bills") or []:
        if isinstance(bill, dict) and BILL_ID.fullmatch(str(bill.get("id", ""))):
            for code, role in member_roles(bill, roster).items():
                if code in bills:
                    bills[code].append((bill, role))
    out_dir.mkdir(parents=True, exist_ok=True)
    written = unchanged = 0
    for code, member in by_code.items():
        if write_if_changed(out_dir / f"{code}.xml", member_feed(member, bills[code], site, reviews)):
            written += 1
        else:
            unchanged += 1
    return written, unchanged


def write_if_changed(path: Path, text: str) -> bool:
    try:
        if path.read_text("utf-8") == text:
            return False
    except OSError:
        pass
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".feed-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return True


def write_feeds(snapshot: dict, out_dir: Path, site: str = SITE, reviews: dict | None = None) -> tuple[int, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = unchanged = 0
    reviews = reviews or {}
    for bill in snapshot.get("bills") or []:
        if not isinstance(bill, dict) or not BILL_ID.fullmatch(str(bill.get("id", ""))):
            continue  # Never build a file name from an unexpected id.
        if write_if_changed(out_dir / f"{bill['id']}.xml", bill_feed(bill, site, reviews.get(bill["id"]))):
            written += 1
        else:
            unchanged += 1
    return written, unchanged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Public feeds directory, e.g. live/feeds")
    parser.add_argument("--site", default=SITE)
    parser.add_argument("--tags", type=Path, default=None,
                        help="Published Luna tags; defaults to luna/tags.json beside the snapshot when present")
    parser.add_argument("--members", type=Path, default=None,
                        help="Legislator roster for per-member feeds; defaults to members.json beside the snapshot")
    args = parser.parse_args()
    tags = args.tags or args.snapshot.parent / "luna" / "tags.json"
    snapshot, reviews = json.loads(args.snapshot.read_text("utf-8")), load_reviews(tags)
    written, unchanged = write_feeds(snapshot, args.out, args.site, reviews)
    print(f"Feeds: {written} written, {unchanged} unchanged", flush=True)
    roster = load_roster(args.members or args.snapshot.parent / "members.json")
    written, unchanged = write_member_feeds(snapshot, roster, args.out / "members", args.site, reviews)
    print(f"Member feeds: {written} written, {unchanged} unchanged", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
