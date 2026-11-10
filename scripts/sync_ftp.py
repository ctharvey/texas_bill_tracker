#!/usr/bin/env python3
"""Import 90R bill-history XML from Texas's expressly provided bulk FTP service.

No scraping of capitol.texas.gov. No dependencies beyond Python's standard library.
If the published format differs from the fields we can parse, this script exits
without overwriting the last good snapshot. Run from the repository root.
"""

from __future__ import annotations

import argparse
import datetime as dt
import ftplib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import xml.etree.ElementTree as ET


HOST = "ftp.legis.state.tx.us"
ROOT = "/bills/90r/billhistory"
OUT = Path(__file__).resolve().parents[1] / "data" / "bills.json"
FOLDERS = (
    "house_bills", "senate_bills", "house_joint_resolutions", "senate_joint_resolutions",
    "house_concurrent_resolutions", "senate_concurrent_resolutions",
    "house_resolutions", "senate_resolutions",
)
BILL_RE = re.compile(r"(?<![A-Z])((?:H|S)(?:B|JR|CR|R))\s*0*(\d{1,5})(?!\d)", re.I)
XML_SIZE_LIMIT = 2_000_000


def local_tag(tag: str) -> str:
    """Normalize namespaces, casing and punctuation in source XML tags."""
    return re.sub(r"[^a-z0-9]", "", tag.rsplit("}", 1)[-1].lower())


def first_text(root: ET.Element, *aliases: str) -> str:
    choices = {local_tag(a) for a in aliases}
    for element in root.iter():
        if local_tag(element.tag) in choices:
            text = " ".join(" ".join(element.itertext()).split())
            if text:
                return text[:1400]
    return ""


def all_text(root: ET.Element, *aliases: str) -> list[str]:
    choices = {local_tag(a) for a in aliases}
    result = []
    for element in root.iter():
        if local_tag(element.tag) in choices:
            text = " ".join(" ".join(element.itertext()).split())
            if text and text not in result:
                result.append(text)
    return result


def parse_bill_number(*candidates: str) -> str | None:
    for candidate in candidates:
        match = BILL_RE.search(candidate.replace('_', ' '))
        if match:
            return match.group(1).upper() + str(int(match.group(2)))
    return None


def member_names(root: ET.Element, *tags: str) -> list[str]:
    """TLC separates members with pipes; preserve source order and distinct roles."""
    return list(dict.fromkeys(
        name.strip() for text in all_text(root, *tags) for name in text.split('|') if name.strip()
    ))


def infer_status(actions: list[str], committees: list[str]) -> str:
    text = " ".join(actions).lower()
    if "signed by the governor" in text or "became law" in text:
        return "Enacted"
    if "passed both" in text or "sent to governor" in text:
        return "Passed"
    if "passed" in text or "engrossed" in text or "reported favorably" in text:
        return "Advanced"
    if any(p in text for p in ("public hearing held", "hearing held", "testimony taken",
                               "heard in committee", "considered in public hearing")):
        return "Heard"
    if any(p in text for p in ("scheduled for public hearing", "scheduled for hearing", "hearing scheduled")):
        return "Scheduled"
    if committees or "referred to" in text:
        return "Referred"
    return "Filed"


def parse_bill_xml(raw: bytes, path: str) -> dict | None:
    """Normalize documented bill-history concepts without assuming one XML layout.

    Fail closed when we cannot confidently identify both the bill and its caption.
    Unknown fields are not fabricated; agency impact is a separate analysis layer.
    """
    if len(raw) > XML_SIZE_LIMIT:
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    bill_id = parse_bill_number(
        first_text(root, "billnumber", "bill", "legislationnumber", "billid"),
        PurePosixPath(path).stem,
    )
    if not bill_id:
        return None
    caption = first_text(root, "captiontext", "currentcaption", "caption", "longtitle", "description", "billtitle")
    if len(caption) < 12:
        return None
    authors = member_names(root, "authors") or member_names(root, "primaryauthor", "authorname", "author")
    author = " | ".join(authors)
    history = [
        (first_text(element, "actiondescription", "actiontext", "description"),
         normalize_date(first_text(element, "date")))
        for element in root.iter() if local_tag(element.tag) == "action"
    ]
    actions = [description for description, _ in history if description]
    if not actions:
        actions = all_text(root, "actiondescription", "actiontext", "action")
    dates = all_text(root, "fileddate", "introductiondate", "filedate", "datefiled")
    committees = all_text(root, "committeename", "currentcommittee", "referredcommittee")
    status = infer_status(actions, committees)
    date = normalize_date(dates[0]) if dates else ""
    if not date:
        filing_dates = [day for description, day in history
                        if day and description.strip().lower() == "filed"]
        date = min(filing_dates, default="")
    last_action = first_text(root, "lastaction") or (actions[-1] if actions else "Filed")
    last_action_date = normalize_date(last_action) or max((day for _, day in history if day), default=date)
    record = {
        "id": bill_id,
        "number": re.sub(r"(?<=\D)(?=\d)", " ", bill_id, count=1),
        "chamber": "House" if bill_id.startswith("H") else "Senate",
        "title": caption,
        "caption": caption,
        "author": author or "Author not available in parsed history",
        "authors": authors,
        "coauthors": member_names(root, "coauthors"),
        "sponsors": member_names(root, "sponsors"),
        "cosponsors": member_names(root, "cosponsors"),
        "filed_at": date,
        "status": status,
        "last_action": last_action[:400],
        "last_action_date": last_action_date,
        "actions": actions[-12:],
        "source_record": "Texas Legislative Council bulk FTP bill history",
        "source_path": path,
    }
    dated = [day for description, day in history if description]
    if len(dated) == len(actions):  # Only when every action came from a dated <action> element.
        record["action_dates"] = dated[-12:]
    if committees:
        record["committee"] = committees[-1][:200]
    return record


def normalize_date(text: str) -> str:
    match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if match:
        try:
            return dt.date(*map(int, match.groups())).isoformat()
        except ValueError:
            return ""
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
    if match:
        try:
            month, day, year = map(int, match.groups())
            return dt.date(year, month, day).isoformat()
        except ValueError:
            return ""
    return ""


def ftp_bytes(conn: ftplib.FTP, path: str) -> bytes:
    contents = io.BytesIO()
    conn.retrbinary(f"RETR {path}", contents.write, blocksize=65536)
    return contents.getvalue()


def ftp_names(conn: ftplib.FTP, path: str) -> list[str]:
    """Return canonical absolute FTP paths; server may list bare names."""
    try:
        entries = conn.nlst(path)
    except ftplib.error_perm as exc:
        if str(exc).startswith("550"):
            return []
        raise
    return sorted(set(str(PurePosixPath(path) / PurePosixPath(name).name) for name in entries if name not in ('.','..')))


def enumerate_xml(conn: ftplib.FTP) -> list[str]:
    """Traverse official type + 100-bill grouping hierarchy.

    The file-name schema is not considered a guarantee of document contents;
    parse_bill_xml validates each bill independently.
    """
    paths = []
    for category in FOLDERS:
        top = f"{ROOT}/{category}"
        for folder in ftp_names(conn, top):
            if folder.lower().endswith('.xml'):
                paths.append(folder)
            else:
                paths.extend(name for name in ftp_names(conn, folder) if name.lower().endswith('.xml'))
    return sorted(set(p for p in paths if not p.lower().endswith('/history.xml')))


HEARTBEAT = dt.timedelta(hours=6)


def choose_generated_at(previous: dict | None, new_payload: dict, now: dt.datetime) -> str:
    """Keep the previous timestamp when nothing else changed and it is under 6 hours old."""
    fresh = now.astimezone(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
    if not previous or not previous.get('generated_at'):
        return fresh
    strip = lambda p: {k: v for k, v in p.items() if k != 'generated_at'}
    if strip(previous) != strip(new_payload):
        return fresh
    try:
        stamp = dt.datetime.fromisoformat(str(previous['generated_at']).replace('Z', '+00:00'))
    except ValueError:
        return fresh
    if stamp.tzinfo is None:
        return fresh
    if dt.timedelta(0) <= now - stamp < HEARTBEAT:
        return previous['generated_at']
    return fresh


def synchronize(conn: ftplib.FTP, prior: dict, max_files: int = 25000) -> tuple[dict, dict]:
    paths = enumerate_xml(conn)
    if not paths:
        raise RuntimeError("The 90R bulk FTP bill-history listing is empty or unavailable")
    if len(paths) > max_files:
        raise RuntimeError(f"Found {len(paths)} XML paths; refusing unexpected volume above {max_files}")
    parsed = {}
    errors = []
    for i, path in enumerate(paths, 1):
        try:
            bill = parse_bill_xml(ftp_bytes(conn, path), path)
            if bill:
                parsed[bill['id']] = bill
        except (ftplib.error_perm, ftplib.error_temp, EOFError, OSError) as exc:
            errors.append(f"{path}: {exc}")
        if i % 250 == 0:
            print(f"Inspected {i}/{len(paths)} XML files; {len(parsed)} parseable", flush=True)
    min_parsed = max(1, len(paths) // 3)
    if len(parsed) < min_parsed:
        raise RuntimeError(f"Could parse only {len(parsed)}/{len(paths)} files; snapshot left untouched. First errors: {errors[:3]}")
    previous = {b['id']: b for b in prior.get('bills',[]) if 'id' in b}
    merged = dict(previous)
    for key,bill in parsed.items():
        old = previous.get(key,{})
        # Manually reviewed impact tags survive later metadata refreshes.
        preserved = {k: old[k] for k in ('agencies','topics','impacts','constituencies','author_profile','notes') if k in old}
        merged[key] = {**old,**bill,**preserved}
    snapshot = {
        'session': '90R',
        'generated_at': '',
        'data_mode': 'official-ftp',
        'coverage_note': f"{len(parsed)} bill histories read from the official bulk FTP; {len(merged)} combined records. Agency inferences are based on available captions and curated overrides.",
        'sources': ['ftp://ftp.legis.state.tx.us/bills/90r/billhistory/', 'https://capitol.texas.gov/billlookup/filedownloads.aspx'],
        'author_profiles': prior.get('author_profiles',{}),
        'bills': sorted(merged.values(), key=lambda b:(b.get('filed_at') or '',b['id']),reverse=True),
    }
    snapshot['generated_at'] = choose_generated_at(prior, snapshot, dt.datetime.now(dt.timezone.utc))
    return snapshot, {'listed':len(paths),'parsed':len(parsed),'combined':len(merged),'transfer_errors':len(errors)}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=OUT)
    parser.add_argument('--max-files',type=int,default=25000)
    args=parser.parse_args()
    prior=json.loads(args.out.read_text(encoding='utf-8')) if args.out.exists() else {'bills':[]}
    with ftplib.FTP(HOST,timeout=55) as conn:
        conn.login('anonymous','legislative-research@example.invalid')
        snapshot,stats=synchronize(conn,prior,args.max_files)
    temp=args.out.with_suffix('.json.tmp')
    temp.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temp,args.out)
    print(json.dumps(stats,indent=2))
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except (*ftplib.all_errors, RuntimeError, OSError, ValueError) as exc:
        print(f"SYNC FAILED, previous snapshot preserved: {exc}",file=sys.stderr)
        sys.exit(1)
