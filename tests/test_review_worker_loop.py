"""Counterexamples for the uncapped serial review loop: failures, stops and ledger days."""
import ftplib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import review_pipeline as pipeline
import classify_bill as classification
from extraction_cache import NotSubmitted


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
        self.assertEqual(set(final), {'format', 'updated_at', 'running', 'current', 'upcoming', 'reviewed', 'retry', 'failed'})

    def test_crash_still_publishes_stopped_status(self):
        def run_document(doc, *a, **k): raise RuntimeError('unexpected')
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
