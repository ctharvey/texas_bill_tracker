"""Code pages (#24): /law lists the tracked codes and /law/<CODE> every chapter in the law copy, marking the chapters
bills change. Built by build_feeds.write_law_code_pages inside the site shell; listed in the laws sitemap."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))  # Linux-only lock; unused by these tests.
import build_feeds as bf
import check_pages
import deploy_static as deploy

SHELL = deploy.shell_page((ROOT / 'index.html').read_text(encoding='utf-8').encode()).decode()
LAW = {'format': 'texas-bill-law-v1', 'codes': {
    'PE': {'name': 'Penal Code', 'copied_at': '2026-11-01T10:00:00-06:00', 'headings': {
        '46': 'CHAPTER 46. WEAPONS', '12': 'CHAPTER 12. PUNISHMENTS', '12A': 'CHAPTER 12A. STATE JAIL',
        '100': 'CHAPTER 100. LAST', '491.v2': 'CHAPTER 491. A SECOND VERSION'}},
    'HS': {'name': 'Health and Safety Code', 'copied_at': '2026-11-02T10:00:00-06:00',
           'headings': {'481': 'CHAPTER 481. TEXAS CONTROLLED SUBSTANCES ACT'}},
    'ZZ': {'name': 'Untracked Code', 'headings': {'1': 'CHAPTER 1. X'}},
    'AG': {'name': 'Agriculture Code', 'headings': {}},
}}
INDEX = {'format': 'texas-bill-statutes-v1',
         'sections': {'PE 46.02': {'b': [['HB1', 'm'], ['SB2', 'm']], 'f': {'SB2': '2026-11-10'}},
                      'PE 46.06': {'b': [['HB1', 'r']]}},
         'chapters': {'HS 481': {'b': [['HB9', 'm']], 'f': {'HB9': '2026-11-12'}}}}


def content(page: str) -> str:
    return page.split('<!--content-->', 1)[1].split('<!--/content-->', 1)[0]


class CodePages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.law = self.tmp / 'law'
        self.law.mkdir()
        (self.law / 'index.json').write_text(json.dumps(LAW), 'utf-8')
        self.share = self.tmp / 'share' / 'law'
        self.changed = []
        self.paths = bf.write_law_code_pages(INDEX, self.share, law_dir=self.law, shell=SHELL, changed=self.changed)
        self.read = lambda rel: (self.share / rel).read_text('utf-8')

    def test_writes_the_index_and_one_page_per_tracked_code_with_chapters(self):
        self.assertEqual(self.paths, ['law', 'law/HS', 'law/PE'])
        self.assertEqual(sorted(p.name for p in self.share.iterdir()), ['HS.html', 'PE.html', 'index.html'])
        self.assertEqual(sorted(self.changed), ['law', 'law/HS', 'law/PE'])

    def test_code_page_lists_every_chapter_in_order_and_marks_the_changed_ones(self):
        page = self.read('PE.html')
        body = content(page)
        order = [body.index(f'law/PE/{c}"') for c in ('12', '12A', '46', '100')]
        self.assertEqual(order, sorted(order))
        self.assertNotIn('491', body)  # A second version (#21) is not a chapter of its own here.
        self.assertIn('Chapter 46</a>: Weapons <strong>(2 bills change it)</strong>', body)
        self.assertIn('Chapter 12A</a>: State Jail</li>', body)
        self.assertIn('4 chapters. Bills in the 90th Legislature would change 1 of them.', body)
        self.assertIn('data-static-view="code:PE"', page)
        self.assertIn('<link rel="canonical" href="https://billatlas.org/law/PE">', page)
        self.assertIn('<title>Texas Penal Code: every chapter', page)
        self.assertNotIn('noindex', page)

    def test_one_bill_reads_in_the_singular(self):
        self.assertIn('(1 bill changes it)', content(self.read('HS.html')))

    def test_index_lists_codes_by_name_with_counts(self):
        page = self.read('index.html')
        body = content(page)
        self.assertLess(body.index('Health and Safety Code'), body.index('Penal Code'))
        self.assertIn('Penal Code</a>: 4 chapters, 1 changed by bills</li>', body)
        self.assertIn('Health and Safety Code</a>: 1 chapter, 1 changed by bills</li>', body)
        self.assertNotIn('Untracked', body)
        self.assertNotIn('Agriculture', body)
        self.assertIn('data-static-view="page:laws"', page)
        self.assertIn('<link rel="canonical" href="https://billatlas.org/law">', page)

    def test_structured_data_matches_what_check_pages_expects(self):
        for rel, url in (('index.html', 'https://billatlas.org/law'), ('PE.html', 'https://billatlas.org/law/PE')):
            parser = check_pages.PageParser()
            parser.feed(self.read(rel))
            blocks = [json.loads(b) for b in parser.ld]
            types_ = [b.get('@type') for b in blocks]
            for want in check_pages.expected_ld(url):
                self.assertIn(want, types_, rel)
        self.assertEqual(check_pages.expected_ld('https://billatlas.org/law'), ('CollectionPage', 'BreadcrumbList'))
        self.assertEqual(check_pages.expected_ld('https://billatlas.org/law/PE'), ('Legislation', 'BreadcrumbList'))

    def test_check_pages_knows_the_addresses_the_gateway_serves_them_at(self):
        root, site = self.tmp / 'share', 'https://billatlas.org/'
        self.assertEqual(check_pages.fixture_address(root / 'law' / 'index.html', root, site), f'{site}law')
        self.assertEqual(check_pages.fixture_address(root / 'law' / 'PE.html', root, site), f'{site}law/PE')

    def test_unchanged_pages_are_not_reported_again(self):
        changed = []
        bf.write_law_code_pages(INDEX, self.share, law_dir=self.law, shell=SHELL, changed=changed)
        self.assertEqual(changed, [])

    def test_nothing_without_the_shell_or_the_law_copy(self):
        out = self.tmp / 'other'
        self.assertEqual(bf.write_law_code_pages(INDEX, out, law_dir=self.law, shell=None), [])
        self.assertEqual(bf.write_law_code_pages(INDEX, out, law_dir=self.tmp / 'missing', shell=SHELL), [])
        self.assertEqual(bf.write_law_code_pages(INDEX, out, law_dir=None, shell=SHELL), [])
        self.assertFalse(out.exists())

    def test_existing_section_and_chapter_pages_are_left_alone(self):
        (self.share / 'PE').mkdir()
        (self.share / 'PE' / '46.html').write_text('chapter', 'utf-8')
        bf.write_law_code_pages(INDEX, self.share, law_dir=self.law, shell=SHELL)
        bf.write_law_chapter_pages(INDEX, self.share, law_dir=self.law, shell=SHELL)
        self.assertTrue((self.share / 'PE.html').is_file())
        self.assertTrue((self.share / 'index.html').is_file())


class CodeBreadcrumbs(unittest.TestCase):
    def crumbs(self, page: str) -> list[str]:
        parser = check_pages.PageParser()
        parser.feed(page)
        trail = [b for b in map(json.loads, parser.ld) if b.get('@type') == 'BreadcrumbList'][0]
        return [i['item'] for i in trail['itemListElement']]

    def test_section_and_chapter_pages_name_their_code_page(self):
        site = 'https://billatlas.org/'
        chapter = bf.law_chapter_page('PE 46', bf.chapter_groups(INDEX)['PE 46'], 'WEAPONS', shell=SHELL)
        self.assertEqual(self.crumbs(chapter), [site, f'{site}law', f'{site}law/PE', f'{site}law/PE/46'])
        section = bf.law_page('PE 46.02', INDEX['sections']['PE 46.02'], 'Penal Code', None, shell=SHELL)
        self.assertEqual(self.crumbs(section), [site, f'{site}law', f'{site}law/PE', f'{site}law/PE/46',
                                                f'{site}law/PE/46.02'])


class CodeSitemap(unittest.TestCase):
    def test_code_paths_go_in_the_laws_sitemap_with_their_newest_day(self):
        copied = {'PE': '2026-11-01', 'HS': '2026-11-02'}
        rows = bf.sitemap_entries({'bills': []}, paths=['law', 'law/PE', 'law/HS', 'today'], index=INDEX, copied=copied)
        laws = dict(rows['laws'])
        self.assertEqual(laws['https://billatlas.org/law/PE'], '2026-11-10')
        self.assertEqual(laws['https://billatlas.org/law/HS'], '2026-11-12')
        self.assertEqual(laws['https://billatlas.org/law'], '2026-11-12')
        self.assertNotIn('https://billatlas.org/law', dict(rows['pages']))
        self.assertIn('https://billatlas.org/today', dict(rows['pages']))


if __name__ == '__main__':
    unittest.main()
