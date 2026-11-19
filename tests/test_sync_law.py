"""The current-law copy: conversion, guards on the official zips, and refreshes that touch only what changed."""
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import sync_law  # noqa: E402

NOW = dt.datetime(2026, 11, 19, tzinfo=dt.timezone.utc)


def chapter_html(code, number, title, sections, label='Sec.'):
    parts = [f'<p class="center" style="font-weight:bold;">{code.upper()} CODE</p><br />',
             f'<p class="center" style="font-weight:bold;">CHAPTER {number}. {title}</p><br />']
    for ident, heading, text in sections:
        parts.append(f'<p class="left"><a name="{ident}"></a></p><p style="text-indent:7ex;" class="left">'
                     f'<a target="_blank" href="x" style="color:inherit;font-weight:bold;">{label} {ident}.  {heading}.</a>'
                     f'  {text}</p>')
        parts.append('<p style="text-indent:13ex;" class="left">(1)  &quot;Board&quot; means the board.</p>')
    return '﻿<html><body><pre>' + ''.join(parts) + '</pre></body></html>'


def make_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def gv_zip(extra=None, drop=()):
    files = {f'gv.{n}.htm': chapter_html('gv', n, f'CHAPTER TITLE {n}', [(f'{n}.001', 'DEFINITIONS', 'In this chapter:')])
             for n in ('2271', '2274', '2275', '2276') if n not in drop}
    files.update(extra or {})
    return make_zip(files)


class Response(io.BytesIO):
    def __init__(self, data, headers):
        super().__init__(data)
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeServer:
    """The code list and zips, answering 304 when the client's ETag matches."""

    def __init__(self):
        self.zips = {'GV': (gv_zip(), '"v1"')}
        self.listing = None
        self.requests = []

    def entries(self):
        return [{'code': c, 'CodeName': c + ' Code', 'Html': f'/Zips/{c}.htm.zip'} for c in self.zips]

    def __call__(self, request, timeout=0):
        url, headers = request.full_url, {k.lower(): v for k, v in request.header_items()}
        self.requests.append((url, headers))
        if url == sync_law.LIST_URL:
            body = json.dumps({'StatuteCode': self.listing if self.listing is not None else self.entries()})
            return Response(body.encode(), {})
        code = url.rsplit('/', 1)[1].split('.')[0]
        data, etag = self.zips[code]
        if headers.get('if-none-match') == etag:
            raise urllib.error.HTTPError(url, 304, 'Not Modified', {}, None)
        return Response(data, {'ETag': etag, 'Last-Modified': 'Thu, 19 Nov 2026 00:00:00 GMT'})


class ConvertTests(unittest.TestCase):
    def test_sections_headings_and_wording(self):
        heading, body, sections = sync_law.convert_chapter(
            chapter_html('gv', '2271', 'PROHIBITION ON CONTRACTS WITH COMPANIES BOYCOTTING ISRAEL',
                         [('2271.001', 'DEFINITIONS', 'In this chapter:')]))
        self.assertEqual(heading, 'CHAPTER 2271. PROHIBITION ON CONTRACTS WITH COMPANIES BOYCOTTING ISRAEL')
        self.assertEqual(sections, [['2271.001', 'Sec. 2271.001. DEFINITIONS.']])
        self.assertIn('## Sec. 2271.001. DEFINITIONS. In this chapter:', body)
        self.assertIn('(1) "Board" means the board.', body)  # entities decoded, wording kept
        self.assertNotIn('<', body)

    def test_articles_and_numbers_with_parentheses_are_sections(self):
        _, _, sections = sync_law.convert_chapter(chapter_html(
            'cv', '4413', 'X', [('11.07', 'PROCEDURE', 'Text.'), ('4413(47e-1)', 'COLLIDER', 'Text.')], label='Art.'))
        self.assertEqual([s[0] for s in sections], ['11.07', '4413(47e-1)'])

    def test_numbered_paragraphs_inside_an_article_are_not_sections(self):
        raw = chapter_html('cr', '11', 'HABEAS CORPUS', [('11.07', 'PROCEDURE', 'Text.')], label='Art.')
        raw = raw.replace('</pre>', '<p class="left">Sec. 1. This article establishes the procedures.</p></pre>')
        _, body, sections = sync_law.convert_chapter(raw)
        self.assertEqual([s[0] for s in sections], ['11.07'])
        self.assertIn('Sec. 1. This article establishes the procedures.', body)


class ReadCodeTests(unittest.TestCase):
    def test_stray_copies_are_skipped_and_listed(self):
        skipped = []
        chapters = sync_law.read_code('GV', 'Government Code', gv_zip({'gv.2271 - Copy.htm': 'x', 'gv.51-old.htm': 'x'}),
                                      skipped)
        self.assertEqual(sorted(chapters), ['2271', '2274', '2275', '2276'])
        self.assertEqual(sorted(skipped), ['gv.2271 - Copy.htm', 'gv.51-old.htm'])

    def test_a_file_from_another_code_is_refused(self):
        with self.assertRaises(ValueError):
            sync_law.read_code('GV', 'Government Code', gv_zip({'pe.22.htm': chapter_html('pe', '22', 'X', [])}))

    def test_a_zip_bomb_is_refused(self):
        with patch.object(sync_law, 'MAX_UNZIPPED_BYTES', 100), self.assertRaises(ValueError):
            sync_law.read_code('GV', 'Government Code', gv_zip())

    def test_path_like_names_never_become_files(self):
        skipped = []
        chapters = sync_law.read_code('GV', 'Government Code', gv_zip({'../gv.1.htm': 'x', 'gv/1.htm': 'x'}), skipped)
        self.assertEqual(len(skipped), 2)
        self.assertTrue(all('/' not in c and '..' not in c.split('.') for c in chapters))


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / 'law'
        self.server = FakeServer()
        p = patch.object(sync_law, 'MIN_CODES', 1); p.start(); self.addCleanup(p.stop)

    def run_once(self, **kwargs):
        return sync_law.run(self.out, sync_law.Source(self.server, delay=0), now=NOW, log=lambda *a: None, **kwargs)

    def test_first_run_writes_chapters_and_indexes(self):
        top, failures = self.run_once()
        self.assertEqual(failures, [])
        self.assertEqual(top['codes']['GV']['chapters'], 4)
        self.assertEqual(top['codes']['GV']['headings']['2271'], 'CHAPTER 2271. CHAPTER TITLE 2271')
        text = (self.out / 'GV' / '2271.md').read_text('utf-8')
        self.assertTrue(text.startswith('# GV Code, CHAPTER 2271.'))
        self.assertIn('https://statutes.capitol.texas.gov/Docs/GV/htm/GV.2271.htm', text)
        index = json.loads((self.out / 'GV' / 'index.json').read_text('utf-8'))
        self.assertEqual(index['chapters']['2271']['sections'], [['2271.001', 'Sec. 2271.001. DEFINITIONS.']])

    def test_an_unchanged_zip_is_not_downloaded_or_rewritten(self):
        self.run_once()
        before = {p: p.stat().st_mtime_ns for p in (self.out / 'GV').glob('*.md')}
        top, failures = self.run_once()
        self.assertEqual(failures, [])
        self.assertEqual(self.server.requests[-1][1].get('if-none-match'), '"v1"')
        self.assertEqual({p: p.stat().st_mtime_ns for p in (self.out / 'GV').glob('*.md')}, before)
        self.assertEqual(top['codes']['GV']['chapters'], 4)

    def test_a_changed_zip_rewrites_only_changed_chapters_and_removes_dropped_ones(self):
        self.run_once()
        kept = (self.out / 'GV' / '2275.md').stat().st_mtime_ns
        changed = chapter_html('gv', '2271', 'CHAPTER TITLE 2271', [('2271.001', 'DEFINITIONS', 'Amended text.')])
        self.server.zips['GV'] = (gv_zip({'gv.2271.htm': changed}, drop=('2276',)), '"v2"')
        top, failures = self.run_once()
        self.assertEqual(failures, [])
        self.assertIn('Amended text.', (self.out / 'GV' / '2271.md').read_text('utf-8'))
        self.assertEqual((self.out / 'GV' / '2275.md').stat().st_mtime_ns, kept)
        self.assertFalse((self.out / 'GV' / '2276.md').exists())
        self.assertNotIn('2276', top['codes']['GV']['headings'])

    def test_a_code_that_suddenly_loses_most_chapters_is_refused_and_kept(self):
        self.run_once()
        self.server.zips['GV'] = (gv_zip(drop=('2271', '2274', '2275')), '"v2"')
        top, failures = self.run_once()
        self.assertEqual(len(failures), 1)
        self.assertTrue((self.out / 'GV' / '2271.md').exists())
        self.assertEqual(top['codes']['GV']['chapters'], 4)
        self.assertEqual(top['codes']['GV']['etag'], '"v1"')  # the next run tries the new zip again

    def test_a_bad_list_entry_stops_the_run_before_writing(self):
        self.server.listing = [{'code': 'GV', 'CodeName': 'x', 'Html': '/Zips/../../etc.htm.zip'}] * 30
        with self.assertRaises(ValueError):
            self.run_once()
        self.assertFalse(self.out.exists())

    def test_a_code_missing_from_the_list_keeps_its_files(self):
        self.run_once()
        self.server.listing = []
        with patch.object(sync_law.Source, 'codes', lambda self: []):
            top, failures = self.run_once()
        self.assertFalse(top['codes']['GV']['listed'])
        self.assertTrue((self.out / 'GV' / '2271.md').exists())


if __name__ == '__main__':
    unittest.main()
