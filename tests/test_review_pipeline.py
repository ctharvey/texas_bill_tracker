import copy
import importlib.util
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
import extract_bill as detailed
import flex_boundary


def raw(value=None):
    return {'model': classification.MODEL, 'service_tier': 'flex', 'status': 'completed',
            'usage': {'input_tokens': 100, 'output_tokens': 100},
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}


class BudgetTests(unittest.TestCase):
    # Phase 5 removed the legacy Budget. Its limit validation lives on in check_limits, which main runs before
    # building the FlexBoundary. Its ledger tests moved to the flex path: spend, budget stops and capacity in
    # test_flex_boundary / test_flex_worker_loop. "An unknown outcome blocks every new call" was legacy-only:
    # the continuous worker holds just that bill (test_timeout_is_uncertain_..._held_without_blocking_other_requests).
    def test_cap_cannot_be_raised_above_authorized_dollar(self):
        for daily, run in ((1.01, .1), (1, 2), (0, 0), (1, -1)):
            with self.assertRaises(ValueError): pipeline.check_limits(daily, run)

    def test_uncapped_budget_must_disable_both_limits(self):
        for daily, run in ((None, .1), (1, None)):
            with self.assertRaises(ValueError): pipeline.check_limits(daily, run)


class QuestionTests(unittest.TestCase):
    def test_capacity_retries_progress_without_starving_new_bills(self):
        queue = {'seen': ['HB1','HB2','HB3','HB4'], 'cursor': 0, 'retry': ['HB1','HB2','HB3','HB4']}
        candidates = pipeline.queue_candidates(['HB1','HB2','HB3','HB4','HB5','HB6'], queue, 5)
        self.assertEqual(candidates, ['HB1','HB2','HB3','HB5','HB6'])
    def test_hb273_condition_is_found_without_model_question(self):
        doc = detailed.document_from_pages('HB273', '90R', 'introduced', [
            'The rules must require an automated messaging system when sending a message to patients.'])
        evidence = [{'span_id': 'P001S001', 'quote': 'require an automated messaging system'}]
        result = {'summary': {'text': 'Providers must send patients an automated notice.', 'evidence': evidence},
                  'agencies': [], 'major_effects': [], 'affected_groups': [], 'uncertainties': []}
        questions = pipeline.questions_for(result, doc)
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]['affected_claims'], ['summary'])
        self.assertIn('when', questions[0]['question'])
        result['summary']['text'] = 'Providers must use automated messaging when sending the specified message.'
        self.assertEqual(pipeline.questions_for(result, doc), [])

    def test_unknown_agency_identity_is_a_question(self):
        result = {'summary': {'text': 'A bill.', 'evidence': []}, 'uncertainties': [], 'major_effects': [],
                  'affected_groups': [], 'agencies': [{'registry_id': None, 'name': 'Board',
                      'explanation': 'Planning body.', 'evidence': [{'span_id': 'P001S001', 'quote': 'Board'}]}]}
        questions = pipeline.questions_for(result, {'spans': {}})
        self.assertEqual(questions[0]['affected_claims'], ['agencies:0'])

    def test_unrelated_sentence_condition_does_not_trigger_rewrite(self):
        doc = detailed.document_from_pages('HB1', '90R', 'introduced', [
            'The department must report annually. When practicable, a separate analysis includes river basins.'])
        result = {'summary': {'text': 'The department must report annually.',
                  'evidence': [{'span_id': 'P001S001', 'quote': 'The department must report annually.'}]},
                  'agencies': [], 'major_effects': [], 'affected_groups': [], 'uncertainties': []}
        self.assertEqual(pipeline.questions_for(result, doc), [])

    def test_invalid_citation_becomes_a_targeted_question(self):
        result = {'summary': {'text': 'A bill.', 'evidence': []}, 'uncertainties': [],
                  'agencies': [], 'major_effects': [], 'affected_groups': []}
        validation = {'verified_citations': [{'status': 'ambiguous', 'claim': 'summary',
                                             'requested_span_id': 'P001S001'}]}
        questions = pipeline.questions_for(result, {'spans': {'P001S001': {'text': 'A bill.'}}}, validation)
        self.assertEqual(questions[0]['affected_claims'], ['summary'])
        self.assertIn('unambiguous', questions[0]['question'])


@unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'Optional schema dependency')
class ResolutionTests(unittest.TestCase):
    def test_correction_contract_rejects_wrong_field_and_overlong_rewrite(self):
        import jsonschema
        from test_classify_bill import result
        value = result(); value['affected_groups'] = [{'group': 'Water providers', 'explanation': 'A role.',
            'evidence': [{'span_id': 'P001S001', 'quote': 'Water providers'}]}]
        doc = detailed.document_from_pages('HB1', '90R', 'introduced', ['Water providers must report.'])
        q = {'question': 'Check condition.', 'affected_claims': ['affected_groups:0'],
             'span_ids': ['P001S001'], 'needed_source': None}
        schema = pipeline.resolution_request(q, value, doc, [])['text']['format']['schema']
        answer = {'status': 'resolved', 'answer': 'A role.', 'evidence_ids': ['E0001'],
                  'corrections': [{'claim': 'affected_groups:0', 'field': 'impact', 'value': 'A role.'}]}
        with self.assertRaises(jsonschema.ValidationError): jsonschema.validate(answer, schema)
        answer['corrections'][0].update(field='explanation', value='x' * 501)
        with self.assertRaises(jsonschema.ValidationError): jsonschema.validate(answer, schema)
    def test_cached_targeted_resolution_changes_only_supported_fields(self):
        from test_classify_bill import result
        value = result(); value['summary']['text'] = 'The commission must publish maps.'
        doc = detailed.document_from_pages('HB1', '90R', 'introduced', [
            'The commission must publish maps when receiving an application.'])
        question = pipeline.questions_for(value, doc)[0]
        answer = {'status': 'resolved', 'answer': 'The requirement is conditional.', 'evidence_ids': ['E0001'],
                  'corrections': [{'claim': 'summary', 'field': 'text',
                                   'value': 'The commission must publish maps when receiving an application.'}]}
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory); before = copy.deepcopy(value)
            budget = flex_boundary.FlexBoundary(cache, 1, .1)
            request = pipeline.resolution_request(question, value, doc, [])
            budget.execute(request, lambda: raw(answer))
            with patch.object(budget, 'send', side_effect=AssertionError('No new call')):
                report, derived = pipeline.resolve(question, value, doc, detailed.load_registry(),
                                                   cache, budget, True, sources=[])
            self.assertEqual(value, before)
            self.assertIn('when receiving', derived['summary']['text'])
            self.assertEqual(report['result']['status'], 'resolved')
            self.assertEqual(derived['policy_tags'], value['policy_tags'])

    def test_statutory_lookup_is_scoped_cached_and_ignores_arbitrary_urls(self):
        doc = detailed.document_from_pages('HB1', '90R', 'introduced', ['Chapter 16, Water Code, is amended.'])
        question = {'needed_source': 'Section 16.001, Water Code'}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _):
                return b'<p>WATER CODE CHAPTER 16.</p><p>Sec. 16.001. Board means TWDB.</p><p>Sec. 16.002. Other.</p>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = pipeline.statutory_sources(question, doc, root, opener=lambda *a, **k: Response())
            self.assertIn('Board means TWDB', sources[0]['text'])
            again = pipeline.statutory_sources(question, doc, root,
                opener=lambda *a, **k: self.fail('Source should be cached'))
            self.assertEqual(sources, again)
            self.assertEqual(pipeline.statutory_sources({'needed_source': 'https://evil.invalid/'}, doc, root), [])


if __name__ == '__main__': unittest.main()
