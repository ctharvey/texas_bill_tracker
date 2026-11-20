"""Law sections and chapters with no static page, rendered on request by the sync service (law_on_demand.py):
noindex, self canonical, current text, a real 404 for keys not in the law copy."""
import http.client
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))  # Linux-only lock; unused by these tests.
import build_feeds as bf
import check_pages as cp
import deploy_static as deploy
import law_on_demand as lod
import sync_service as svc
from test_law_context import write_law

SHELL = deploy.shell_page((ROOT / 'index.html').read_text(encoding='utf-8').encode()).decode()
SITE = 'https://billatlas.org/'
STATUTES = {'sections': {'GV 2271.002': {'h': 'PROVISION REQUIRED IN CONTRACT', 'b': [['HB10', 'm']]}},
            'chapters': {'GV 2271': {'h': 'PROHIBITION ON CONTRACTS', 'b': [['SB5', 'r']]}}}


def head(page: str) -> str:
    return page.split('</head>', 1)[0]


def content(page: str) -> str:
    return page.split('<!--content-->', 1)[1].split('<!--/content-->', 1)[0]


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.law = write_law(self.base)
        self.statutes = self.base / 'statutes.json'
        self.statutes.write_text(json.dumps(STATUTES), 'utf-8')
        self.shell = self.base / 'shell.html'
        self.shell.write_text(SHELL, 'utf-8')
        self.pages = lod.LawPages(self.law, self.statutes, self.shell)
        (self.base / 'bills.json').write_text('{"bills": []}', 'utf-8')
        store = svc.Store(self.base / 'sync.db'); self.addCleanup(store.close)
        self.app = svc.App(store, svc.Snapshot(self.base / 'bills.json'), law_pages=self.pages)

    def get(self, path, method='GET', peer='203.0.113.9'):
        try:
            status, headers, body = self.app.handle(method, path, {}, None, peer)
        except svc.Rejected as error:
            return error.status, {}, error.message
        return status, headers, body.decode('utf-8')


class SectionPages(Fixture):
    def test_an_untouched_section_has_its_own_head_and_current_text(self):
        status, headers, page = self.get('/law/GV/2271.001')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'text/html; charset=utf-8')
        self.assertEqual(headers['X-Robots-Tag'], 'noindex, follow')
        self.assertEqual(headers['Cache-Control'], 'no-cache')
        self.assertIn('<title>Government Code § 2271.001: DEFINITIONS · Texas Bill Atlas</title>', head(page))
        self.assertIn('<link rel="canonical" href="https://billatlas.org/law/GV/2271.001">', head(page))
        self.assertIn('<meta name="robots" content="noindex, follow">', head(page))
        self.assertIn('<section id="dynamic-content" data-static-view="law:GV 2271.001"', page)
        body = content(page)
        self.assertIn('No bill in the 90th Legislature changes this section yet', body)
        self.assertIn('<h2>Current law</h2>', body)
        self.assertIn('Boycott Israel', body)
        self.assertIn('<a href="https://billatlas.org/law/GV/2271">', body)  # Its chapter, rendered on request too.
        self.assertNotIn('<ul>\n\n</ul>', body)
        description = re.search(r'<meta name="description" content="([^"]*)"', page)[1]
        self.assertTrue(description.startswith('The current text of Government Code § 2271.001.'), description)

    def test_a_section_in_the_statute_index_lists_its_bills(self):
        # Between the index update and the data run writing its page, the on-demand page says the same thing.
        status, _headers, page = self.get('/law/GV/2271.002')
        self.assertEqual(status, 200)
        self.assertIn('/bill/HB10', content(page))
        self.assertIn('1 bill in the 90th Legislature would change this section', content(page))

    def test_the_page_passes_the_crawl_checker_rules_it_is_held_to(self):
        _status, _headers, page = self.get('/law/GV/2271.002')
        found = cp.inspect(page, SITE + 'law/GV/2271.002')
        self.assertEqual(found['failures'], [])
        self.assertEqual(found['canonical'], SITE + 'law/GV/2271.002')
        self.assertIn('noindex', found['robots'])


class ChapterPages(Fixture):
    def test_an_untouched_chapter_lists_every_section(self):
        status, headers, page = self.get('/law/GV/403')
        self.assertEqual(status, 200)
        self.assertEqual(headers['X-Robots-Tag'], 'noindex, follow')
        self.assertIn('<link rel="canonical" href="https://billatlas.org/law/GV/403">', head(page))
        self.assertIn('<meta name="robots" content="noindex, follow">', head(page))
        self.assertIn('data-static-view="chapter:GV 403"', page)
        body = content(page)
        self.assertIn('No bill in the 90th Legislature changes this chapter yet', body)
        self.assertIn('<h3>Sections in this chapter</h3>', body)
        self.assertIn('<a href="https://billatlas.org/law/GV/403.606">§ 403.606</a>: CERTAIN PERSONS INELIGIBLE', body)

    def test_a_chapter_in_the_statute_index_lists_its_bills(self):
        _status, _headers, page = self.get('/law/GV/2271')
        self.assertIn('Bills that change the whole chapter', content(page))
        self.assertIn('/bill/SB5', content(page))
        self.assertIn('<a href="https://billatlas.org/law/GV/2271.002">', content(page))


class Addresses(Fixture):
    def test_keys_not_in_the_law_copy_are_a_real_404(self):
        for path in ('/law/GV/999.99', '/law/GV/2271.999', '/law/GV/999', '/law/ZZ/1.01', '/law/GV/1.' + '1' * 20,
                     '/law/GV/abc', '/law/GV'):
            status, headers, page = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertEqual(headers['X-Robots-Tag'], 'noindex', path)
            self.assertIn('Not in our copy of Texas law', page, path)

    def test_other_spellings_redirect_to_the_canonical_address_after_the_key_is_found(self):
        self.assertEqual(self.get('/law/gv/2271.001')[:2][0], 301)
        self.assertEqual(self.get('/law/gv/2271.001')[1]['Location'], '/law/GV/2271.001')
        self.assertEqual(self.get('/law/GV/403/')[1]['Location'], '/law/GV/403')
        self.assertEqual(self.get('/law/gv/999.99')[0], 404)  # Never a redirect to a page that does not exist.

    def test_a_query_string_is_ignored(self):
        self.assertEqual(self.get('/law/GV/403?utm_source=x')[0], 200)

    def test_only_get_and_head(self):
        self.assertEqual(self.get('/law/GV/403', 'HEAD')[0], 200)
        self.assertEqual(self.get('/law/GV/403', 'POST')[0], 405)

    def test_unavailable_without_the_shell_or_the_law_copy(self):
        self.shell.unlink()
        self.assertEqual(self.get('/law/GV/403')[0], 503)
        self.shell.write_text(SHELL, 'utf-8')
        pages = lod.LawPages(self.base / 'missing', None, self.shell)
        store = svc.Store(self.base / 'other.db'); self.addCleanup(store.close)
        app = svc.App(store, svc.Snapshot(self.base / 'bills.json'), law_pages=pages)
        with self.assertRaises(svc.Rejected) as caught:
            app.handle('GET', '/law/GV/403', {}, None, '203.0.113.9')
        self.assertEqual(caught.exception.status, 503)

    def test_works_without_a_statute_index(self):
        pages = lod.LawPages(self.law, None, self.shell)
        self.assertEqual(pages.render('/law/GV/403.606')[0], 200)

    def test_a_refreshed_law_copy_is_read_again(self):
        self.assertEqual(self.get('/law/GV/2271.003')[0], 404)
        index = json.loads((self.law / 'GV' / 'index.json').read_text('utf-8'))
        index['chapters']['2271']['sections'].append(['2271.003', 'Sec. 2271.003. NEW.'])
        (self.law / 'GV' / 'index.json').write_text(json.dumps(index), 'utf-8')
        top = self.law / 'index.json'
        top.write_text(top.read_text('utf-8') + ' ', 'utf-8')
        import os
        stat = top.stat()
        os.utime(top, (stat.st_atime, stat.st_mtime + 5))
        self.assertEqual(self.get('/law/GV/2271.003')[0], 200)

    def test_law_pages_have_their_own_rate_limit(self):
        self.app.limiter = svc.RateLimiter({**svc.LIMITS, 'law': (2, 3600)})
        self.assertEqual(self.get('/law/GV/403')[0], 200)
        self.assertEqual(self.get('/law/GV/403')[0], 200)
        self.assertEqual(self.get('/law/GV/403')[0], 429)
        self.assertEqual(self.get('/law/GV/403', peer='198.51.100.7')[0], 200)

    def test_without_law_pages_the_service_does_not_answer_law_addresses(self):
        store = svc.Store(self.base / 'plain.db'); self.addCleanup(store.close)
        app = svc.App(store, svc.Snapshot(self.base / 'bills.json'))
        with self.assertRaises(svc.Rejected) as caught:
            app.handle('GET', '/law/GV/403', {}, None, '203.0.113.9')
        self.assertEqual(caught.exception.status, 404)


class OverHttp(Fixture):
    """The handler's own header merge and HEAD handling."""

    def setUp(self):
        super().setUp()
        self.server = svc.Server(('127.0.0.1', 0), svc.make_handler(self.app))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True); thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=5)
        self.addCleanup(conn.close)
        conn.request(method, path)
        response = conn.getresponse()
        return response, response.read()

    def test_get_keeps_the_page_cache_header_and_head_sends_no_body(self):
        response, body = self.request('GET', '/law/GV/403')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Cache-Control'), 'no-cache')
        self.assertEqual(response.getheader('X-Robots-Tag'), 'noindex, follow')
        self.assertEqual(int(response.getheader('Content-Length')), len(body))
        response, body = self.request('HEAD', '/law/GV/403')
        self.assertEqual(response.status, 200)
        self.assertEqual(body, b'')
        self.assertGreater(int(response.getheader('Content-Length')), 0)

    def test_sync_answers_stay_no_store(self):
        response, _body = self.request('GET', '/api/sync/health')
        self.assertEqual(response.getheader('Cache-Control'), 'no-store')


if __name__ == '__main__':
    unittest.main()
