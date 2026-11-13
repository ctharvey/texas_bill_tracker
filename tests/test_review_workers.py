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

    def test_unknown_outcome_on_one_worker_holds_only_that_bill(self):
        # HB1 times out (maybe billed) while HB2 is in flight on the other worker: HB1 is held, every other bill
        # is reviewed (a pending row seen by the other worker would have stopped the run), HB1 is never resent.
        self.sdk = BillSDK(both_in_flight(then=lambda bill: TimeoutError('read timeout') if bill == 'HB1' else OK))
        queue = self.run_workers()
        self.assertEqual(sorted(self.sdk.calls), sorted(self.ids))  # every bill sent exactly once
        self.assertEqual(sorted(queue['seen']), sorted(set(self.ids) - {'HB1'}))
        self.assertEqual(queue['failed']['HB1']['stage'], 'held')
        rows = self.ledger_rows()
        self.assertEqual(sorted((r['state'], r.get('held', False)) for r in rows),
                         [('returned', False)] * (len(self.ids) - 1) + [('returned', True)])
        # The next run, whatever its worker count, never resends HB1 and keeps it held.
        self.sdk.handler = lambda bill, n: self.fail('Must not resend a held call')
        queue = self.run_workers(workers=3)
        self.assertEqual(sorted(self.sdk.calls), sorted(self.ids))
        self.assertEqual(queue['failed']['HB1']['stage'], 'held')

    def test_capacity_refusal_on_one_worker_while_another_is_in_flight(self):
        self.fake_time()
        self.sdk = BillSDK(both_in_flight(then=lambda bill: capacity(300) if bill == 'HB1' else OK))
        queue = self.run_workers()
        self.assertEqual(sorted(queue['seen']), sorted(self.ids))
        self.assertEqual(self.sdk.calls.count('HB1'), 2)  # refused unbilled, then revisited after its cooldown
        self.assertEqual([r['state'] for r in self.ledger_rows()], ['returned'] * len(self.ids))
        self.assertGreaterEqual(sum(self.sleeps), 300)  # the revisit waited for retry-after

    def stranded(self, count):
        self.cache.mkdir(parents=True)
        (self.cache / 'budget.json').write_text(json.dumps({'2026-11-10': {
            c * 64: {'state': 'pending', 'reserved': .01, 'owner': 'dead'} for c in 'abcdefghij'[:count]}}), 'utf-8')

    def test_rows_of_a_crashed_run_are_held_at_start_and_other_bills_go_on(self):
        # Was "block every worker" until an operator ran --hold (13 Nov stall): a crash with two calls in flight
        # leaves two pending rows owned by a dead run; the next run books and holds them under the worker lock.
        self.stranded(2)
        queue = self.run_workers()
        self.assertEqual(sorted(queue['seen']), sorted(self.ids))
        held = [r for r in self.ledger_rows() if r.get('held')]
        self.assertEqual([(r['error_type'], r['cost']) for r in held], [('PendingAfterStop', .01)] * 2)
        self.assertNotIn('pending', [r['state'] for r in self.ledger_rows()])

    def test_a_crash_loop_past_the_daily_cap_leaves_rows_pending_and_sends_nothing(self):
        self.stranded(flex_boundary.CRASH_HOLD_LIMIT + 1)
        self.sdk.handler = lambda bill, n: self.fail('Must not send past unresolved rows')
        queue = self.run_workers()
        self.assertEqual(self.sdk.calls, [])
        self.assertEqual(queue.get('seen', []), [])
        self.assertEqual(queue.get('failed', {}), {})  # a systemic refusal fails no bill
        self.assertEqual([r['state'] for r in self.ledger_rows()], ['pending'] * (flex_boundary.CRASH_HOLD_LIMIT + 1))

    def test_a_stopped_runs_own_unknown_outcome_holds_only_its_bill_on_the_next_run(self):
        # Run 1: HB1's reply is lost and the hold never lands (as a crash mid-send): its row stays pending and the
        # run stops, failing no bill. Run 2 holds the row; HB1 fails as held and is never resent; the rest go on.
        self.sdk = BillSDK(lambda bill, n: (_ for _ in ()).throw(TimeoutError('read timeout')) if bill == 'HB1' else OK)
        with patch.object(flex_boundary.FlexBoundary, '_hold', lambda self, request, error: None), \
                self.assertRaises(SystemExit):
            self.run_workers(workers=1)
        path = self.cache / 'queue.json'
        self.assertEqual(json.loads(path.read_text('utf-8')).get('failed', {}) if path.exists() else {}, {})
        self.assertEqual([r['state'] for r in self.ledger_rows()], ['pending'])
        queue = self.run_workers(workers=1)
        self.assertEqual(self.sdk.calls.count('HB1'), 1)
        self.assertEqual(queue['failed']['HB1']['stage'], 'held')
        self.assertEqual(sorted(queue['seen']), sorted(self.ids[1:]))
        self.assertNotIn('HB1', pipeline.queue_candidates(self.ids, queue))  # parked: not visited for six hours
        later = queue['failed']['HB1']['at'] + pipeline.PARK_RETRY_S
        self.assertEqual(pipeline.queue_candidates(self.ids, queue, now=later)[-1], 'HB1')  # then after all others
        # The operator checks the usage log and releases the call: HB1's next visit sends it once more.
        [(_, key, _row)] = flex_boundary.FlexBoundary(self.cache, None, None).held()
        flex_boundary.FlexBoundary(self.cache, None, None).release_held(key)
        queue['failed']['HB1']['at'] -= pipeline.PARK_RETRY_S
        (self.cache / 'queue.json').write_text(json.dumps(queue), 'utf-8')
        self.sdk.handler = lambda bill, n: OK
        queue = self.run_workers(workers=1)
        self.assertEqual(self.sdk.calls.count('HB1'), 2)
        self.assertNotIn('HB1', queue['failed'])
        self.assertIn('HB1', queue['seen'])

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
        self.assertEqual(boundary.ledger['pending'], {})  # held, not pending: other workers' calls go on
        self.assertEqual(len(boundary.held()), 1)

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
