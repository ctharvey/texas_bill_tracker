"""First passes for every unseen bill come before follow-up questions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import review_pipeline as pipeline


def bundle(bill_id, pending=()):
    return {'bill_id': bill_id, 'status': 'needs_review' if pending else 'ready_for_review', 'result': {},
            'pending_questions': list(pending), 'publishable': False, 'stop_run': None}


class QueueOrderTests(unittest.TestCase):
    def test_unseen_bills_come_before_every_retry(self):
        queue = {'seen': ['HB1', 'HB2', 'HB3', 'HB4', 'HB5'], 'cursor': 0,
                 'retry': ['HB1', 'HB2', 'HB3', 'HB4', 'HB5'], 'failed': {'HB8': {}}}
        ids = ['HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6', 'HB7', 'HB8']
        self.assertEqual(pipeline.queue_candidates(ids, queue, first_pass_first=True),
                         ['HB6', 'HB7', 'HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB8'])
        # The default keeps the bounded retry-first order.
        self.assertEqual(pipeline.queue_candidates(ids, queue)[:3], ['HB1', 'HB2', 'HB3'])


class RunDocumentTests(unittest.TestCase):
    def test_deferred_questions_make_no_calls_and_stay_retryable(self):
        result = {'summary': {'text': 's', 'evidence': []}, 'agencies': [], 'uncertainties': []}
        questions = [{'question': 'q1', 'affected_claims': ['summary'], 'span_ids': [], 'needed_source': None},
                     {'question': 'q2', 'affected_claims': ['summary'], 'span_ids': [], 'needed_source': None}]
        schema = {'text': {'format': {'schema': {}}}}
        with patch.object(pipeline.classification, 'classify', return_value={'result': result, 'request_key': 'k'}), \
                patch.object(pipeline, 'questions_for', return_value=questions), \
                patch.object(pipeline, 'resolve', side_effect=AssertionError('no question may be sent')), \
                patch.object(pipeline.classification, 'build_request', return_value=schema), \
                patch.object(pipeline.classification, 'validate_result', return_value={'errors': []}):
            budget = type('Budget', (), {'send': None, 'run_spent': 0.0, 'ledger': {}})()
            out = pipeline.run_document({'bill_id': 'HB9'}, [], Path('.'), budget, True, ask_questions=False)
        self.assertEqual(out['status'], 'needs_review')
        self.assertEqual([q['reason'] for q in out['pending_questions']], [pipeline.QUESTIONS_LATER] * 2)
        self.assertTrue(pipeline.QUESTIONS_LATER.startswith('Deferred'))  # The worker's retryable prefix.
        self.assertIsNone(out['stop_run'])


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo, self.cache = base / 'repo', base / 'cache'
        (self.repo / 'data').mkdir(parents=True)
        self.ids = ['HB1', 'HB2', 'HB3']
        (self.repo / 'data' / 'bills.json').write_text(json.dumps({'bills': [{'id': i} for i in self.ids]}), 'utf-8')
        for target, value in ((pipeline, 'ROOT'),):
            p = patch.object(target, value, self.repo); p.start(); self.addCleanup(p.stop)
        p = patch.object(pipeline.detailed, 'load_registry', return_value=[]); p.start(); self.addCleanup(p.stop)
        self.asked = {}

    def run_main(self, *extra):
        def run_document(doc, *a, **k):
            self.asked.setdefault(doc['bill_id'], []).append(k.get('ask_questions'))
            later = [{'question': 'q', 'reason': pipeline.QUESTIONS_LATER}]
            return bundle(doc['bill_id'], () if k.get('ask_questions') else later)
        argv = ['review_pipeline.py', '--cache-dir', str(self.cache), '--execute', *extra]
        with patch.object(sys, 'argv', argv), \
                patch.object(pipeline, 'download_document', side_effect=lambda b, r: {'bill_id': b}), \
                patch.object(pipeline, 'run_document', side_effect=run_document):
            pipeline.main()
        return json.loads((self.cache / 'queue.json').read_text('utf-8'))

    def test_first_visit_defers_questions_and_the_next_visit_asks_them(self):
        queue = self.run_main()
        self.assertEqual(self.asked, {'HB1': [False], 'HB2': [False], 'HB3': [False]})
        self.assertEqual(queue['retry'], self.ids)
        self.asked.clear()
        queue = self.run_main()
        self.assertEqual(self.asked, {'HB1': [True], 'HB2': [True], 'HB3': [True]})
        self.assertEqual(queue['retry'], [])

    def test_start_while_previous_run_holds_the_lock_exits_cleanly(self):
        self.cache.mkdir(parents=True, exist_ok=True)
        with pipeline.ResponseCache(self.cache / 'worker-lock')._lock('worker'):
            argv = ['review_pipeline.py', '--cache-dir', str(self.cache), '--execute']
            with patch.object(sys, 'argv', argv), \
                    patch.object(pipeline, 'run_document', side_effect=AssertionError('must not run')):
                self.assertEqual(pipeline.main(), 0)
        self.assertFalse((self.cache / 'queue.json').exists())
        self.assertEqual(pipeline.build_parser().parse_args(['--cache-dir', 'x']).max_minutes, 55)

    def test_existing_review_explicit_bill_and_inline_flag_ask_at_once(self):
        (self.cache / 'reviews').mkdir(parents=True)
        (self.cache / 'reviews' / 'HB2.json').write_text('{}', 'utf-8')
        self.run_main()
        self.assertEqual(self.asked['HB2'], [True])  # Never replace an earlier review with a bare first pass.
        self.assertEqual(self.asked['HB1'], [False])
        self.asked.clear()
        self.run_main('--bill-id', 'HB9')
        self.assertEqual(self.asked, {'HB9': [True]})
        self.asked.clear()
        (self.cache / 'queue.json').unlink()
        self.run_main('--questions-inline')
        self.assertEqual(set(map(tuple, self.asked.values())), {(True,)})


if __name__ == '__main__':
    unittest.main()
