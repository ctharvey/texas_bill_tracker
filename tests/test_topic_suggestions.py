"""`review_pipeline.py --suggest-topics`: the lowest-priority second pass, end to end with only the OpenAI SDK faked
(the harness from test_review_stages_pipeline). No network, no paid calls."""
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review_stages_pipeline import (  # noqa: E402
    CLASSIFY, QUOTE_I, FakeSDK, StagesCase, body, classification_result, pipeline)
from test_flex_boundary import Err  # noqa: E402

SUGGEST = 'texas_bill_topic_suggestions_v1'
REAL_TAGS = pipeline.classification.load_policy_tags


class SDK(FakeSDK):
    """Suggestion requests carry no bill text; the bill is read from the summary marker when there is one."""
    def create(self, **kw):
        text = json.dumps(kw['input'])
        name = kw['text']['format']['name']
        found = re.search(r'MARKER-([A-Z]+\d+)', text)
        bill = found[1] if found else None
        self.requests.append((bill, name))
        out = self.case.respond(bill, name, text)
        if isinstance(out, BaseException):
            raise out
        return type('Reply', (), {'model_dump': lambda s, mode='json': out})()


class SuggestionCase(StagesCase):
    def setUp(self):
        super().setUp()
        self.sdk = SDK(self)
        self.summary = lambda bill: f'Summary MARKER-{bill}.'
        self.suggestions = [{'topic': 'Water', 'reason': 'It regulates wells.', 'closest_existing': None},
                            {'topic': 'taxes', 'reason': 'Same as a current topic.', 'closest_existing': 'Taxes'}]
        self.overrides[CLASSIFY] = self.classify
        self.overrides[SUGGEST] = lambda bill, text: body({'suggestions': self.suggestions})

    def classify(self, bill, text):
        result = classification_result(bill, QUOTE_I, self.first_uncertainties)
        result['summary']['text'] = self.summary(bill)
        return body(result)

    def run_once(self, *extra, suggest=True):
        return self.run_main(*(['--suggest-topics'] if suggest else []), *extra, stages=False)

    def record(self, bill='HB1'):
        path = self.cache / 'suggestions' / (bill + '.json')
        return json.loads(path.read_text('utf-8')) if path.exists() else None

    def count(self, name, since=0):
        return sum(1 for _, n in self.sdk.requests[since:] if n == name)


class TopicSuggestionTests(SuggestionCase):
    def test_runs_once_the_queue_is_empty_and_drops_current_topics(self):
        self.seed()
        out = self.run_once()
        self.assertEqual(self.sdk.requests, [('HB1', CLASSIFY), ('HB1', SUGGEST)])  # review first, then the pass
        record = self.record()
        self.assertEqual([s['topic'] for s in record['suggestions']], ['Water'])
        self.assertEqual([s['topic'] for s in record['dropped']], ['taxes'])
        self.assertIn('Topic suggestions checked for 1 bills', out)
        self.assertFalse((self.live / 'luna' / 'suggestions').exists())  # private: never published

    def test_a_repeat_run_sends_nothing(self):
        self.seed()
        self.run_once()
        mark = len(self.sdk.requests)
        self.run_once()
        self.assertEqual(self.count(SUGGEST, mark), 0)

    def test_identical_companion_reviews_cost_one_call(self):
        self.summary = lambda bill: 'Shared companion summary.'
        self.seed(['HB1', 'SB1'])
        self.run_once()
        self.assertEqual(self.count(SUGGEST), 1)  # the second bill's identical request is a cache hit
        self.assertEqual(self.record('HB1')['request_key'], self.record('SB1')['request_key'])

    def test_a_bill_with_queued_questions_waits_until_its_review_settles(self):
        self.first_uncertainties = [{'question': 'Does the sunset apply?', 'affected_claims': ['summary'],
                                     'span_ids': ['P004S001'], 'needed_source': None}]
        self.seed()
        self.run_once()
        self.assertIn('HB1', json.loads((self.cache / 'queue.json').read_text('utf-8'))['retry'])
        self.assertEqual(self.count(SUGGEST), 0)
        self.assertIsNone(self.record())

    def test_a_topic_list_change_reasks_once(self):
        self.seed()
        self.run_once()
        mark = len(self.sdk.requests)
        with patch.object(pipeline.classification, 'load_policy_tags', lambda *a, **k: REAL_TAGS() + ['Water']):
            self.run_once()
            self.assertEqual(self.count(SUGGEST, mark), 1)
            self.assertEqual(self.record()['suggestions'], [])  # "Water" is now a current topic
            mark = len(self.sdk.requests)
            self.run_once()
            self.assertEqual(self.count(SUGGEST, mark), 0)

    def test_capacity_ends_the_pass_without_a_record_or_a_stop(self):
        self.seed(['HB1', 'HB2'])
        self.overrides[SUGGEST] = lambda bill, text: Err(429, 'flex_unavailable')
        out = self.run_once()
        self.assertIn('Topic suggestions: capacity unavailable', out)
        self.assertIsNone(self.record('HB1')); self.assertIsNone(self.record('HB2'))
        self.assertNotIn('pending', self.ledger_states())
        self.assertTrue((self.live / 'luna' / 'tags.json').exists())  # the run still published normally

    def test_one_rejected_bill_does_not_hold_up_the_others(self):
        self.seed(['HB1', 'HB2', 'HB3'])
        reply = lambda bill, text: (Err(429, 'flex_unavailable') if bill == 'HB2'
                                    else body({'suggestions': self.suggestions}))
        self.overrides[SUGGEST] = reply
        out = self.run_once()
        self.assertIn('capacity unavailable for HB2', out)
        self.assertIsNone(self.record('HB2'))
        self.assertIsNotNone(self.record('HB1')); self.assertIsNotNone(self.record('HB3'))

    def test_three_rejections_in_a_row_end_the_pass(self):
        self.seed(['HB1', 'HB2', 'HB3', 'HB4'])
        self.overrides[SUGGEST] = lambda bill, text: Err(429, 'flex_unavailable')
        out = self.run_once()
        self.assertIn('3 times in a row', out)
        self.assertNotIn('HB4', [b for b, n in self.sdk.requests if n == SUGGEST])  # never tried

    def test_off_without_the_flag(self):
        self.seed()
        self.run_once(suggest=False)
        self.assertEqual(self.count(SUGGEST), 0)


if __name__ == '__main__':
    unittest.main()
