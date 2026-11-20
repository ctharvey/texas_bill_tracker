"""Bill pages inside the site shell: one full page for everyone at /bill/<ID>, no redirect, and IndexNow told only
about bills whose own part changed (SEO chunk 4, phase 4)."""
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))  # Linux-only lock; unused by these tests.
import build_feeds as bf
import deploy_static as deploy
import pages

INDEX = (ROOT / 'index.html').read_text(encoding='utf-8')
SHELL = deploy.shell_page(INDEX.encode()).decode()
BILL = {'id': 'HB486', 'caption': 'Relating to wildlife.', 'status': 'Filed', 'filed_at': '2026-11-09',
        'last_action': '11/09/2026 H Filed', 'authors': ['Leo Wilson'], 'subjects': ['Wildlife']}


def head(page: str) -> str:
    return page.split('</head>', 1)[0]


def content(page: str) -> str:
    return page.split('<!--content-->', 1)[1].split('<!--/content-->', 1)[0]


class BillPageInShell(unittest.TestCase):
    def setUp(self):
        self.page = bf.share_page(BILL, headline='Lets drivers keep roadkill.', shell=SHELL)

    def test_is_the_site_page_with_the_bill_in_the_content_area(self):
        self.assertIn('class="app-shell"', self.page)
        self.assertIn('<section id="dynamic-content" data-static-view="bill:HB486"', self.page)
        self.assertIn('<h1>HB 486: Relating to wildlife.</h1>', content(self.page))
        self.assertIn('<strong>AI summary (not official):</strong> Lets drivers keep roadkill.', content(self.page))
        self.assertIn('<div class="page-heading" hidden', self.page)  # The bill view has its own header.

    def test_keeps_every_element_the_app_looks_up(self):
        # The app writes into #page-title and the rest by id; one missing and its first view throws.
        for element in re.findall(r'\sid="([^"]+)"', INDEX):
            self.assertIn(f'id="{element}"', self.page, element)

    def test_never_redirects_and_loads_the_app_from_the_stable_entry_point(self):
        self.assertNotIn('location.replace', self.page)
        self.assertNotIn('#bill?id=', self.page)  # No "Open in" link back to the app: this page is the app.
        self.assertIn('<script type="module" src="/boot.js"></script>', self.page)
        self.assertIn('href="/app.css"', self.page)

    def test_every_script_has_a_src_is_json_ld_or_is_a_hashed_shell_script(self):
        hashed = re.findall(r'<script>(.*?)</script>', INDEX, re.S)
        for tag, body in re.findall(r'(<script[^>]*>)(.*?)</script>', self.page, re.S):
            if 'src=' in tag or tag == '<script type="application/ld+json">':
                continue
            self.assertEqual(tag, '<script>')
            self.assertIn(body, hashed)

    def test_head_tags_are_the_bills_and_appear_once(self):
        h = head(self.page)
        self.assertEqual(h.count('<title>'), 1)
        self.assertIn('<title>HB 486: Relating to wildlife. · Texas Bill Atlas</title>', h)
        self.assertEqual(h.count('rel="canonical"'), 1)
        self.assertIn('<link rel="canonical" href="https://billatlas.org/bill/HB486">', h)
        self.assertEqual(h.count('name="description"'), 1)
        self.assertEqual(h.count('property="og:url"'), 1)
        self.assertIn('<link rel="alternate" type="text/markdown" href="https://agent.billatlas.org/bills/HB486.md">', h)
        self.assertEqual(h.count('application/ld+json'), 2)  # Legislation and BreadcrumbList (SEO chunk 6).
        self.assertEqual(h.count('"@type":"Legislation"'), 1)
        self.assertIn('<link rel="icon" href="/favicon.ico" sizes="32x32">', h)
        self.assertIn('<link rel="apple-touch-icon" href="/apple-touch-icon.png">', h)

    def test_page_version_covers_the_bill_not_the_shell(self):
        other_shell = SHELL.replace('<html lang="en">', '<html lang="en" data-shell="2">')
        moved = bf.share_page(BILL, headline='Lets drivers keep roadkill.', shell=other_shell)
        self.assertNotEqual(moved, self.page)
        self.assertEqual(bf._page_version(moved), bf._page_version(self.page))
        self.assertNotEqual(bf._page_version(bf.share_page(BILL, headline='Another line.', shell=SHELL)),
                            bf._page_version(self.page))

    def test_without_a_shell_the_standalone_page_is_unchanged(self):
        page = bf.share_page(BILL)
        self.assertIn('location.replace("https://billatlas.org/#bill?id=HB486")', page)
        self.assertIsNone(bf._page_version(page))


class WriteSharePagesWithShell(unittest.TestCase):
    def test_a_new_shell_rewrites_pages_without_reporting_them_changed(self):
        snap = {'bills': [BILL, {'id': 'HB1', 'caption': 'A.'}]}
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            changed = []
            bf.write_share_pages(snap, out, changed=changed)  # standalone pages, as before the shell is deployed
            self.assertEqual(changed, ['HB486', 'HB1'])
            changed = []
            self.assertEqual(bf.write_share_pages(snap, out, changed=changed, shell=SHELL), (2, 0, 0))
            self.assertEqual(changed, ['HB486', 'HB1'])  # Moving into the shell is a real change, once.
            changed = []
            self.assertEqual(bf.write_share_pages(snap, out, changed=changed, shell=SHELL), (0, 2, 0))
            other_shell = SHELL.replace('<html lang="en">', '<html lang="en" data-shell="2">')
            self.assertEqual(bf.write_share_pages(snap, out, changed=changed, shell=other_shell), (2, 0, 0))
            self.assertEqual(changed, [])
            edited = {'bills': [dict(BILL, status='Referred'), {'id': 'HB1', 'caption': 'A.'}]}
            bf.write_share_pages(edited, out, changed=changed, shell=other_shell)
            self.assertEqual(changed, ['HB486'])
            self.assertIn('data-shell="2"', (out / 'HB1.html').read_text('utf-8'))


class ShellFromTheRelease(unittest.TestCase):
    def test_the_data_run_reads_the_shell_beside_the_current_release(self):
        self.assertEqual(pages.SHELL_PATH, Path('/var/www/html/texas-bill-atlas/current/shell.html'))

    def test_a_missing_shell_means_standalone_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(pages.load_shell(Path(folder) / 'shell.html'))


if __name__ == '__main__':
    unittest.main()
