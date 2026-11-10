"""Public Luna tags: only citation-verified claims are published, with per-field caption fallback."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import review_pipeline as pipeline


def review(bill_id='HB273', resolved=(), failed=(), scope=None, **result):
    base = {'bill_id': bill_id, 'summary': {'text': 'Summary text', 'evidence': []},
            'policy_tags': [{'tag': 'Healthcare', 'explanation': 'e', 'evidence': []},
                            {'tag': 'Technology & privacy', 'explanation': 'e', 'evidence': []}],
            'agencies': [{'registry_id': 'hhsc', 'name': 'Health and Human Services Commission',
                          'impact': 'direct', 'explanation': 'e', 'evidence': []}],
            'locations': [], 'affected_groups': [{'group': 'Patients', 'explanation': 'e', 'evidence': []}],
            'major_effects': [{'effect': 'rulemaking', 'label': 'Rules', 'explanation': 'e', 'evidence': []}],
            'all_state_agencies_scope': scope or {'applies': False, 'basis': 'not_applicable', 'explanation': 'x'},
            'uncertainties': []}
    base.update(result)
    citations = [{'claim': c, 'status': 'resolved'} for c in resolved] + \
                [{'claim': c, 'status': 'unresolved'} for c in failed]
    return {'format': 'texas-bill-review-v1', 'bill_id': bill_id, 'status': 'needs_review',
            'document': {'version': 'introduced'}, 'result': base, 'validation': {'verified_citations': citations}}


ALL = ['summary', 'policy_tags:0', 'policy_tags:1', 'agencies:0', 'affected_groups:0', 'major_effects:0']


class PublicEntryTests(unittest.TestCase):
    def test_fully_verified_review_publishes_every_field(self):
        entry = pipeline.public_entry(review(resolved=ALL), '2026-11-10T04:37:00Z')
        self.assertEqual([t['tag'] for t in entry['policy_tags']], ['Healthcare', 'Technology & privacy'])
        self.assertEqual(entry['agencies'], [{'id': 'hhsc', 'name': 'Health and Human Services Commission',
                                              'impact': 'direct', 'explanation': 'e'}])
        self.assertEqual(entry['locations'], [])  # Luna found none: published as empty, not a fallback.
        self.assertEqual(entry['summary'], 'Summary text')
        self.assertEqual(entry['all_state_agencies'], {'applies': False, 'explanation': 'x'})
        self.assertEqual(entry['unverified_omitted'], 0)
        self.assertNotIn('evidence', json.dumps(entry))

    def test_unverified_claim_is_dropped_but_verified_siblings_stay(self):
        entry = pipeline.public_entry(review(resolved=[c for c in ALL if c != 'policy_tags:1'],
                                             failed=['policy_tags:1']), 'now')
        self.assertEqual([t['tag'] for t in entry['policy_tags']], ['Healthcare'])
        self.assertEqual(entry['unverified_omitted'], 1)

    def test_field_with_no_verified_claims_is_omitted_for_caption_fallback(self):
        entry = pipeline.public_entry(review(resolved=[c for c in ALL if c != 'agencies:0']), 'now')
        self.assertNotIn('agencies', entry)
        self.assertNotIn('summary', pipeline.public_entry(review(resolved=ALL[1:]), 'now'))

    def test_statewide_scope_needs_its_own_verified_citation(self):
        scope = {'applies': True, 'basis': 'direct', 'explanation': 'all agencies'}
        self.assertNotIn('all_state_agencies', pipeline.public_entry(review(resolved=ALL, scope=scope), 'now'))
        entry = pipeline.public_entry(review(resolved=ALL + ['all_state_agencies_scope'], scope=scope), 'now')
        self.assertEqual(entry['all_state_agencies'], {'applies': True, 'explanation': 'all agencies'})

    def test_bundle_without_result_is_skipped(self):
        self.assertIsNone(pipeline.public_entry({'bill_id': 'HB1', 'status': 'deferred'}, 'now'))


class PublishTagsTests(unittest.TestCase):
    def test_publish_writes_public_overlay_for_reviewed_bills(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / 'cache'; (cache / 'reviews').mkdir(parents=True)
            (cache / 'reviews' / 'HB273.json').write_text(json.dumps(review(resolved=ALL)), 'utf-8')
            (cache / 'reviews' / 'HB1.json').write_text(json.dumps({'bill_id': 'HB1', 'status': 'needs_review'}), 'utf-8')
            (cache / 'reviews' / 'HB2.json').write_text(json.dumps(review('HB9', resolved=ALL)), 'utf-8')  # Mismatched id.
            (cache / 'reviews' / 'HB3.json').write_text('{broken', 'utf-8')
            out = Path(temp) / 'live' / 'luna' / 'tags.json'
            count = pipeline.publish_tags(cache, out, [{'id': 'hhsc', 'name': 'HHSC'}])
            data = json.loads(out.read_text('utf-8'))
            self.assertEqual(count, 1)
            self.assertEqual(data['format'], 'texas-bill-luna-tags-v1')
            self.assertEqual(sorted(data['bills']), ['HB273'])
            self.assertEqual(data['agencies'], {'hhsc': 'HHSC'})
            self.assertTrue(data['bills']['HB273']['reviewed_at'].endswith('Z'))
            if os.name != 'nt':
                self.assertEqual(out.stat().st_mode & 0o777, 0o644)


if __name__ == '__main__':
    unittest.main()
