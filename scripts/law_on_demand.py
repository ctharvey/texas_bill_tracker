"""Law section and chapter pages rendered on request, for the parts of Texas law no bill touches yet.

The data run writes a static page (live/share/law/<CODE>/<key>.html) only for sections and chapters a bill changes.
The gateway sends every other /law/<CODE>/<key> address here (scripts/sync_service.py). The page is built by the same
build_feeds.law_page / law_chapter_page inside the current site shell, so the app takes it over the same way, but it
is marked noindex: these pages are for following a law until a bill changes it, not for search. A key that is not in
our law copy gets a real 404.
"""
from __future__ import annotations

from html import escape
import json
from pathlib import Path
import re
import threading

import build_feeds
import pages
from law_context import LawCopy

ROBOTS = "noindex, follow"
PATH = re.compile(r"/law/([A-Za-z]{2})/([0-9]+[A-Za-z]?(?:\.[0-9]+[A-Za-z]?)*)/?")
# The Constitution (#20): /law/CN/<article>/<section> ("/law/CN/8/1-b"), or the key's own form "/law/CN/8.1-b".
CN_PATH = re.compile(r"/law/([Cc][Nn])/(" + build_feeds.CN_ARTICLE + r")[./](" + build_feeds.CN_SECTION + r")/?")
KEY_MAX = 16  # The app's longest section key (src/prefs.js).
HTML = "text/html; charset=utf-8"
PAGE_HEADERS = {"Content-Type": HTML, "Cache-Control": "no-cache", "X-Robots-Tag": ROBOTS}


class Unavailable(Exception):
    """The law copy or the site shell cannot be read; the caller answers 503."""


def is_law_path(path: str) -> bool:
    return path.startswith("/law/")


class _Cached:
    """A value loaded from a file, reloaded when the file's modification time changes."""

    def __init__(self, path: Path, load):
        self.path, self.load, self.mtime, self.value, self.lock = path, load, None, None, threading.Lock()

    def get(self):
        with self.lock:
            try:
                mtime = self.path.stat().st_mtime
            except OSError:
                return self.value
            if mtime != self.mtime:
                try:
                    self.value, self.mtime = self.load(self.path), mtime
                except (OSError, ValueError):
                    pass  # Keep the last good value.
            return self.value


def _load_statutes(path: Path) -> tuple[dict, dict]:
    index = json.loads(path.read_text("utf-8"))
    if not isinstance(index, dict):
        raise ValueError("statute index is not an object")
    return index.get("sections") if isinstance(index.get("sections"), dict) else {}, build_feeds.chapter_groups(index)


def not_found_page(site: str = build_feeds.SITE) -> str:
    a = lambda value: escape(value, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Not in our copy of Texas law · Texas Bill Atlas</title>
</head>
<body>
<h1>Not in our copy of Texas law</h1>
<p>No section or chapter has this address in Texas Bill Atlas's copy of the Texas statutes. Section addresses look like
<a href="{a(site)}law/PE/46.06">/law/PE/46.06</a> and chapter addresses like <a href="{a(site)}law/PE/46">/law/PE/46</a>.
The Texas Constitution's sections are numbered within each article: <a href="{a(site)}law/CN/8/1-b">/law/CN/8/1-b</a>.</p>
<p><a href="{a(site)}explorer">Search bills and law in Texas Bill Atlas</a></p>
</body>
</html>
"""


class LawPages:
    def __init__(self, law_dir: Path, statutes: Path | None, shell: Path, site: str = build_feeds.SITE):
        self.site, self.shell_path = site, shell
        # A new LawCopy whenever the copy's top index changes (sync_law.py rewrites it with each refresh). Chapter texts
        # are read per request, never kept: the copy is 171 MB.
        self.law = _Cached(law_dir / "index.json", lambda p: LawCopy(p.parent, keep_texts=False))
        self.statutes = _Cached(statutes, _load_statutes) if statutes else None

    def render(self, path: str) -> tuple[int, dict, bytes]:
        """(status, headers, body) for a /law/... path: 200 page, 301 to the canonical form, or 404."""
        cn = CN_PATH.fullmatch(path)
        match = cn or PATH.fullmatch(path)
        if cn:  # The Constitution's sections keep their case until the copy names the stored one.
            code, key = "CN", f"{cn[2]}.{cn[3]}"
        else:
            code, key = (match[1].upper(), match[2].upper()) if match else ("", "")
        if not match or code not in build_feeds.LAW_NAME or len(key) > KEY_MAX:
            return self.not_found()
        law, shell = self.law.get(), pages.load_shell(self.shell_path)
        if law is None or shell is None:
            raise Unavailable("law copy or site shell unavailable")
        sections, groups = (self.statutes.get() if self.statutes else None) or ({}, {})
        try:
            # LawCopy fills its code index cache lazily; two threads loading one code at once only repeat a read.
            found = (self.section(law, shell, sections, code, key) if "." in key
                     else self.chapter(law, shell, groups, code, key))
        except (OSError, ValueError, KeyError) as error:
            raise Unavailable(str(error)) from None
        if found is None:
            return self.not_found()
        page, key = found
        canonical = "/" + build_feeds.law_path(code, key)
        if path != canonical:
            return 301, {"Location": canonical, "Content-Type": HTML, "Cache-Control": "no-cache"}, b""
        return 200, dict(PAGE_HEADERS), page.encode("utf-8")

    def section(self, law: LawCopy, shell: str, sections: dict, code: str, number: str) -> tuple[str, str] | None:
        """(page, the key's canonical number) or None. Keys are upper case; a Constitution key takes the copy's case
        ("CN 1.3a"), so another spelling redirects to it."""
        found = law.section_chapter(code, number)
        if not found:
            return None
        chapter, entry = found
        stored = law.section_id(entry, law.local_section(code, number))  # "42.04a" in the copy for the key "42.04A"
        if code == "CN":
            number = f"{chapter}.{stored}"
        heading = next((s[1] for s in entry.get("sections", []) if s[0] == stored), "")
        current = (heading, law.section_texts(code, chapter).get(stored) or "", f"live/law/{code}/{chapter}.md")
        index_entry = sections.get(f"{code} {number}")
        own_chapter = number.split(".")[0]
        # The chapter's page always exists now (static or on request), so the section always links it.
        chapters = {f"{code} {own_chapter}"} if law.chapter(code, own_chapter) else set()
        return build_feeds.law_page(f"{code} {number}", index_entry if isinstance(index_entry, dict) else {},
                                    build_feeds.LAW_NAME[code], current, self.site, shell, chapters,
                                    robots=ROBOTS), number

    def chapter(self, law: LawCopy, shell: str, groups: dict, code: str, number: str) -> tuple[str, str] | None:
        found = law.chapter(code, number)
        if not found:
            return None
        _stored, entry = found
        g = groups.get(f"{code} {number}") or {"h": "", "whole": [], "since": {}, "sections": {}}
        heading = g["h"] or build_feeds.chapter_title(entry.get("heading") or "")
        return build_feeds.law_chapter_page(f"{code} {number}", g, heading, self.site, shell, robots=ROBOTS,
                                            all_sections=entry.get("sections") or []), number

    def not_found(self) -> tuple[int, dict, bytes]:
        return 404, {"Content-Type": HTML, "Cache-Control": "no-cache", "X-Robots-Tag": "noindex"}, \
            not_found_page(self.site).encode("utf-8")
