"""The worker-loop scenarios of test_review_worker_loop.py and test_review_stages.py, driven through
`--transport flex`: the real review_pipeline.main / run_document, the real classify/extract code and a real
FlexBoundary, with only the OpenAI SDK faked. No network, no paid calls.
"""
import datetime as dt
import ftplib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import review_pipeline as pipeline  # noqa: E402
import flex_boundary  # noqa: E402
import cth_flex  # noqa: E402
import classify_bill as classification  # noqa: E402
import extract_bill as extraction  # noqa: E402
from extraction_cache import CapacityUnavailable, NotSubmitted  # noqa: E402

REAL_BOUNDARY = flex_boundary.FlexBoundary
REAL_CLIENT = flex_boundary.FlexClient
MODEL = classification.MODEL
BASE_TIME = 1_800_000_000.0
OK = {'model': MODEL, 'service_tier': 'flex', 'status': 'completed', 'output': [],
      'usage': {'input_tokens': 10, 'output_tokens': 5}}


class Reply:
    def __init__(self, body): self.body = body
    def model_dump(self, mode='json'): return self.body


class Err(Exception):
    def __init__(self, status, code, headers=None):
        super().__init__('provider error'); self.status_code = status; self.code = code
        self.response = types.SimpleNamespace(status_code=status, headers=headers or {})
        self.body = {'error': {'code': code}}


def capacity(retry_after=None):
    return Err(429, 'flex_unavailable', {'retry-after': str(retry_after)} if retry_after is not None else None)


class BillSDK:
    """Fake OpenAI SDK. `handler(bill_id, n)` returns a reply body or raises; `calls` lists the bill of every send."""
    def __init__(self, handler=None):
        self.handler, self.calls = handler or (lambda bill, n: OK), []
        self.responses = self

    def with_options(self, **kw): return self

    def create(self, **kw):
        bill = re.search(r'MARKER-([A-Z]+\d+)', json.dumps(kw['input']))[1]
        self.calls.append(bill)
        result = self.handler(bill, self.calls.count(bill))
        if isinstance(result, BaseException):
            raise result
        return Reply(result)


def document(bill_id, pages=None):
    return extraction.document_from_pages(bill_id, '90R', 'introduced', pages or [f'MARKER-{bill_id} A full bill.'])


class FlexLoopCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo, self.cache = base / 'repo', base / 'cache'
        (self.repo / 'data').mkdir(parents=True)
        self.ids = ['HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6', 'HB7', 'HB8']
        (self.repo / 'data' / 'bills.json').write_text(json.dumps({'bills': [{'id': i} for i in self.ids]}), 'utf-8')
        p = patch.object(pipeline, 'ROOT', self.repo); p.start(); self.addCleanup(p.stop)
        p = patch.object(pipeline.detailed, 'load_registry', return_value=[]); p.start(); self.addCleanup(p.stop)
        self.sdk, self.factory, self.sleeps, self.default_factory = BillSDK(), None, [], False
        self.clock = [0.0]
        self.boundary_args = []
        self.downloads = []

    # ---- fake time: the pipeline's monotonic clock, the cache/ledger wall clock and every sleep move together ----
    def fake_time(self):
        def sleep(seconds):
            self.sleeps.append(seconds); self.clock[0] += seconds
        wall = lambda: BASE_TIME + self.clock[0]
        for name, fake in (('sleep', sleep), ('monotonic', lambda: self.clock[0]), ('time', wall)):
            p = patch.object(pipeline.time, name, side_effect=fake); p.start(); self.addCleanup(p.stop)
        # FlexClient binds time.time at import, so give it the fake wall clock explicitly.
        p = patch.object(flex_boundary, 'FlexClient',
                         side_effect=lambda *a, **k: REAL_CLIENT(*a, clock=wall, **k)); p.start(); self.addCleanup(p.stop)
        self.sleep = sleep

    def make_boundary(self, cache_dir, daily, run):
        self.boundary_args.append((daily, run))
        kwargs = {'sleep': getattr(self, 'sleep', self.sleeps.append), 'log': lambda text: None}
        if not self.default_factory:
            kwargs['openai_factory'] = self.factory or (lambda: self.sdk)
        return REAL_BOUNDARY(cache_dir, daily, run, **kwargs)

    def run_main(self, download=None, *extra):
        def default_download(bill_id, root):
            self.downloads.append(bill_id); return document(bill_id)
        argv = ['review_pipeline.py', '--cache-dir', str(self.cache), '--execute', '--transport', 'flex', *extra]
        with patch.object(sys, 'argv', argv), patch.object(pipeline, 'download_document',
                                                           side_effect=download or default_download), \
                patch.object(flex_boundary, 'FlexBoundary', side_effect=self.make_boundary):
            pipeline.main()
        path = self.cache / 'queue.json'
        return json.loads(path.read_text('utf-8')) if path.exists() else {}

    def ledger_rows(self):
        path = self.cache / 'budget.json'
        ledger = json.loads(path.read_text('utf-8')) if path.exists() else {}
        return [row for day in ledger.values() for row in day.values()]


class OutageTests(FlexLoopCase):
    def test_ftp_outage_stops_after_consecutive_new_failures(self):
        calls = []
        def download(bill_id, root):
            calls.append(bill_id); raise OSError('connection refused')
        queue = self.run_main(download)
        self.assertEqual(len(calls), pipeline.OUTAGE_LIMIT)
        self.assertEqual(queue['seen'], [])
        self.assertEqual(self.sdk.calls, [])

    def test_known_failures_do_not_trip_the_outage_stop(self):
        failing = {'HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6'}
        def download(bill_id, root):
            if bill_id in failing:
                raise ftplib.error_perm('550')
            return document(bill_id)
        self.run_main(download)  # Stops at the 5th new failure.
        queue = self.run_main(download)
        self.assertIn('HB7', queue['seen']); self.assertIn('HB8', queue['seen'])
        self.assertEqual(queue['failed']['HB1']['count'], 2)

    def test_repeated_provider_rejections_stop_the_run(self):
        self.sdk = BillSDK(lambda bill, n: Err(400, 'invalid_request_error'))
        queue = self.run_main()
        self.assertEqual(len(self.sdk.calls), pipeline.OUTAGE_LIMIT)  # one send each, never retried
        self.assertEqual(queue['seen'], [])
        self.assertEqual(set(queue['failed']), set(self.ids[:pipeline.OUTAGE_LIMIT]))
        self.assertEqual({k: v for k, v in queue['failed']['HB1'].items() if k != 'at'},
                         {'count': 1, 'stage': 'processing', 'reason': 'ApiRejected'})
        self.assertNotIn('pending', [r['state'] for r in self.ledger_rows()])
        # The next run (two minutes later under the continuous timer) does not send the rejected bills again.
        self.sdk.handler = lambda bill, n: OK
        queue = self.run_main()
        self.assertEqual(self.sdk.calls[pipeline.OUTAGE_LIMIT:], self.ids[pipeline.OUTAGE_LIMIT:])
        self.assertEqual(set(queue['failed']), set(self.ids[:pipeline.OUTAGE_LIMIT]))

    def test_successful_first_pass_marks_every_bill_seen(self):
        queue = self.run_main()
        self.assertEqual(queue['seen'], self.ids)
        self.assertEqual(self.sdk.calls, self.ids)
        self.assertEqual([r['state'] for r in self.ledger_rows()], ['returned'] * len(self.ids))


class CapacityBackoffTests(FlexLoopCase):
    def setUp(self):
        super().setUp()
        self.fake_time()

    def test_first_pass_capacity_sets_bill_aside_and_continues_without_waiting(self):
        failures = {'HB2': 1}
        def handler(bill, n):
            if failures.get(bill):
                failures[bill] -= 1; return capacity(300)
            return OK
        self.sdk = BillSDK(handler)
        queue = self.run_main()
        # Every other bill runs immediately; the only wait is for HB2's cooldown once nothing else is left.
        self.assertEqual(self.sdk.calls, ['HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6', 'HB7', 'HB8', 'HB2'])
        self.assertEqual(self.sleeps, [301])
        self.assertEqual(queue['seen'], ['HB1', 'HB3', 'HB4', 'HB5', 'HB6', 'HB7', 'HB8', 'HB2'])

    def test_cooled_bill_is_revisited_as_soon_as_ready(self):
        def handler(bill, n):
            self.clock[0] += 100  # Each review takes real time, so HB1's cooldown passes mid-run.
            if bill == 'HB1' and n == 1:
                return capacity(150)  # Ready at t=251; HB3 finishes at t=300.
            return OK
        self.sdk = BillSDK(handler)
        self.run_main()
        self.assertEqual(self.sdk.calls, ['HB1', 'HB2', 'HB3', 'HB1', 'HB4', 'HB5', 'HB6', 'HB7', 'HB8'])
        self.assertEqual(self.sleeps, [])

    def test_cooled_bill_is_not_resent_before_its_cooldown_ends(self):
        # Counterexample for the flex cache: the bill's capacity_wait entry must still hold while others run.
        self.sdk = BillSDK(lambda bill, n: capacity(300) if (bill, n) == ('HB1', 1) else OK)
        queue = self.run_main(None, '--bill-id', 'HB1', '--max-minutes', '1')  # cooldown ends past this run's deadline
        self.assertEqual(self.sdk.calls, ['HB1'])
        self.assertEqual(queue.get('seen', []), [])
        self.clock[0] += 10  # a new run 10 s later, long before retry-after
        self.run_main(None, '--bill-id', 'HB1', '--max-minutes', '1')
        self.assertEqual(self.sdk.calls, ['HB1'])  # CacheCoolingDown: no second send
        self.clock[0] += 400
        queue = self.run_main(None, '--bill-id', 'HB1', '--max-minutes', '1')
        self.assertEqual(self.sdk.calls, ['HB1', 'HB1'])
        self.assertEqual(queue['seen'], ['HB1'])

    def test_sustained_outage_pauses_at_most_a_minute_and_runs_to_the_deadline(self):
        self.sdk = BillSDK(lambda bill, n: capacity())
        queue = self.run_main(None, '--max-minutes', '10')
        self.assertEqual(self.sleeps[:2], [30, 60])
        self.assertLessEqual(max(self.sleeps), 60)
        self.assertGreater(len(self.sdk.calls), len(self.ids))  # Kept trying instead of stopping at the first rejection.
        # The legacy test asserts <= 600 because it mocks run_document. Here the client's own 30 s + 60 s waits run
        # inside a bill that began before the deadline, so the run may overshoot by one bill's 90 s of waits.
        self.assertLessEqual(self.clock[0], 600 + 90)
        self.assertEqual(queue.get('seen', []), [])

    def test_success_resets_the_pause(self):
        failures = {'HB2': 1, 'HB3': 1, 'HB6': 1}
        def handler(bill, n):
            if failures.get(bill):
                failures[bill] -= 1; return capacity(1000)
            return OK
        self.sdk = BillSDK(handler)
        self.run_main()
        # HB2 then HB3 back to back: no pause, then 30 s. HB6 after successes: no pause again.
        self.assertEqual(self.sleeps[0], 30)
        self.assertNotIn(60, self.sleeps)

    def test_cooldown_past_the_deadline_leaves_bill_queued(self):
        self.sdk = BillSDK(lambda bill, n: capacity(600) if bill == 'HB2' else OK)
        queue = self.run_main(None, '--max-minutes', '5')
        self.assertEqual(self.sdk.calls, self.ids)
        self.assertEqual(self.sleeps, [])
        self.assertNotIn('HB2', queue['seen'])
        self.assertEqual(self.ledger_rows().count({'state': 'pending'}), 0)

    def test_budget_stop_is_not_retried(self):
        queue = self.run_main(None, '--daily-budget', '0.001', '--run-budget', '0.001')
        self.assertEqual((self.downloads, self.sleeps), (['HB1'], []))
        self.assertEqual(self.sdk.calls, [])  # the reservation was refused before any send
        self.assertEqual(queue.get('seen', []), [])
        self.assertEqual(self.ledger_rows(), [])

    def test_unknown_outcomes_hold_their_bills_until_the_held_cap_stops_the_run(self):
        self.sdk = BillSDK(lambda bill, n: TimeoutError('unknown submission outcome'))
        queue = self.run_main()
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.sdk.calls, ['HB1', 'HB2', 'HB3'])  # each sent once, never resent; HB4 refused unsent
        self.assertEqual([(r['state'], r['held']) for r in self.ledger_rows()], [('returned', True)] * 3)
        self.assertEqual({b: f['stage'] for b, f in queue['failed'].items()},
                         {'HB1': 'held', 'HB2': 'held', 'HB3': 'held'})
        self.assertEqual(queue.get('seen', []), [])
        self.sdk.handler = lambda bill, n: self.fail('Must not send while three calls are held')
        self.run_main()  # the cap is durable: the next run sends nothing either
        self.assertEqual(self.sdk.calls, ['HB1', 'HB2', 'HB3'])


class FirstPassStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)
        self.sdk = BillSDK()
        self.doc = document('HB9')
        self.request = classification.build_request(self.doc, [])

    def run_with(self, execute=True, daily=None, run=None, factory=None, doc=None, **_):
        boundary = REAL_BOUNDARY(self.cache, daily, run, openai_factory=factory or (lambda: self.sdk),
                                 sleep=lambda s: None, log=lambda t: None)
        out = pipeline.run_document(doc or self.doc, [], self.cache, boundary, execute)
        self.assertEqual(self.sdk.calls, [])  # none of these obstacles may reach the provider
        return out

    def test_long_context_is_per_bill_and_does_not_stop_the_run(self):
        big = document('HB9', ['MARKER-HB9 ' + 'x' * 300000])
        out = self.run_with(doc=big)
        self.assertEqual((out['status'], out['first_pass']['reason_type']), ('needs_review', 'LongContext'))

    def test_already_billed_is_per_bill_and_does_not_stop_the_run(self):
        key = REAL_BOUNDARY.key(self.request)
        (self.cache / 'budget.json').write_text(json.dumps(
            {'2026-11-09': {key: {'state': 'returned', 'cost': 0.01, 'reserved': 0}}}), 'utf-8')
        out = self.run_with()
        self.assertEqual((out['status'], out['first_pass']['reason_type']), ('needs_review', 'AlreadyBilled'))

    def test_budget_and_unresolved_outcomes_stop_the_run(self):
        out = self.run_with(daily=.001, run=.001)
        self.assertEqual((out['status'], out['first_pass']['reason_type']), ('deferred', 'BudgetExceeded'))
        (self.cache / 'budget.json').write_text(json.dumps(
            {'2026-11-09': {'other': {'state': 'pending', 'reserved': 0.01}}}), 'utf-8')
        out = self.run_with()
        self.assertEqual((out['status'], out['first_pass']['reason_type']), ('deferred', 'OutcomeUnresolved'))

    def test_dry_run_is_prepared_not_reviewed(self):
        out = self.run_with(execute=False)
        self.assertEqual((out['status'], out['first_pass']['reason_type']), ('prepared', 'NotSubmitted'))

    def test_environmental_not_submitted_stops_the_run(self):
        # e.g. OPENAI_API_KEY missing: must not be treated as a per-bill problem and mark every bill seen.
        def factory():
            raise cth_flex.NotSent('OPENAI_API_KEY is required for execution on a cache miss')
        out = self.run_with(factory=factory)
        self.assertEqual((out['status'], out['first_pass']['reason_type']), ('deferred', 'NotSubmitted'))


class EnvironmentFailureLoopTests(FlexLoopCase):
    def test_missing_key_stops_after_first_bill_without_marking_seen(self):
        self.default_factory = True  # the real default factory, with no key in the environment
        with patch.dict(os.environ):
            os.environ.pop('OPENAI_API_KEY', None)
            queue = self.run_main()
        self.assertEqual(self.downloads, ['HB1'])
        self.assertEqual(queue.get('seen', []), [])
        self.assertEqual(self.sdk.calls, [])
        self.assertEqual(self.ledger_rows(), [])

    def test_quota_on_the_first_bill_ends_the_run_with_exit_2(self):
        self.sdk = BillSDK(lambda bill, n: Err(429, 'insufficient_quota'))
        with self.assertRaises(SystemExit) as caught:
            self.run_main()
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.sdk.calls, ['HB1'])  # one send, not three
        self.assertEqual(self.downloads, ['HB1'])  # the remaining bills are never visited
        queue_path = self.cache / 'queue.json'
        queue = json.loads(queue_path.read_text('utf-8')) if queue_path.exists() else {}
        self.assertEqual(queue.get('seen', []), [])
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.ledger_rows(), [])  # nothing billed, nothing pending

    def test_auth_failure_ends_the_run_the_same_way(self):
        self.sdk = BillSDK(lambda bill, n: Err(401, 'invalid_api_key'))
        with self.assertRaises(SystemExit) as caught:
            self.run_main()
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual((self.sdk.calls, self.downloads), (['HB1'], ['HB1']))

    def test_flex_transport_validates_limits_like_legacy(self):
        with self.assertRaises(ValueError):
            self.run_main(None, '--daily-budget', '2')
        self.assertEqual(self.boundary_args, [])  # refused before a boundary exists
        self.run_main(None, '--no-spending-cap', '--max-bills', '1')
        self.assertEqual(self.boundary_args, [(None, None)])


class LedgerDayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.path = self.dir / 'budget.json'
        self.sdk = BillSDK(lambda bill, n: OK)
        self.request = {'model': MODEL, 'max_output_tokens': 5000, 'input': 'MARKER-HB1 Source',
                        'service_tier': 'flex', 'prompt_cache_options': {'mode': 'explicit'}}

    def boundary(self, daily=1, run=.1):
        return REAL_BOUNDARY(self.dir, daily, run, openai_factory=lambda: self.sdk, sleep=lambda s: None,
                             log=lambda t: None)

    def go(self, b, request=None):
        request = request or self.request
        return b.execute(request, lambda: b.send(request))

    def test_spend_after_chicago_midnight_books_to_the_new_day(self):
        b = self.boundary()
        days = iter(['2026-11-09', '2026-11-10'])
        with patch.object(b.spend, 'day', side_effect=lambda: next(days)):
            self.go(b)
            self.go(b, {**self.request, 'input': 'MARKER-HB2 Source'})
        ledger = json.loads(self.path.read_text('utf-8'))
        self.assertEqual(set(ledger), {'2026-11-09', '2026-11-10'})
        for day in ledger.values():
            self.assertEqual([r['state'] for r in day.values()], ['returned'])
            self.assertGreater(sum(r['cost'] for r in day.values()), 0)

    def test_previous_day_spend_does_not_count_against_today(self):
        self.path.write_text(json.dumps({'2026-11-09': {'old': {'state': 'returned', 'cost': 0.999, 'reserved': 0}}}))
        b = self.boundary()
        with patch.object(b.spend, 'day', return_value='2026-11-10'):
            self.assertFalse(self.go(b).cache_hit)  # the old day's $0.999 leaves room under $1
        # Counterexample: the same spend booked today does block.
        self.setUp()
        self.path.write_text(json.dumps({'2026-11-10': {'old': {'state': 'returned', 'cost': 0.999, 'reserved': 0}}}))
        b = self.boundary()
        with patch.object(b.spend, 'day', return_value='2026-11-10'):
            with self.assertRaises(pipeline.BudgetExceeded):
                self.go(b)
        self.assertEqual(self.sdk.calls, [])

    def test_ledger_day_uses_chicago_time(self):
        b = self.boundary()
        self.assertEqual(b.spend.zone.key, 'America/Chicago')
        self.assertEqual(b.spend.day(), dt.datetime.now(ZoneInfo('America/Chicago')).date().isoformat())

    def test_oversized_request_is_a_long_context_not_submitted(self):
        big = {**self.request, 'input': 'x' * 300000}
        with self.assertRaises(pipeline.LongContext) as caught:
            self.go(self.boundary(), big)
        self.assertIsInstance(caught.exception, NotSubmitted)
        self.assertEqual(self.sdk.calls, [])


if __name__ == '__main__':
    unittest.main()
