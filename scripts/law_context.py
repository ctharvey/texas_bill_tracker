"""Current Texas law a bill changes, as review context (follow-a-law phase 0b).

Built from this site's copy of the law (live/law, written by sync_law.py) and the bill's own text, never from the web.
Each item carries an L_ id the model cites as span_id; classify_bill.validate_result accepts a quote only if it
appears verbatim in the item's text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import build_feeds

FORMAT = "texas-bill-law-context-v1"
SECTION_TEXT_MAX = 2000   # Characters of one section's current text.
BILL_TEXT_MAX = 20000     # Characters of section text per bill; headings are always kept, text is trimmed first.
HEADINGS_MAX = 60         # Section headings listed under one repealed chapter.
OFFICIAL_CHAPTER = "https://statutes.capitol.texas.gov/Docs/{code}/htm/{code}.{chapter}.htm"
_SECTION_SPLIT = re.compile(r"(?m)^## ")


class LawCopy:
    """Read-only view of live/law; each code's index and chapter file is read at most once. keep_texts=False reads
    chapter files again on each call (a long-running reader, scripts/law_on_demand.py, keeps memory bounded)."""

    def __init__(self, law_dir: Path, keep_texts: bool = True):
        self.law_dir, self.keep_texts = law_dir, keep_texts
        self.top = json.loads((law_dir / "index.json").read_text("utf-8"))
        self._codes: dict[str, dict] = {}
        self._texts: dict[str, dict[str, str]] = {}

    def code(self, code: str) -> dict | None:
        if code not in self._codes:
            entry = (self.top.get("codes") or {}).get(code)
            path = self.law_dir / code / "index.json"
            self._codes[code] = (json.loads(path.read_text("utf-8"))
                                 if isinstance(entry, dict) and path.is_file() else {"chapters": {}})
        return self._codes[code]

    def chapter(self, code: str, number: str) -> tuple[str, dict] | None:
        """(chapter id as stored, its index entry); chapter ids are matched without case ("30A" and "30a")."""
        chapters = self.code(code)["chapters"]
        for key in (number, number.lower(), number.upper()):
            entry = chapters.get(key)
            if isinstance(entry, dict) and entry.get("file") == f"{code}/{key}.md":
                return key, entry
        return None

    @staticmethod
    def section_id(entry: dict, section: str) -> str | None:
        """The section id as a chapter entry stores it, matched without case (keys are upper case, the copy has CR
        "42.04a"); None when the chapter has no such section."""
        want = section.upper()
        return next((s[0] for s in entry.get("sections", []) if isinstance(s, (list, tuple)) and s
                     and str(s[0]).upper() == want), None)

    def section_chapter(self, code: str, section: str) -> tuple[str, dict] | None:
        """(chapter id as stored, its index entry) for a section, matched without case; section_id gives its stored id."""
        guess = section.split(".")[0]
        found = self.chapter(code, guess)
        if found and self.section_id(found[1], section):
            return found
        for key, entry in self.code(code)["chapters"].items():
            if self.section_id(entry, section) and entry.get("file") == f"{code}/{key}.md":
                return key, entry
        return None

    def section_texts(self, code: str, chapter: str) -> dict[str, str]:
        """{section id: '## Sec. ...' block without the leading '## '} for one chapter file."""
        name = f"{code}/{chapter}.md"
        if name not in self._texts:
            blocks = _SECTION_SPLIT.split((self.law_dir / name).read_text("utf-8"))[1:]
            ids = [s[0] for s in self.code(code)["chapters"][chapter].get("sections", [])]
            texts = {sid: block.strip() for sid, block in zip(ids, blocks)}
            if not self.keep_texts:
                return texts
            self._texts[name] = texts
        return self._texts[name]


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = text.rfind(" ", 0, limit)
    return text[:cut if cut > limit // 2 else limit], True


def build(markdown: str, law_dir: Path) -> list[dict]:
    """The law items for one bill text: a heading item for every chapter it repeals, amends, adds to or names (with
    the section headings of a repealed chapter), then the current text of each section it amends or repeals, and of
    the sections of each repealed chapter, while the text budget lasts."""
    law = LawCopy(law_dir)
    names = (law.top.get("codes") or {})
    sections, _ = build_feeds.bill_statutes(markdown)
    chapters = build_feeds.bill_chapters(markdown)
    wanted_sections = [(key, entry["kind"]) for key, entry in sections.items() if entry["kind"] in ("amend", "repeal")]
    for key, _ in wanted_sections:  # The chapter of every changed section gets its heading too.
        code, number = key.split(" ")
        found = law.section_chapter(code, number)
        if found and f"{code} {found[0].upper()}" not in chapters:
            chapters[f"{code} {found[0].upper()}"] = "contains_changed_section"
    rank = dict(build_feeds.CHAPTER_RANK, contains_changed_section=0)
    headings, texts = [], []
    for key, action in sorted(chapters.items(), key=lambda kv: (-rank[kv[1]], kv[0])):
        code, number = key.split(" ")
        found = law.chapter(code, number)
        if not found:
            continue  # A new chapter, or one not in current law.
        chapter, entry = found
        name = (names.get(code) or {}).get("name") or build_feeds.CODE_NAME.get(code, code)
        text = entry.get("heading") or f"CHAPTER {chapter}"
        if action == "repeal":
            listed = [s[1] for s in entry.get("sections", [])]
            text += "\n" + "\n".join(listed[:HEADINGS_MAX])
            if len(listed) > HEADINGS_MAX:
                text += f"\n({len(listed) - HEADINGS_MAX} more sections)"
            texts += [(f"{code} {sid}", "repeal_with_chapter", chapter) for sid, _ in entry.get("sections", [])]
        headings.append({"kind": "chapter", "code": code, "chapter": chapter, "action": action,
                         "section": f"{name}, Chapter {chapter.upper()}", "text": text,
                         "source_url": OFFICIAL_CHAPTER.format(code=code, chapter=chapter),
                         "law_sha256": entry.get("sha256")})
    explicit = [(key, kind, None) for key, kind in wanted_sections]
    items, used, seen = list(headings), 0, set()
    for key, action, chapter in explicit + texts:
        if key in seen:
            continue
        seen.add(key)
        code, number = key.split(" ")
        found = law.chapter(code, chapter) if chapter else law.section_chapter(code, number)
        if not found:
            continue
        current = law.section_texts(code, found[0]).get(LawCopy.section_id(found[1], number) or number)
        if not current:
            continue
        text, trimmed = _clip(current, SECTION_TEXT_MAX)
        if used + len(text) > BILL_TEXT_MAX:
            continue
        used += len(text)
        name = (names.get(code) or {}).get("name") or build_feeds.CODE_NAME.get(code, code)
        items.append({"kind": "section", "code": code, "chapter": found[0], "action": action,
                      "section": f"{name} Section {number}", "text": text, "trimmed": trimmed,
                      "source_url": OFFICIAL_CHAPTER.format(code=code, chapter=found[0]),
                      "law_sha256": found[1].get("sha256")})
    for index, item in enumerate(items, 1):
        item["id"] = f"L_{index}"
    return items


def request_items(items: list[dict]) -> list[dict]:
    """What the model sees of each item (no hashes or URLs)."""
    return [{k: item[k] for k in ("id", "section", "action", "text")} for item in items]
