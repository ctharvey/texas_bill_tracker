"""The data run's Cloudflare purge: one prefix purge with the token, a skip without one, and a failing exit
(never a retry) when Cloudflare refuses or can't be reached."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import purge_cache as pc


class Response:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def run(environ, opener):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = pc.main(environ, opener)
    return code, out.getvalue()


class PurgeCacheTest(unittest.TestCase):
    def setUp(self):
        self.environ = {'CF_PURGE_TOKEN': 'secret-token\n'}

    def test_purges_the_data_run_prefixes_with_the_token(self):
        sent = []

        def opener(request, timeout):
            sent.append(request)
            return Response({'success': True, 'result': {'id': 'x'}})

        code, out = run(self.environ, opener)
        self.assertEqual(code, 0)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].get_method(), 'POST')
        self.assertEqual(sent[0].full_url, pc.ENDPOINT)
        self.assertEqual(sent[0].get_header('Authorization'), 'Bearer secret-token')
        prefixes = json.loads(sent[0].data)['prefixes']
        self.assertIn('billatlas.org/live/bills.json', prefixes)
        self.assertIn('billatlas.org/live/feeds/', prefixes)
        self.assertFalse(any(p.startswith(('billatlas.org/live/luna', 'billatlas.org/live/og', 'billatlas.org/live/members'))
                             for p in prefixes), 'paths with other writers keep the 5-minute rule and are not purged')
        self.assertLessEqual(len(prefixes), 100)
        self.assertIn('prefixes purged', out)
        self.assertNotIn('secret-token', out)

    def test_no_credential_skips_without_sending(self):
        for environ in ({}, {'CF_PURGE_TOKEN': '  '}):
            code, out = run(environ, lambda *a, **k: self.fail('sent'))
            self.assertEqual(code, 0)
            self.assertIn('skipped', out)

    def test_refusals_and_outages_fail_once_without_leaking_the_token(self):
        calls = []

        def limited(request, timeout):
            calls.append(1)
            raise urllib.error.HTTPError(request.full_url, 429, 'Too Many Requests', {}, io.BytesIO())

        def offline(request, timeout):
            raise urllib.error.URLError('down')

        def refused(request, timeout):
            return Response({'success': False, 'errors': [{'code': 10000, 'message': 'auth'}]})

        for opener, expected in ((limited, 'HTTP 429'), (offline, 'failed: URLError'), (refused, 'not accepted (10000)')):
            code, out = run(self.environ, opener)
            self.assertEqual(code, 1)
            self.assertIn(expected, out)
            self.assertNotIn('secret-token', out)
        self.assertEqual(len(calls), 1, 'a refused purge is never retried')


class SelectivePurgeTest(unittest.TestCase):
    """With a live folder: only files changed since the last successful purge are purged, and a failed purge is
    carried into the next run instead of being lost."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name)
        self.environ = {'CF_PURGE_TOKEN': 'secret-token'}
        self.clock = 1_800_000_000
        for rel in ('bills.json', 'sitemap.xml', 'share/HB1.html', 'share/HB2.html', 'feeds/HB1.xml', 'text/HB1/1.md'):
            self.write(rel, 'v1')
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.live / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self.clock += 10  # Each write gets its own modification time, as on the server.
        os.utime(path, ns=(self.clock * 10**9, self.clock * 10**9))

    def opener(self, ok=True):
        def send(request, timeout):
            self.sent.append(json.loads(request.data)['prefixes'])
            if not ok:
                raise urllib.error.HTTPError(request.full_url, 429, 'Too Many Requests', {}, io.BytesIO())
            return Response({'success': True})
        return send

    def run_purge(self, ok=True):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = pc.main(self.environ, self.opener(ok), live=self.live, now=self.clock)
        return code, out.getvalue()

    def state(self):
        return json.loads((self.live / pc.STATE_NAME).read_text())

    def test_first_run_purges_everything_and_records_the_files(self):
        code, out = self.run_purge()
        self.assertEqual(code, 0)
        self.assertEqual(self.sent, [pc.PREFIXES])
        self.assertIn('everything', out)
        self.assertIn('share/HB1.html', self.state()['files'])
        self.assertIsNone(self.state()['pending_since'])

    def test_an_unchanged_run_sends_nothing(self):
        self.run_purge()
        code, out = self.run_purge()
        self.assertEqual((code, len(self.sent)), (0, 1))
        self.assertIn('nothing changed', out)

    def test_only_added_rewritten_and_deleted_files_are_purged(self):
        self.run_purge()
        self.write('share/HB1.html', 'v2')
        self.write('text/HB1/2.md', 'new')
        (self.live / 'feeds/HB1.xml').unlink()
        self.write('luna/tags.json', 'other writer')  # Not a data-run path: never purged here.
        self.run_purge()
        self.assertEqual(self.sent[-1], ['billatlas.org/live/feeds/HB1.xml', 'billatlas.org/live/share/HB1.html',
                                         'billatlas.org/live/text/HB1/2.md'])

    def test_a_failed_purge_is_retried_with_the_next_runs_changes(self):
        self.run_purge()
        self.write('share/HB1.html', 'v2')
        code, _ = self.run_purge(ok=False)
        self.assertEqual(code, 1)
        failed = self.state()
        self.assertIsNotNone(failed['pending_since'])
        self.write('share/HB2.html', 'v2')
        code, _ = self.run_purge()
        self.assertEqual(code, 0)
        self.assertEqual(self.sent[-1], ['billatlas.org/live/share/HB1.html', 'billatlas.org/live/share/HB2.html'])
        self.assertIsNone(self.state()['pending_since'])

    def test_a_failure_before_any_success_purges_everything_next_time(self):
        self.run_purge(ok=False)
        self.run_purge()
        self.assertEqual(sorted(self.sent[-1]), sorted(f'billatlas.org/live/{p}' for p in
                         ('bills.json', 'sitemap.xml', 'share/HB1.html', 'share/HB2.html', 'feeds/HB1.xml', 'text/HB1/1.md')))

    def test_more_than_100_changes_purge_the_busiest_folder_whole(self):
        self.run_purge()
        for n in range(150):
            self.write(f'share/SB{n + 1}.html', 'x')
        self.write('feeds/HB1.xml', 'v2')
        self.run_purge()
        self.assertEqual(self.sent[-1], ['billatlas.org/live/feeds/HB1.xml', 'billatlas.org/live/share/'])

    def test_a_state_for_other_paths_purges_everything(self):
        self.run_purge()
        state = self.state()
        state['paths'] = ['bills.json']
        (self.live / pc.STATE_NAME).write_text(json.dumps(state))
        self.run_purge()
        self.assertEqual(self.sent[-1], pc.PREFIXES)


if __name__ == '__main__':
    unittest.main()
