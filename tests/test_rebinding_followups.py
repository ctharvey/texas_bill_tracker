"""Counterexamples from the re-attach / Markdown-only audit: records bound to a review's text move with it on a
re-attach, a re-render during a run is not withheld, breaker-held bills stay held until approved, and a reviewed
version that left the index does not wedge the bill. End to end with only the OpenAI SDK faked."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review_stages_pipeline import (CLASSIFY, FISCAL_QUOTE, StagesCase, body, md_h, md_i,  # noqa: E402
                                         pipeline, sha)
from test_text_rebinding import BILLS, rerender, reword  # noqa: E402
import review_audit  # noqa: E402

AUDIT = 'texas_bill_review_audit_v1'


class FollowupTests(StagesCase):
    def published(self):
        return json.loads(self.tags.read_text('utf-8'))['bills']

    def audit_counts(self):
        return json.loads((self.live / 'luna' / 'audit.json').read_text('utf-8'))

    def test_a_reattached_review_keeps_its_audit_verdict_counted(self):
        self.overrides[AUDIT] = lambda bill, text: body({'verdict': 'agree', 'issues': []})
        self.seed()
        with patch.object(review_audit, 'SAMPLE_PER_MILLE', 1000):
            self.run_main('--audit-sample', stages=False)
            self.assertEqual(self.audit_counts()['checked'], 1)
            self.put('HB1', 'I', rerender(md_i('HB1')))
            mark = len(self.sdk.requests)
            out = self.run_main('--audit-sample', stages=False)
        self.assertIn('Re-attached 1', out)
        self.assertEqual(self.sent_since(mark), [])
        self.assertEqual(self.audit_counts()['checked'], 1)
        record = json.loads((self.cache / 'audit' / 'HB1.json').read_text('utf-8'))
        self.assertEqual(record['text_sha256'], sha(rerender(md_i('HB1'))))

    def test_a_reattached_review_keeps_its_fiscal_check_published_without_a_visit(self):
        self.seed(['HB1'])
        self.put_fiscal('HB1', 'I', f'# Fiscal Note MARKER-HB1\n\n{FISCAL_QUOTE}\n')
        self.run_main()
        self.run_main()
        self.assertIsNotNone(self.luna('fiscal'))
        self.seed(['HB1', 'HB2'])  # an unseen bill takes the only slot, so HB1 is not visited
        self.put('HB1', 'I', rerender(md_i('HB1')))
        out = self.run_main('--max-bills', '1')
        self.assertIn('Re-attached 1', out)
        self.assertNotIn('Stage tasks due', out)  # the re-attach did not make a fiscal check look stale
        fiscal = self.luna('fiscal')
        self.assertIsNotNone(fiscal)
        self.assertEqual(fiscal['text_sha256'], sha(rerender(md_i('HB1'))))

    def test_a_rerender_during_the_run_is_reattached_before_publishing(self):
        self.seed(['HB1', 'HB2'])
        self.put_fiscal('HB1', 'I', f'# Fiscal Note MARKER-HB1\n\n{FISCAL_QUOTE}\n')
        self.run_main()
        self.run_main()
        real_rebind = pipeline.rebind_equivalent_reviews
        calls = []

        def rebind(cache_dir, text_dir):
            calls.append(1)
            if len(calls) == 2:  # the late pass: simulate the sync landing just before it
                self.put('HB1', 'I', rerender(md_i('HB1')))
            return real_rebind(cache_dir, text_dir)
        with patch.object(pipeline, 'rebind_equivalent_reviews', rebind):
            out = self.run_main()
        self.assertEqual(len(calls), 2)
        self.assertNotIn('Withheld', out)
        self.assertIn('re-rendered during the run', out)
        self.assertEqual(sorted(self.published()), ['HB1', 'HB2'])
        self.assertIsNotNone(self.luna('highlights'))
        self.assertIsNotNone(self.luna('fiscal'))

    def test_bills_the_breaker_held_stay_held_until_approved(self):
        self.seed(BILLS)
        self.run_main()
        for bill in BILLS:  # still contains the cited quote, so no follow-up questions muddy the counts
            self.put(bill, 'I', md_i(bill) + '\nAn extra paragraph from a new converter.\n')
        mark = len(self.sdk.requests)
        self.run_main('--allow-text-rereview', '3')
        self.assertEqual(sum(n == CLASSIFY for _, n in self.sent_since(mark)), 3)
        for _ in range(2):  # 5 remain, under the threshold: still not re-reviewed without approval
            mark = len(self.sdk.requests)
            out = self.run_main()
            self.assertEqual(self.sent_since(mark), [])
            self.assertIn('not visiting 5 of them', out)
        queue = json.loads((self.cache / 'queue.json').read_text('utf-8'))
        self.assertEqual(len(queue['text_blocked']), 5)
        mark = len(self.sdk.requests)
        self.run_main('--allow-text-rereview', '5')
        self.assertEqual(sum(n == CLASSIFY for _, n in self.sent_since(mark)), 5)
        mark = len(self.sdk.requests)
        out = self.run_main()  # the held list is recomputed at planning: re-reviewed bills leave it
        self.assertEqual(self.sent_since(mark), [])
        self.assertNotIn('changed text under the same version', out)
        queue = json.loads((self.cache / 'queue.json').read_text('utf-8'))
        self.assertEqual(queue['text_blocked'], [])

    def test_a_single_revision_below_the_threshold_is_still_reviewed(self):
        self.seed(BILLS)
        self.run_main()
        self.put('HB3', 'I', reword(md_i('HB3')))
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [('HB3', CLASSIFY)])

    def test_a_run_that_stops_still_withdraws_reviews_of_changed_text(self):
        self.seed(['HB1', 'HB2'])
        self.run_main()
        self.assertEqual(sorted(self.published()), ['HB1', 'HB2'])
        self.put('HB1', 'I', reword(md_i('HB1')))  # real change: HB1's review no longer matches the site
        self.overrides[CLASSIFY] = lambda bill, text: RuntimeError('unknown outcome')  # the run stops
        with self.assertRaises(SystemExit) as caught:
            self.run_main()
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(sorted(self.published()), ['HB2'])
        self.assertIsNone(self.luna('highlights'))

    def test_a_new_version_whose_reviewed_version_left_the_index_is_reviewed_afresh(self):
        self.seed(['HB1'])
        self.run_main()
        self.versions['HB1'] = []  # the index now lists only H
        self.put('HB1', 'H', md_h('HB1'))
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [('HB1', CLASSIFY)])
        queue = json.loads((self.cache / 'queue.json').read_text('utf-8'))
        self.assertNotIn('HB1', queue.get('failed', {}))
        review = self.review()
        self.assertEqual(review['document']['text_sha256'], sha(md_h('HB1')))
        self.assertNotIn('version_update', review)
        self.assertEqual(sorted(self.published()), ['HB1'])


if __name__ == '__main__':
    unittest.main()
