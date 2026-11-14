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
import hashlib
from html.parser import HTMLParser
import io
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import urlsplit
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
    if any(local_tag(element.tag) == "companions" for element in root.iter()):
        record["companions"] = parse_companions(first_text(root, "companions"), bill_id)
    subject_lists = [e for e in root.iter() if local_tag(e.tag) == "subjects"]
    if subject_lists:
        record["subjects"] = parse_subjects(subject_lists[0])
    billtext = next((e for e in root.iter() if local_tag(e.tag) == "billtext"), None)
    if billtext is not None:
        record["text_versions"] = parse_text_versions(billtext)
    for key, value in root.attrib.items():
        if local_tag(key) == "lastupdate" and value.strip():
            record["source_updated"] = value.strip()
            break
    events = parse_events(root)
    if events:
        record["events"] = events
    if billtext is not None:
        documents = parse_documents(billtext)
        if documents:
            record["documents"] = documents
    return record


def parse_events(root: ET.Element) -> list[dict]:
    """Every <action> in document order as {code, date, text}; last 400. [] when no action has a code."""
    events = []
    for element in root.iter():
        if local_tag(element.tag) != "action":
            continue
        events.append({
            "code": first_text(element, "actionnumber"),
            "date": normalize_date(first_text(element, "date")),
            "text": first_text(element, "actiondescription", "actiontext", "description")[:300],
        })
    if not any(event["code"] for event in events):
        return []
    return events[-400:]


DOCUMENT_PATHS = {
    "analysis": "/bills/90r/analysis/html/",
    "fiscal_note": "/bills/90r/fiscalnotes/html/",
}
DOCUMENT_DOCTYPES = {"analysis": "analysis", "fiscalnote": "fiscal_note"}


def parse_documents(billtext: ET.Element) -> list[dict]:
    """Bill analyses and fiscal notes (billtext/docTypes/<type>/versions/version), deduped by (type, code)."""
    def children(element: ET.Element, tag: str):
        return [c for c in element if local_tag(c.tag) == tag]
    found, seen = [], set()
    for doctypes in children(billtext, "doctypes"):
        for doctype in doctypes:
            kind = DOCUMENT_DOCTYPES.get(local_tag(doctype.tag))
            if not kind:
                continue
            for versions in children(doctype, "versions"):
                for version in children(versions, "version"):
                    url = first_text(version, "ftphtmlurl")
                    try:
                        parts = urlsplit(url)
                        host = (parts.hostname or "").lower()
                    except ValueError:
                        continue
                    if parts.scheme.lower() != "ftp" or host != HOST \
                            or not parts.path.lower().startswith(DOCUMENT_PATHS[kind]):
                        continue
                    match = TEXT_FILE_RE.match(PurePosixPath(parts.path).name)
                    if not match or (kind, match.group(1)) in seen:
                        continue
                    code = match.group(1)
                    seen.add((kind, code))
                    found.append({"type": kind, "code": code,
                                  "name": first_text(version, "versiondescription") or code, "html": url})
    return found


TEXT_URL_PATH = "/bills/90R/billtext/HTML/"
TEXT_FILE_RE = re.compile(r"^[A-Za-z]+\d{5}([A-Za-z0-9]{1,8})\.htm$", re.I)


def text_url_path(url: str) -> str | None:
    """Path part of a TLC 90R bill-text HTML FTP URL, or None for anything else."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme.lower() != "ftp" or host != HOST or not parts.path.startswith(TEXT_URL_PATH):
        return None
    return parts.path


def parse_text_versions(billtext: ET.Element) -> list[dict]:
    """Bill-text versions (billtext/docTypes/bill/versions/version) in document order."""
    def children(element: ET.Element, tag: str):
        return [c for c in element if local_tag(c.tag) == tag]
    found, codes = [], set()
    for doctypes in children(billtext, "doctypes"):
        for bill in children(doctypes, "bill"):
            for versions in children(bill, "versions"):
                for version in children(versions, "version"):
                    url = first_text(version, "ftphtmlurl")
                    path = text_url_path(url)
                    match = TEXT_FILE_RE.match(PurePosixPath(path).name) if path else None
                    if not match or match.group(1) in codes:
                        continue
                    code = match.group(1)
                    codes.add(code)
                    found.append({"code": code, "name": first_text(version, "versiondescription") or code, "html": url})
    return found


SUBJECT_CODE = re.compile(r"\s*\(([A-Z0-9]{3,8})\)\s*$")


def parse_subjects(element: ET.Element) -> list[str]:
    """The Legislative Council's subject index: 'Artificial Intelligence (IQ7C5)' -> 'Artificial Intelligence'."""
    found = []
    for item in element:
        if local_tag(item.tag) != "subject":
            continue
        name = SUBJECT_CODE.sub("", " ".join(" ".join(item.itertext()).split()))[:120]
        if name and name not in found:
            found.append(name)
    return found[:40]


COMPANION = re.compile(r"\b(HJR|SJR|HCR|SCR|HB|SB|HR|SR)\s*0*([1-9]\d{0,4})\b(?:\s+by\s+([^,;\n]+?))?\s*(?:,\s*([A-Za-z][A-Za-z ]{0,30}?))?\s*(?=[;\n]|$|\b(?:HJR|SJR|HCR|SCR|HB|SB|HR|SR)\s*\d)")


def bill_order(bill_id: str) -> tuple[str, int]:
    """Sort key that compares bill numbers as numbers: 'HB99' < 'HB100'."""
    match = re.fullmatch(r"([A-Z]+)(\d+)", bill_id or "")
    return (match.group(1), int(match.group(2))) if match else (bill_id or "", 0)


def parse_companions(text: str, bill_id: str) -> list[dict]:
    """'SB 132 by Menéndez, Identical' -> [{'id': 'SB132', 'author': 'Menéndez', 'relation': 'Identical'}]."""
    found, seen = [], set()
    for prefix, number, author, relation in COMPANION.findall(text or ""):
        companion = f"{prefix}{number}"
        if companion == bill_id or companion in seen:
            continue
        seen.add(companion)
        found.append({"id": companion, "author": (author or "").strip()[:80], "relation": (relation or "").strip()[:40]})
    return found[:10]


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


class _LineParser(HTMLParser):
    """Collect one entry per <tr>: the characters of its cells after the first, as (char, kind) pairs.

    kind is 'ins' inside <u>, 'del' inside <s>, else None. Markup state resets at each row end.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[tuple[list, bool]] = []
        self.row: list | None = None
        self.cell: list | None = None
        self.kind: str | None = None
        self.center = False
        self.skip = 0

    def _end_cell(self) -> None:
        if self.cell is not None and self.row is not None:
            self.row.append(self.cell)
        self.cell = None
        self.kind = None

    def end_row(self) -> None:
        self._end_cell()
        if self.row:
            # The first cell holds the PGLN line marker; join the rest ("By: Cole" + "H.B. No. 1001").
            cells = self.row[1:] if len(self.row) > 1 else self.row
            joined: list = []
            for i, cell in enumerate(cells):
                if i:
                    joined.append((" ", None))
                joined.extend(cell)
            self.lines.append((joined, self.center))
        self.row = None
        self.center = False
        self.kind = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.end_row()
            self.row = []
        elif tag in ("td", "th"):
            self._end_cell()
            if self.row is None:
                self.row = []
            self.cell = []
        elif tag == "u":
            self.kind = "ins"
        elif tag == "s":
            self.kind = "del"
        elif tag == "center":
            self.center = True
        elif tag == "br" and self.cell is not None:
            self.cell.append((" ", self.kind))
        elif tag in ("style", "script"):
            self.skip += 1

    def handle_startendtag(self, tag, attrs):
        if tag not in ("u", "s", "td", "th", "tr", "center", "style", "script"):
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._end_cell()
        elif tag == "tr":
            self.end_row()
        elif (tag == "u" and self.kind == "ins") or (tag == "s" and self.kind == "del"):
            self.kind = None
        elif tag in ("style", "script"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip and self.cell is not None:
            self.cell.extend((ch, self.kind) for ch in data)


_BLANK = re.compile(r"[\s\xa0]")
_HEADING = re.compile(r"(?:SECTION|ARTICLE)\s+\d+[A-Za-z]*\.(?!\d)")
_LEAD_FORMAT = re.compile(r"[ \t]*[\r\n][ \t\r\n\f]*")
_LEAD_INDENT = re.compile(r"[ \xa0]*")


def _normalize(chars: list) -> list:
    """Collapse whitespace to single spaces, trim, and let whitespace join same-kind neighbours."""
    items: list[tuple[str, str | None]] = []
    for ch, kind in chars:
        if _BLANK.match(ch):
            if items and items[-1][0] == " ":
                continue
            items.append((" ", kind))
        else:
            items.append((ch, kind))
    while items and items[0][0] == " ":
        items.pop(0)
    while items and items[-1][0] == " ":
        items.pop()
    for i, (ch, _) in enumerate(items):
        if ch == " ":
            before, after = items[i - 1][1], items[i + 1][1]
            items[i] = (" ", before if before == after else None)
    return items


def _escape(text: str, start: bool = False) -> str:
    out = []
    digits_end = 0
    if start:
        while digits_end < len(text) and text[digits_end].isascii() and text[digits_end].isdigit():
            digits_end += 1
    for i, ch in enumerate(text):
        special = ch in "\\`*_[]<>"
        if start and not special:
            if i == 0 and ch in "#+-=":
                special = True
            elif digits_end and i == digits_end and ch in ".)":
                special = True
        out.append("\\" + ch if special else ch)
    return "".join(out)


def _render(chars: list) -> str:
    parts = []
    for n, (kind, group) in enumerate(itertools.groupby(chars, key=lambda item: item[1])):
        text = "".join(ch for ch, _ in group)
        if kind is None:
            parts.append(_escape(text, start=(n == 0)))
        else:
            tag = "ins" if kind == "ins" else "del"
            parts.append(f"<{tag}>{_escape(text)}</{tag}>")
    return "".join(parts)


class TextNotPosted(ValueError):
    """TLC posted its "not currently available ... see the PDF" placeholder instead of the bill text."""


# The placeholder's visible text: "This version is not currently available, but is coming soon. In the meantime,
# please see the PDF for the content of this bill." (a Word page; real bill text is a table of rows).
_PLACEHOLDER = re.compile(r"version\s+is\s+not\s+currently\s+available", re.I)


def bill_text_markdown(html: str, number: str, version_name: str) -> str:
    """Convert TLC bill-text HTML to the paragraph-per-line Markdown of the bill-text format."""
    parser = _LineParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # HTMLParser is lenient, but never let odd markup escape as a new error type.
        raise ValueError(f"unparseable bill text HTML: {exc}") from exc
    parser.end_row()
    paragraphs: list[list] = []
    current: list | None = None
    previous_center = False
    for chars, center in parser.lines:
        text = "".join(ch for ch, _ in chars)
        formatting = _LEAD_FORMAT.match(text)
        if formatting:
            chars, text = chars[formatting.end():], text[formatting.end():]
        if not any(not _BLANK.match(ch) for ch in text):
            if current is not None:
                paragraphs.append(current)
            current, previous_center = None, False
            continue
        indent = len(_LEAD_INDENT.match(text).group())
        if current is None or indent >= 2 or center or previous_center:
            if current is not None:
                paragraphs.append(current)
            current = list(chars)
        else:
            current = current + [(" ", None)] + list(chars)
        previous_center = center
    if current is not None:
        paragraphs.append(current)
    lines = []
    for paragraph in paragraphs:
        chars = _normalize(paragraph)
        if not chars:
            continue
        match = _HEADING.match("".join(ch for ch, _ in chars))
        if match:
            head, rest = _normalize(chars[:match.end()]), _normalize(chars[match.end():])
            lines.append("### " + _render(head))
            if rest:
                lines.append(_render(rest))
        else:
            lines.append(_render(chars))
    if not lines:
        if _PLACEHOLDER.search(re.sub(r"<[^>]*>", " ", html)):
            raise TextNotPosted("official text not posted yet (TLC placeholder page); retried next run")
        raise ValueError("no text lines found in bill text HTML")
    title = f"# {_escape(number)} - {_escape(version_name)}"
    return "\n\n".join([title, *lines]) + "\n"


_TAGS = re.compile(r"</?(?:ins|del)>")


def plain_paragraphs(markdown: str) -> list[str]:
    """Plain projection per paragraph (index 0 is the title line); the coordinate space for highlights."""
    result = []
    for line in markdown.split("\n"):
        if not line:
            continue
        if line.startswith("### "):
            line = line[4:]
        elif line.startswith("# "):
            line = line[2:]
        result.append(re.sub(r"\\(.)", r"\1", _TAGS.sub("", line), flags=re.S))
    return result


TEXT_INDEX_FORMAT = "texas-bill-text-index-v1"
BILL_DIR_RE = re.compile(r"^[A-Z]{2,4}\d{1,5}$")
CODE_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


def _atomic_write(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def _decode_html(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def _source_modified(conn, bill: dict, path: str) -> str | None:
    if bill.get("source_updated"):
        return str(bill["source_updated"])
    try:
        return str(conn.sendcmd(f"MDTM {path}")).split()[-1]
    except Exception:
        return None


def _load_index(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {v["code"]: v for v in data.get("versions", []) if isinstance(v, dict) and "code" in v}
    except (OSError, ValueError, AttributeError, TypeError, KeyError):
        return {}


def sync_texts(conn, bills: list[dict], text_dir: Path, max_texts: int) -> dict:
    """Write text_dir/<BILL>/<CODE>.md and index.json for each bill's TLC text versions."""
    counts = {"bills": 0, "versions": 0, "downloaded": 0, "unchanged": 0, "deferred": 0, "failed": 0, "not_posted": 0}
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    for bill in bills:
        versions = bill.get("text_versions") or []
        bill_id = str(bill.get("id", ""))
        if not versions or not BILL_DIR_RE.match(bill_id):
            continue
        counts["bills"] += 1
        bill_dir = text_dir / bill_id
        index_path = bill_dir / "index.json"
        previous = _load_index(index_path)
        entries = []
        for version in versions:
            counts["versions"] += 1
            code, url = str(version.get("code", "")), str(version.get("html", ""))
            path = text_url_path(url)
            if not CODE_RE.match(code) or not path:
                counts["failed"] += 1
                continue
            md_path = bill_dir / f"{code}.md"
            old = previous.get(code)
            exists = md_path.is_file()
            current = _source_modified(conn, bill, path)
            if exists and old is not None and (not current or old.get("source_modified") == current):
                counts["unchanged"] += 1
                entries.append(old)
                continue
            if exists and old is None and not current:
                counts["unchanged"] += 1
                data = md_path.read_bytes()
                entries.append({"code": code, "name": version.get("name", code), "path": f"{code}.md", "source_url": url,
                                "source_modified": "", "sha256": hashlib.sha256(data).hexdigest(), "generated_at": now})
                continue
            if counts["downloaded"] >= max_texts:
                counts["deferred"] += 1
                if exists and old is not None:
                    entries.append(old)
                continue
            counts["downloaded"] += 1
            try:
                html = _decode_html(ftp_bytes(conn, path))
                data = bill_text_markdown(html, str(bill.get("number") or bill_id), str(version.get("name", code))).encode("utf-8")
                bill_dir.mkdir(parents=True, exist_ok=True)
                _atomic_write(md_path, data)
            except (*ftplib.all_errors, ValueError) as exc:
                # A placeholder is not a failure: nothing is written, and the next run checks again.
                counts["not_posted" if isinstance(exc, TextNotPosted) else "failed"] += 1
                print(f"text {bill_id}/{code}: {exc}", file=sys.stderr)
                if exists and old is not None:
                    entries.append(old)
                continue
            entries.append({"code": code, "name": version.get("name", code), "path": f"{code}.md", "source_url": url,
                            "source_modified": current or "", "sha256": hashlib.sha256(data).hexdigest(), "generated_at": now})
        if entries:
            index = {"format": TEXT_INDEX_FORMAT, "bill_id": bill_id, "versions": entries}
            try:
                bill_dir.mkdir(parents=True, exist_ok=True)
                _atomic_write(index_path, (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            except OSError as exc:
                counts["failed"] += 1
                print(f"text {bill_id}/index.json: {exc}", file=sys.stderr)
    return counts


HISTORY_FORMAT = "texas-bill-history-v1"


def pop_history(bills: list[dict]) -> dict[str, dict]:
    """Remove events/documents from each record in place; return {bill id: {events, documents, source_updated}}."""
    histories = {}
    for bill in bills:
        events, documents = bill.pop("events", None), bill.pop("documents", None)
        if events or documents:
            histories[str(bill.get("id", ""))] = {
                "events": events or [], "documents": documents or [], "source_updated": bill.get("source_updated")}
    return histories


def sync_history(histories: dict[str, dict], history_dir: Path) -> dict:
    """Write history_dir/<BILL>/history.json atomically, only when its canonical JSON changed."""
    counts = {"bills": 0, "written": 0, "unchanged": 0, "failed": 0}
    for bill_id, info in histories.items():
        if not BILL_DIR_RE.match(bill_id):
            continue
        counts["bills"] += 1
        payload = {"format": HISTORY_FORMAT, "bill": bill_id, "source_updated": info.get("source_updated"),
                   "events": info.get("events", []), "documents": info.get("documents", [])}
        data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        path = history_dir / bill_id / "history.json"
        try:
            if path.is_file() and path.read_bytes() == data:
                counts["unchanged"] += 1
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, data)
            counts["written"] += 1
        except OSError as exc:
            counts["failed"] += 1
            print(f"history {bill_id}: {exc}", file=sys.stderr)
    return counts


class _ProseParser(HTMLParser):
    """Collect (kind, text) blocks from prose HTML; kind is 'p', 'h', 'li' or 'tr' (cells joined by ' | ')."""

    SKIP = ("script", "style", "head", "title")
    BREAKS = ("p", "div", "br", "ul", "ol", "table", "center", "blockquote", "pre", "hr")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self.buf: list[str] = []
        self.kind = "p"
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.nest = 0
        self.skip = 0

    @staticmethod
    def _clean(parts: list[str]) -> str:
        return " ".join("".join(parts).replace("\xa0", " ").replace("�", " ").replace("​", "").split())

    def _flush(self) -> None:
        text = self._clean(self.buf)
        if text:
            self.blocks.append((self.kind, text))
        self.buf = []
        self.kind = "p"

    def _end_cell(self) -> None:
        if self.cell is not None and self.row is not None:
            self.row.append(self._clean(self.cell))
        self.cell = None

    def _end_row(self) -> None:
        self._end_cell()
        cells = [c for c in (self.row or []) if c]
        if len(cells) == 1:
            self.blocks.append(("p", cells[0]))
        elif cells:
            self.blocks.append(("tr", " | ".join(cells)))
        self.row = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if self.cell is not None:
            if tag == "table":
                self.nest += 1
            if tag in self.BREAKS or tag in ("tr", "td", "th", "li") or re.fullmatch(r"h[1-6]", tag):
                self.cell.append(" ")
            return
        if tag == "tr":
            self._flush()
            self._end_row()
            self.row = []
        elif tag in ("td", "th"):
            if self.row is None:
                self._flush()
                self.row = []
            self._end_cell()
            self.cell = []
        elif tag == "li" or re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.kind = "li" if tag == "li" else "h"
        elif tag in self.BREAKS:
            self._flush()

    def handle_startendtag(self, tag, attrs):
        if tag in ("br", "hr", "p", "div"):
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if self.cell is not None:
            if tag == "table" and self.nest:
                self.nest -= 1
            elif tag in ("td", "th") and not self.nest:
                self._end_cell()
            elif tag == "tr" and not self.nest:
                self._end_row()
            elif tag in self.BREAKS or tag == "li":
                self.cell.append(" ")
            return
        if tag == "tr":
            self._end_row()
        elif tag == "table":
            self._end_row()
        elif tag == "li" or re.fullmatch(r"h[1-6]", tag) or tag in self.BREAKS:
            self._flush()

    def handle_data(self, data):
        if self.skip:
            return
        (self.cell if self.cell is not None else self.buf).append(data)

    def finish(self) -> list[tuple[str, str]]:
        self._end_row()
        self._flush()
        return self.blocks


def _prose_blocks(html: str) -> list[tuple[str, str]]:
    parser = _ProseParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # HTMLParser is lenient; never let odd markup escape as a new error type.
        raise ValueError(f"unparseable HTML: {exc}") from exc
    return parser.finish()


DOCUMENT_LABELS = {"fiscal_note": "Fiscal Note", "analysis": "Bill Analysis"}
DOCUMENTS_FORMAT = "texas-bill-documents-v1"
WITNESSES_FORMAT = "texas-bill-witnesses-v1"


def document_markdown(html: str, kind: str = "fiscal_note", number: str = "", version_name: str = "") -> str:
    """Convert a fiscal note or bill analysis HTML page to Markdown, one paragraph per block."""
    lines, previous = [], None
    for block, text in _prose_blocks(html):
        if block == "h":
            line = "### " + _escape(text)
        elif block == "li":
            line = "- " + _escape(text)
        elif block == "tr":
            line = " | ".join(_escape(cell, start=True) for cell in text.split(" | "))
        else:
            line = _escape(text, start=True)
        if line == previous:
            continue
        lines.append(line)
        previous = line
    if not lines:
        raise ValueError("no text found in document HTML")
    title = "# " + DOCUMENT_LABELS.get(kind, "Document")
    if number:
        title += f" — {_escape(number)}"
        if version_name:
            title += f" ({_escape(version_name)})"
    return "\n\n".join([title, *lines]) + "\n"


def _document_url_path(kind: str, url: str) -> str | None:
    """Path part of a TLC 90R analysis / fiscal-note HTML FTP URL (as parse_documents validates), else None."""
    prefix = DOCUMENT_PATHS.get(kind)
    if not prefix:
        return None
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme.lower() != "ftp" or host != HOST or not parts.path.lower().startswith(prefix):
        return None
    if not TEXT_FILE_RE.match(PurePosixPath(parts.path).name):
        return None
    return parts.path


def _mdtm(conn, path: str) -> str | None:
    try:
        return str(conn.sendcmd(f"MDTM {path}")).split()[-1]
    except Exception:
        return None


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_if_changed(path: Path, payload: dict) -> bool:
    """Write canonical JSON atomically; True only when the file was created or its content changed."""
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, data)
    return True


def sync_documents(conn, histories: dict, out_dir: Path, max_docs: int) -> dict:
    """Write out_dir/<BILL>/<type>-<code>.md and documents.json for fiscal notes and analyses."""
    counts = {"bills": 0, "documents": 0, "downloaded": 0, "unchanged": 0, "deferred": 0, "failed": 0, "written": 0}
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    for bill_id, info in histories.items():
        documents = (info or {}).get("documents") or []
        if not documents or not BILL_DIR_RE.match(str(bill_id)):
            continue
        counts["bills"] += 1
        bill_dir = out_dir / bill_id
        index_path = bill_dir / "documents.json"
        previous = {(d.get("type"), d.get("code")): d for d in _load_json(index_path).get("documents", [])
                    if isinstance(d, dict)}
        number = re.sub(r"(?<=\D)(?=\d)", " ", bill_id, count=1)
        entries = []
        for document in documents:
            counts["documents"] += 1
            try:
                kind, code = str(document.get("type", "")), str(document.get("code", ""))
                name = str(document.get("name", code))
                path = _document_url_path(kind, str(document.get("html", "")))
                if kind not in DOCUMENT_PATHS or not CODE_RE.match(code) or not path:
                    counts["failed"] += 1
                    continue
                filename = f"{kind}-{code}.md"
                md_path = bill_dir / filename
                old = previous.get((kind, code))
                exists = md_path.is_file()
                current = _mdtm(conn, path)
                if exists and old is not None and (not current or old.get("ftp_modified") == current):
                    counts["unchanged"] += 1
                    entries.append(old)
                    continue
                if counts["downloaded"] >= max_docs:
                    counts["deferred"] += 1
                    if exists and old is not None:
                        entries.append(old)
                    continue
                counts["downloaded"] += 1
                try:
                    html = _decode_html(ftp_bytes(conn, path))
                    data = document_markdown(html, kind, number, name).encode("utf-8")
                    bill_dir.mkdir(parents=True, exist_ok=True)
                    _atomic_write(md_path, data)
                except Exception as exc:
                    counts["failed"] += 1
                    print(f"document {bill_id}/{filename}: {exc}", file=sys.stderr)
                    if exists and old is not None:
                        entries.append(old)
                    continue
                entries.append({"type": kind, "code": code, "name": name, "path": filename,
                                "sha256": hashlib.sha256(data).hexdigest(), "ftp_modified": current or "",
                                "fetched_at": now})
            except Exception as exc:
                counts["failed"] += 1
                print(f"document {bill_id}: {exc}", file=sys.stderr)
        if entries:
            try:
                if _write_if_changed(index_path, {"format": DOCUMENTS_FORMAT, "bill": bill_id, "documents": entries}):
                    counts["written"] += 1
            except OSError as exc:
                counts["failed"] += 1
                print(f"document {bill_id}/documents.json: {exc}", file=sys.stderr)
    return counts


WITNESS_ROOT = "/bills/90R/witlistbill/html/"
WITNESS_HEARING_CODES = {"H": {"H215", "H216", "H240"}, "S": {"S260", "S270", "S290"}}


def witness_list_path(bill_id: str, chamber: str) -> str:
    """FTP path of a bill's witness-list HTML for chamber 'H' or 'S'; mirrors review_pipeline.download_document."""
    match = re.fullmatch(r"(HB|SB|HJR|SJR|HCR|SCR|HR|SR)([1-9]\d{0,4})", bill_id)
    if not match or chamber not in ("H", "S"):
        raise ValueError("Invalid bill ID or chamber")
    family, number = match[1], int(match[2])
    stem = {"HJR": "HJ", "SJR": "SJ", "HCR": "HC", "SCR": "SC"}.get(family, family)
    directory = ("house" if family.startswith("H") else "senate") + "_" + {
        "HB": "bills", "SB": "bills", "HJR": "joint_resolutions", "SJR": "joint_resolutions",
        "HCR": "concurrent_resolutions", "SCR": "concurrent_resolutions", "HR": "resolutions", "SR": "resolutions"}[family]
    start = max(1, number // 100 * 100)
    end = number // 100 * 100 + 99
    return f"{WITNESS_ROOT}{directory}/{stem}{start:05d}_{stem}{end:05d}/{stem}{number:05d}{chamber}.htm"


_WIT_DATE = re.compile(r"^[A-Z][a-z]+\.? \d{1,2}, \d{4}\b")
_WIT_BILL = re.compile(r"^[HS](?:B|JR|CR|R) \d+$")
_WIT_POSITION = re.compile(r"^(For|Against|On)\s*:$", re.I)
_WIT_ENTRY = re.compile(r"^(.*?)\s*\((.*)\)\s*$", re.S)


def parse_witness_list(html: str) -> dict:
    """Parse a TLC witness-list page into {committee, hearing, hearings, witnesses[]}.

    Lists can hold several hearings (a date line starts each) and repeat their header on page breaks.
    """
    committee, current, hearings = "", "", []
    position, testified, committee_next, pending = None, True, False, ""
    witnesses = []
    for _, raw in _prose_blocks(html):
        line = raw
        if pending:
            line, pending = f"{pending} {line}", ""
        elif re.fullmatch(r"WITNESS LIST", line, re.I) or re.fullmatch(r"\d+", line) or _WIT_BILL.match(line):
            continue
        elif re.search(r"\b(?:HOUSE|SENATE) COMMITTEE REPORT\b", line, re.I):
            committee_next = True
            continue
        elif committee_next:
            committee, committee_next = committee or re.sub(r"\s+Committee$", "", line, flags=re.I), False
            continue
        elif _WIT_DATE.match(line):
            if line != current:
                current, position, testified = line, None, True
                if line not in hearings:
                    hearings.append(line)
            continue
        elif line.lower().startswith("registering, but not testifying"):
            testified, position = False, None
            continue
        else:
            heading = _WIT_POSITION.match(line)
            if heading:
                position = heading.group(1).lower()
                continue
        if position is None:
            continue
        if line.count("(") > line.count(")"):
            pending = line
            continue
        entry = _WIT_ENTRY.match(line)
        name, organization = (entry.group(1), entry.group(2)) if entry else (line, "")
        witnesses.append({"name": " ".join(name.split()), "organization": " ".join(organization.split()),
                          "position": position, "testified": testified, "hearing": current})
    if pending and position:
        witnesses.append({"name": " ".join(pending.split()), "organization": "", "position": position,
                          "testified": testified, "hearing": current})
    if not witnesses and not committee:
        raise ValueError("no witness list found in HTML")
    return {"committee": committee, "hearing": hearings[0] if hearings else "", "hearings": hearings,
            "witnesses": witnesses}


def sync_witnesses(conn, histories: dict, out_dir: Path, max_lists: int) -> dict:
    """Write out_dir/<BILL>/witnesses-<H|S>.json for bills whose events show committee hearings."""
    counts = {"bills": 0, "lists": 0, "downloaded": 0, "unchanged": 0, "missing": 0, "deferred": 0,
              "failed": 0, "written": 0}
    for bill_id, info in histories.items():
        if not BILL_DIR_RE.match(str(bill_id)):
            continue
        codes = {str(e.get("code", "")) for e in (info or {}).get("events") or [] if isinstance(e, dict)}
        chambers = [c for c in ("H", "S") if codes & WITNESS_HEARING_CODES[c]]
        if not chambers:
            continue
        counts["bills"] += 1
        for chamber in chambers:
            counts["lists"] += 1
            try:
                path = witness_list_path(bill_id, chamber)
                target = out_dir / bill_id / f"witnesses-{chamber}.json"
                old = _load_json(target)
                try:
                    current = str(conn.sendcmd(f"MDTM {path}")).split()[-1]
                except ftplib.error_perm as exc:
                    if str(exc).startswith("550"):
                        counts["missing"] += 1
                        continue
                    current = None
                except Exception:
                    current = None
                if old and (not current or old.get("ftp_modified") == current):
                    counts["unchanged"] += 1
                    continue
                if counts["downloaded"] >= max_lists:
                    counts["deferred"] += 1
                    continue
                counts["downloaded"] += 1
                try:
                    parsed = parse_witness_list(_decode_html(ftp_bytes(conn, path)))
                except ftplib.error_perm as exc:
                    if str(exc).startswith("550"):
                        counts["missing"] += 1
                        continue
                    raise
                payload = {"format": WITNESSES_FORMAT, "bill": bill_id, "chamber": chamber,
                           "source": "ftp://" + HOST + path, "ftp_modified": current or "", **parsed}
                if _write_if_changed(target, payload):
                    counts["written"] += 1
            except Exception as exc:
                counts["failed"] += 1
                print(f"witnesses {bill_id}/{chamber}: {exc}", file=sys.stderr)
    return counts


HEARTBEAT = dt.timedelta(hours=6)
# More failed transfers than this share: publish what was read, but keep the previous generated_at so a refresh
# that keeps failing shows as stale on the site, and report it as a failure (exit 1 via --failures-file).
INCOMPLETE_SHARE = 0.10


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


def synchronize(conn: ftplib.FTP, prior: dict, max_files: int = 25000, histories: dict | None = None) -> tuple[dict, dict]:
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
        # Newest filing first, then by bill number as a number (HB 99 before HB 100), not as text.
        'bills': sorted(sorted(merged.values(), key=lambda b: bill_order(b['id'])), key=lambda b: b.get('filed_at') or '', reverse=True),
    }
    popped = pop_history(list(parsed.values()))
    if histories is not None:
        histories.update(popped)
    for bill in merged.values():
        bill.pop('events', None)
        bill.pop('documents', None)
    snapshot['generated_at'] = choose_generated_at(prior, snapshot, dt.datetime.now(dt.timezone.utc))
    incomplete = len(errors) > INCOMPLETE_SHARE * len(paths)
    if incomplete and prior.get('generated_at'):
        snapshot['generated_at'] = prior['generated_at']
    return snapshot, {'listed':len(paths),'parsed':len(parsed),'combined':len(merged),'transfer_errors':len(errors),
                      'incomplete':incomplete}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=OUT)
    parser.add_argument('--max-files',type=int,default=25000)
    parser.add_argument('--text-dir',type=Path,default=None)
    parser.add_argument('--max-texts',type=int,default=400)
    parser.add_argument('--history-dir',type=Path,default=None)
    parser.add_argument('--documents-dir',type=Path,default=None)
    parser.add_argument('--max-docs',type=int,default=200)
    parser.add_argument('--failures-file',type=Path,default=None,
                        help='Write the secondary stages that failed here, one per line (the unit fails on a non-empty file '
                             'after building feeds); the snapshot itself is still written')
    args=parser.parse_args()
    failures=[]
    prior=json.loads(args.out.read_text(encoding='utf-8')) if args.out.exists() else {'bills':[]}
    with ftplib.FTP(HOST,timeout=55) as conn:
        conn.login('anonymous','legislative-research@example.invalid')
        histories={}
        snapshot,stats=synchronize(conn,prior,args.max_files,histories)
    temp=args.out.with_suffix('.json.tmp')
    temp.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temp,args.out)
    print(json.dumps(stats,indent=2))
    if stats.get('incomplete'):
        failures.append(f"incomplete read: {stats['transfer_errors']} of {stats['listed']} transfers failed")
    try:
        history_counts=sync_history(histories,args.history_dir or args.out.parent/'history')
        print(json.dumps({'history':history_counts},indent=2))
    except Exception as exc:  # History files are secondary; never fail a written snapshot.
        print(f"HISTORY SYNC FAILED, snapshot unaffected: {exc}",file=sys.stderr)
        failures.append(f"history: {exc}")
    try:
        with ftplib.FTP(HOST,timeout=55) as conn:
            conn.login('anonymous','legislative-research@example.invalid')
            text_counts=sync_texts(conn,snapshot['bills'],args.text_dir or args.out.parent/'text',args.max_texts)
        print(json.dumps({'texts':text_counts},indent=2))
    except Exception as exc:  # Text files are secondary; never fail a written snapshot.
        print(f"TEXT SYNC FAILED, snapshot unaffected: {exc}",file=sys.stderr)
        failures.append(f"texts: {exc}")
    try:
        documents_dir=args.documents_dir or args.out.parent/'history'
        with ftplib.FTP(HOST,timeout=55) as conn:
            conn.login('anonymous','legislative-research@example.invalid')
            document_counts=sync_documents(conn,histories,documents_dir,args.max_docs)
            print(json.dumps({'documents':document_counts},indent=2))
            witness_counts=sync_witnesses(conn,histories,documents_dir,args.max_docs)
            print(json.dumps({'witnesses':witness_counts},indent=2))
    except Exception as exc:  # Documents and witness lists are secondary; never fail a written snapshot.
        print(f"DOCUMENT SYNC FAILED, snapshot unaffected: {exc}",file=sys.stderr)
        failures.append(f"documents: {exc}")
    if args.failures_file is not None:
        args.failures_file.write_text(''.join(f"{line}\n" for line in failures),encoding='utf-8')
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except (*ftplib.all_errors, RuntimeError, OSError, ValueError) as exc:
        print(f"SYNC FAILED, previous snapshot preserved: {exc}",file=sys.stderr)
        sys.exit(1)
