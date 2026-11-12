"""Build one RSS feed per bill, and one per legislator, from the live snapshot, so people can follow bills and
legislators without an account. Also builds the statute index (live/statutes) from the bill text.

Stateless: item identity comes from (bill, date, action text), so readers see only new actions. A feed file
is rewritten only when its content changes. Standard library only (the data unit extracts it via git show).
"""
from __future__ import annotations

import argparse
from collections import Counter
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


# ---------------------------------------------------------------------------------------------------------------
# Statute index: which sections of Texas law each bill amends, adds or repeals, with the text it quotes.
# It lives here because the data unit fetches only sync_ftp.py and this file from main on every run.

STATUTE_FORMAT = "texas-bill-statutes-v1"
STATUTE_SECTION_FORMAT = "texas-bill-statute-section-v1"
KIND_LETTER = {"amend": "m", "add": "n", "repeal": "r"}  # In the index: amends, new section, repeals.
# Bill-text names -> statutes.capitol.texas.gov abbreviations (each checked against a real section there).
CODE_ABBR = {
    "Agriculture Code": "AG", "Alcoholic Beverage Code": "AL", "Business and Commerce Code": "BC",
    "Business Organizations Code": "BO", "Civil Practice and Remedies Code": "CP", "Code of Criminal Procedure": "CR",
    "Education Code": "ED", "Election Code": "EL", "Estates Code": "ES", "Family Code": "FA", "Finance Code": "FI",
    "Government Code": "GV", "Health and Safety Code": "HS", "Human Resources Code": "HR", "Insurance Code": "IN",
    "Labor Code": "LA", "Local Government Code": "LG", "Natural Resources Code": "NR", "Occupations Code": "OC",
    "Parks and Wildlife Code": "PW", "Penal Code": "PE", "Property Code": "PR", "Special District Local Laws Code": "SD",
    "Tax Code": "TX", "Transportation Code": "TN", "Utilities Code": "UT", "Water Code": "WA",
}
CODE_NAME = {abbr: name for name, abbr in CODE_ABBR.items()}
_CODE_RE = re.compile("(" + "|".join(sorted(map(re.escape, CODE_ABBR), key=len, reverse=True)) + ")")
SECTION_NUM = re.compile(r"\d+[A-Z]?(?:\.\d+[A-Z]?)+")      # 48.160, 42A.054, 2051.151; never a bare "1"
STATUTE_KEY = re.compile(r"([A-Z]{2}) (" + SECTION_NUM.pattern + r")")
_SUBSECTION = re.compile(r"\(([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\)")
# A list after "Section(s)": "123.001(b) and (c) and 126.001(b)", "1.01, 1.02(a), and 1.03".
_LIST = r" ((?:(?:[0-9A-Z.]+|\([A-Za-z0-9-]+\))(?:\([A-Za-z0-9-]+\))*(?:, and |, | and )?)+)"
_VERB = re.compile(r",? (?:is|are) (?:hereby )?(amended|repealed|added|reenacted|transferred|redesignated|renumbered)\b")
_HEADER = re.compile(r"^(?:Sec|Art)\. (" + SECTION_NUM.pattern + r")\.")
_ONLY_HEADING = re.compile(r"^The headings? (?:to|of) ")
_OTHER_LAW = re.compile(r"Acts of the|Revised Statutes|Vernon's|Constitution|General Appropriations|\(H\.B\.|\(S\.B\.")
_REPEALER = re.compile(r"^(?:The following|Effective [^,]+, the following)[^:]*(?:is|are) repealed")
_TAGS = re.compile(r"</?(?:ins|del)>")
_HEADING_LINE = re.compile(r"^### ")


def plain_text(markdown_line: str) -> str:
    """The bill text line without ins/del tags or Markdown escapes (both versions merged)."""
    return re.sub(r"\s+", " ", re.sub(r"\\(.)", r"\1", _TAGS.sub("", markdown_line))).strip()


def _numbers(text: str) -> list[str]:
    """Section numbers in a list such as "21.0031(b), 21.004, and 21.005(a) and (c)"; subsections are dropped."""
    return [m.group(0) for m in SECTION_NUM.finditer(_SUBSECTION.sub("", text))]


def _subsections(text: str) -> list[str]:
    return [m.group(1) for m in _SUBSECTION.finditer(text)]


def parse_clause(clause: str) -> dict:
    """Classify one SECTION's opening sentence.

    Returns {"kind": amend|add|repeal|chapter|heading|repealer|other_law|none|unparsed, "code": abbr or None,
    "targets": [section numbers], "subsections": [...], "from_body": bool}. from_body means the section numbers
    come from the "Sec. N." headers in the body (a chapter or subchapter being added) or, for a repealer, from the
    listed items."""
    text = plain_text(clause).replace(" & ", " and ")
    out = {"kind": "none", "code": None, "targets": [], "subsections": [], "from_body": False}
    if _REPEALER.match(text):
        code = _CODE_RE.search(text)
        return {**out, "kind": "repealer", "code": CODE_ABBR[code.group(1)] if code else None, "from_body": True}
    verb = _VERB.search(text)
    if not verb:
        return out
    path, rest, action = text[:verb.start()], text[verb.end():].strip(), verb.group(1)
    codes = list(_CODE_RE.finditer(path))
    if not codes:
        return {**out, "kind": "other_law" if _OTHER_LAW.search(text) else "unparsed"}
    code = CODE_ABBR[codes[-1].group(1)]
    before = path[:codes[-1].start()]
    out["code"] = code
    if _ONLY_HEADING.match(before) and not re.match(r"^The headings? (?:to|of) (?:Section|Article)", before):
        return {**out, "kind": "heading"}  # Chapter, subchapter or title headings: no section to track.
    # Code of Criminal Procedure: articles are the sections ("Section 1(c), Article 46.04" keys to Article 46.04).
    unit = r"Articles?" if code == "CR" else r"Sections?"
    named = [m for m in re.finditer(r"\b" + unit + _LIST, before)]
    targets = [n for m in named for n in _numbers(m.group(1))]
    subs = _subsections(before)
    if action == "repealed":
        return {**out, "kind": "repeal" if targets else "chapter", "targets": targets, "subsections": subs}
    if action == "added":
        return {**out, "kind": "add" if targets else "chapter", "targets": targets, "from_body": not targets}
    adding = re.match(r"by (?:amending [^,]*?(?:and )?)?adding (Sections?|Articles?|Subsections?|Subdivisions?|Subchapters?|Chapters?|Subtitles?|Titles?|Parts?) ([^,]*?)(?: to read|,|$)", rest)
    if targets:
        amending = re.search(r"by amending ((?:Subsections?|Subdivisions?) [^,]*?)(?: and adding|,| to read|$)", rest)
        if amending:
            subs += _subsections(amending.group(1))
        if adding and adding.group(1)[:6] in ("Subsec", "Subdiv"):
            subs += _subsections(adding.group(2))
        return {**out, "kind": "amend", "targets": targets, "subsections": list(dict.fromkeys(subs))}
    if adding and adding.group(1).startswith(("Section", "Article")):
        return {**out, "kind": "add", "targets": _numbers(adding.group(2))}
    if adding:
        return {**out, "kind": "add", "from_body": True}  # A new chapter or subchapter: its sections are in the body.
    return {**out, "kind": "chapter"}


def _split_body(body: list[str], targets: list[str], from_body: bool) -> dict[str, list[str]]:
    """Assign body paragraphs to sections by their "Sec. N." / "Art. N." headers."""
    parts: dict[str, list[str]] = {}
    current = targets[0] if len(targets) == 1 and not from_body else None
    for line in body:
        header = _HEADER.match(plain_text(line))
        if header and (from_body or header.group(1) in targets):
            current = header.group(1)
        if current is not None:
            parts.setdefault(current, []).append(line)
    return parts


def _repealed_items(body: list[str], code: str | None) -> list[tuple[str, str]]:
    found = []
    for line in body:
        text = plain_text(line).replace(" & ", " and ")
        named = _CODE_RE.search(text)
        item_code = CODE_ABBR[named.group(1)] if named else code
        unit = "Articles?" if item_code == "CR" else "Sections?"
        for m in re.finditer(r"\b" + unit + _LIST, text):
            found += [(item_code, n) for n in _numbers(m.group(1)) if item_code]
    return found


def bill_statutes(markdown: str) -> tuple[dict[str, dict], int]:
    """({key: {kind, subsections, partial, paragraphs}}, unparsed clause count) for one bill text."""
    lines = [line for line in markdown.split("\n") if line.strip()]
    sections: dict[str, dict] = {}
    unparsed = 0
    rank = {"amend": 3, "add": 2, "repeal": 1}

    def note(code: str, number: str, kind: str, subs: list[str], paragraphs: list[str]):
        key = f"{code} {number}"
        if not STATUTE_KEY.fullmatch(key) or len(number) > 16:
            return
        entry = sections.setdefault(key, {"kind": kind, "subsections": [], "partial": True, "paragraphs": []})
        if rank[kind] > rank[entry["kind"]]:
            entry["kind"] = kind
        if kind == "amend":
            entry["partial"] = entry["partial"] and bool(subs)
            entry["subsections"] = list(dict.fromkeys(entry["subsections"] + subs))
        elif kind == "add":
            entry["partial"] = False
        entry["paragraphs"] += paragraphs

    i = 0
    while i < len(lines):
        if not _HEADING_LINE.match(lines[i]) or i + 1 >= len(lines):
            i += 1
            continue
        clause = lines[i + 1]
        end = i + 2
        while end < len(lines) and not _HEADING_LINE.match(lines[end]):
            end += 1
        body = lines[i + 2:end]
        parsed = parse_clause(clause)
        kind = parsed["kind"]
        if kind == "unparsed":
            unparsed += 1
        elif kind == "repealer":
            for code, number in _repealed_items(body, parsed["code"]):
                note(code, number, "repeal", [], [])
        elif kind == "repeal":
            for number in parsed["targets"]:
                note(parsed["code"], number, "repeal", parsed["subsections"], [])
        elif kind in ("amend", "add"):
            parts = _split_body(body, parsed["targets"], parsed["from_body"])
            numbers = list(parts) if parsed["from_body"] else parsed["targets"]
            for number in numbers:
                note(parsed["code"], number, kind, parsed["subsections"] if kind == "amend" else [], parts.get(number, []))
        i = end
    return sections, unparsed


def _latest_text(text_dir: Path, bill_id: str) -> tuple[dict, str] | None:
    try:
        index = json.loads((text_dir / bill_id / "index.json").read_text("utf-8"))
        versions = [v for v in index.get("versions", []) if isinstance(v, dict) and re.fullmatch(r"[A-Z0-9]{1,3}", str(v.get("code", "")))]
        if index.get("bill_id") != bill_id or not versions:
            return None
        version = versions[-1]
        return version, (text_dir / bill_id / f"{version['code']}.md").read_text("utf-8")
    except (OSError, ValueError, AttributeError):
        return None


def section_heading(paragraphs: list[str]) -> str:
    """"Sec. 48.160. FUNDING FOR X." -> "Funding for X" style heading as written (proposed wording)."""
    for line in paragraphs:
        proposed = plain_text(re.sub(r"\\\[<del>.*?</del>\\\]|<del>.*?</del>", "", line))
        m = re.match(r"^(?:Sec|Art)\. " + SECTION_NUM.pattern + r"\.\s+([^a-z]{3,200}?)\.(?:\s|$)", proposed)
        if m:
            return m.group(1).strip()
    return ""


def build_statutes(snapshot: dict, text_dir: Path) -> tuple[dict, dict[str, dict]]:
    """(index, {file name: section document}) from every bill's latest text version."""
    by_key: dict[str, list[dict]] = {}
    bills_meta: dict[str, dict] = {}
    for bill in snapshot.get("bills") or []:
        bill_id = str(bill.get("id", "")) if isinstance(bill, dict) else ""
        if not BILL_ID.fullmatch(bill_id):
            continue
        found = _latest_text(text_dir, bill_id)
        if not found:
            continue
        version, markdown = found
        sections, unparsed = bill_statutes(markdown)
        bills_meta[bill_id] = {"v": version["code"], "n": len(sections), "u": unparsed}
        for key, entry in sections.items():
            by_key.setdefault(key, []).append({"bill": bill_id, "version": version["code"],
                                               "version_name": str(version.get("name") or version["code"]), **entry})
    index = {"format": STATUTE_FORMAT, "codes": {abbr: CODE_NAME[abbr] for abbr in sorted({k[:2] for k in by_key})},
             "sections": {}, "bills": dict(sorted(bills_meta.items()))}
    files = {}
    for key in sorted(by_key):
        entries = sorted(by_key[key], key=lambda e: (e["bill"][:2] != "HB", int(re.sub(r"\D", "", e["bill"]) or 0), e["bill"]))
        heading = next((h for e in entries if (h := section_heading(e["paragraphs"]))), "")
        index["sections"][key] = {"h": heading, "b": [[e["bill"], KIND_LETTER[e["kind"]]] for e in entries]}
        code, number = key.split(" ")
        files[f"{code}-{number}.json"] = {"format": STATUTE_SECTION_FORMAT, "key": key, "code": code,
                                          "code_name": CODE_NAME[code], "section": number, "heading": heading,
                                          "entries": entries}
    return index, files


def write_statutes(snapshot: dict, text_dir: Path, out_dir: Path) -> tuple[int, int, int]:
    """Writes out_dir/index.json and out_dir/sections/<CODE>-<section>.json; removes sections no bill touches now.
    Returns (written, unchanged, removed). Does nothing without a text directory."""
    if not text_dir.is_dir():
        return 0, 0, 0
    index, files = build_statutes(snapshot, text_dir)
    sections_dir = out_dir / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    written = unchanged = removed = 0
    for name, document in files.items():
        if write_if_changed(sections_dir / name, json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"):
            written += 1
        else:
            unchanged += 1
    for stale in sections_dir.glob("*.json"):
        if stale.name not in files and re.fullmatch(r"[A-Z]{2}-[0-9A-Z.]+\.json", stale.name):
            stale.unlink()
            removed += 1
    # The index goes last, so it never names a section file that is not there yet.
    write_if_changed(out_dir / "index.json", json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n")
    return written, unchanged, removed


# Population brackets: "a county with a population of more than four million" resolved to the places that meet the
# population test under the 2020 census. Extra conditions ("adjacent to ...") are flagged, never resolved.
BRACKET_FORMAT = "texas-bill-brackets-v1"
POPULATION_FORMAT = "texas-population-2020-v1"
BRACKET_LIST_MAX = 40   # places listed by name; bigger sets are only counted
NEAR_SHARE = 0.02       # a place within 2% of a threshold is "close to the line"
BRACKET_BILL = re.compile(r"(HB|SB|HJR|SJR)[1-9]\d{0,4}")  # laws; resolutions are prose
_WORD_NUMBER = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_POP_NUM = (r"(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?: million)?"
            r"|(?:one|two|three|four|five|six|seven|eight|nine|ten) million)")
_OP_BEFORE = (r"(?:not more than|not less than|not greater than|at least|more than|greater than|less than|fewer than|"
              r"in excess of|exceeding|that exceeds|over|under)")
_OP_AFTER = r"(?:or more|or greater|or less|or fewer)"
_ONE = rf"(?:{_OP_BEFORE} )?{_POP_NUM}(?: {_OP_AFTER})?"
_RANGE = rf"(?P<range>between {_POP_NUM} and {_POP_NUM}|{_ONE}(?:,? (?:and|but) {_ONE})?)"
_ENTITY = (r"(?P<entity>county or municipality|municipality or county|municipality|municipalities|city|cities|county|"
           r"counties)")
_HAS = r"(?:,? (?:that|which) (?:has|had)|,? having|,? with|,? of|,? has)"
_POPULATION = r"(?:a (?:total )?population|populations)"
_BRACKET = re.compile(rf"\b{_ENTITY}{_HAS} {_POPULATION} (?:of |that is )?{_RANGE}", re.I)
_ITEM = re.compile(rf"^\([0-9A-Za-z-]+\) (?:(?:that|which) (?:has|had) |having |with |has ){_POPULATION} "
                   rf"(?:of |that is )?{_RANGE}", re.I)
_LEAD_ENTITY = re.compile(rf"\b{_ENTITY}\b", re.I)
# Any "population ... <number>" phrase, for counting the ones no clause covers.
_POP_PHRASE = re.compile(r"populations?(?:(?!population)[^.;:]){0,60}?(?=\d|(?:one|two|three|four|five|six|seven|eight|"
                         r"nine|ten) million)", re.I)
# A test on a related place, not on the place the provision covers; the last such word before the bracket wins.
_RELATED = re.compile(r".*\b(adjacent to|adjoining|bordering|borders|border|neighboring|contains|contain|containing|"
                      r"includes|include|including|seat of|principal)\b[^.;:]{0,30}$", re.I)
_RELATION = {"adjacent to": "near", "adjoining": "near", "bordering": "near", "borders": "near", "border": "near",
             "neighboring": "near", "contains": "inside", "contain": "inside", "containing": "inside",
             "includes": "inside", "include": "inside", "including": "inside", "seat of": "seat", "principal": "principal"}
_CENSUS_YEAR = re.compile(r"\b(1[89]\d0|20\d0) (?:federal )?(?:decennial )?census", re.I)
_CENSUS_TAIL = re.compile(r"^,? ?(?:as determined by|according to|under) (?:the )?(?:most recent )?(?:federal )?"
                          r"(?:decennial )?census,?", re.I)
_CONDITION = re.compile(r"^,? ?(?:and |or )?(?:that|which|located|is located|bordering|that borders|adjacent|containing|"
                        r"in which|where|bisected|through which|within|having|in a county|on the|along)\b", re.I)


def _population_number(text: str) -> int:
    m = re.fullmatch(r"([\d,]+(?:\.\d+)?|[a-z]+)( million)?", text.lower())
    base = float(m.group(1).replace(",", "")) if m.group(1)[0].isdigit() else _WORD_NUMBER[m.group(1)]
    return int(round(base * (1_000_000 if m.group(2) else 1)))


def bracket_bounds(text: str) -> tuple[int | None, int | None] | None:
    """Inclusive (low, high) for a range such as "more than 2.1 million" or "50,000 or more but less than 250,000".
    None when a part has no comparison word (a bare number) or the range is empty."""
    between = re.fullmatch(rf"between ({_POP_NUM}) and ({_POP_NUM})", text.strip(), re.I)
    if between:  # read as inclusive at both ends
        low, high = _population_number(between.group(1)), _population_number(between.group(2))
        return (low, high) if low <= high else None
    low = high = None
    for part in re.split(r",? (?:and|but) ", text.strip()):
        m = re.fullmatch(rf"(?:({_OP_BEFORE}) )?({_POP_NUM})(?: ({_OP_AFTER}))?", part, re.I)
        op = ((m.group(1) or m.group(3) or "").lower()) if m else ""
        if not op:
            return None
        n = _population_number(m.group(2))
        if op in ("at least", "not less than", "or more", "or greater"):
            low = n
        elif op in ("more than", "greater than", "in excess of", "exceeding", "that exceeds", "over"):
            low = n + 1
        elif op in ("not more than", "not greater than", "or less", "or fewer"):
            high = n
        else:
            high = n - 1
    if low is not None and high is not None and low > high:
        return None
    return low, high


def _wording(line: str, keep: str) -> str:
    """One paragraph as current law (keep="del") or as proposed (keep="ins"), in plain text."""
    drop = "ins" if keep == "del" else "del"
    text = re.sub(rf"\\?\[?<{drop}>.*?</{drop}>\\?\]?", "", line)
    text = re.sub(rf"\\?\[<{keep}>(.*?)</{keep}>\\?\]", r"\1", text)
    return re.sub(r"\s{2,}", " ", plain_text(text)).strip()


def _paragraph_brackets(text: str, lead: tuple[str, bool] | None) -> list[dict]:
    """Brackets in one plain paragraph. `lead` is (entity, joint) from a lead-in line ending in ":" for list items such
    as "(1) has a population of ..."; joint means the items are conditions together ("a county that:")."""
    found = [(m, m.group("entity"), False) for m in _BRACKET.finditer(text)]
    item = _ITEM.match(text)
    if item and lead:
        found.append((item, lead[0], lead[1] or bool(re.search(r"\band$", text))))
    out = []
    for m, entity, joint in found:
        tail = re.split(r"(?<=[.;:])(?:\s|$)", text[m.end():m.end() + 240])[0]
        year = _CENSUS_YEAR.search(tail)
        related = _RELATED.match(text[max(0, m.start() - 60):m.start()]) if m is not item else None
        entity = entity.lower()
        kinds = ["county", "city"] if " or " in entity else ["county" if entity.startswith("count") else "city"]
        for kind in kinds:
            out.append({"kind": kind, "text": m.group(0)[:200], "bounds": bracket_bounds(m.group("range")),
                        "census": int(year.group(1)) if year and year.group(1) != "2020" else None,
                        "cond": joint or bool(_CONDITION.match(_CENSUS_TAIL.sub("", tail.strip()).strip())),
                        "rel": _RELATION[related.group(1).lower()] if related else None})
    return out


def _unread(wordings: list[str], clauses: list[dict]) -> int:
    """Population phrases with a number that no readable clause covers (bare numbers, "either ... or", nested wording)."""
    covered = [c["text"] for c in clauses if c["bounds"] is not None]
    missing = set()
    for wording in wordings:
        for m in _POP_PHRASE.finditer(wording):
            number = re.match(r"\d+(?:[,.]\d+)*|\w+ million", wording[m.end():])
            if number and re.match(r"\s*(?:percent|%)", wording[m.end() + len(number.group(0)):]):
                continue
            phrase = m.group(0) + (number.group(0) if number else "")
            if not any(phrase in t for t in covered):
                missing.add(phrase)
    return len(missing)


def bill_brackets(markdown: str) -> tuple[list[dict], int]:
    """(clauses, unparsed) from a bill's text. A clause is new, changed (with "was"), existing or removed: unmarked
    wording is existing law inside a SECTION that amends a code and new law in any other SECTION."""
    clauses: list[dict] = []
    unparsed = 0
    section, codified, lead, expect_clause, last_entity = "", False, None, False, None
    for line in markdown.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("### "):
            section, expect_clause, lead, last_entity = line[4:].strip().rstrip("."), True, None, None
            continue
        if expect_clause:
            codified, expect_clause = parse_clause(plain_text(line))["kind"] != "none", False
        cur, new = _wording(line, "del"), _wording(line, "ins")
        if "population" in line.lower():
            marked = "<ins>" in line or "<del>" in line
            now = _paragraph_brackets(new, lead)
            before = _paragraph_brackets(cur, lead) if marked else []
            before_texts = {b["text"] for b in before}
            gone = [b for b in before if b["text"] not in {n["text"] for n in now}]
            for c in now:
                if not marked:
                    c["status"] = "existing" if codified else "new"
                elif c["text"] in before_texts:
                    c["status"] = "existing"
                else:
                    # "(1) has a population of 25,000 [(A) ... 10,000]": list labels may be renumbered too.
                    stem = lambda t: re.sub(r"^\([0-9A-Za-z-]+\) ", "", t).split(" population")[0]
                    was = next((g for g in gone if g["kind"] == c["kind"] and stem(g["text"]) == stem(c["text"])), None)
                    c["status"] = "changed" if was else "new"
                    if was:
                        gone.remove(was)
                        c["was"] = was
                c["section"] = section
                clauses.append(c)
            for g in gone:
                clauses.append({**g, "status": "removed", "section": section})
            unparsed += _unread([new, cur] if marked else [new], now + before)
        entities = _LEAD_ENTITY.findall(new)
        if new.endswith(":"):
            # "a municipality[:] / [(1)] that:" - a lead-in naming no place keeps the place named just before it.
            entity = entities[-1] if entities else (lead[0] if lead else last_entity)
            lead = (entity, bool(re.search(r"\b(?:that|which)\s*:$", new))) if entity else None
        elif not re.match(r"^\([0-9A-Za-z-]+\) ", new):
            lead = None
        if entities:
            last_entity = entities[-1]
    seen, out = set(), []
    for c in clauses:
        if c["bounds"] is None:
            continue
        key = (c["kind"], c["text"], c["status"], c.get("was", {}).get("text"))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out, unparsed


def load_population(path: Path) -> dict | None:
    """The census table from scripts/census_places.py, or None when it is missing or not that format."""
    try:
        table = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(table, dict) or table.get("format") != POPULATION_FORMAT:
        return None
    counties, places = table.get("counties"), table.get("places")
    ok = lambda rows, width: isinstance(rows, dict) and rows and all(
        isinstance(v, list) and len(v) == width and isinstance(v[0], str) and isinstance(v[1], int) for v in rows.values())
    return table if ok(counties, 2) and ok(places, 3) else None


def _resolve(table: dict, kind: str, low: int | None, high: int | None) -> list[str]:
    rows = table["counties"] if kind == "county" else table["places"]
    hits = [g for g, v in rows.items() if (low is None or v[1] >= low) and (high is None or v[1] <= high)]
    return sorted(hits, key=lambda g: (-rows[g][1], g))


def _near(table: dict, kind: str, low: int | None, high: int | None) -> list[str]:
    rows = table["counties"] if kind == "county" else table["places"]
    near = []
    for t in (low, high):
        if t:
            near += [(abs(v[1] - t), g) for g, v in rows.items() if abs(v[1] - t) <= t * NEAR_SHARE]
    return [g for _, g in sorted(set(near))][:8]


def build_brackets(snapshot: dict, text_dir: Path, table: dict) -> dict:
    used: set[str] = set()
    bills: dict[str, dict] = {}

    def listed(geoids: list[str]) -> list[str] | None:
        if len(geoids) > BRACKET_LIST_MAX:
            return None
        used.update(geoids)
        return geoids

    for bill in snapshot.get("bills") or []:
        bill_id = str(bill.get("id", "")) if isinstance(bill, dict) else ""
        if not BRACKET_BILL.fullmatch(bill_id):
            continue
        found = _latest_text(text_dir, bill_id)
        if not found:
            continue
        version, markdown = found
        clauses, unparsed = bill_brackets(markdown)
        rows = []
        for c in clauses:
            low, high = c["bounds"]
            row = {"s": c["status"], "k": c["kind"], "t": c["text"], "lo": low, "hi": high, "sec": c["section"],
                   "cond": c["cond"]}
            if c["rel"]:
                row["rel"] = c["rel"]   # a neighbor, a place inside, the county a city is seat of, or the principal city
            if c["census"]:
                row["census"] = c["census"]       # tied to an older census: not resolved
            else:
                hits = _resolve(table, c["kind"], low, high)
                row["n"], row["p"] = len(hits), listed(hits)
                near = _near(table, c["kind"], low, high)
                if near:
                    used.update(near)
                    row["near"] = near
            was = c.get("was")
            if was:
                row["was"] = {"t": was["text"], "lo": was["bounds"][0], "hi": was["bounds"][1]}
                if not c["census"] and not was["census"]:
                    before = set(_resolve(table, was["kind"], *was["bounds"]))
                    after = set(row.get("p") or _resolve(table, c["kind"], low, high))
                    added = sorted(after - before, key=lambda g: (-table["counties" if c["kind"] == "county" else "places"][g][1], g))
                    dropped = sorted(before - after, key=lambda g: (-table["counties" if c["kind"] == "county" else "places"][g][1], g))
                    row["was"].update({"n": len(before), "added": len(added), "dropped": len(dropped),
                                       "added_p": listed(added), "dropped_p": listed(dropped)})
            rows.append(row)
        if rows or unparsed:
            bills[bill_id] = {"v": version["code"], "c": rows, "u": unparsed}
    counties, places = table["counties"], table["places"]
    shared = {n for n, k in Counter(v[0] for v in places.values()).items() if k > 1}  # e.g. two Renos
    names = {}
    for g in sorted(used):
        if g in counties:
            names[g] = counties[g]
        elif g in places:
            name, pop, county = places[g]
            names[g] = [name, pop, counties.get(county, [""])[0] if name in shared else ""]
    return {"format": BRACKET_FORMAT, "census": table.get("source", ""), "places": names, "bills": bills}


def write_brackets(snapshot: dict, text_dir: Path, census: Path, out_dir: Path) -> str:
    """Writes out_dir/index.json. Skips (and says why) without bill text or a valid census table."""
    if not text_dir.is_dir():
        return "skipped (no bill text)"
    table = load_population(census)
    if table is None:
        return f"skipped (no valid census table at {census})"
    index = build_brackets(snapshot, text_dir, table)
    out_dir.mkdir(parents=True, exist_ok=True)
    changed = write_if_changed(out_dir / "index.json", json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n")
    clauses = sum(len(b["c"]) for b in index["bills"].values())
    return f"{len(index['bills'])} bills, {clauses} clauses, {'written' if changed else 'unchanged'}"


def default_census() -> Path:
    """Beside this script (the data unit copies it there), else the repository's data/census copy."""
    here = Path(__file__).resolve().parent
    beside = here / "tx_population_2020.json"
    return beside if beside.exists() else here.parent / "data" / "census" / "tx_population_2020.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Public feeds directory, e.g. live/feeds")
    parser.add_argument("--site", default=SITE)
    parser.add_argument("--tags", type=Path, default=None,
                        help="Published Luna tags; defaults to luna/tags.json beside the snapshot when present")
    parser.add_argument("--members", type=Path, default=None,
                        help="Legislator roster for per-member feeds; defaults to members.json beside the snapshot")
    parser.add_argument("--text", type=Path, default=None, help="Bill text directory; defaults to text/ beside the snapshot")
    parser.add_argument("--statutes", type=Path, default=None,
                        help="Statute index output; defaults to statutes/ beside the snapshot")
    parser.add_argument("--census", type=Path, default=None,
                        help="2020 population table (scripts/census_places.py); defaults to one beside this script")
    parser.add_argument("--brackets", type=Path, default=None,
                        help="Population bracket output; defaults to brackets/ beside the snapshot")
    args = parser.parse_args()
    tags = args.tags or args.snapshot.parent / "luna" / "tags.json"
    snapshot, reviews = json.loads(args.snapshot.read_text("utf-8")), load_reviews(tags)
    written, unchanged = write_feeds(snapshot, args.out, args.site, reviews)
    print(f"Feeds: {written} written, {unchanged} unchanged", flush=True)
    roster = load_roster(args.members or args.snapshot.parent / "members.json")
    written, unchanged = write_member_feeds(snapshot, roster, args.out / "members", args.site, reviews)
    print(f"Member feeds: {written} written, {unchanged} unchanged", flush=True)
    text_dir = args.text or args.snapshot.parent / "text"
    written, unchanged, removed = write_statutes(snapshot, text_dir, args.statutes or args.snapshot.parent / "statutes")
    print(f"Statute sections: {written} written, {unchanged} unchanged, {removed} removed", flush=True)
    status = write_brackets(snapshot, text_dir, args.census or default_census(), args.brackets or args.snapshot.parent / "brackets")
    print(f"Population brackets: {status}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
