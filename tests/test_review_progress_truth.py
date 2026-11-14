"""The review page's two live facts: status.json names the later pass's bills in flight (one per slot, with the step)
while it runs, and a published review's reviewed_at is when Luna answered, not when a free revisit rewrote the file.
Real main / FlexBoundary; only the OpenAI SDK is faked."""
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_later_pass_slots import BILLS, FALSE, SUGGEST, SlotCase  # noqa: E402
from test_review_stages_pipeline import pipeline  # noqa: E402

OLD = 1767268800  # 2026-01-01T12:00:00Z


class InFlightStatus(SlotCase):
    def status(self):
        return json.loads((self.tags.parent / 'status.json').read_text('utf-8'))

    def test_status_lists_each_slots_bill_and_step_while_the_pass_runs(self):
        self.prepare(BILLS[:3])
        self.gather, self.answers = 3, {1: FALSE, 2: FALSE}
        seen = []
        reply = self.reply

        def watch(bill, text):
            out = reply(bill, text)  # returns once three bills are in flight
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    snap = self.status()
                except (OSError, ValueError):
                    snap = {}
                if len(snap.get('pass_jobs') or []) >= 3:
                    seen.append(snap)
                    break
                time.sleep(0.01)
            return out
        self.overrides[SUGGEST] = watch
        self.later('--later-workers', '3')
        self.assertTrue(seen, 'status never showed three bills in flight')
        snap = seen[0]
        self.assertEqual(snap['pass'], 'topics')
        self.assertTrue(snap['running'])
        self.assertEqual({j['bill'] for j in snap['pass_jobs']}, set(BILLS[:3]))
        self.assertTrue(all(j['job'] in ('headline and scope vote 1', 'scope vote 2') for j in snap['pass_jobs']))
        final = self.status()
        self.assertNotIn('pass_jobs', final)
        self.assertFalse(final['running'])
        self.assertEqual(final['passes']['topics']['checked'], 3)


class ReviewedAt(SlotCase):
    def published_at(self, bill):
        return json.loads(self.tags.read_text('utf-8'))['bills'][bill]['reviewed_at']

    def test_a_free_revisit_does_not_move_reviewed_at(self):
        self.prepare(['HB1'])
        review = json.loads((self.cache / 'reviews' / 'HB1.json').read_text('utf-8'))
        response = self.cache / 'responses' / (review['first_pass_request_key'] + '.json')
        entry = json.loads(response.read_text('utf-8'))
        self.assertEqual(entry['state'], 'returned')
        entry['returned_at'] = OLD  # Luna answered long ago
        response.write_text(json.dumps(entry), 'utf-8')
        sent = len(self.sdk.requests)
        queue = json.loads((self.cache / 'queue.json').read_text('utf-8'))
        with unittest.mock.patch.object(pipeline, 'queue_candidates', lambda *a, **k: ['HB1']):
            self.run_once(suggest=False)  # the cycle revisits HB1: a cache hit that rewrites its review file
        self.assertEqual(len(self.sdk.requests), sent)  # no new call
        self.assertGreater((self.cache / 'reviews' / 'HB1.json').stat().st_mtime, OLD + 3600)
        self.assertEqual(self.published_at('HB1'), '2026-01-01T12:00:00Z')
        self.assertIsInstance(queue, dict)

    def test_a_follow_up_answer_counts_as_the_latest_review(self):
        bundle = {'first_pass_request_key': 'a' * 64, 'resolutions': [{'request_key': 'b' * 64}, {'request_key': 'bad/key'}]}
        responses = self.cache / 'responses'
        responses.mkdir(parents=True)
        (responses / ('a' * 64 + '.json')).write_text(json.dumps({'state': 'returned', 'returned_at': OLD}), 'utf-8')
        (responses / ('b' * 64 + '.json')).write_text(json.dumps({'state': 'returned', 'returned_at': OLD + 60}), 'utf-8')
        path = self.cache / 'HB1.json'
        path.write_text('{}', 'utf-8')
        self.assertEqual(pipeline.review_time(self.cache, bundle, path), '2026-01-01T12:01:00Z')

    def test_no_readable_reply_falls_back_to_the_file_time(self):
        path = self.cache / 'HB1.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}', 'utf-8')
        import os
        os.utime(path, (OLD, OLD))
        self.assertEqual(pipeline.review_time(self.cache, {'first_pass_request_key': 'c' * 64}, path),
                         '2026-01-01T12:00:00Z')


if __name__ == '__main__':
    unittest.main()
