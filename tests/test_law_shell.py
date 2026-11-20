"""Law section and chapter pages inside the site shell: one full page for everyone at /law/<CODE>/<section> and
/law/<CODE>/<chapter>, no redirect, taken over by the app in place (SEO chunk 4, phase 5)."""
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))  # Linux-only lock; unused by these tests.
import build_feeds as bf
import deploy_static as deploy
from test_law_chapters import INDEX

INDEX_HTML = (ROOT / 'index.html').read_text(encoding='utf-8')
SHELL = deploy.shell_page(INDEX_HTML.encode()).decode()
ENTRY = {'h': 'Unlawful Sale of Firearms', 'b': [['SB12', 'a'], ['HB1094', 'r']]}
CURRENT = ('Sec. 46.06. UNLAWFUL SALE OF FIREARMS.', '(a) A person commits an offense if the person sells a firearm.',
           'live/law/PE/46.md')


def head(page: str) -> str:
    return page.split('</head>', 1)[0]


def content(page: str) -> str:
    return page.split('<!--content-->', 1)[1].split('<!--/content-->', 1)[0]


class LawPagesInShell(unittest.TestCase):
    def setUp(self):
        self.section = bf.law_page('PE 46.06', ENTRY, 'Penal Code', CURRENT, shell=SHELL)
        with tempfile.TemporaryDirectory() as tmp:
            bf.write_law_chapter_pages(INDEX, Path(tmp), shell=SHELL)
            self.chapter = (Path(tmp) / 'PE' / '46.html').read_text('utf-8')

    def test_each_is_the_site_page_tagged_with_its_static_view(self):
        self.assertIn('class="app-shell"', self.section)
        self.assertIn('<section id="dynamic-content" data-static-view="law:PE 46.06"', self.section)
        self.assertIn('<section id="dynamic-content" data-static-view="chapter:PE 46"', self.chapter)
        self.assertIn('<h1>Penal Code § 46.06: UNLAWFUL SALE OF FIREARMS</h1>', content(self.section))
        self.assertIn('<h2>Current law</h2>', content(self.section))
        self.assertIn('href="https://billatlas.org/bill/SB12"', content(self.section))
        self.assertIn('<h1>Penal Code Chapter 46: Weapons</h1>', content(self.chapter))
        self.assertIn('href="https://billatlas.org/law/PE/46.06"', content(self.chapter))
        for page in (self.section, self.chapter):
            self.assertIn('<div class="page-heading" hidden', page)  # The law views write their own heading.

    def test_canonical_is_the_path(self):
        self.assertIn('<link rel="canonical" href="https://billatlas.org/law/PE/46.06">', head(self.section))
        self.assertIn('<link rel="canonical" href="https://billatlas.org/law/PE/46">', head(self.chapter))
        self.assertIn('<meta property="og:url" content="https://billatlas.org/law/PE/46">', head(self.chapter))

    def test_never_redirects_and_has_no_open_in_link(self):
        for page in (self.section, self.chapter):
            self.assertNotIn('location.replace', page)
            self.assertNotIn('#statute?', page)
            self.assertNotIn('#chapter?', page)
            self.assertNotIn('Open Penal Code', page)
            self.assertIn('<script type="module" src="/boot.js"></script>', page)
            self.assertIn('href="/app.css"', page)

    def test_keeps_every_element_the_app_looks_up(self):
        for element in re.findall(r'\sid="([^"]+)"', INDEX_HTML):
            self.assertIn(f'id="{element}"', self.section, element)
            self.assertIn(f'id="{element}"', self.chapter, element)

    def test_every_script_has_a_src_or_is_a_hashed_shell_script(self):
        hashed = re.findall(r'<script>(.*?)</script>', INDEX_HTML, re.S)
        for page in (self.section, self.chapter):
            for tag, body in re.findall(r'(<script[^>]*>)(.*?)</script>', page, re.S):
                if 'src=' in tag or tag == '<script type="application/ld+json">':
                    continue
                self.assertEqual(tag, '<script>')
                self.assertIn(body, hashed)

    def test_one_title_description_and_canonical(self):
        for page in (self.section, self.chapter):
            self.assertEqual(head(page).count('<title>'), 1)
            self.assertEqual(head(page).count('<link rel="canonical"'), 1)
            self.assertEqual(head(page).count('<meta name="description"'), 1)

    def test_page_version_covers_only_the_page_so_a_new_shell_is_not_a_new_page(self):
        version = re.compile(r'<meta name="page-version" content="([0-9a-f]+)">')
        other_shell = SHELL.replace('<footer', '<footer data-x="1"', 1)
        self.assertNotEqual(other_shell, SHELL)
        again = bf.law_page('PE 46.06', ENTRY, 'Penal Code', CURRENT, shell=other_shell)
        self.assertNotEqual(again, self.section)
        self.assertEqual(version.search(again).group(1), version.search(self.section).group(1))

    def test_without_a_shell_the_pages_stay_standalone(self):
        page = bf.law_page('PE 46.06', ENTRY, 'Penal Code', CURRENT)
        self.assertIn('location.replace("https://billatlas.org/#statute?law=PE&sec=46.06")', page)
        self.assertNotIn('data-static-view', page)


if __name__ == '__main__':
    unittest.main()
