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


BODY = ('A BILL TO BE ENTITLED AN ACT relating to a prohibition on the installation of barriers on public land. '
        'BE IT ENACTED BY THE LEGISLATURE OF THE STATE OF TEXAS: SECTION 1. Chapter 2, Government Code, is amended. '
        'SECTION 2. This Act takes effect September 1, 2027.')


def doc(bill_id, author, number, body=BODY):
    return {'bill_id': bill_id, 'pages': [f'By:AA{author} {number} {body}', f'1 2 {number} 2']}


class CompanionReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name); (self.cache / 'reviews').mkdir()
        p = patch.object(pipeline.classification, 'build_request', return_value={'text': {'format': {'schema': {}}}})
        p.start(); self.addCleanup(p.stop)
        self.verified = ['summary', 'agencies:0']
        def validate(result, document, *a, **k):
            return {'errors': [], 'verified_citations': [{'claim': c, 'status': 'resolved'} for c in self.verified]}
        p = patch.object(pipeline.classification, 'validate_result', side_effect=validate); p.start(); self.addCleanup(p.stop)

    def donor(self, bill_id='HB111', **extra):
        review = {'bill_id': bill_id, 'document': doc(bill_id, 'Morales of Maverick', 'H.B.ANo.A111'),
                  'result': {'bill_id': bill_id, 'summary': {'text': 's'}}, 'status': 'ready_for_review',
                  'first_pass_request_key': 'k', 'questions': [], 'resolutions': [], 'pending_questions': [],
                  'validation': {'errors': [], 'verified_citations': [{'claim': 'summary', 'status': 'resolved'},
                                                                      {'claim': 'agencies:0', 'status': 'resolved'}]},
                  **extra}
        (self.cache / 'reviews' / f'{bill_id}.json').write_text(json.dumps(review), 'utf-8')

    def reuse(self, relation='Identical', recipient=None):
        recipient = recipient or doc('SB273', 'Blanco', 'S.B.ANo.A273')
        return pipeline.reuse_companion_review('SB273', recipient, [{'id': 'HB111', 'relation': relation}],
                                               self.cache, [])

    def test_own_number_forms(self):
        pattern = pipeline.own_number_pattern('HB111')
        for text in ('H.B.ANo.A111', 'H.B. No. 111', 'H.B. No. 0111'):
            self.assertTrue(pattern.search(text), text)
        self.assertIsNone(pattern.search('H.B. No. 1111'))
        self.assertTrue(pipeline.own_number_pattern('HJR5').search('H.J.R.ANo.A5'))
        self.assertIsNone(pipeline.own_number_pattern('nonsense'))

    def test_body_hash_ignores_author_and_own_number_only(self):
        house = pipeline.body_hash(doc('HB111', 'Morales of Maverick', 'H.B.ANo.A111'), 'HB111')
        self.assertEqual(house, pipeline.body_hash(doc('SB273', 'Blanco', 'S.B.ANo.A273'), 'SB273'))
        cites_other = doc('SB273', 'Blanco', 'S.B.ANo.A273', BODY.replace('Chapter 2', 'Chapter 2 (H.B. No. 8)'))
        self.assertNotEqual(house, pipeline.body_hash(cites_other, 'SB273'))
        self.assertIsNone(pipeline.body_hash({'pages': ['too short H.B. No. 111']}, 'HB111'))

    def test_identical_companion_review_is_reused_for_this_bill(self):
        self.donor()
        out = self.reuse()
        self.assertEqual((out['bill_id'], out['result']['bill_id'], out['reused_from']), ('SB273', 'SB273', 'HB111'))
        self.assertEqual(out['document']['bill_id'], 'SB273')

    def test_refuses_without_proof(self):
        self.donor()
        self.assertIsNone(self.reuse(relation='Similar'))
        changed = doc('SB273', 'Blanco', 'S.B.ANo.A273', BODY.replace('2027', '2029'))
        self.assertIsNone(self.reuse(recipient=changed))
        self.verified = ['summary']  # A claim that verified for the donor fails on this text.
        self.assertIsNone(self.reuse())

    def test_never_replaces_a_first_hand_review_or_copies_a_copy(self):
        self.donor()
        (self.cache / 'reviews' / 'SB273.json').write_text(json.dumps({'bill_id': 'SB273', 'result': {}}), 'utf-8')
        self.assertIsNone(self.reuse())
        (self.cache / 'reviews' / 'SB273.json').unlink()
        self.donor(reused_from='SB999')
        self.assertIsNone(self.reuse())


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

    def test_worker_uses_a_reused_review_instead_of_a_paid_one(self):
        reused = {**bundle('HB2'), 'reused_from': 'HB1'}
        with patch.object(pipeline, 'reuse_companion_review', side_effect=lambda b, *a: reused if b == 'HB2' else None):
            queue = self.run_main()
        self.assertNotIn('HB2', self.asked)  # No first pass was sent for HB2.
        self.assertIn('HB2', queue['seen'])
        self.assertEqual(json.loads((self.cache / 'reviews' / 'HB2.json').read_text('utf-8'))['reused_from'], 'HB1')
        self.asked.clear()
        with patch.object(pipeline, 'reuse_companion_review', side_effect=AssertionError('disabled')):
            self.run_main('--no-companion-reuse')

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
