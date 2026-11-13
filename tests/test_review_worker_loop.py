"""Counterexamples for the uncapped serial review loop: failures, stops and ledger days."""
import ftplib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import review_pipeline as pipeline
import classify_bill as classification
from extraction_cache import CapacityUnavailable, NotSubmitted, UnresolvedCall


def bundle(bill_id, status='ready_for_review', pending=(), stop_run=None):
    return {'bill_id': bill_id, 'status': status, 'result': {}, 'pending_questions': list(pending),
            'publishable': False, 'stop_run': stop_run}


class WorkerLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo, self.cache = base / 'repo', base / 'cache'
        (self.repo / 'data').mkdir(parents=True)
        self.ids = ['HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6', 'HB7', 'HB8']
        (self.repo / 'data' / 'bills.json').write_text(json.dumps({'bills': [{'id': i} for i in self.ids]}), 'utf-8')
        for target, value in ((pipeline, 'ROOT'),):
            p = patch.object(target, value, self.repo); p.start(); self.addCleanup(p.stop)
        p = patch.object(pipeline.detailed, 'load_registry', return_value=[]); p.start(); self.addCleanup(p.stop)

    def run_main(self, download, run_document, *extra):
        argv = ['review_pipeline.py', '--cache-dir', str(self.cache), '--execute', *extra]
        with patch.object(sys, 'argv', argv), patch.object(pipeline, 'download_document', side_effect=download), \
                patch.object(pipeline, 'run_document', side_effect=run_document):
            pipeline.main()
        path = self.cache / 'queue.json'
        return json.loads(path.read_text('utf-8')) if path.exists() else {}

    def test_download_failure_is_not_marked_seen_and_follows_new_work(self):
        def download(bill_id, root):
            if bill_id in ('HB2', 'HB3'):
                raise ftplib.error_perm('550 not posted')
            return {'bill_id': bill_id}
        queue = self.run_main(download, lambda doc, *a, **k: bundle(doc['bill_id']))
        self.assertEqual(queue['seen'], ['HB1', 'HB4', 'HB5', 'HB6', 'HB7', 'HB8'])
        self.assertEqual(set(queue['failed']), {'HB2', 'HB3'})
        self.assertEqual(queue['failed']['HB2'], {'count': 1, 'stage': 'download', 'reason': 'error_perm'})
        queue['seen'].remove('HB8')  # A newly filed bill appears before the failing ones.
        self.assertEqual(pipeline.queue_candidates(self.ids, queue)[:3], ['HB8', 'HB2', 'HB3'])

    def test_successful_retry_clears_failure(self):
        calls = []
        def download(bill_id, root):
            calls.append(bill_id)
            if bill_id == 'HB2' and calls.count('HB2') == 1:
                raise OSError('timed out')
            return {'bill_id': bill_id}
        self.run_main(download, lambda doc, *a, **k: bundle(doc['bill_id']))
        queue = self.run_main(download, lambda doc, *a, **k: bundle(doc['bill_id']))
        self.assertNotIn('HB2', queue['failed'])
        self.assertIn('HB2', queue['seen'])

    def test_ftp_outage_stops_after_consecutive_new_failures(self):
        calls = []
        def download(bill_id, root):
            calls.append(bill_id); raise OSError('connection refused')
        queue = self.run_main(download, lambda *a, **k: self.fail('No document was downloaded'))
        self.assertEqual(len(calls), pipeline.OUTAGE_LIMIT)
        self.assertEqual(queue['seen'], [])

    def test_known_failures_do_not_trip_the_outage_stop(self):
        failing = {'HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6'}
        def download(bill_id, root):
            if bill_id in failing:
                raise ftplib.error_perm('550')
            return {'bill_id': bill_id}
        self.run_main(download, lambda doc, *a, **k: bundle(doc['bill_id']))  # Stops at the 5th new failure.
        queue = self.run_main(download, lambda doc, *a, **k: bundle(doc['bill_id']))
        self.assertIn('HB7', queue['seen']); self.assertIn('HB8', queue['seen'])
        self.assertEqual(queue['failed']['HB1']['count'], 2)

    def test_budget_stop_during_questions_ends_run_and_keeps_retry(self):
        processed = []
        def run_document(doc, *a, **k):
            processed.append(doc['bill_id'])
            if doc['bill_id'] == 'HB2':
                return bundle('HB2', 'needs_review', [{'id': 'q', 'reason': 'BudgetExceeded'}], 'BudgetExceeded')
            return bundle(doc['bill_id'])
        queue = self.run_main(lambda b, r: {'bill_id': b}, run_document)
        self.assertEqual(processed, ['HB1', 'HB2'])
        self.assertEqual(queue['retry'], ['HB2'])
        self.assertEqual(queue['seen'], ['HB1', 'HB2'])

    def test_deferred_first_pass_keeps_bill_unseen_and_earlier_review(self):
        reviews = self.cache / 'reviews'; reviews.mkdir(parents=True)
        (reviews / 'HB1.json').write_text('{"earlier": true}', 'utf-8')
        deferred = {'bill_id': 'HB1', 'status': 'deferred', 'publishable': False,
                    'first_pass': {'action': 'not_submitted', 'reason_type': 'BudgetExceeded'}}
        queue = self.run_main(lambda b, r: {'bill_id': b}, lambda *a, **k: deferred)
        self.assertEqual(queue.get('seen', []), [])
        self.assertEqual(json.loads((reviews / 'HB1.json').read_text('utf-8')), {'earlier': True})

    def test_run_time_limit_is_checked_between_bills(self):
        clock = iter([0, 0, 10, 4000, 4000])
        with patch.object(pipeline.time, 'monotonic', side_effect=lambda: next(clock)):
            queue = self.run_main(lambda b, r: {'bill_id': b}, lambda doc, *a, **k: bundle(doc['bill_id']),
                                  '--max-minutes', '1')
        self.assertEqual(queue['seen'], ['HB1', 'HB2'])

    def stop_output(self, error):
        import contextlib, io
        def run_document(doc, *a, **k): raise error
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            self.run_main(lambda b, r: {'bill_id': b}, run_document)
        return out.getvalue()

    def test_an_unexpected_error_fails_only_its_bill_and_names_where_but_never_the_error_text(self):
        # Was a whole-run stop (exit 2) until the next hourly run, which hit the same bill again.
        import contextlib, io
        def run_document(doc, *a, **k):
            if doc['bill_id'] == 'HB2':
                raise KeyError('sk-secret-from-sdk')
            return bundle(doc['bill_id'])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            queue = self.run_main(lambda b, r: {'bill_id': b}, run_document)
        self.assertIn('HB2 failed KeyError - unexpected error at test_review_worker_loop.py:', out.getvalue())
        self.assertIn('the bill waits at the end of the queue', out.getvalue())
        self.assertNotIn('sk-secret', out.getvalue())
        self.assertEqual(queue['failed'], {'HB2': {'count': 1, 'stage': 'processing', 'reason': 'KeyError'}})
        self.assertEqual(queue['seen'], [b for b in self.ids if b != 'HB2'])
        queue['seen'].remove('HB8')  # parked after new work and every known bill
        self.assertEqual(pipeline.queue_candidates(self.ids, queue)[0], 'HB8')
        self.assertEqual(pipeline.queue_candidates(self.ids, queue)[-1], 'HB2')

    def test_an_error_with_an_unresolved_ledger_row_still_stops(self):
        # Fails closed: an unexpected error while a call has no recorded outcome says nothing about one bill.
        budget = type('B', (), {'ledger': {'d': {'k': {'state': 'pending'}}}})()
        self.assertTrue(pipeline.stops_run(KeyError('x'), budget))
        self.assertTrue(pipeline.stops_run(KeyError('x'), object()))  # unreadable ledger
        self.assertFalse(pipeline.stops_run(KeyError('x'), type('B', (), {'ledger': {}})()))
        held = RuntimeError('x'); held.held = True
        self.assertFalse(pipeline.stops_run(held, budget))
        quota = RuntimeError('x'); quota.code = 'insufficient_quota'
        self.assertTrue(pipeline.stops_run(quota, type('B', (), {'ledger': {}})()))

    def test_a_held_question_keeps_its_bill_off_the_retry_list(self):
        held = [{'id': 'q1', 'reason': 'UncertainOutcome', 'held': True},
                {'id': 'q2', 'reason': 'Deferred with preceding request', 'held': True}]
        queue = self.run_main(lambda b, r: {'bill_id': b},
                              lambda doc, *a, **k: bundle(doc['bill_id'], 'needs_review',
                                                          held if doc['bill_id'] == 'HB1' else ()))
        self.assertEqual(queue['retry'], [])
        self.assertEqual(queue['seen'], self.ids)

    def test_a_quota_stop_backs_off_for_an_hour(self):
        import contextlib, io
        processed = []
        def run_document(doc, *a, **k):
            processed.append(doc['bill_id']); raise pipeline.ApiStopped('insufficient_quota')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
            self.run_main(lambda b, r: {'bill_id': b}, run_document)
        self.assertEqual((caught.exception.code, processed), (2, ['HB1']))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.run_main(lambda b, r: self.fail('Must not start within the backoff'), run_document)
        self.assertIn('waiting an hour between tries', out.getvalue())
        marker = self.cache / pipeline.ACCOUNT_STOP
        marker.write_text(json.dumps({'stopped_at': pipeline.time.time() - pipeline.ACCOUNT_BACKOFF_S - 1}), 'utf-8')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            self.run_main(lambda b, r: {'bill_id': b}, run_document)
        self.assertEqual(processed, ['HB1', 'HB1'])  # tried again once the hour passed

    def test_an_unknown_outcome_stop_prints_the_pending_key_and_the_command(self):
        out = self.stop_output(pipeline.WorkerStopped('Unknown request outcome; worker stopped after TimeoutError. '
                                                      'Pending request abc; run --hold abc'))
        self.assertIn('HB1 stopped WorkerStopped - Unknown request outcome; worker stopped after TimeoutError. '
                      'Pending request abc', out)

    def test_held_and_deferred_lines_say_what_happens_next(self):
        held = RuntimeError('provider said sk-secret'); held.held = True; held.request_key = 'k1'
        self.assertEqual(pipeline.next_step(held), 'request k1; check the provider usage log, then release it '
                         'with scripts/flex_boundary.py --cache-dir CACHE --release k1')
        self.assertEqual(pipeline.next_step(pipeline.CacheBusy('x')), 'retried automatically in a later run')
        self.assertIn('spending limit', pipeline.next_step(pipeline.BudgetExceeded('x')))
        quota = RuntimeError('sk-secret'); quota.code = 'insufficient_quota'
        self.assertIn('provider account', pipeline.next_step(quota))
        for error in (held, quota, ValueError('sk-secret'), OSError('sk-secret')):
            self.assertNotIn('sk-secret', pipeline.next_step(error))


class PublicStatusTests(WorkerLoopTests):
    def setUp(self):
        super().setUp()
        self.tags = Path(self.temp.name) / 'live' / 'luna' / 'tags.json'; self.tags.parent.mkdir(parents=True)
        self.status = self.tags.parent / 'status.json'
        p = patch.object(pipeline, 'publish_tags', return_value=0); p.start(); self.addCleanup(p.stop)

    def read(self):
        return json.loads(self.status.read_text('utf-8'))

    def test_status_names_current_bill_during_run_and_clears_after(self):
        seen = {}
        def run_document(doc, *a, **k):
            seen[doc['bill_id']] = self.read(); return bundle(doc['bill_id'])
        def download(bill_id, root):
            if bill_id == 'HB3':
                raise ftplib.error_perm('550 not posted')
            return {'bill_id': bill_id}
        queue = self.run_main(download, run_document, '--publish-tags', str(self.tags))
        self.assertEqual((seen['HB2']['current'], seen['HB2']['running']), ('HB2', True))
        self.assertEqual(seen['HB2']['upcoming'], ['HB3', 'HB4', 'HB5', 'HB6', 'HB7'])
        self.assertEqual(seen['HB2']['reviewed'], ['HB1'])
        final = self.read()
        self.assertEqual((final['running'], final['current'], final['upcoming']), (False, None, []))
        self.assertEqual(final['reviewed'], queue['seen'])
        self.assertEqual(final['failed'], {'HB3': 'download'})  # Stage only; no error reasons.
        self.assertEqual(set(final), {'format', 'updated_at', 'running', 'current', 'in_progress', 'upcoming',
                                      'waiting_until', 'reviewed', 'retry', 'failed', 'run_started_at', 'pass',
                                      'passes'})
        self.assertEqual((seen['HB2']['pass'], final['pass']), ('review', None))
        self.assertEqual((seen['HB2']['in_progress'], final['in_progress']), (['HB2'], []))

    def test_parallel_status_lists_every_bill_in_flight_and_drops_finished_ones(self):
        # Counterexample for the one-bill view: two workers hold HB1 and HB2 at once; HB2 must not finish
        # until the published status shows HB1 gone and HB2 still in progress.
        snapshots, both, hb1_gone = [], threading.Barrier(2, timeout=10), threading.Event()
        publish = pipeline.try_publish_status

        def record(out, queue, **kwargs):
            publish(out, queue, **kwargs)
            held = self.read()['in_progress']
            snapshots.append(held)
            if held == ['HB2']:
                hb1_gone.set()

        def run_document(doc, *a, **k):
            if doc['bill_id'] in ('HB1', 'HB2'):
                both.wait()
            if doc['bill_id'] == 'HB2':
                self.assertTrue(hb1_gone.wait(10), 'status never dropped finished HB1 while HB2 ran')
            return bundle(doc['bill_id'])

        with patch.object(pipeline, 'try_publish_status', side_effect=record):
            queue = self.run_main(lambda b, r: {'bill_id': b}, run_document, '--publish-tags', str(self.tags),
                                  '--transport', 'flex', '--workers', '2')
        self.assertEqual(sorted(queue['seen']), sorted(self.ids))
        self.assertIn(['HB1', 'HB2'], snapshots)
        self.assertTrue(all(len(h) <= 2 for h in snapshots))
        final = self.read()
        self.assertEqual((final['running'], final['in_progress'], final['current']), (False, [], None))

    def topic_pass(self, during):
        """--suggest-topics with its jobs and runner faked: due HB1 (two votes) and HB2; `during` runs mid-pass."""
        fake_jobs = lambda *a: iter([('HB1', None, None), ('HB1', None, None), ('HB2', None, None)])
        def run(*a):
            during(self.read())
            return 1
        return patch.object(pipeline, 'topic_jobs', side_effect=fake_jobs), \
            patch.object(pipeline, 'suggest_topics', side_effect=run)

    def test_status_stays_running_through_a_second_pass_and_counts_it(self):
        # Counterexample for the old status: the first pass's end published running=false while topics ran.
        seen = []
        jobs, run = self.topic_pass(seen.append)
        with jobs, run:
            self.run_main(lambda b, r: {'bill_id': b}, lambda doc, *a, **k: bundle(doc['bill_id']),
                          '--publish-tags', str(self.tags), '--suggest-topics')
        [during] = seen
        self.assertEqual((during['running'], during['pass'], during['current']), (True, 'topics', None))
        self.assertEqual(during['passes'], {'topics': {'due': 2, 'checked': 0}})  # bills, not votes
        final = self.read()
        self.assertEqual((final['running'], final['pass']), (False, None))
        self.assertEqual(final['passes'], {'topics': {'due': 2, 'checked': 1}})
        self.assertEqual(final['run_started_at'], during['run_started_at'])

    def test_a_stop_inside_a_second_pass_still_publishes_stopped_status(self):
        def stop(status):
            raise SystemExit(2)
        jobs, run = self.topic_pass(stop)
        with jobs, run, self.assertRaises(SystemExit):
            self.run_main(lambda b, r: {'bill_id': b}, lambda doc, *a, **k: bundle(doc['bill_id']),
                          '--publish-tags', str(self.tags), '--suggest-topics')
        self.assertEqual((self.read()['running'], self.read()['pass']), (False, None))

    def test_crash_still_publishes_stopped_status(self):
        def run_document(doc, *a, **k): raise pipeline.WorkerStopped('Unknown request outcome')
        with self.assertRaises(SystemExit):
            self.run_main(lambda b, r: {'bill_id': b}, run_document, '--publish-tags', str(self.tags))
        self.assertFalse(self.read()['running'])

    def test_no_status_without_publish_or_on_dry_run(self):
        self.run_main(lambda b, r: {'bill_id': b}, lambda doc, *a, **k: bundle(doc['bill_id']))
        self.assertFalse(self.status.exists())
        argv = ['review_pipeline.py', '--cache-dir', str(self.cache), '--publish-tags', str(self.tags)]
        with patch.object(sys, 'argv', argv), patch.object(pipeline, 'download_document', side_effect=lambda b, r: {'bill_id': b}), \
                patch.object(pipeline, 'run_document', side_effect=lambda doc, *a, **k: {**bundle(doc['bill_id'], 'prepared'), 'first_pass': {}}):
            pipeline.main()
        self.assertFalse(self.status.exists())

    def test_reverse_order_starts_at_the_bottom(self):
        processed = []
        def download(bill_id, root):
            processed.append(bill_id); return {'bill_id': bill_id}
        self.run_main(download, lambda doc, *a, **k: bundle(doc['bill_id']), '--order', 'reverse')
        self.assertEqual(processed, self.ids[::-1])


class CapacityBackoffTests(WorkerLoopTests):
    def setUp(self):
        super().setUp()
        self.sleeps, self.clock = [], [0.0]
        def sleep(seconds):
            self.sleeps.append(seconds); self.clock[0] += seconds
        for name, fake in (('sleep', sleep), ('monotonic', lambda: self.clock[0])):
            p = patch.object(pipeline.time, name, side_effect=fake); p.start(); self.addCleanup(p.stop)

    def test_first_pass_capacity_sets_bill_aside_and_continues_without_waiting(self):
        processed, failures = [], {'HB2': 1}
        def run_document(doc, *a, **k):
            processed.append(doc['bill_id'])
            if failures.get(doc['bill_id']):
                failures[doc['bill_id']] -= 1; raise CapacityUnavailable(300)
            return bundle(doc['bill_id'])
        queue = self.run_main(lambda b, r: {'bill_id': b}, run_document)
        # Every other bill runs immediately; the only wait is for HB2's cooldown once nothing else is left.
        self.assertEqual(processed, ['HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6', 'HB7', 'HB8', 'HB2'])
        self.assertEqual(self.sleeps, [301])
        self.assertEqual(queue['seen'], ['HB1', 'HB3', 'HB4', 'HB5', 'HB6', 'HB7', 'HB8', 'HB2'])

    def test_cooled_bill_is_revisited_as_soon_as_ready(self):
        processed = []
        def run_document(doc, *a, **k):
            processed.append(doc['bill_id'])
            self.clock[0] += 100  # Each review takes real time, so HB1's cooldown passes mid-run.
            if doc['bill_id'] == 'HB1' and processed.count('HB1') == 1:
                raise CapacityUnavailable(150)  # Ready at t=251; HB3 finishes at t=300.
            return bundle(doc['bill_id'])
        self.run_main(lambda b, r: {'bill_id': b}, run_document)
        self.assertEqual(processed, ['HB1', 'HB2', 'HB3', 'HB1', 'HB4', 'HB5', 'HB6', 'HB7', 'HB8'])
        self.assertEqual(self.sleeps, [])

    def test_question_capacity_revisits_bill_and_clears_retry(self):
        processed = []
        def run_document(doc, *a, **k):
            processed.append(doc['bill_id'])
            if doc['bill_id'] == 'HB2' and processed.count('HB2') == 1:
                return {**bundle('HB2', 'needs_review', [{'id': 'q', 'reason': 'CapacityUnavailable'}],
                                 'CapacityUnavailable'), 'retry_after': 300}
            return bundle(doc['bill_id'])
        queue = self.run_main(lambda b, r: {'bill_id': b}, run_document)
        self.assertEqual(processed[:3], ['HB1', 'HB2', 'HB3'])
        self.assertEqual(processed[-1], 'HB2')
        self.assertEqual(self.sleeps, [301])
        self.assertEqual(queue['retry'], [])
        self.assertEqual(queue['seen'], self.ids)
        self.assertEqual(queue['cursor'], 0)

    def test_sustained_outage_pauses_at_most_a_minute_and_runs_to_the_deadline(self):
        calls = []
        def run_document(doc, *a, **k):
            calls.append(doc['bill_id']); raise CapacityUnavailable(0)
        queue = self.run_main(lambda b, r: {'bill_id': b}, run_document, '--max-minutes', '10')
        self.assertEqual(self.sleeps[:2], [30, 60])
        self.assertLessEqual(max(self.sleeps), 60)
        self.assertGreater(len(calls), len(self.ids))  # Kept trying instead of stopping at the first rejection.
        self.assertLessEqual(self.clock[0], 600)
        self.assertEqual(queue.get('seen', []), [])

    def test_success_resets_the_pause(self):
        failures = {'HB2': 1, 'HB3': 1, 'HB6': 1}
        def run_document(doc, *a, **k):
            if failures.get(doc['bill_id']):
                failures[doc['bill_id']] -= 1; raise CapacityUnavailable(1000)
            return bundle(doc['bill_id'])
        self.run_main(lambda b, r: {'bill_id': b}, run_document)
        # HB2 then HB3 back to back: no pause, then 30 s. HB6 after successes: no pause again.
        self.assertEqual(self.sleeps[0], 30)
        self.assertNotIn(60, self.sleeps)

    def test_cooldown_past_the_deadline_leaves_bill_queued(self):
        processed = []
        def run_document(doc, *a, **k):
            processed.append(doc['bill_id'])
            if doc['bill_id'] == 'HB2':
                raise CapacityUnavailable(600)
            return bundle(doc['bill_id'])
        queue = self.run_main(lambda b, r: {'bill_id': b}, run_document, '--max-minutes', '5')
        self.assertEqual(processed, self.ids)
        self.assertEqual(self.sleeps, [])
        self.assertNotIn('HB2', queue['seen'])

    def test_budget_stop_is_not_retried(self):
        processed = []
        def run_document(doc, *a, **k):
            processed.append(doc['bill_id']); raise pipeline.BudgetExceeded('cap')
        self.run_main(lambda b, r: {'bill_id': b}, run_document)
        self.assertEqual((processed, self.sleeps), (['HB1'], []))

    def test_unknown_outcome_during_questions_still_stops_the_worker(self):
        def run_document(doc, *a, **k): raise pipeline.WorkerStopped('Unknown request outcome; worker stopped')
        with self.assertRaises(SystemExit):
            self.run_main(lambda b, r: {'bill_id': b}, run_document)
        self.assertEqual(self.sleeps, [])


class HeldQuestionTests(unittest.TestCase):
    def test_a_held_question_waits_with_its_bill_and_does_not_stop_the_run(self):
        fresh = RuntimeError('outcome unknown'); fresh.held = True  # as flex_boundary marks a held call
        first = {'result': {'uncertainties': [], 'agencies': []}, 'request_key': 'k'}
        questions = [{'id': 'q1', 'question': 'a'}, {'id': 'q2', 'question': 'b'}]
        for error in (UnresolvedCall('earlier outcome is uncertain'), fresh):
            with self.subTest(type(error).__name__):
                budget = type('Budget', (), {'ledger': {}, 'run_spent': 0.0, 'send': None})()
                with patch.object(classification, 'classify', return_value=first), \
                        patch.object(pipeline, 'questions_for', return_value=questions), \
                        patch.object(pipeline, 'resolve', side_effect=error) as resolve, \
                        patch.object(classification, 'build_request', return_value={'text': {'format': {'schema': {}}}}), \
                        patch.object(classification, 'validate_result', return_value={'errors': []}):
                    out = pipeline.run_document({'bill_id': 'HB9'}, [], Path('.'), budget, True)
                self.assertEqual(resolve.call_count, 1)  # the bill's later question waits with it
                self.assertIsNone(out['stop_run'])
                self.assertEqual([q['reason'] for q in out['pending_questions']],
                                 [type(error).__name__, 'Deferred with preceding request'])

    def test_an_unmarked_unknown_outcome_with_a_pending_row_still_stops(self):
        first = {'result': {'uncertainties': [], 'agencies': []}, 'request_key': 'k'}
        budget = type('Budget', (), {'ledger': {'d': {'x': {'state': 'pending'}}}, 'run_spent': 0.0, 'send': None})()
        with patch.object(classification, 'classify', return_value=first), \
                patch.object(pipeline, 'questions_for', return_value=[{'id': 'q1', 'question': 'a'}]), \
                patch.object(pipeline, 'resolve', side_effect=TimeoutError('read timeout')), \
                self.assertRaises(RuntimeError):
            pipeline.run_document({'bill_id': 'HB9'}, [], Path('.'), budget, True)


    def test_the_unknown_outcome_stop_names_the_pending_keys_and_the_error_type_only(self):
        first = {'result': {'uncertainties': [], 'agencies': []}, 'request_key': 'k'}
        budget = type('Budget', (), {'ledger': {'d': {'k2': {'state': 'pending'}, 'k1': {'state': 'pending'},
                                                      'k0': {'state': 'returned'}}},
                                     'run_spent': 0.0, 'send': None})()
        with patch.object(classification, 'classify', return_value=first),                 patch.object(pipeline, 'questions_for', return_value=[{'id': 'q1', 'question': 'a'}]),                 patch.object(pipeline, 'resolve', side_effect=TimeoutError('sk-secret read timeout')),                 self.assertRaises(pipeline.WorkerStopped) as stop:
            pipeline.run_document({'bill_id': 'HB9'}, [], Path('.'), budget, True)
        message = str(stop.exception)
        self.assertIn('after TimeoutError. Pending request k1, k2;', message)
        self.assertIn('scripts/flex_boundary.py --cache-dir CACHE --hold k1', message)
        self.assertNotIn('sk-secret', message)


class SecondPassFailureTests(unittest.TestCase):
    def run_pass(self, errors, ledger=None):
        import contextlib, io, types
        saved = []
        def job(bill_id):
            def call():
                if bill_id in errors:
                    raise errors[bill_id]
                return {}
            return bill_id, call, lambda report, b=bill_id: saved.append(b)
        args = types.SimpleNamespace(execute=True, cache_dir=Path(tempfile.mkdtemp()))
        budget = type('B', (), {'ledger': ledger or {}})()
        with contextlib.redirect_stdout(io.StringIO()):
            count = pipeline._second_pass('Topic suggestions', iter([job(b) for b in ('HB1', 'HB2', 'HB3')]),
                                          args, float('inf'), budget=budget)
        return count, saved

    def test_a_held_call_and_an_unexpected_error_skip_only_their_bills(self):
        held = RuntimeError('lost reply'); held.held = True
        self.assertEqual(self.run_pass({'HB1': held, 'HB2': KeyError('bug')}), (1, ['HB3']))

    def test_an_error_with_an_unresolved_ledger_row_stops_the_worker(self):
        with self.assertRaises(SystemExit):
            self.run_pass({'HB1': RuntimeError('lost reply')}, ledger={'d': {'k': {'state': 'pending'}}})

    def test_repeated_errors_end_the_pass_not_the_run(self):
        errors = {b: KeyError('bug') for b in ('HB1', 'HB2', 'HB3')}
        with patch.object(pipeline, 'OUTAGE_LIMIT', 2):
            self.assertEqual(self.run_pass(errors), (0, []))


class FirstPassStatusTests(unittest.TestCase):
    def run_with(self, reason_type, execute=True):
        first = {'action': 'not_submitted', 'request_key': 'k', 'reason_type': reason_type}
        with patch.object(classification, 'classify', return_value=first):
            budget = type('Budget', (), {'send': lambda self, request: self.fail()})()
            return pipeline.run_document({'bill_id': 'HB9'}, [], Path('.'), budget, execute)['status']

    def test_long_context_is_per_bill_and_does_not_stop_the_run(self):
        self.assertEqual(self.run_with('LongContext'), 'needs_review')
        self.assertEqual(self.run_with('AlreadyBilled'), 'needs_review')

    def test_budget_and_unresolved_outcomes_stop_the_run(self):
        self.assertEqual(self.run_with('BudgetExceeded'), 'deferred')
        self.assertEqual(self.run_with('OutcomeUnresolved'), 'deferred')

    def test_dry_run_is_prepared_not_reviewed(self):
        self.assertEqual(self.run_with('NotSubmitted', execute=False), 'prepared')

    def test_environmental_not_submitted_stops_the_run(self):
        # e.g. OPENAI_API_KEY missing: must not be treated as a per-bill problem and mark every bill seen.
        self.assertEqual(self.run_with('NotSubmitted'), 'deferred')
        self.assertEqual(self.run_with(None), 'deferred')


class EnvironmentFailureLoopTests(WorkerLoopTests):
    def test_missing_key_stops_after_first_bill_without_marking_seen(self):
        deferred = lambda doc, *a, **k: {'bill_id': doc['bill_id'], 'status': 'deferred', 'publishable': False,
                                         'first_pass': {'action': 'not_submitted', 'reason_type': 'NotSubmitted'}}
        processed = []
        queue = self.run_main(lambda b, r: processed.append(b) or {'bill_id': b}, deferred)
        self.assertEqual(processed, ['HB1'])
        self.assertEqual(queue.get('seen', []), [])

    def test_repeated_processing_failures_stop_the_run(self):
        processed = []
        def run_document(doc, *a, **k):
            processed.append(doc['bill_id']); raise OSError('No space left on device')
        queue = self.run_main(lambda b, r: {'bill_id': b}, run_document)
        self.assertEqual(len(processed), pipeline.OUTAGE_LIMIT)
        self.assertEqual(queue['seen'], [])

    def test_unexpected_download_error_stops_with_exit_2(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_main(lambda b, r: (_ for _ in ()).throw(NotSubmitted('Install requirements')),
                          lambda *a, **k: self.fail('No document'))
        self.assertEqual(caught.exception.code, 2)


class LedgerDayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'budget.json'
        self.request = {'model': classification.MODEL, 'max_output_tokens': 5000, 'input': 'Source'}

    def test_spend_after_chicago_midnight_books_to_the_new_day(self):
        days = iter(['2026-11-09', '2026-11-10', '2026-11-10'])
        with patch.object(pipeline, 'ledger_day', side_effect=lambda: next(days)), \
                patch.object(classification, 'response_cost', return_value=(0, 0.01)):
            budget = pipeline.Budget(self.path, 1, .1)
            budget.send(self.request, sender=lambda _: {'ok': True})
        ledger = json.loads(self.path.read_text('utf-8'))
        self.assertEqual(ledger['2026-11-09'], {})
        self.assertEqual(sum(r['cost'] for r in ledger['2026-11-10'].values()), 0.01)

    def test_previous_day_spend_does_not_count_against_today(self):
        self.path.write_text(json.dumps({'2026-11-09': {'old': {'state': 'returned', 'cost': 0.99, 'reserved': 0}}}))
        with patch.object(pipeline, 'ledger_day', return_value='2026-11-10'), \
                patch.object(classification, 'response_cost', return_value=(0, 0.01)):
            pipeline.Budget(self.path, 1, .1).send(self.request, sender=lambda _: {'ok': True})

    def test_ledger_day_uses_chicago_time(self):
        import datetime as dt
        from zoneinfo import ZoneInfo
        self.assertEqual(pipeline.ledger_day(), dt.datetime.now(ZoneInfo('America/Chicago')).date().isoformat())

    def test_oversized_request_is_a_long_context_not_submitted(self):
        big = {**self.request, 'input': 'x' * 300000}
        with self.assertRaises(pipeline.LongContext) as caught:
            pipeline.Budget(self.path, 1, .1).send(big, sender=lambda _: self.fail('Must not send'))
        self.assertIsInstance(caught.exception, NotSubmitted)


if __name__ == '__main__':
    unittest.main()
