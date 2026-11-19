"""Copy current Texas law (the Constitution and every code) into live/law/ as Markdown, one file per chapter.

Source: the Texas Legislative Council's own per-code downloads, listed in statutes.capitol.texas.gov's
`assets/StatuteCodeDownloads.json` and served from tcss.legis.texas.gov as zipped HTML (about 42 MB for all codes,
2026-11-19). Each chapter becomes `live/law/<CODE>/<chapter>.md`; there is one file per chapter, not per section,
because 123k section files would take over 500 MB in 4 KB blocks while the whole text is about 130 MB.

Indexes: `live/law/index.json` (codes, their source zip's fingerprints, chapter headings) and
`live/law/<CODE>/index.json` (each chapter's file, SHA-256 and section headings). A refresh downloads only codes
whose zip changed (ETag / Last-Modified), rewrites only chapters whose text changed, and deletes chapters that left
the code. No zip or HTML is kept. Standard library only, so the server runs it from the deployer's repository.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

LIST_URL = 'https://statutes.capitol.texas.gov/assets/StatuteCodeDownloads.json'
ZIP_BASE = 'https://tcss.legis.texas.gov/resources'
OFFICIAL_CHAPTER = 'https://statutes.capitol.texas.gov/Docs/{code}/htm/{code}.{chapter}.htm'
UA = {'User-Agent': 'Mozilla/5.0 (compatible; texas-bill-atlas law import; +https://billatlas.org)'}
FORMAT = 'texas-bill-law-v1'
MAX_ZIP_BYTES = 50_000_000         # largest code (SD) was 7.3 MB zipped
MAX_UNZIPPED_BYTES = 200_000_000   # largest code unzips to about 40 MB; guards against a zip bomb
MIN_CODES = 20                     # 31 listed on 2026-11-19; a shorter list is a broken page, not repeals
MIN_KEPT_SHARE = 0.5               # a code that suddenly loses half its chapters is refused, never published

CODE = re.compile(r'^[A-Z][A-Z0-9]$')  # e.g. I1, the uncodified Insurance Code
ZIP_PATH = re.compile(r'^/Zips/([A-Z][A-Z0-9])\.htm\.zip$')
MEMBER = re.compile(r'^([A-Za-z][A-Za-z0-9])\.([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)\.htm$')
PARAGRAPH = re.compile(r'<p\b([^>]*)>(.*?)</p>', re.S | re.I)
# Codes number by "Sec."; the Code of Criminal Procedure and the uncodified statutes (CV, I1) by "Art.".
SECTION_LINK = re.compile(r'<a\b[^>]*font-weight:\s*bold[^>]*>\s*((?:Sec|Art)\.\s.*?)</a>', re.S | re.I)
SECTION_ID = re.compile(r'^(?:Sec|Art)\.\s+([0-9A-Za-z][0-9A-Za-z.\-()]*?)\.(?:\s|$)')  # e.g. Art. 4413(47e-1).
TAG = re.compile(r'<[^>]+>')
SPACE = re.compile(r'[ \t\r\n\xa0]+')


def text_of(fragment: str) -> str:
    return SPACE.sub(' ', html.unescape(TAG.sub('', fragment))).strip()


def convert_chapter(raw: str) -> tuple[str, str, list[list[str]]]:
    """(heading, markdown, sections) for one chapter file. Heading lines (title, subtitle, chapter) are the centered
    bold paragraphs before the first section; each section starts a `## Sec. ...` line. Wording is unchanged apart
    from collapsed whitespace, so an excerpt can be matched against it verbatim."""
    lines, sections, heading = [], [], ''
    for match in PARAGRAPH.finditer(raw):
        attrs, body = match.group(1), match.group(2)
        line = text_of(body)
        if not line:
            continue
        link = SECTION_LINK.search(body)
        if link:
            title = text_of(link.group(1))
            ident = SECTION_ID.match(title)
            if ident:
                sections.append([ident.group(1), title])
            lines.append('## ' + line)
            continue
        if not sections and 'center' in attrs and re.match(r'(CHAPTER|ARTICLE|SUBCHAPTER)\b', line):
            heading = heading or line
        lines.append(line)
    return heading, '\n\n'.join(lines) + '\n', sections


def chapter_markdown(code: str, name: str, chapter: str, heading: str, body: str) -> str:
    return (f'# {name}, {heading or "Chapter " + chapter}\n\n'
            f'Official text: {OFFICIAL_CHAPTER.format(code=code, chapter=chapter)}\n\n'
            'Copied unchanged in wording from the Texas Legislative Council\'s statute files; the official site is the '
            'authority.\n\n' + body)


def read_code(code: str, name: str, data: bytes, skipped: list | None = None) -> dict[str, dict]:
    """chapter id -> {heading, markdown, sections}. Files not named like a chapter are skipped (listed in
    `skipped`); raises ValueError for a zip that is not this code's chapters."""
    chapters = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if sum(m.file_size for m in members) > MAX_UNZIPPED_BYTES:
            raise ValueError(f'{code}: unzipped size over the limit')
        for member in members:
            match = MEMBER.match(member.filename)
            if member.is_dir() or match is None:
                # The official zips carry stray working copies ('cr.17 - Copy.htm', 'ed.51-old.htm', 2026-11-19):
                # never published, only listed.
                if skipped is not None:
                    skipped.append(member.filename[:120])
                continue
            if match.group(1).upper() != code:
                raise ValueError(f'{code}: file from another code: {member.filename!r}')
            chapter = match.group(2).lower()
            if chapter in chapters:
                raise ValueError(f'{code}: chapter {chapter} twice')
            raw = archive.read(member).decode('utf-8-sig', 'replace')
            heading, body, sections = convert_chapter(raw)
            chapters[chapter] = {'heading': heading, 'markdown': chapter_markdown(code, name, chapter, heading, body),
                                 'sections': sections}
    if not chapters:
        raise ValueError(f'{code}: empty zip')
    return chapters


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def atomic_json(path: Path, value) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def publish_code(out: Path, code: str, name: str, chapters: dict[str, dict], previous: dict | None) -> dict:
    """Write changed chapter files and the code index; delete chapters no longer in the code. Returns counts."""
    folder = out / code
    before = (previous or {}).get('chapters', {})
    if before and len(chapters) < MIN_KEPT_SHARE * len(before):
        raise ValueError(f'{code}: {len(chapters)} chapters, was {len(before)}; refused')
    entries, written = {}, 0
    for chapter, item in sorted(chapters.items()):
        data = item['markdown'].encode('utf-8')
        digest = sha256(data)
        path = folder / (chapter + '.md')
        if (before.get(chapter) or {}).get('sha256') != digest or not path.exists():
            atomic_write(path, data)
            written += 1
        entries[chapter] = {'heading': item['heading'], 'file': f'{code}/{chapter}.md', 'sha256': digest,
                            'bytes': len(data), 'sections': item['sections']}
    removed = 0
    for chapter in set(before) - set(entries):
        try:
            (folder / (chapter + '.md')).unlink()
            removed += 1
        except FileNotFoundError:
            pass
    index = {'format': FORMAT, 'code': code, 'name': name, 'chapters': entries}
    atomic_json(folder / 'index.json', index)
    return {'chapters': len(entries), 'written': written, 'removed': removed,
            'sections': sum(len(e['sections']) for e in entries.values())}


class Source:
    """The official list and zips. `opener` is injectable for tests."""

    def __init__(self, opener=None, delay: float = 0.5):
        self.open = opener or urllib.request.urlopen
        self.delay, self.last = delay, 0.0

    def _get(self, url: str, headers: dict | None = None, limit: int = MAX_ZIP_BYTES):
        wait = self.last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(url, headers={**UA, **(headers or {})})
        try:
            with self.open(request, timeout=120) as response:
                body = response.read(limit + 1)
                meta = {'etag': response.headers.get('ETag'), 'last_modified': response.headers.get('Last-Modified')}
        except urllib.error.HTTPError as error:
            if error.code == 304:
                return None, {}
            raise
        finally:
            self.last = time.monotonic()
        if len(body) > limit:
            raise ValueError(f'{url}: over {limit} bytes')
        return body, meta

    def codes(self) -> list[dict]:
        body, _ = self._get(LIST_URL, limit=1_000_000)
        out = []
        for item in json.loads(body.decode('utf-8-sig'))['StatuteCode']:
            code, path = item.get('code'), item.get('Html') or ''
            match = ZIP_PATH.match(path)
            if not (isinstance(code, str) and CODE.match(code) and match and match.group(1) == code):
                raise ValueError(f'Unexpected entry in the code list: {str(item)[:120]}')
            out.append({'code': code, 'name': str(item.get('CodeName') or code).strip(), 'url': ZIP_BASE + path})
        if len(out) < MIN_CODES:
            raise ValueError(f'Code list has only {len(out)} codes')
        return out

    def zip(self, url: str, previous: dict | None):
        headers = {}
        if previous and previous.get('url') == url:
            if previous.get('etag'):
                headers['If-None-Match'] = previous['etag']
            if previous.get('last_modified'):
                headers['If-Modified-Since'] = previous['last_modified']
        return self._get(url, headers)


def load_json(path: Path):
    try:
        return json.loads(path.read_text('utf-8'))
    except (OSError, ValueError):
        return None


# Heading search: live/law/search/<prefix>.json = [[key, heading]], one file per 3-letter word prefix, for every section
# and chapter of the tracked codes (the 27 in build_feeds.CODE_ABBR; a test keeps the two lists equal), plus
# search/index.json = {format, generated_at, prefixes: {prefix: count}}. Built from the published code indexes.
SEARCH_FORMAT = 'texas-bill-law-search-v1'
SEARCH_CODES = ('AG', 'AL', 'BC', 'BO', 'CP', 'CR', 'ED', 'EL', 'ES', 'FA', 'FI', 'GV', 'HS', 'HR', 'IN', 'LA', 'LG', 'NR',
                'OC', 'PW', 'PE', 'PR', 'SD', 'TX', 'TN', 'UT', 'WA')
SEARCH_STOP = frozenset('of and the for to in by or a an on with under from as at certain other'.split())
SEARCH_WORD = re.compile(r'[a-z0-9]+')
SEARCH_FILE = re.compile(r'^[a-z0-9]{3}\.json$')
CHAPTER_PREFIX = re.compile(r'^(?:CHAPTER|ARTICLE|SUBCHAPTER)\s+[0-9A-Za-z.\-]+?\.\s+', re.I)
SECTION_PREFIX = re.compile(r'^(?:Sec|Art)\.\s+[0-9A-Za-z][0-9A-Za-z.\-()]*?\.(?:\s+|$)')


def search_prefixes(heading: str) -> set[str]:
    return {w[:3] for w in SEARCH_WORD.findall(heading.lower()) if len(w) >= 3 and w not in SEARCH_STOP}


def search_entries(out: Path) -> list[list[str]]:
    """[key, heading] for every section and chapter in the tracked codes' published indexes."""
    entries = []
    for code in SEARCH_CODES:
        index = load_json(out / code / 'index.json')
        if not isinstance(index, dict) or not isinstance(index.get('chapters'), dict):
            continue
        for chapter, item in index['chapters'].items():
            if not isinstance(item, dict):
                continue
            title = CHAPTER_PREFIX.sub('', str(item.get('heading') or '').strip()).strip().rstrip('.').strip()
            if title:
                entries.append([f'{code} {chapter.upper()}', title])
            for section in item.get('sections') or []:
                if isinstance(section, list) and len(section) == 2 and isinstance(section[0], str):
                    name = SECTION_PREFIX.sub('', str(section[1]).strip()).strip().rstrip('.').strip()
                    if name:
                        entries.append([f'{code} {section[0].upper()}', name])
    return entries


def write_search(out: Path, now: dt.datetime | None = None) -> dict:
    """Rebuild out/search from the code indexes: a shard is written only when its bytes change, shards whose prefix
    vanished are removed, and an empty build (no code index readable) changes nothing."""
    entries = search_entries(out)
    if not entries:
        return {'entries': 0, 'shards': 0, 'written': 0, 'removed': 0}
    shards: dict[str, list[list[str]]] = {}
    for entry in sorted(entries):
        for prefix in search_prefixes(entry[1]):
            shards.setdefault(prefix, []).append(entry)
    folder = out / 'search'
    written = removed = 0
    for prefix, items in shards.items():
        data = (json.dumps(items, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
        path = folder / f'{prefix}.json'
        try:
            same = path.read_bytes() == data
        except OSError:
            same = False
        if not same:
            atomic_write(path, data)
            written += 1
    if folder.is_dir():
        for path in folder.iterdir():
            if SEARCH_FILE.match(path.name) and path.stem not in shards:
                path.unlink(missing_ok=True)
                removed += 1
    prefixes = {prefix: len(items) for prefix, items in sorted(shards.items())}
    previous = load_json(folder / 'index.json')
    if written or removed or not isinstance(previous, dict) or previous.get('prefixes') != prefixes:
        now = now or dt.datetime.now(dt.timezone.utc)
        atomic_json(folder / 'index.json', {'format': SEARCH_FORMAT, 'generated_at': now.isoformat(), 'prefixes': prefixes})
    return {'entries': len(entries), 'shards': len(shards), 'written': written, 'removed': removed}


def run(out: Path, source: Source, *, force: bool = False, now: dt.datetime | None = None,
        log=print) -> tuple[dict, list[str]]:
    """One refresh. Returns (top index, failures). A failed code keeps its previous files and index entry."""
    now = now or dt.datetime.now(dt.timezone.utc)
    top_path = out / 'index.json'
    top = load_json(top_path)
    if not isinstance(top, dict) or top.get('format') != FORMAT:
        top = {'format': FORMAT, 'codes': {}}
    known = top.get('codes') or {}
    codes, failures, result = source.codes(), [], {}
    for entry in codes:
        code, previous = entry['code'], known.get(entry['code'])
        try:
            data, meta = source.zip(entry['url'], None if force else previous)
            if data is None and previous:  # 304: the zip has not changed
                result[code] = {**previous, 'checked_at': now.isoformat()}
                continue
            if data is None:
                raise ValueError(f'{code}: not modified, but nothing published yet')
            skipped = []
            chapters = read_code(code, entry['name'], data, skipped)
            counts = publish_code(out, code, entry['name'], chapters, load_json(out / code / 'index.json'))
            result[code] = {'name': entry['name'], 'url': entry['url'], 'etag': meta.get('etag'),
                            'last_modified': meta.get('last_modified'), 'zip_sha256': sha256(data),
                            'zip_bytes': len(data), 'checked_at': now.isoformat(), 'copied_at': now.isoformat(),
                            'chapters': counts['chapters'], 'sections': counts['sections'],
                            'index': f'{code}/index.json', 'skipped_files': skipped,
                            'headings': {c: chapters[c]['heading'] for c in sorted(chapters)}}
            log(f'{code}: {counts["chapters"]} chapters, {counts["sections"]} sections, '
                f'{counts["written"]} written, {counts["removed"]} removed')
        except Exception as error:  # noqa: BLE001 - one code's failure keeps its old copy; the run reports it
            failures.append(f'{code}: {type(error).__name__}: {str(error)[:160]}')
            log('FAILED', failures[-1])
            if previous:
                result[code] = previous
    # A code that left the official list keeps its files until an operator removes it: never delete on a bad list.
    for code, previous in known.items():
        result.setdefault(code, {**previous, 'listed': False})
    top = {'format': FORMAT, 'generated_at': now.isoformat(), 'source': LIST_URL, 'codes': result,
           'failures': failures}
    atomic_json(top_path, top)
    try:
        counts = write_search(out, now)
        log(f'Search: {counts["entries"]} entries, {counts["shards"]} shards, {counts["written"]} written, '
            f'{counts["removed"]} removed')
    except Exception as error:  # noqa: BLE001 - the copy is published; the shards are rebuilt by the next run
        failures.append(f'search: {type(error).__name__}: {str(error)[:160]}')
        log('FAILED', failures[-1])
        top['failures'] = failures
        atomic_json(top_path, top)
    return top, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, required=True, help='live/law folder')
    parser.add_argument('--force', action='store_true', help='download every code even if unchanged')
    parser.add_argument('--search-only', action='store_true',
                        help='rebuild live/law/search from the published code indexes; download nothing')
    args = parser.parse_args()
    if args.search_only:
        result = write_search(args.out)
        print(f'Law search: {result["entries"]} entries, {result["shards"]} shards, {result["written"]} written, '
              f'{result["removed"]} removed')
        return 0
    top, failures = run(args.out, Source(), force=args.force)
    total = sum(c.get('sections', 0) for c in top['codes'].values())
    print(f'Law copy: {len(top["codes"])} codes, {total} sections, {len(failures)} failures')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
