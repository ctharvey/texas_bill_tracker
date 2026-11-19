"""Counterexamples for first-pass retries: a cut-off answer or an unverified summary is sent again, changed, at most
MAX_FIRST_PASS_RETRIES times per text; a cached failure is never replayed as a retry; a worse retry never replaces a
better review."""
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
from extraction_cache import ResponseCache
import flex_boundary  # noqa: F401 - puts scripts/vendor on sys.path
from cth_flex.cache import ResponseCache as FlexCache

CAP = classification.MAX_FIRST_PASS_RETRIES


def truncated(raw_model=classification.MODEL):
    return {"id": "r", "model": raw_model, "service_tier": "flex", "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"}, "output": [],
            "usage": {"input_tokens": 10, "output_tokens": 12000}}


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.registry = detailed.load_registry()
        self.doc = detailed.document_from_pages("HB1", "90R", "introduced", ["The board shall publish maps."])

    def test_attempt_zero_is_the_unchanged_first_pass(self):
        request = classification.build_request(self.doc, self.registry)
        self.assertEqual(request, classification.build_request(self.doc, self.registry, 0))
        self.assertEqual(request["max_output_tokens"], 12000)
        self.assertNotIn("RETRY", json.dumps(request))

    def test_each_retry_is_a_different_request_with_more_room(self):
        requests = [classification.build_request(self.doc, self.registry, a) for a in range(CAP + 1)]
        keys = {ResponseCache.key(r) for r in requests}
        self.assertEqual(len(keys), CAP + 1)
        self.assertEqual([r["max_output_tokens"] for r in requests], [12000 * (1 + a) for a in range(CAP + 1)])
        # The shared prompt (before the cache breakpoint) is unchanged; only the bill's own message differs.
        self.assertTrue(all(r["input"][0] == requests[0]["input"][0] for r in requests))


class NoReplayTests(unittest.TestCase):
    def test_a_cached_cut_off_answer_replays_but_a_retry_is_sent(self):
        registry = detailed.load_registry()
        doc = detailed.document_from_pages("HB1", "90R", "introduced", ["The board shall publish maps."])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "cache"
            cache, sent = FlexCache(root / "responses"), []

            def sender(request):
                sent.append(request["max_output_tokens"])
                return truncated()
            first = classification.classify(doc, registry, root, execute=True, sender=sender, cache=cache)
            again = classification.classify(doc, registry, root, execute=True, sender=sender, cache=cache)
            retry = classification.classify(doc, registry, root, execute=True, sender=sender, cache=cache, attempt=1)
        self.assertEqual(sent, [12000, 24000])
        self.assertTrue(again["cache_hit"])
        self.assertFalse(retry["cache_hit"])
        self.assertNotEqual(first["request_key"], retry["request_key"])
        for report in (first, again, retry):
            self.assertNotIn("result", report)
            self.assertEqual(report["incomplete_reason"], "max_output_tokens")


def no_result(bill_id, text_hash, attempt):
    out = {"bill_id": bill_id, "status": "needs_review", "publishable": False,
           "first_pass": {"request_key": "k%d" % attempt, "text_hash": text_hash,
                          "errors": ["Response failed validation: ValueError"]}}
    if attempt:
        out["first_pass_attempt"] = attempt
    return out


def reviewed(bill_id, text_hash, attempt, verified):
    out = {"bill_id": bill_id, "status": "needs_review", "publishable": False, "result": {"summary": {}},
           "document": {"text_hash": text_hash}, "pending_questions": [], "stop_run": None,
           "first_pass_request_key": "k%d" % attempt,
           "validation": {"errors": [], "verified_citations": [
               {"claim": c, "status": "resolved"} for c in verified] + [
               {"claim": "summary", "status": "not_found"}] * ("summary" not in verified)}}
    if attempt:
        out["first_pass_attempt"] = attempt
    return out


class PipelineRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo, self.cache = base / 'repo', base / 'cache'
        (self.repo / 'data').mkdir(parents=True)
        (self.repo / 'data' / 'bills.json').write_text(json.dumps({'bills': [{'id': 'HB1'}]}), 'utf-8')
        p = patch.object(pipeline, 'ROOT', self.repo); p.start(); self.addCleanup(p.stop)
        p = patch.object(pipeline.detailed, 'load_registry', return_value=[]); p.start(); self.addCleanup(p.stop)
        self.text_hash, self.attempts = 'h1', []

    def run_main(self, answer):
        def download(bill_id, root):
            return {'bill_id': bill_id, 'text_hash': self.text_hash}

        def run_document(document, *args, attempt=0, **kwargs):
            self.attempts.append(attempt)
            return answer(document['bill_id'], document['text_hash'], attempt)
        argv = ['review_pipeline.py', '--cache-dir', str(self.cache), '--execute']
        with patch.object(sys, 'argv', argv), patch.object(pipeline, 'download_document', side_effect=download), \
                patch.object(pipeline, 'run_document', side_effect=run_document):
            pipeline.main()
        return json.loads((self.cache / 'queue.json').read_text('utf-8'))

    def review(self):
        return json.loads((self.cache / 'reviews' / 'HB1.json').read_text('utf-8'))

    def test_cut_off_first_pass_is_retried_until_the_cap_then_stops(self):
        for _ in range(CAP + 2):
            queue = self.run_main(no_result)
        # Past the cap the visit rebuilds the stored (attempt 0) request: a cache hit, never a new call.
        self.assertEqual(self.attempts, list(range(CAP + 1)) + [0])
        self.assertNotIn('HB1', queue['retry'])
        self.assertEqual(queue['first_pass_retry']['HB1'], {'text_hash': 'h1', 'tried': CAP, 'reason': 'incomplete'})

    def test_bill_stays_on_the_retry_list_while_a_retry_is_owed(self):
        queue = self.run_main(no_result)
        self.assertIn('HB1', queue['retry'])
        self.assertIn('HB1', queue['seen'])
        self.assertEqual(queue['first_pass_retry']['HB1']['tried'], 0)

    def test_a_retry_that_verifies_the_summary_clears_the_debt(self):
        answer = lambda b, h, a: no_result(b, h, a) if a == 0 else reviewed(b, h, a, ['summary', 'policy_tags:0'])
        self.run_main(answer)
        queue = self.run_main(answer)
        self.assertEqual(self.attempts, [0, 1])
        self.assertNotIn('HB1', queue['retry'])
        self.assertNotIn('HB1', queue['first_pass_retry'])
        self.assertEqual(self.review()['first_pass_attempt'], 1)
        self.run_main(answer)  # a later visit rebuilds the successful request, not attempt 0
        self.assertEqual(self.attempts, [0, 1, 1])

    def test_unverified_summary_is_retried_and_a_worse_retry_never_replaces_the_review(self):
        def answer(b, h, a):
            return reviewed(b, h, a, ['policy_tags:0', 'agencies:0'] if a == 0 else [])
        for _ in range(CAP + 2):
            queue = self.run_main(answer)
        self.assertEqual(self.attempts, list(range(CAP + 1)) + [0])
        review = self.review()
        self.assertNotIn('first_pass_attempt', review)
        self.assertEqual(review['first_pass_request_key'], 'k0')
        self.assertNotIn('HB1', queue['retry'])
        self.assertEqual(queue['first_pass_retry']['HB1']['tried'], CAP)

    def test_a_new_text_starts_again_at_attempt_zero(self):
        for _ in range(CAP + 1):
            self.run_main(no_result)
        self.text_hash = 'h2'
        queue = self.run_main(no_result)
        self.assertEqual(self.attempts[-1], 0)
        self.assertEqual(queue['first_pass_retry']['HB1'], {'text_hash': 'h2', 'tried': 0, 'reason': 'incomplete'})
        self.assertIn('HB1', queue['retry'])

    def test_questions_still_owed_come_before_a_first_pass_retry(self):
        def answer(b, h, a):
            out = reviewed(b, h, a, [])
            out['pending_questions'] = [{'id': 'q', 'reason': 'NotSubmitted'}]
            return out
        queue = self.run_main(answer)
        self.assertIn('HB1', queue['retry'])  # the questions' own retry
        self.assertNotIn('HB1', queue.get('first_pass_retry', {}))
        self.run_main(answer)
        self.assertEqual(self.attempts, [0, 0])

    def test_a_good_first_pass_owes_nothing(self):
        queue = self.run_main(lambda b, h, a: reviewed(b, h, a, ['summary']))
        self.assertEqual(self.attempts, [0])
        self.assertNotIn('HB1', queue['retry'])
        self.assertEqual(queue.get('first_pass_retry'), {})


class AttemptChoiceTests(unittest.TestCase):
    def test_debt_for_another_text_is_ignored(self):
        queue = {'first_pass_retry': {'HB1': {'text_hash': 'old', 'tried': 0, 'reason': 'incomplete'}}}
        self.assertEqual(pipeline.first_pass_attempt(queue, 'HB1', None, 'new'), 0)

    def test_version_update_and_companion_reviews_are_not_retried(self):
        base = reviewed('HB1', 'h', 0, [])
        self.assertEqual(pipeline.first_pass_retry_reason(base), 'summary_unverified')
        self.assertIsNone(pipeline.first_pass_retry_reason({**base, 'version_update': {'from_code': 'I'}}))
        self.assertIsNone(pipeline.first_pass_retry_reason({**base, 'reused_from': 'SB1'}))

    def test_a_never_sent_first_pass_is_not_a_failure(self):
        self.assertIsNone(pipeline.first_pass_retry_reason(
            {'status': 'needs_review', 'first_pass': {'action': 'not_submitted', 'text_hash': 'h'}}))


if __name__ == '__main__':
    unittest.main()
