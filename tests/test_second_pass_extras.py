"""Second-pass reader extras (headline, search and opposing terms), the spot-check audit, and related bills, end to
end through review_pipeline.py with only the OpenAI SDK (and the embedder) faked. No network, no paid calls."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_topic_suggestions import SUGGEST, SuggestionCase, pipeline  # noqa: E402
from test_review_stages_pipeline import body  # noqa: E402
from test_flex_boundary import Err  # noqa: E402

import related_bills  # noqa: E402
import review_audit  # noqa: E402
import topic_suggestions  # noqa: E402

AUDIT = 'texas_bill_review_audit_v1'


class ExtrasTests(SuggestionCase):
    def extras(self):
        return json.loads((self.live / 'luna' / 'extras.json').read_text('utf-8'))

    def test_extras_are_published_for_the_current_review(self):
        self.seed()
        self.run_once()
        extras = self.extras()
        self.assertEqual(extras['format'], 'texas-bill-luna-extras-v1')
        self.assertEqual(extras['bills']['HB1'], {'headline': 'Sets rules for water wells.',
                                                  'search_terms': ['groundwater'], 'opposing_terms': []})
        record = self.record()
        self.assertEqual(record['input_sha256'], topic_suggestions.input_hash(
            json.loads((self.cache / 'reviews' / 'HB1.json').read_text('utf-8'))))

    def test_a_changed_review_hides_stale_extras(self):
        self.seed()
        self.run_once()
        review = self.cache / 'reviews' / 'HB1.json'
        bundle = json.loads(review.read_text('utf-8'))
        bundle['result']['summary']['text'] = 'A different summary MARKER-HB1.'
        review.write_text(json.dumps(bundle), 'utf-8')
        with patch.object(pipeline, 'suggest_topics', lambda *a, **k: 0), \
                patch.object(pipeline, 'queue_candidates', lambda *a, **k: []):  # publish only
            self.run_once()
        self.assertNotIn('HB1', self.extras()['bills'])

    def test_an_unverified_summary_never_reaches_the_request_or_a_headline(self):
        self.seed()
        self.run_once()
        review = self.cache / 'reviews' / 'HB1.json'
        bundle = json.loads(review.read_text('utf-8'))
        bundle['validation']['verified_citations'] = [c for c in bundle['validation']['verified_citations']
                                                     if c.get('claim') != 'summary']
        self.assertIsNone(topic_suggestions.review_input(bundle)['summary'])
        record = {**self.record(), 'input_sha256': topic_suggestions.input_hash(bundle)}
        entry = topic_suggestions.extras_entry(bundle, record)
        self.assertNotIn('headline', entry)
        self.assertEqual(entry['search_terms'], ['groundwater'])

    def test_terms_are_trimmed_and_deduplicated(self):
        self.overrides[SUGGEST] = lambda bill, text: body({
            'headline': '  Sets   rules. ', 'search_terms': ['Water', 'water ', 'wells'],
            'opposing_terms': ['gun control', 'gun rights'], 'suggestions': []})
        self.seed()
        self.run_once()
        entry = self.extras()['bills']['HB1']
        self.assertEqual(entry['headline'], 'Sets rules.')
        self.assertEqual(entry['search_terms'], ['Water', 'wells'])
        self.assertEqual(entry['opposing_terms'], ['gun control', 'gun rights'])


class AuditTests(SuggestionCase):
    def setUp(self):
        super().setUp()
        self.verdict = {'verdict': 'minor_issues', 'issues': [
            {'claim': 'summary', 'problem': 'Leaves out a date.', 'severity': 'minor', 'quote': 'not in the bill'}]}
        self.overrides[AUDIT] = lambda bill, text: body(self.verdict)

    def run_audit(self, *extra):
        return self.run_once('--audit-sample', *extra)

    def counts(self):
        return json.loads((self.live / 'luna' / 'audit.json').read_text('utf-8'))

    def test_a_sampled_review_is_checked_privately_and_only_counts_are_published(self):
        self.seed(['HB1', 'HB2'])
        with patch.object(review_audit, 'SAMPLE_PER_MILLE', 1000):
            out = self.run_audit()
        self.assertEqual(self.count(AUDIT), 2)
        self.assertIn('Review audit checked for 2 bills', out)
        record = json.loads((self.cache / 'audit' / 'HB1.json').read_text('utf-8'))
        self.assertEqual(record['verdict'], 'minor_issues')
        self.assertFalse(record['issues'][0]['quote_found'])
        counts = self.counts()
        self.assertEqual({k: counts[k] for k in ('checked', 'agree', 'minor_issues', 'major_issues')},
                         {'checked': 2, 'agree': 0, 'minor_issues': 2, 'major_issues': 0})
        published = (self.live / 'luna' / 'audit.json').read_text('utf-8')
        self.assertNotIn('Leaves out a date', published)
        self.assertFalse((self.live / 'luna' / 'audit').exists())

    def test_a_repeat_run_sends_nothing_and_unsampled_bills_are_never_sent(self):
        self.seed()
        with patch.object(review_audit, 'SAMPLE_PER_MILLE', 1000):
            self.run_audit()
            mark = len(self.sdk.requests)
            self.run_audit()
        self.assertEqual(self.count(AUDIT, mark), 0)
        with patch.object(review_audit, 'SAMPLE_PER_MILLE', 0):
            (self.cache / 'audit' / 'HB1.json').unlink()
            self.run_audit()
        self.assertEqual(self.count(AUDIT, mark), 0)

    def test_text_on_disk_that_differs_from_the_reviewed_text_is_skipped(self):
        self.seed()
        self.run_once()
        self.put('HB1', 'I', '# changed text MARKER-HB1\n\nSomething else entirely.\n')
        mark = len(self.sdk.requests)
        with patch.object(review_audit, 'SAMPLE_PER_MILLE', 1000), \
                patch.object(pipeline, 'suggest_topics', lambda *a, **k: 0), \
                patch.object(pipeline, 'queue_candidates', lambda *a, **k: []):
            self.run_audit()
        self.assertEqual(self.count(AUDIT, mark), 0)

    def test_capacity_skips_the_bill_without_a_stop(self):
        self.seed()
        self.overrides[AUDIT] = lambda bill, text: Err(429, 'flex_unavailable')
        with patch.object(review_audit, 'SAMPLE_PER_MILLE', 1000):
            out = self.run_audit()
        self.assertIn('Review audit: capacity unavailable for HB1', out)
        self.assertNotIn('pending', self.ledger_states())
        self.assertEqual(self.counts()['checked'], 0)

    def test_off_without_the_flag(self):
        self.seed()
        with patch.object(review_audit, 'SAMPLE_PER_MILLE', 1000):
            self.run_once()
        self.assertEqual(self.count(AUDIT), 0)
        self.assertFalse((self.live / 'luna' / 'audit.json').exists())


class FakeEmbedder:
    """Deterministic 256-d vectors from word buckets, so texts sharing words are similar."""
    def __init__(self):
        self.calls, self.fail = [], None

    def __call__(self, texts):
        if self.fail:
            raise self.fail
        self.calls.append(list(texts))
        out = []
        for text in texts:
            vector = [0.0] * related_bills.DIMENSIONS
            for word in text.lower().replace('.', ' ').split():
                vector[sum(map(ord, word)) % related_bills.DIMENSIONS] += 1.0
            out.append(vector)
        return out, sum(len(t.split()) for t in texts)


class RelatedTests(SuggestionCase):
    def setUp(self):
        super().setUp()
        self.embedder = FakeEmbedder()
        p = patch.object(pipeline, 'RELATED_EMBEDDER', self.embedder); p.start(); self.addCleanup(p.stop)

    def seed_snapshot(self, bills):
        self.seed([b['id'] for b in bills])
        self.snap.write_text(json.dumps({'bills': bills}), 'utf-8')

    def related(self):
        return json.loads((self.live / 'luna' / 'related.json').read_text('utf-8'))

    def bills(self):
        return [{'id': 'HB1', 'caption': 'Relating to groundwater wells and water districts.'},
                {'id': 'HB2', 'caption': 'Relating to water districts and groundwater permits.'},
                {'id': 'HB3', 'caption': 'Relating to groundwater wells and water districts.',
                 'companions': [{'id': 'HB1', 'relation': 'Identical'}]},
                {'id': 'HB4', 'caption': 'Relating to school bus seat belts.'}]

    def test_related_bills_skip_companions_and_unrelated_bills(self):
        self.seed_snapshot(self.bills())
        out = self.run_once('--related-bills', suggest=False)
        related = self.related()
        self.assertEqual(related['format'], 'texas-bill-related-v1')
        ids = [r['id'] for r in related['bills']['HB1']]
        self.assertIn('HB2', ids)
        self.assertNotIn('HB3', ids)  # listed companion (and identical text)
        self.assertNotIn('HB4', ids)  # below the score floor
        self.assertIn('Published related bills for', out)

    def test_a_repeat_run_embeds_nothing_new(self):
        self.seed_snapshot(self.bills())
        self.run_once('--related-bills', suggest=False)
        sent = sum(len(c) for c in self.embedder.calls)
        self.run_once('--related-bills', suggest=False)
        self.assertEqual(sum(len(c) for c in self.embedder.calls), sent)
        usage = (self.cache / 'embeddings' / 'usage.jsonl').read_text('utf-8').splitlines()
        self.assertEqual(len(usage), 1)

    def test_a_failure_keeps_the_previous_file_and_the_run_succeeds(self):
        self.seed_snapshot(self.bills())
        self.run_once('--related-bills', suggest=False)
        before = (self.live / 'luna' / 'related.json').read_bytes()
        self.snap.write_text(json.dumps({'bills': self.bills() + [{'id': 'HB5', 'caption': 'Relating to ponds.'}]}),
                             'utf-8')
        self.embedder.fail = RuntimeError('429')
        out = self.run_once('--related-bills', suggest=False)
        self.assertIn('Related bills not updated: RuntimeError', out)
        self.assertEqual((self.live / 'luna' / 'related.json').read_bytes(), before)
        self.assertTrue((self.live / 'luna' / 'tags.json').exists())

    def test_off_without_the_flag_or_without_execute(self):
        self.seed_snapshot(self.bills())
        self.run_once(suggest=False)
        self.assertEqual(self.embedder.calls, [])
        self.assertFalse((self.live / 'luna' / 'related.json').exists())


class AuditTextTests(unittest.TestCase):
    MARKDOWN = ('# HB 7 - Introduced\n\nSECTION 1. Section 2.01 is amended to read:\n\n'
                'An office may <del>not offer the old program</del> <ins>offer the new program</ins> to students.\n\n'
                + 'Long paragraph ' + 'word ' * 200 + 'END.\n')

    def document(self):
        return pipeline.detailed.document_from_markdown('HB7', '90R', 'introduced', self.MARKDOWN)

    def test_the_auditor_sees_insertions_and_deletions(self):
        document = self.document()
        bundle = {'bill_id': 'HB7', 'document': document, 'validation': {'verified_citations': []},
                  'result': {'summary': {'text': 'x'}}}
        text = review_audit.build_request(bundle, document)['input'][1]['content'][0]['text']
        self.assertIn('<del>not offer the old program</del> <ins>offer the new program</ins>', text)
        self.assertIn('<ins>', review_audit.build_request(bundle, document)['input'][0]['content'][0]['text'])
        marked = review_audit.marked_text(document)
        self.assertEqual(marked.count('\n\n'), review_audit.bill_text(document).count('\n\n'))  # paragraphs kept
        self.assertIn('word ' * 199 + 'word END.', ' '.join(marked.split()) + ' ')  # split spans rejoined

    def test_quotes_are_checked_without_the_tags(self):
        result = {'verdict': 'major_issues', 'issues': [
            {'claim': 'summary', 'problem': 'p', 'severity': 'major', 'quote': 'offer the new program'},
            {'claim': 'summary', 'problem': 'p', 'severity': 'major', 'quote': '<ins>offer the new program</ins>'},
            {'claim': 'summary', 'problem': 'p', 'severity': 'minor', 'quote': 'not in this bill'}]}
        found = [i['quote_found'] for i in review_audit.validate(result, self.document())['issues']]
        self.assertEqual(found, [True, True, False])


class TopRelatedTests(unittest.TestCase):
    def test_keeps_the_best_five_in_order(self):
        unit = lambda v: [x / sum(y * y for y in v) ** .5 for x in v]
        vectors = {f'k{i}': unit([1.0, i / 10]) for i in range(8)}
        keys = {f'B{i}': f'k{i}' for i in range(8)}
        result = related_bills.top_related(keys, vectors, set(), top=5, min_score=0)
        self.assertEqual([r['id'] for r in result['B0']], ['B1', 'B2', 'B3', 'B4', 'B5'])
        scores = [r['score'] for r in result['B0']]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == '__main__':
    unittest.main()
