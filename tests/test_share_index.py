"""Share pages are worth indexing (bill record and text in plain HTML), crawlers stay on them, and changed pages
are submitted to IndexNow from the server's live run only."""
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_feeds as bf

BILL = {'id': 'HB486', 'caption': 'Relating to wildlife.', 'status': 'Filed', 'filed_at': '2026-11-09',
        'last_action': '11/09/2026 H Filed', 'authors': ['Leo Wilson'], 'coauthors': [], 'subjects': ['Wildlife']}
TEXT = ({'code': 'I', 'name': 'Introduced'},
        '# HB 486 - Introduced\n\nAN ACT\n\n### SECTION 1.\n\n'
        '(1) raptors; \\[<del>or</del>\\]\n\n<ins>(3) roadkill</ins>.\n\nA <script>alert(1)</script> line & more.\n')


def body(html: str) -> str:
    return html.split('<body>', 1)[1]


class ShareBody(unittest.TestCase):
    def test_the_page_carries_the_official_record_and_links(self):
        page = body(bf.share_page(BILL, text=TEXT))
        self.assertIn('<h1>HB 486: Relating to wildlife.</h1>', page)
        for fact in ('<dt>Status</dt><dd>Filed</dd>', '<dt>Filed</dt><dd>Nov 9, 2026</dd>',
                     '<dt>Most recent action</dt><dd>11/09/2026 H Filed</dd>', '<dt>Authors</dt><dd>Leo Wilson</dd>',
                     '<dt>Official subjects</dt><dd>Wildlife</dd>'):
            self.assertIn(fact, page)
        self.assertNotIn('Coauthors', page)  # empty lists are left out
        self.assertIn('href="https://billatlas.org/live/text/HB486/I.md"', page)
        self.assertIn('href="https://agent.billatlas.org/bills/HB486.md"', page)
        self.assertIn('href="https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&amp;Bill=HB486"', page)

    def test_bill_text_keeps_its_marks_and_escapes_everything_else(self):
        page = body(bf.share_page(BILL, text=TEXT))
        self.assertIn('<h2>Bill text (Introduced)</h2>', page)
        self.assertIn('<h3>SECTION 1.</h3>', page)
        self.assertIn('<p>(1) raptors; [<del>or</del>]</p>', page)
        self.assertIn('<p><ins>(3) roadkill</ins>.</p>', page)
        self.assertIn('A &lt;script&gt;alert(1)&lt;/script&gt; line &amp; more.', page)
        self.assertNotIn('HB 486 - Introduced', page)  # the copy's own heading is dropped

    def test_long_text_is_cut_at_a_line_with_a_link_to_the_rest(self):
        long = ({'code': 'E', 'name': 'Engrossed'}, '\n\n'.join(f'Line {i} ' + 'x' * 90 for i in range(100)))
        html, cut = bf.share_text_html(long[1])
        self.assertTrue(cut)
        self.assertLess(len(re.sub('<[^>]+>', '', html)), bf.SHARE_TEXT_MAX + 200)
        self.assertIn('The text continues: <a href="https://billatlas.org/live/text/HB486/E.md">', bf.share_page(BILL, text=long))
        self.assertFalse(bf.share_text_html(TEXT[1])[1])

    def test_without_text_the_page_still_has_the_record(self):
        page = body(bf.share_page(BILL))
        self.assertNotIn('Bill text', page)
        self.assertIn('<dt>Status</dt>', page)

    def test_an_ai_line_is_labelled_and_escaped(self):
        page = body(bf.share_page(BILL, headline='Lets <b>drivers</b> keep roadkill.'))
        self.assertIn('<strong>AI summary (not official):</strong> Lets &lt;b&gt;drivers&lt;/b&gt; keep roadkill.', page)


class CrawlerRedirect(unittest.TestCase):
    def test_people_are_sent_to_the_app_and_crawlers_stay(self):
        html = bf.share_page(BILL)
        script = re.search(r'<script>(if\(.*?)</script>', html).group(1)
        self.assertTrue(script.endswith('location.replace("https://billatlas.org/#bill?id=HB486")'))
        pattern = re.compile(re.search(r'!/(.*?)/i\.test', script).group(1), re.I)
        for crawler in ('Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                        'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0) Chrome/116',
                        'Mozilla/5.0 (compatible; YandexBot/3.0)', 'Mozilla/5.0 (compatible; Baiduspider/2.0)',
                        'Mozilla/5.0 Google-InspectionTool/1.0'):
            self.assertTrue(pattern.search(crawler), crawler)
        for person in ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36',
                       'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'):
            self.assertFalse(pattern.search(person), person)

    def test_agents_get_the_page_with_the_markdown_record_advertised(self):
        # Every visitor gets this page at /bill/<ID>; agents choose the Markdown record from the link.
        html = bf.share_page(BILL)
        self.assertIn('<link rel="alternate" type="text/markdown" href="https://agent.billatlas.org/bills/HB486.md">',
                      html.split('</head>')[0])
        pattern = re.compile(re.search(r'!/(.*?)/i\.test', html).group(1), re.I)
        for agent in ('Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)',
                      'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)'):
            self.assertTrue(pattern.search(agent), agent)


class WriteSharePages(unittest.TestCase):
    def test_changed_lists_only_rewritten_pages_and_text_is_read_from_the_text_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'text' / 'HB486').mkdir(parents=True)
            (base / 'text' / 'HB486' / 'index.json').write_text(json.dumps(
                {'bill_id': 'HB486', 'versions': [{'code': 'I', 'name': 'Introduced'}]}), 'utf-8')
            (base / 'text' / 'HB486' / 'I.md').write_text(TEXT[1], 'utf-8')
            snap = {'bills': [BILL, {'id': 'HB1', 'caption': 'A.'}]}
            changed = []
            bf.write_share_pages(snap, base / 'share', text_dir=base / 'text', changed=changed)
            self.assertEqual(changed, ['bill/HB486', 'bill/HB1'])
            self.assertIn('<ins>(3) roadkill</ins>', (base / 'share' / 'HB486.html').read_text('utf-8'))
            changed = []
            bf.write_share_pages(snap, base / 'share', text_dir=base / 'text', changed=changed)
            self.assertEqual(changed, [])


class Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class IndexNow(unittest.TestCase):
    def test_the_key_file_is_published_at_the_site_root(self):
        key_file = ROOT / 'public' / f'{bf.INDEXNOW_KEY}.txt'
        self.assertEqual(key_file.read_text('utf-8').strip(), bf.INDEXNOW_KEY)
        self.assertRegex(bf.INDEXNOW_KEY, r'^[a-f0-9]{32}$')

    def test_payload_names_the_host_key_and_bill_pages(self):
        payload = bf.indexnow_payload(['bill/HB1', 'bill/SB2'])
        self.assertEqual(payload, {'host': 'billatlas.org', 'key': bf.INDEXNOW_KEY,
                                   'keyLocation': f'https://billatlas.org/{bf.INDEXNOW_KEY}.txt',
                                   'urlList': ['https://billatlas.org/bill/HB1', 'https://billatlas.org/bill/SB2']})
        self.assertEqual(len(bf.indexnow_payload([f'bill/HB{i}' for i in range(12000)])['urlList']), bf.INDEXNOW_MAX_URLS)

    def test_submission_posts_json_and_reports_the_status(self):
        sent = []

        def opener(request, timeout):
            sent.append(request)
            return Response(202)
        self.assertEqual(bf.submit_indexnow(['bill/HB1'], opener=opener), 'HTTP 202 for 1 pages')
        self.assertEqual(sent[0].get_method(), 'POST')
        self.assertEqual(sent[0].full_url, bf.INDEXNOW_ENDPOINT)
        self.assertEqual(json.loads(sent[0].data)['urlList'], ['https://billatlas.org/bill/HB1'])

    def test_nothing_changed_sends_nothing_and_failures_never_raise(self):
        self.assertEqual(bf.submit_indexnow([], opener=lambda *a, **k: self.fail('sent')), 'nothing changed')

        def refused(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, 'Forbidden', {}, io.BytesIO())

        def offline(request, timeout):
            raise urllib.error.URLError('down')
        self.assertEqual(bf.submit_indexnow(['bill/HB1'], opener=refused), 'HTTP 403 for 1 pages (not accepted)')
        self.assertEqual(bf.submit_indexnow(['bill/HB1'], opener=offline), 'failed: URLError')


if __name__ == '__main__':
    unittest.main()
