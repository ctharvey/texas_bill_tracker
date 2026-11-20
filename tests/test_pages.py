"""Static pages built from the deployed shell, and the shell loader next to the site's releases."""
import base64
import hashlib
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))  # Linux-only lock; unused by these tests.
import deploy_static as deploy
import pages

INDEX = (ROOT / 'index.html').read_text(encoding='utf-8')
SHELL = deploy.shell_page(INDEX.encode()).decode()
MARKERS = ('<!--head-->', '<!--/head-->', '<!--heading-->', '<!--/heading-->', '<!--content-->', '<!--/content-->')
LD_JSON = '<script type="application/ld+json">'


def render(**kwargs) -> str:
    values = {'head': '<meta name="description" content="d">', 'content': '<p>body</p>', 'view': 'bill:HB1094'}
    values.update(kwargs)
    return pages.render_page(values.pop('shell', SHELL), **values)


def version(page: str) -> str:
    return re.search(r'<meta name="shell-version" content="([0-9a-f]+)">', page).group(1)


class RenderPageTests(unittest.TestCase):
    def test_fills_the_slots_and_keeps_the_markers(self):
        page = render(head='<title>Bill</title>', heading='<h1>HB 1094</h1>', content='<p>body</p>')
        for marker in MARKERS:
            self.assertEqual(page.count(marker), 1, marker)
        self.assertIn('<title>Bill</title>', page)
        self.assertIn('<h1>HB 1094</h1>', page)
        self.assertIn('<p>body</p>', page)

    def test_stamps_the_shell_version_into_the_head(self):
        page = render()
        self.assertEqual(version(page), pages.shell_version(SHELL))
        changed = render(shell=SHELL.replace('<html lang="en">', '<html lang="en" data-shell="2">'))
        self.assertNotEqual(version(changed), version(page))

    def test_tags_the_content_section_with_the_static_view(self):
        self.assertIn('<section id="dynamic-content" data-static-view="bill:HB1094"', render())
        self.assertIn('data-static-view="law:PE 46.06"', render(view='law:PE 46.06'))

    def test_no_heading_empties_the_slot_and_hides_the_page_heading(self):
        page = render(heading=None)
        self.assertIn('<!--heading--><h1 id="page-title"></h1><p id="page-subtitle"></p><!--/heading-->', page)
        self.assertIn('<div class="page-heading" hidden', page)
        self.assertNotIn('<div class="page-heading"><div>', page)

    def test_rejects_an_inline_script_but_allows_json_ld(self):
        bad = '<script>alert(1)</script>'
        for kwargs in ({'head': bad}, {'heading': bad}, {'content': bad}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                render(**kwargs)
        page = render(content=LD_JSON + '{"@type":"Legislation"}</script>')
        self.assertIn(LD_JSON, page)

    def test_rejects_a_bad_view(self):
        for view in ('home:HB1', 'bill', 'law:PE/46', 'member:A4875', 'bill:HB-1'):
            with self.subTest(view=view), self.assertRaises(ValueError):
                render(view=view)

    def test_rejects_a_missing_or_doubled_marker(self):
        for marker in MARKERS:
            with self.subTest(marker=marker, state='missing'), self.assertRaises(ValueError):
                pages.render_page(SHELL.replace(marker, ''), head='', content='', view='bill:HB1')
            with self.subTest(marker=marker, state='doubled'), self.assertRaises(ValueError):
                pages.render_page(SHELL + marker, head='', content='', view='bill:HB1')

    def test_every_script_is_hashed_or_has_a_src(self):
        page = render(head='<title>Bill</title>')
        allowed = re.findall(r'<script>(.*?)</script>', INDEX, re.S)
        policy = re.search(r'Content-Security-Policy" content="([^"]+)"', INDEX).group(1)
        for tag in re.findall(r'<script\b[^>]*>', page, re.IGNORECASE):
            if 'src=' in tag or tag.lower() == LD_JSON:
                continue
            body = page[page.index(tag) + len(tag):page.index('</script>', page.index(tag))]
            self.assertIn(body, allowed, 'inline script is not one the CSP already hashes')
            digest = "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
            self.assertIn(digest, policy)


class LoadShellTests(unittest.TestCase):
    def test_reads_a_shell_with_all_its_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'shell.html'
            path.write_text(SHELL, encoding='utf-8')
            self.assertEqual(pages.load_shell(path), SHELL)

    def test_missing_file_or_markers_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(pages.load_shell(Path(tmp) / 'missing.html'))
            path = Path(tmp) / 'no-markers.html'
            path.write_text('<html></html>', encoding='utf-8')
            self.assertIsNone(pages.load_shell(path))


if __name__ == '__main__':
    unittest.main()
