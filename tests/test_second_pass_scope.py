"""The "all state agencies" marker is decided by the second pass from the bill text: published only when its quotes
are current (not deleted) bill text long enough to carry a clause, only for the review and text content it was
made for, and never from the first pass's own marker. End to end with only the OpenAI SDK faked."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_topic_suggestions import SUGGEST, SuggestionCase, pipeline  # noqa: E402
from test_review_stages_pipeline import CLASSIFY, QUOTE_I, body, classification_result, ev, md_i  # noqa: E402
from test_text_rebinding import rerender  # noqa: E402

AGENCY_LINE = 'Each state agency shall adopt a widget safety policy.'


def with_line(markdown, line=AGENCY_LINE):
    return markdown + '\n' + line + '\n'


class ScopeTests(SuggestionCase):
    def setUp(self):
        super().setUp()
        self.scope = {'applies': True, 'explanation': 'Every state agency must adopt a policy.',
                      'quotes': [AGENCY_LINE]}
        self.overrides[SUGGEST] = lambda bill, text: body({**self.second_pass(), 'all_state_agencies': self.scope})

    def published(self, bill='HB1'):
        return json.loads(self.tags.read_text('utf-8'))['bills'].get(bill)

    def start(self, markdown=None):
        self.seed()
        self.put('HB1', 'I', markdown or with_line(md_i('HB1')))
        return self.run_once()

    def publish_only(self):
        with patch.object(pipeline, 'suggest_topics', lambda *a, **k: 0), \
                patch.object(pipeline, 'queue_candidates', lambda *a, **k: []):
            return self.run_once()

    def test_a_verified_marker_is_published_and_highlighted(self):
        self.start()
        sent = [n for _, n in self.sdk.requests]
        self.assertEqual(sent, [CLASSIFY, SUGGEST, SUGGEST])  # votes 1 and 2 agree; no vote 3
        self.assertEqual(self.published()['all_state_agencies'],
                         {'applies': True, 'explanation': 'Every state agency must adopt a policy.'})
        claims = {c['id']: c for c in self.luna('highlights')['claims']}
        self.assertEqual(claims['all_state_agencies_scope']['kind'], 'scope')
        self.assertTrue(claims['all_state_agencies_scope']['ranges'])

    def test_the_request_carries_the_bill_text(self):
        seen = []
        self.overrides[SUGGEST] = lambda bill, text: (seen.append(text), body(
            {**self.second_pass(), 'all_state_agencies': self.scope}))[1]
        self.start()
        self.assertIn('BILL TEXT:', seen[0])
        self.assertIn(AGENCY_LINE, seen[0])

    def test_the_first_pass_marker_is_ignored_in_favour_of_the_second_pass(self):
        def classify(bill, text):
            result = classification_result(bill, QUOTE_I)
            result['all_state_agencies_scope'] = {'applies': True, 'basis': 'direct',
                                                  'explanation': 'First pass says all.', 'evidence': ev(QUOTE_I)}
            return body(result)
        self.overrides[CLASSIFY] = classify
        self.scope = {'applies': False, 'explanation': '', 'quotes': []}
        self.start()
        self.assertEqual(self.published()['all_state_agencies'], {'applies': False, 'explanation': ''})

    def test_a_quote_not_in_the_text_is_not_published(self):
        self.scope['quotes'] = ['Each state agency shall file a gadget report with the governor.']
        self.start()
        self.assertNotIn('all_state_agencies', self.published())
        self.assertFalse(self.record()['scope']['verified'])
        self.assertNotIn('all_state_agencies_scope', {c['id'] for c in self.luna('highlights')['claims']})

    def test_a_quote_from_deleted_text_is_not_published(self):
        self.start(with_line(md_i('HB1'), f'<del>{AGENCY_LINE}</del>'))
        self.assertNotIn('all_state_agencies', self.published())

    def test_a_quote_too_short_to_carry_a_clause_is_not_published(self):
        self.scope['quotes'] = ['Each state agency']
        self.start()
        self.assertNotIn('all_state_agencies', self.published())

    def test_the_marker_follows_the_review_and_survives_an_identical_rerender(self):
        self.start()
        self.put('HB1', 'I', rerender(with_line(md_i('HB1'))))
        out = self.publish_only()
        self.assertIn('Re-attached 1', out)
        self.assertTrue(self.published()['all_state_agencies']['applies'])
        review = self.cache / 'reviews' / 'HB1.json'
        bundle = json.loads(review.read_text('utf-8'))
        bundle['result']['summary']['text'] = 'A different summary MARKER-HB1.'
        review.write_text(json.dumps(bundle), 'utf-8')
        self.publish_only()
        self.assertNotIn('all_state_agencies', self.published())  # made for the earlier review: not shown


if __name__ == '__main__':
    unittest.main()
