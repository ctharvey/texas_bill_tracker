"""The Texas Constitution (#20): keys "CN <article>.<section>" (CN 8.1-b), pages at /law/CN/<article>/<section>,
articles as chapters, and joint resolutions read as amending its sections."""
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
import law_on_demand as lod
from law_context import LawCopy
import pages
import sync_law

SHELL = deploy.shell_page((ROOT / 'index.html').read_text(encoding='utf-8').encode()).decode()
SITE = 'https://billatlas.org/'

# Shaped like the 89th Legislature's joint resolutions (HJR 1, HJR 2, SJR 14, SJR 16).
RESOLUTION = """# HJR 1 - Introduced

A JOINT RESOLUTION

### SECTION 1.

Section 1(g), Article VIII, Texas Constitution, is amended to read as follows:

(g) The legislature may provide for <ins>a homestead</ins> \\[<del>an</del>\\] exemption.

### SECTION 2.

Article VIII, Texas Constitution, is amended by adding Section 26 to read as follows:

<ins>Sec. 26. (a) The legislature by general law may exempt property from taxation.</ins>

<ins>(b) This section expires in 2040. See Chapter 11, Tax Code.</ins>

### SECTION 3.

Article III, Texas Constitution, is amended by amending Section 1 and adding Sections 1A and 1B to read as follows:

Sec. 1. <ins>Subject to Sections 1A and 1B of this article, the</ins> \\[<del>The</del>\\] Legislative power.

<ins>Sec. 1A. (a) The people reserve the power to propose laws.</ins>

<ins>Sec. 1B. (a) The people reserve the power to reject laws.</ins>

### SECTION 4.

Sections 49-d-14 and 49-n, Article III, Texas Constitution, are repealed.

### SECTION 5.

The following temporary provision is added to the Texas Constitution:

TEMPORARY PROVISION. (a) This temporary provision applies to the constitutional amendment.

### SECTION 6.

Section 46.06, Penal Code, is amended to read as follows:

Sec. 46.06. UNLAWFUL TRANSFER. Text.
"""


def write_constitution(root: Path) -> Path:
    """A law copy with the Constitution's articles 1 and 8 (section ids as the official copy writes them)."""
    law = root / 'law'
    (law / 'CN').mkdir(parents=True)
    articles = {
        '1': ('ARTICLE 1. BILL OF RIGHTS', [('1', 'FREEDOM AND SOVEREIGNTY OF STATE.', 'Texas is a free state.'),
                                            ('3a', 'EQUALITY UNDER THE LAW.', 'Equality under the law shall not be denied.')]),
        '8': ('ARTICLE 8. TAXATION AND REVENUE', [('1', 'EQUALITY AND UNIFORMITY.', 'Taxation shall be equal.'),
                                                  ('1-b', 'HOMESTEAD EXEMPTIONS.', 'Residence homesteads are exempt.')]),
    }
    entries = {}
    for number, (heading, sections) in articles.items():
        body = f'# The Texas Constitution, {heading}\n\n{heading}\n\n' + ''.join(
            f'## Sec. {sid}. {title} {text}\n\n' for sid, title, text in sections)
        (law / 'CN' / f'{number}.md').write_text(body, 'utf-8')
        entries[number] = {'heading': heading, 'file': f'CN/{number}.md', 'sha256': 'a' * 64,
                           'sections': [[sid, f'Sec. {sid}. {title}'] for sid, title, _ in sections]}
    entries['ap'] = {'heading': '', 'file': 'CN/ap.md', 'sha256': 'b' * 64, 'sections': []}
    (law / 'CN' / 'ap.md').write_text('# The Texas Constitution\n', 'utf-8')
    (law / 'CN' / 'index.json').write_text(json.dumps({'code': 'CN', 'chapters': entries}), 'utf-8')
    headings = {n: h for n, (h, _s) in articles.items()} | {'ap': '', 'pr': ''}
    (law / 'index.json').write_text(json.dumps({'format': 'texas-bill-law-v1', 'codes': {
        'CN': {'name': 'The Texas Constitution', 'index': 'CN/index.json', 'headings': headings}}}), 'utf-8')
    return law


def content(page: str) -> str:
    return page.split('<!--content-->', 1)[1].split('<!--/content-->', 1)[0]


class Parser(unittest.TestCase):
    def setUp(self):
        self.sections, self.unparsed = bf.bill_statutes(RESOLUTION)

    def test_each_clause_form_names_article_and_section(self):
        got = {k: (v['kind'], v['subsections']) for k, v in self.sections.items()}
        self.assertEqual(got, {
            'CN 8.1': ('amend', ['g']), 'CN 8.26': ('add', []), 'CN 3.1': ('amend', []), 'CN 3.1A': ('add', []),
            'CN 3.1B': ('add', []), 'CN 3.49-d-14': ('repeal', []), 'CN 3.49-n': ('repeal', []),
            'PE 46.06': ('amend', [])})
        self.assertEqual(self.unparsed, 0)

    def test_body_paragraphs_go_to_their_section(self):
        self.assertIn('The people reserve the power to propose laws', ' '.join(self.sections['CN 3.1A']['paragraphs']))
        self.assertNotIn('reject', ' '.join(self.sections['CN 3.1A']['paragraphs']))
        self.assertIn('exempt property', ' '.join(self.sections['CN 8.26']['paragraphs']))

    def test_a_temporary_provision_is_not_a_section(self):
        clause = 'The following temporary provision is added to the Texas Constitution:'
        self.assertEqual(bf.parse_clause(clause)['kind'], 'other_law')

    def test_a_code_section_that_cites_the_constitution_stays_a_code_section(self):
        parsed = bf.parse_clause('Section 11.13(n), Tax Code, as authorized by Section 1-b, Article VIII, Texas '
                                 'Constitution, is amended to read as follows:')
        self.assertEqual((parsed['kind'], parsed['code'], parsed['targets']), ('amend', 'TX', ['11.13']))

    def test_an_article_number_out_of_range_is_not_the_constitution(self):
        self.assertIsNone(bf._roman('XX'))
        self.assertEqual(bf._roman('XVII'), 17)
        self.assertNotEqual(bf.parse_clause('Section 1, Article XX, Texas Constitution, is amended to read as follows:')
                            .get('code'), 'CN')

    def test_chapter_words_in_a_resolution_never_mark_an_article(self):
        chapters = bf.bill_chapters(RESOLUTION)
        self.assertFalse([k for k in chapters if k.startswith('CN ')], chapters)
        self.assertNotIn('TX 11', chapters)  # Cited from a Constitution body: no code is the default there.


class Index(unittest.TestCase):
    def test_keys_take_the_copy_case_and_new_sections_keep_the_bill_case(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        law = write_constitution(tmp)
        texts = tmp / 'text' / 'SJR9'
        texts.mkdir(parents=True)
        (texts / 'index.json').write_text(json.dumps({'bill_id': 'SJR9', 'versions': [{'code': 'I', 'name': 'Introduced'}]}),
                                          'utf-8')
        (texts / 'I.md').write_text("""# SJR 9

### SECTION 1.

Section 3A, Article I, Texas Constitution, is amended to read as follows:

Sec. 3A. EQUALITY UNDER THE LAW. Equality \\[<del>shall not</del>\\] <ins>may not</ins> be denied.

### SECTION 2.

Article I, Texas Constitution, is amended by adding Section 3B to read as follows:

<ins>Sec. 3B. NEW RIGHT. Text.</ins>
""", 'utf-8')
        index, files = bf.build_statutes({'bills': [{'id': 'SJR9'}]}, tmp / 'text', law)
        self.assertEqual(sorted(index['sections']), ['CN 1.3B', 'CN 1.3a'])
        self.assertEqual(index['sections']['CN 1.3a']['h'], 'EQUALITY UNDER THE LAW')
        self.assertEqual(index['codes'], {'CN': 'Texas Constitution'})
        self.assertEqual(sorted(files), ['CN-1.3B.json', 'CN-1.3a.json'])


class Labels(unittest.TestCase):
    def test_keys_paths_labels_and_official_links(self):
        self.assertTrue(bf.STATUTE_KEY.fullmatch('CN 8.1-b'))
        self.assertTrue(bf.STATUTE_KEY.fullmatch('CN 3.49-d-14'))
        self.assertTrue(bf.STATUTE_KEY.fullmatch('CN 1.3a'))
        for bad in ('CN 8', 'CN 123.1', 'CN 8.1--b', 'PE 46.06-a', 'PE 1-b'):
            self.assertFalse(bf.STATUTE_KEY.fullmatch(bad), bad)
        self.assertEqual(bf.law_path('CN', '8.1-b'), 'law/CN/8/1-b')
        self.assertEqual(bf.law_path('CN', '8'), 'law/CN/8')
        self.assertEqual(bf.law_path('PE', '46.06'), 'law/PE/46.06')
        self.assertEqual(bf.law_label('CN', '8.1-b'), 'Tex. Const. art. 8, \u00a7 1-b')
        self.assertEqual(bf.chapter_label('CN', '8'), 'Texas Constitution, Article 8')
        self.assertEqual(bf.official_law_url('CN', '8.1-b'),
                         'https://statutes.capitol.texas.gov/Docs/CN/htm/CN.8.htm#8.1-b')
        self.assertEqual(bf.official_law_url('CN', '8'), 'https://statutes.capitol.texas.gov/Docs/CN/htm/CN.8.htm')
        self.assertEqual(bf.official_law_url('PE', '46.06'),
                         'https://statutes.capitol.texas.gov/?tab=1&code=PE&chapter=PE.46&artSec=46.06')
        self.assertEqual(bf.chapter_of('CN 8.1-b'), 'CN 8')

    def test_the_page_view_and_the_fixture_address_take_constitution_keys(self):
        self.assertTrue(pages.VIEW.fullmatch('law:CN 8.1-b'))
        root = Path('/tmp/share')
        self.assertEqual(check_pages.fixture_address(root / 'law' / 'CN' / '8.1-b.html', root, SITE), f'{SITE}law/CN/8/1-b')
        self.assertEqual(check_pages.fixture_address(root / 'law' / 'CN' / '8.html', root, SITE), f'{SITE}law/CN/8')


class Pages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.law = write_constitution(self.tmp)
        self.index = {'format': bf.STATUTE_FORMAT, 'codes': {'CN': 'Texas Constitution'},
                      'sections': {'CN 8.1-b': {'h': 'HOMESTEAD EXEMPTIONS', 'b': [['HJR2', 'm']],
                                                'f': {'HJR2': '2026-11-15'}}},
                      'chapters': {}}

    def test_section_page_has_its_address_label_and_article_trail(self):
        share = self.tmp / 'share' / 'law'
        bf.write_law_pages(self.index, share, SITE, law_dir=self.law, shell=SHELL)
        page = (share / 'CN' / '8.1-b.html').read_text('utf-8')
        self.assertIn('<link rel="canonical" href="https://billatlas.org/law/CN/8/1-b">', page)
        self.assertIn('<title>Tex. Const. art. 8, \u00a7 1-b: HOMESTEAD EXEMPTIONS', page)
        self.assertIn('data-static-view="law:CN 8.1-b"', page)
        self.assertIn('Residence homesteads are exempt.', content(page))
        self.assertIn('https://statutes.capitol.texas.gov/Docs/CN/htm/CN.8.htm#8.1-b', page)
        trail = [b for b in map(json.loads, self._ld(page)) if b.get('@type') == 'BreadcrumbList'][0]
        self.assertEqual([i['item'] for i in trail['itemListElement']],
                         [SITE, f'{SITE}law', f'{SITE}law/CN', f'{SITE}law/CN/8', f'{SITE}law/CN/8/1-b'])
        self.assertEqual([i['name'] for i in trail['itemListElement']][2:4],
                         ['Texas Constitution', 'Texas Constitution, Article 8'])

    def test_article_page_lists_its_sections_at_their_addresses(self):
        share = self.tmp / 'share' / 'law'
        bf.write_law_chapter_pages(self.index, share, SITE, law_dir=self.law, shell=SHELL)
        page = (share / 'CN' / '8.html').read_text('utf-8')
        self.assertIn('<title>Texas Constitution, Article 8: Taxation and Revenue', page)
        self.assertIn('<a href="https://billatlas.org/law/CN/8/1-b">\u00a7 1-b</a>', content(page))
        self.assertIn('in this article', content(page))

    def test_code_page_lists_the_articles_in_order(self):
        share = self.tmp / 'share' / 'law'
        paths = bf.write_law_code_pages(self.index, share, SITE, law_dir=self.law, shell=SHELL)
        self.assertIn('law/CN', paths)
        page = (share / 'CN.html').read_text('utf-8')
        body = content(page)
        self.assertIn('<h1>Texas Constitution</h1>', body)
        self.assertIn('<title>Texas Constitution: every article', page)
        self.assertLess(body.index('Article 1</a>'), body.index('Article 8</a>'))
        self.assertIn('Article 8</a>: Taxation and Revenue <strong>(1 bill changes it)</strong>', body)
        self.assertNotIn('law/CN/ap', body)
        self.assertIn('Texas Constitution</a>: 2 articles, 1 changed by bills',
                      content((share / 'index.html').read_text('utf-8')))

    def test_sitemap_and_bill_links_use_the_article_address(self):
        rows = bf.sitemap_entries({'bills': []}, law_keys=['CN 8.1-b'], index=self.index)
        laws = dict(rows['laws'])
        self.assertIn(f'{SITE}law/CN/8/1-b', laws)
        self.assertIn(f'{SITE}law/CN/8', laws)
        self.assertEqual(bf.bill_law_links(self.index)['HJR2'],
                         [('law/CN/8/1-b', 'Tex. Const. art. 8, \u00a7 1-b', 'amends')])

    @staticmethod
    def _ld(page: str) -> list[str]:
        parser = check_pages.PageParser()
        parser.feed(page)
        return parser.ld


class OnRequest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        law = write_constitution(self.tmp)
        shell = self.tmp / 'shell.html'
        shell.write_text(SHELL, 'utf-8')
        self.pages = lod.LawPages(law, None, shell)

    def test_a_section_renders_at_its_article_address(self):
        status, headers, body = self.pages.render('/law/CN/8/1-b')
        self.assertEqual(status, 200)
        page = body.decode('utf-8')
        self.assertIn('<link rel="canonical" href="https://billatlas.org/law/CN/8/1-b">', page)
        self.assertIn('Residence homesteads are exempt.', page)
        self.assertNotIn('Taxation shall be equal.', content(page))  # Section 1 of the same article is another one.

    def test_the_same_number_in_two_articles_is_two_sections(self):
        first = self.pages.render('/law/CN/1/1')[2].decode('utf-8')
        eighth = self.pages.render('/law/CN/8/1')[2].decode('utf-8')
        self.assertIn('Texas is a free state.', first)
        self.assertIn('Taxation shall be equal.', eighth)

    def test_other_spellings_redirect_to_the_copy_id(self):
        for path in ('/law/CN/8/1-B', '/law/cn/8/1-b', '/law/CN/8.1-b', '/law/CN/8/1-b/'):
            status, headers, _ = self.pages.render(path)
            self.assertEqual((status, headers.get('Location')), (301, '/law/CN/8/1-b'), path)
        self.assertEqual(self.pages.render('/law/CN/1/3A')[1].get('Location'), '/law/CN/1/3a')

    def test_an_article_page_and_unknown_addresses(self):
        status, _h, body = self.pages.render('/law/CN/8')
        self.assertEqual(status, 200)
        self.assertIn('<a href="https://billatlas.org/law/CN/8/1-b">', body.decode('utf-8'))
        for path in ('/law/CN/9/1', '/law/CN/8/2', '/law/CN/8/1--b', '/law/CN/123/1', '/law/CN/ap'):
            self.assertEqual(self.pages.render(path)[0], 404, path)

    def test_the_copy_finds_a_section_in_its_own_article_only(self):
        law = LawCopy(self.tmp / 'law')
        self.assertEqual(law.section_chapter('CN', '8.1')[0], '8')
        self.assertEqual(law.section_chapter('CN', '1.1')[0], '1')
        self.assertIsNone(law.section_chapter('CN', '1.1-b'))  # Article 8 has a 1-b; article 1 does not.
        self.assertEqual(LawCopy.local_section('CN', '8.1-b'), '1-b')
        self.assertEqual(LawCopy.local_section('PE', '46.06'), '46.06')


class Search(unittest.TestCase):
    def test_heading_search_rows_use_constitution_keys(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        write_constitution(tmp)
        entries = sync_law.search_entries(tmp / 'law')
        self.assertIn(['CN 8', 'TAXATION AND REVENUE'], entries)
        self.assertIn(['CN 8.1-b', 'HOMESTEAD EXEMPTIONS'], entries)
        self.assertIn(['CN 1.3a', 'EQUALITY UNDER THE LAW'], entries)
        self.assertFalse([e for e in entries if e[0].startswith('CN ap')])


if __name__ == '__main__':
    unittest.main()
