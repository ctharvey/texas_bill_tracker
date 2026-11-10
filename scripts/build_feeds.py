"""Build one RSS feed per bill from the live snapshot, so people can follow bills without an account.

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


def bill_feed(bill: dict, site: str = SITE) -> str:
    return render_rss(f"{bill['id']} · Texas Bill Atlas", f"{site}#all?bill={bill['id']}",
                      (bill.get("caption") or bill.get("title") or "")[:500]
                      + " Unofficial; confirm on Texas Legislature Online.", bill_items(bill), site)


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


def write_feeds(snapshot: dict, out_dir: Path, site: str = SITE) -> tuple[int, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = unchanged = 0
    for bill in snapshot.get("bills") or []:
        if not isinstance(bill, dict) or not BILL_ID.fullmatch(str(bill.get("id", ""))):
            continue  # Never build a file name from an unexpected id.
        if write_if_changed(out_dir / f"{bill['id']}.xml", bill_feed(bill, site)):
            written += 1
        else:
            unchanged += 1
    return written, unchanged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Public feeds directory, e.g. live/feeds")
    parser.add_argument("--site", default=SITE)
    args = parser.parse_args()
    written, unchanged = write_feeds(json.loads(args.snapshot.read_text("utf-8")), args.out, args.site)
    print(f"Feeds: {written} written, {unchanged} unchanged", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
