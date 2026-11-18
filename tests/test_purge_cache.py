"""The data run's Cloudflare purge: one prefix purge with the token, a skip without one, and a failing exit
(never a retry) when Cloudflare refuses or can't be reached."""
import contextlib
import io
import json
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


if __name__ == '__main__':
    unittest.main()
