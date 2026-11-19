"""Full review: a reviewed bill whose visit would only re-read its own cached answers is visited on its turn (once
every QUIET_ROTATION runs), not every run; anything that changes what its review would be is visited right away.
Real main / FlexBoundary / ledger; only the OpenAI SDK is faked. No network, no paid calls."""
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review_stages_pipeline import CLASSIFY, StagesCase, classification, md_h, pipeline  # noqa: E402

BILLS = [f'HB{i}' for i in range(1, 25)]


def visited(out):
    return {m[1] for m in re.finditer(r'^(\w+) (?:ready_for_review|needs_review)$', out, re.M)}


class QuietRotation(StagesCase):
    def setUp(self):
        super().setUp()
        self.seed(BILLS)
        self.first = self.run_main()  # every bill reviewed once

    def queue(self):
        return json.loads((self.cache / 'queue.json').read_text('utf-8'))

    def test_the_first_run_visits_every_new_bill(self):
        self.assertEqual(visited(self.first), set(BILLS))

    def test_each_run_visits_one_turn_of_quiet_bills_and_every_bill_within_the_rotation(self):
        seen, runs = set(), []
        for _ in range(pipeline.QUIET_ROTATION):
            mark = len(self.sdk.requests)
            out = self.run_main()
            self.assertEqual(self.sent_since(mark), [])  # quiet visits are free cache hits
            self.assertIn('Full review: %d reviewed bills unchanged' % len(BILLS), out)
            runs.append(visited(out))
            seen |= runs[-1]
        self.assertEqual(seen, set(BILLS))  # nobody waits longer than the rotation
        for n, run in enumerate(runs):
            self.assertEqual(run, {b for b in BILLS if pipeline.quiet_group(b) == n % pipeline.QUIET_ROTATION})
        self.assertLess(max(len(r) for r in runs), len(BILLS))

    def test_a_new_version_is_visited_on_the_next_run_whatever_its_turn(self):
        bill = next(b for b in BILLS if pipeline.quiet_group(b) != 0)  # not the next run's turn
        self.put(bill, 'H', md_h(bill))
        out = self.run_main()
        self.assertIn(bill, visited(out))
        self.assertEqual(self.review(bill)['document']['version'], 'H')

    def test_a_prompt_change_brings_every_bill_back(self):
        real = classification.build_request

        def changed_prompt(document, registry, attempt=0):
            request = real(document, registry, attempt)
            request['input'][0]['content'][0]['text'] += '\nREVISED PROMPT'
            return request
        mark = len(self.sdk.requests)
        with patch.object(classification, 'build_request', side_effect=changed_prompt):
            out = self.run_main()
        self.assertEqual(visited(out), set(BILLS))
        self.assertEqual(sorted(b for b, _k in self.sent_since(mark)), sorted(BILLS))

    def test_a_validator_change_brings_every_bill_back_without_a_call(self):
        mark = len(self.sdk.requests)
        with patch.object(classification, 'VALIDATOR_REVISION', classification.VALIDATOR_REVISION + 1):
            out = self.run_main()
            self.assertEqual(visited(out), set(BILLS))
            self.assertEqual(self.sent_since(mark), [])
            self.assertEqual(self.review('HB1')['validation']['validator_revision'], classification.VALIDATOR_REVISION)
            self.assertNotIn('HB1', visited(self.run_main()) - {b for b in BILLS if pipeline.quiet_group(b) == 1})

    def test_retry_and_failed_bills_are_never_held_back(self):
        queue = self.queue()
        held = [b for b in BILLS if pipeline.quiet_group(b) != 0][:2]
        queue['retry'] = [held[0]]
        queue['failed'] = {held[1]: {'stage': 'download', 'at': 0}}
        (self.cache / 'queue.json').write_text(json.dumps(queue), 'utf-8')
        out = self.run_main()
        self.assertTrue(set(held) <= visited(out), out)

    def test_the_turn_is_kept_in_the_queue_and_moves_once_per_run(self):
        self.assertNotIn('quiet_turn', self.queue())  # the first run had no reviewed bills
        self.run_main()
        self.assertEqual(self.queue()['quiet_turn'], 1)
        self.run_main()
        self.assertEqual(self.queue()['quiet_turn'], 2)


if __name__ == '__main__':
    unittest.main()
