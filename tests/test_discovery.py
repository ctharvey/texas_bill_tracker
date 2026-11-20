"""SEO chunk 7 phases 2-4: IndexNow for every page type, internal links on static pages, clean feed channel links."""
import json
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))  # Linux-only lock; unused by these tests.
import build_feeds as bf
import deploy_static as deploy

SHELL = deploy.shell_page((ROOT / 'index.html').read_bytes()).decode()
SITE = bf.SITE
ROSTER = {
    'house|Ann Smith': {'code': 'A1001', 'chamber': 'house', 'display_name': 'Ann Smith', 'full_name': 'Ann Smith'},
    'senate|Ann Smith': {'code': 'A2002', 'chamber': 'senate', 'display_name': 'Ann Smith', 'full_name': 'Ann Smith'},
    'senate|Bo Jones': {'code': 'A2003', 'chamber': 'senate', 'display_name': 'Bo Jones', 'full_name': 'Bo Jones'},
    'house|Odd': {'code': '../evil', 'chamber': 'house', 'display_name': 'Odd'},
}
BILL = {'id': 'HB1', 'caption': 'Relating to guns.', 'authors': ['Ann Smith', 'Nobody'], 'coauthors': [],
        'sponsors': ['Ann Smith', 'Bo Jones'], 'cosponsors': ['Odd'], 'actions': []}
INDEX = {'chapters': {'PE 46': {'h': 'WEAPONS', 'b': [['HB1', 'r']]}},
         'sections': {'PE 46.06': {'h': 'Unlawful', 'b': [['HB1', 'm'], ['SB2', 'n']]},
                      'PE 9.01': {'h': 'Other', 'b': [['HB1', 'n']]}}}


class WritePage(unittest.TestCase):
    def test_append_rule(self):
        page = lambda v, extra='': f'<html><meta name="page-version" content="{v}">{extra}</html>'
        with tempfile.TemporaryDirectory() as folder:
            path, changed = Path(folder) / 'p.html', []
            self.assertTrue(bf._write_page(path, page('aaa'), 'topic/water', changed))
            self.assertEqual(changed, ['topic/water'])  # new page
            self.assertFalse(bf._write_page(path, page('aaa'), 'topic/water', changed))
            self.assertEqual(changed, ['topic/water'])  # unchanged: not appended
            self.assertTrue(bf._write_page(path, page('bbb'), 'topic/water', changed))
            self.assertEqual(changed, ['topic/water'] * 2)  # new version
            self.assertTrue(bf._write_page(path, page('bbb', 'new shell'), 'topic/water', changed))
            self.assertEqual(len(changed), 2)  # rewritten with a new shell only
            self.assertTrue(bf._write_page(path, page('ccc'), '', None))  # no list given: fine

    def test_every_writer_reports_its_url_path(self):
        data = {'format': bf.SITE_PAGES_FORMAT,
                'topics': [{'slug': 'water', 'name': 'Water', 'bills': ['HB1']}],
                'agencies': [{'id': 'tea', 'name': 'TEA', 'bills': ['HB1']}],
                'about': [{'view': 'method', 'path': '/about/method', 'heading': ['Method.', 'How'], 'html': '<p>x</p>'}],
                'views': [{'view': 'home', 'path': '/', 'heading': ['Home', 'h'], 'html': '<p>x</p>'},
                          {'view': 'today', 'path': '/today', 'heading': ['Today.', 't'], 'html': '<p>y</p>'}]}
        snap = {'bills': [BILL]}
        with tempfile.TemporaryDirectory() as folder:
            share, changed = Path(folder), []
            bf.write_share_pages(snap, share, shell=SHELL, changed=changed)
            bf.write_law_pages(INDEX, share / 'law', shell=SHELL, changed=changed)
            bf.write_law_chapter_pages(INDEX, share / 'law', shell=SHELL, changed=changed)
            bf.write_member_pages(snap, ROSTER, share / 'member', shell=SHELL, changed=changed)
            bf.write_group_pages(data, snap, share, shell=SHELL, changed=changed)
            bf.write_about_pages(data, share, shell=SHELL, changed=changed)
            bf.write_view_pages(data, share, shell=SHELL, changed=changed)
        self.assertEqual(changed[0], 'bill/HB1')
        for path in ('law/PE/46.06', 'law/PE/9.01', 'law/PE/46', 'member/A1001/ann-smith', 'member/A2003/bo-jones',
                     'topic/water', 'agency/tea', 'about/method', 'today', ''):
            self.assertIn(path, changed)
        self.assertEqual(len(changed), len(set(changed)))


class IndexNow(unittest.TestCase):
    def test_payload_order_dedupe_and_cap(self):
        paths = ['', 'today', 'topic/water', 'member/A1/x', 'law/PE/46', 'bill/SB2', 'law/PE/46', 'about/method', 'bill/HB1']
        urls = bf.indexnow_payload(paths)['urlList']
        self.assertEqual(urls, [SITE + p for p in ('bill/SB2', 'bill/HB1', 'law/PE/46', 'member/A1/x', 'topic/water',
                                                    '', 'today', 'about/method')])
        many = [f'about/p{i}' for i in range(bf.INDEXNOW_MAX_URLS)] + ['bill/HB1']
        capped = bf.indexnow_payload(many)['urlList']
        self.assertEqual(len(capped), bf.INDEXNOW_MAX_URLS)
        self.assertEqual(capped[0], SITE + 'bill/HB1')  # bills are never cut for lesser pages

    def test_submit_posts_the_paths(self):
        sent = []

        class Response:
            status = 200
            __enter__ = lambda self: self
            __exit__ = lambda self, *exc: False

        def opener(request, timeout):
            sent.append(json.loads(request.data))
            return Response()
        self.assertEqual(bf.submit_indexnow(['law/PE/46', 'bill/HB1'], SITE, opener), 'HTTP 200 for 2 pages')
        self.assertEqual(sent[0]['urlList'], [SITE + 'bill/HB1', SITE + 'law/PE/46'])
        self.assertEqual(bf.submit_indexnow([], SITE, lambda *a, **k: self.fail('sent')), 'nothing changed')


def bill_page(**kwargs) -> str:
    return bf.share_page(BILL, SITE, shell=SHELL, **kwargs)


class BillPageLinks(unittest.TestCase):
    def test_members_link_only_when_resolved_in_the_right_chamber(self):
        paths = bf.bill_member_paths(BILL, ROSTER)
        # HB: authors serve in the House, sponsors in the Senate; the coded roster only.
        self.assertEqual(paths, {('authors', 'Ann Smith'): 'member/A1001/ann-smith',
                                 ('sponsors', 'Ann Smith'): 'member/A2002/ann-smith',
                                 ('sponsors', 'Bo Jones'): 'member/A2003/bo-jones'})
        page = bill_page(member_paths=paths)
        self.assertIn(f'<dt>Authors</dt><dd><a href="{SITE}member/A1001/ann-smith">Ann Smith</a>, Nobody</dd>', page)
        self.assertIn(f'<a href="{SITE}member/A2002/ann-smith">Ann Smith</a>, <a href="{SITE}member/A2003/bo-jones">', page)
        self.assertIn('<dt>Cosponsors</dt><dd>Odd</dd>', page)  # a bad code is never linked
        plain = bill_page()
        self.assertNotIn('/member/', plain)
        self.assertIn('<dt>Authors</dt><dd>Ann Smith, Nobody</dd>', plain)

    def test_write_share_pages_links_members_only_with_the_roster(self):
        with tempfile.TemporaryDirectory() as folder:
            bf.write_share_pages({'bills': [BILL]}, Path(folder), shell=SHELL, roster=ROSTER)
            self.assertIn('/member/A1001/ann-smith', (Path(folder) / 'HB1.html').read_text('utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            bf.write_share_pages({'bills': [BILL]}, Path(folder), shell=SHELL)
            self.assertNotIn('/member/', (Path(folder) / 'HB1.html').read_text('utf-8'))

    def test_laws_list_kind_words_for_written_pages_only(self):
        links = bf.bill_law_links(INDEX)
        self.assertEqual(links['HB1'], [
            ('law/PE/9.01', 'Penal Code § 9.01', 'adds'),
            ('law/PE/46', 'Penal Code chapter 46', 'repeals'),
            ('law/PE/46.06', 'Penal Code § 46.06', 'amends')])
        self.assertEqual(links['SB2'], [('law/PE/46.06', 'Penal Code § 46.06', 'adds')])
        junk = {'sections': {'XX 1.01': {'b': [['HB1', 'm']]}, '../x 1.01': {'b': [['HB1', 'm']]}}}
        self.assertEqual(bf.bill_law_links(junk), {})
        page = bill_page(laws=links['HB1'])
        self.assertIn('<h2>Laws this bill changes</h2>', page)
        self.assertIn(f'<li>amends <a href="{SITE}law/PE/46.06">Penal Code § 46.06</a></li>', page)
        self.assertIn(f'<li>repeals <a href="{SITE}law/PE/46">Penal Code chapter 46</a></li>', page)
        self.assertNotIn('Laws this bill changes', bill_page())

    def test_laws_are_capped_with_a_count_of_the_rest(self):
        laws = [(f'law/PE/{i}.01', f'Penal Code § {i}.01', 'amends') for i in range(1, 106)]
        page = bill_page(laws=laws)
        self.assertEqual(page.count('Penal Code §'), 100)
        self.assertIn('<p>and 5 more.</p>', page)


class LawSectionLink(unittest.TestCase):
    def test_links_its_chapter_only_when_that_page_exists(self):
        entry = INDEX['sections']['PE 46.06']
        with_chapter = bf.law_page('PE 46.06', entry, 'Penal Code', None, SITE, SHELL, frozenset({'PE 46'}))
        self.assertIn(f'<a href="{SITE}law/PE/46">Penal Code Chapter 46</a>', with_chapter.split('<!--content-->')[1])
        for chapters in (None, frozenset(), frozenset({'PE 47'})):
            page = bf.law_page('PE 46.06', entry, 'Penal Code', None, SITE, SHELL, chapters)
            self.assertNotIn('Part of', page)

    def test_write_law_pages_passes_the_chapters_the_index_gives(self):
        with tempfile.TemporaryDirectory() as folder:
            bf.write_law_pages(INDEX, Path(folder), shell=SHELL)
            self.assertIn('law/PE/46"', (Path(folder) / 'PE' / '46.06.html').read_text('utf-8').split('<!--content-->')[1])


class CleanLinks(unittest.TestCase):
    def test_member_and_chapter_feed_channels_are_paths(self):
        root = ET.fromstring(bf.member_feed(ROSTER['house|Ann Smith'], [(BILL, 'Author')]))
        self.assertEqual(root.findtext('./channel/link'), SITE + 'member/A1001/ann-smith')
        g = bf.chapter_groups(INDEX)['PE 46']
        root = ET.fromstring(bf.chapter_feed('PE 46', g, {'HB1': BILL}, 'WEAPONS'))
        self.assertEqual(root.findtext('./channel/link'), SITE + 'law/PE/46')

    def test_no_app_hash_links_in_generated_feeds_and_shell_pages(self):
        snap = {'bills': [BILL]}
        texts = [bf.bill_feed(BILL), bf.member_feed(ROSTER['house|Ann Smith'], [(BILL, 'Author')]),
                 bf.law_feed('PE 46.06', [(BILL, 'm')]), bf.chapter_feed('PE 46', bf.chapter_groups(INDEX)['PE 46'], {'HB1': BILL})]
        with tempfile.TemporaryDirectory() as folder:
            share = Path(folder)
            bf.write_share_pages(snap, share, shell=SHELL, roster=ROSTER, laws=bf.bill_law_links(INDEX))
            bf.write_law_pages(INDEX, share / 'law', shell=SHELL)
            bf.write_law_chapter_pages(INDEX, share / 'law', shell=SHELL)
            bf.write_member_pages(snap, ROSTER, share / 'member', shell=SHELL)
            texts += [p.read_text('utf-8') for p in share.rglob('*.html')]
        self.assertGreater(len(texts), 8)
        for text in texts:
            self.assertEqual(re.findall(r'https://billatlas\.org/#[^"<\s]*', text), [])


if __name__ == '__main__':
    unittest.main()
