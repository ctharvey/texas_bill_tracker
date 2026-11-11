"""Re-rendered bill text: an identical re-render keeps its review attached and published at no cost; a real content
change is withheld and re-reviewed only within the breaker's limits or an operator's approval. Highlights are built
from the exact Markdown the publish check verified. End to end with only the OpenAI SDK faked."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review_stages_pipeline import CLASSIFY, StagesCase, md_i, pipeline, sha  # noqa: E402

BILLS = [f'HB{n}' for n in range(1, 9)]  # 8 reviewed bills: the breaker trips above 5


def rerender(markdown):
    """Byte-different, content-identical: an escaped period and trailing empty paragraphs."""
    return markdown.replace('.', '\\.', 1) + '\n\n\n'


def reword(markdown):
    return markdown.replace('annually', 'quarterly')


class RebindingTests(StagesCase):
    def published(self):
        return json.loads(self.tags.read_text('utf-8'))['bills']

    def test_an_identical_rerender_keeps_the_review_attached_published_and_unbilled(self):
        self.seed(BILLS)
        self.run_main()
        before = self.review('HB1')
        for bill in BILLS:
            self.put(bill, 'I', rerender(md_i(bill)))
        mark = len(self.sdk.requests)
        out = self.run_main()
        self.assertEqual(self.sent_since(mark), [])
        self.assertIn('Re-attached 8 reviews', out)
        self.assertNotIn('changed text under the same version', out)  # the breaker never sees them
        self.assertEqual(sorted(self.published()), BILLS)
        after = self.review('HB1')
        self.assertEqual(after['document']['text_sha256'], sha(rerender(md_i('HB1'))))
        self.assertEqual(after['result'], before['result'])
        evidence = after['text_rebindings'][-1]
        self.assertEqual((evidence['from_sha256'], evidence['to_sha256'], evidence['version']),
                         (sha(md_i('HB1')), sha(rerender(md_i('HB1'))), 'I'))
        self.assertEqual(evidence['text_hash'], before['document']['text_hash'])
        self.assertIsNotNone(self.luna('highlights'))

    def test_a_real_change_is_not_reattached(self):
        self.seed(BILLS)
        self.run_main()
        for bill in BILLS:
            self.put(bill, 'I', reword(md_i(bill)))
        mark = len(self.sdk.requests)
        out = self.run_main()
        self.assertNotIn('Re-attached', out)
        self.assertIn('changed text under the same version; not visiting 8 of them', out)
        self.assertEqual(self.sent_since(mark), [])
        self.assertEqual(self.published(), {})  # withheld: the reviews describe text the site no longer serves
        self.assertNotIn('text_rebindings', self.review('HB1'))
        self.assertIsNone(self.luna('highlights'))

    def test_the_operator_can_approve_some_rereviews(self):
        self.seed(BILLS)
        self.run_main()
        for bill in BILLS:
            self.put(bill, 'I', reword(md_i(bill)))
        mark = len(self.sdk.requests)
        out = self.run_main('--allow-text-rereview', '3')
        self.assertIn('not visiting 5 of them', out)
        sent = self.sent_since(mark)
        self.assertEqual(len(sent), 3)
        self.assertTrue(all(name == CLASSIFY for _, name in sent))
        self.assertEqual(len(self.published()), 3)  # the re-reviewed ones match the live text again

    def test_a_reattached_review_follows_further_rerenders_but_not_a_later_real_change(self):
        self.seed()
        self.run_main()
        self.put('HB1', 'I', rerender(md_i('HB1')))
        self.run_main()
        self.put('HB1', 'I', rerender(md_i('HB1')) + '\n\n')
        mark = len(self.sdk.requests)
        self.run_main()
        self.assertEqual(self.sent_since(mark), [])
        self.assertEqual(len(self.review('HB1')['text_rebindings']), 2)
        self.assertIn('HB1', self.published())
        self.put('HB1', 'I', reword(md_i('HB1')))
        with patch.object(pipeline, 'queue_candidates', lambda *a, **k: []):  # publish only, no re-review
            out = self.run_main(stages=False)
        self.assertNotIn('Re-attached', out)
        self.assertEqual(self.published(), {})

    def test_reattaching_keeps_the_review_file_time(self):
        self.seed()
        self.run_main()
        path = self.cache / 'reviews' / 'HB1.json'
        os.utime(path, (1_700_000_000, 1_700_000_000))
        self.put('HB1', 'I', rerender(md_i('HB1')))
        rebound, changed = pipeline.rebind_equivalent_reviews(self.cache, self.text)
        self.assertEqual((rebound, changed), (['HB1'], []))
        self.assertEqual(path.stat().st_mtime, 1_700_000_000)  # reviewed_at stays the review's own time
        self.assertEqual(pipeline.rebind_equivalent_reviews(self.cache, self.text), ([], []))  # idempotent

    def test_a_dry_run_does_not_reattach(self):
        self.seed()
        self.run_main()
        self.put('HB1', 'I', rerender(md_i('HB1')))
        argv = ['review_pipeline.py', '--cache-dir', str(self.cache), '--snapshot', str(self.snap),
                '--input', 'markdown', '--transport', 'flex']
        with patch.object(sys, 'argv', argv), patch.object(pipeline, 'rebind_equivalent_reviews',
                                                          side_effect=AssertionError('rebind in dry run')):
            pipeline.main()

    def test_highlights_use_the_markdown_the_check_verified(self):
        self.seed()
        self.run_main()
        real = pipeline.live_reviews

        def swap_after_check(cache_dir, served):
            live = real(cache_dir, served)
            (served / 'HB1' / 'I.md').write_text('# swapped mid-publish\n\nOther text.\n', 'utf-8')
            return live
        with patch.object(pipeline, 'live_reviews', swap_after_check), \
                patch.object(pipeline, 'queue_candidates', lambda *a, **k: []):
            self.run_main(stages=False)
        self.assertIn('HB1', self.published())
        self.assertEqual(self.luna('highlights')['text_sha256'], sha(md_i('HB1')))


if __name__ == '__main__':
    unittest.main()
