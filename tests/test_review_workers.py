"""--workers N: counterexamples for concurrent review calls. Real threads, the real pipeline loop, FlexBoundary,
cache and ledger; only the OpenAI SDK is faked. Barriers force the interleavings instead of hoping for them."""
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_flex_worker_loop import BillSDK, FlexLoopCase, OK, capacity  # noqa: E402
import flex_boundary  # noqa: E402
import review_pipeline as pipeline  # noqa: E402
from extraction_cache import CacheBusy  # noqa: E402

TIMEOUT = 10


def both_in_flight(pair=('HB1', 'HB2'), then=None):
    """Handler: the first sends of `pair` wait until both are inside `create`, then return `then(bill)` or OK."""
    barrier = threading.Barrier(2, timeout=TIMEOUT)

    def handler(bill, n):
        if bill in pair and n == 1:
            barrier.wait()
            if then is not None:
                return then(bill)
        return OK
    return handler


class ConcurrentWorkerTests(FlexLoopCase):
    def run_workers(self, *extra, workers=2):
        return self.run_main(None, '--workers', str(workers), *extra)

    def test_two_bills_are_in_flight_at_once(self):
        # Fails (BrokenBarrierError -> SystemExit) if the second bill only starts after the first one returns.
        self.sdk = BillSDK(both_in_flight())
        queue = self.run_workers()
        self.assertEqual(sorted(queue['seen']), sorted(self.ids))
        self.assertEqual(sorted(self.sdk.calls), sorted(self.ids))  # every bill sent exactly once
        self.assertEqual([r['state'] for r in self.ledger_rows()], ['returned'] * len(self.ids))

    def test_unknown_outcome_on_one_worker_stops_new_calls_and_blocks_the_next_run(self):
        # HB1 times out (maybe billed) while HB2 is still in flight. HB2 still settles; nothing new is sent.
        hb2_may_return = threading.Event()

        def handler(bill, n):
            if bill == 'HB1':
                barrier.wait()
                return TimeoutError('read timeout')
            if bill == 'HB2':
                barrier.wait()
                hb2_may_return.wait(TIMEOUT)
            return OK
        barrier = threading.Barrier(2, timeout=TIMEOUT)
        original = pipeline.ThreadPoolExecutor

        class ReleaseHB2AfterHB1(original):
            # Let HB2 finish only once HB1's failure has been raised on the main thread.
            def __exit__(self, *exc):
                hb2_may_return.set()
                return super().__exit__(*exc)

        self.sdk = BillSDK(handler)
        with patch.object(pipeline, 'ThreadPoolExecutor', ReleaseHB2AfterHB1), \
                self.assertRaises(SystemExit) as stopped:
            self.run_workers()
        self.assertEqual(stopped.exception.code, 2)
        self.assertEqual(sorted(self.sdk.calls), ['HB1', 'HB2'])
        states = sorted(r['state'] for r in self.ledger_rows())
        self.assertEqual(states, ['pending', 'returned'])  # HB1 unknown, HB2 billed and recorded
        # The next run, whatever its worker count, sends nothing while HB1's outcome is unresolved.
        self.sdk.handler = lambda bill, n: self.fail('Must not send while an outcome is unresolved')
        with self.assertRaises(SystemExit) as blocked:  # HB1's indeterminate entry stops it (as legacy)
            self.run_workers()
        self.assertEqual(blocked.exception.code, 2)
        self.assertEqual(sorted(self.sdk.calls), ['HB1', 'HB2'])

    def test_capacity_refusal_on_one_worker_while_another_is_in_flight(self):
        self.fake_time()
        self.sdk = BillSDK(both_in_flight(then=lambda bill: capacity(300) if bill == 'HB1' else OK))
        queue = self.run_workers()
        self.assertEqual(sorted(queue['seen']), sorted(self.ids))
        self.assertEqual(self.sdk.calls.count('HB1'), 2)  # refused unbilled, then revisited after its cooldown
        self.assertEqual([r['state'] for r in self.ledger_rows()], ['returned'] * len(self.ids))
        self.assertGreaterEqual(sum(self.sleeps), 300)  # the revisit waited for retry-after

    def test_rows_of_a_crashed_run_block_every_worker(self):
        # A crash with two calls in flight leaves two pending rows owned by a dead run.
        self.cache.mkdir(parents=True)
        (self.cache / 'budget.json').write_text(json.dumps({'2026-11-10': {
            'a' * 64: {'state': 'pending', 'reserved': .01, 'owner': 'dead'},
            'b' * 64: {'state': 'pending', 'reserved': .01, 'owner': 'dead'}}}), 'utf-8')
        self.sdk.handler = lambda bill, n: self.fail('Must not send past unresolved rows')
        queue = self.run_workers()
        self.assertEqual(self.sdk.calls, [])
        self.assertEqual(queue.get('seen', []), [])

    def test_deadline_stops_new_bills_but_in_flight_ones_finish_and_are_recorded(self):
        self.fake_time()

        def past_deadline(bill):
            if bill == 'HB1':
                self.clock[0] += 3600
            return OK
        self.sdk = BillSDK(both_in_flight(then=past_deadline))
        queue = self.run_workers('--max-minutes', '1')
        self.assertEqual(sorted(queue['seen']), ['HB1', 'HB2'])
        self.assertEqual(sorted(self.sdk.calls), ['HB1', 'HB2'])
        self.assertNotIn('pending', [r['state'] for r in self.ledger_rows()])

    def test_quota_on_one_worker_ends_the_run(self):
        def quota(bill):
            from test_flex_worker_loop import Err
            return Err(429, 'insufficient_quota') if bill == 'HB1' else OK
        self.sdk = BillSDK(both_in_flight(then=quota))
        with self.assertRaises(SystemExit):
            self.run_workers()
        self.assertEqual(sorted(self.sdk.calls), ['HB1', 'HB2'])
        self.assertNotIn('pending', [r['state'] for r in self.ledger_rows()])

    def test_same_request_in_flight_on_another_worker_is_deferred_not_fatal(self):
        real = pipeline.run_document

        def run_document(document, *args, **kwargs):
            if document['bill_id'] == 'HB3':
                raise CacheBusy('The same extraction is already running')
            return real(document, *args, **kwargs)
        with patch.object(pipeline, 'run_document', side_effect=run_document):
            queue = self.run_workers()
        self.assertNotIn('HB3', queue['seen'])
        self.assertEqual(len(queue['seen']), len(self.ids) - 1)

    def test_more_than_one_worker_needs_the_flex_transport(self):
        argv = ['review_pipeline.py', '--cache-dir', str(self.cache), '--workers', '2']
        with patch.object(sys, 'argv', argv), self.assertRaises(SystemExit) as refused:
            pipeline.main()
        self.assertEqual(refused.exception.code, 2)
        self.assertFalse((self.cache / 'budget.json').exists())


class BoundaryThreadTests(unittest.TestCase):
    REQUEST = {'model': 'gpt-6-luna', 'input': 'MARKER-HB1 text', 'max_output_tokens': 100, 'service_tier': 'flex'}

    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)

    def boundary(self, sdk):
        return flex_boundary.FlexBoundary(self.cache, None, None, openai_factory=lambda: sdk, sleep=lambda s: None,
                                          log=lambda t: None)

    def test_one_request_on_two_threads_is_sent_once(self):
        entered, release = threading.Event(), threading.Event()

        def handler(bill, n):
            entered.set(); release.wait(TIMEOUT); return OK
        sdk = BillSDK(handler)
        boundary = self.boundary(sdk)
        outcomes = []
        first = threading.Thread(target=lambda: outcomes.append(
            boundary.execute(self.REQUEST, lambda: boundary.send(self.REQUEST)).cache_hit))
        first.start()
        self.assertTrue(entered.wait(TIMEOUT))
        with self.assertRaises(CacheBusy):
            boundary.execute(self.REQUEST, lambda: boundary.send(self.REQUEST))
        release.set(); first.join(TIMEOUT)
        self.assertEqual(outcomes, [False])
        self.assertEqual(sdk.calls, ['HB1'])

    def test_in_flight_row_is_not_unresolved_but_an_unknown_outcome_is(self):
        entered, release = threading.Event(), threading.Event()
        seen = {}

        def handler(bill, n):
            entered.set(); release.wait(TIMEOUT)
            return TimeoutError('read timeout') if bill == 'HB2' else OK
        boundary = self.boundary(BillSDK(handler))
        other = dict(self.REQUEST, input='MARKER-HB2 text')
        worker = threading.Thread(target=lambda: seen.setdefault('error', self._capture(boundary, other)))
        worker.start()
        self.assertTrue(entered.wait(TIMEOUT))
        seen['during'] = boundary.ledger['pending']  # HB2 in flight on another thread
        release.set(); worker.join(TIMEOUT)
        self.assertEqual(seen['during'], {})
        self.assertEqual(seen['error'], 'UncertainOutcome')
        self.assertEqual(len(boundary.ledger['pending']), 1)  # now unresolved: run_document stops on it

    def test_billed_call_counts_are_per_thread(self):
        boundary = self.boundary(BillSDK())
        counts = {}

        def call(bill):
            request = dict(self.REQUEST, input=f'MARKER-{bill} text')
            boundary.execute(request, lambda: boundary.send(request))
            counts[bill] = boundary.thread_calls
        threads = [threading.Thread(target=call, args=(b,)) for b in ('HB1', 'HB2', 'HB3')]
        for t in threads: t.start()
        for t in threads: t.join(TIMEOUT)
        self.assertEqual(counts, {'HB1': 1, 'HB2': 1, 'HB3': 1})
        self.assertEqual(boundary.thread_calls, 0)  # this thread sent nothing

    @staticmethod
    def _capture(boundary, request):
        try:
            boundary.execute(request, lambda: boundary.send(request))
            return 'ok'
        except Exception as error:  # noqa: BLE001
            return type(error).__name__


if __name__ == '__main__':
    unittest.main()
