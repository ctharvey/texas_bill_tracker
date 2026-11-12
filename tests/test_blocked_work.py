"""Work that cannot be done yet must not block the rest: bills with no posted text do not trip the outage stop, and
bills a second pass was refused for capacity go last without ending the pass for everyone else."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_topic_suggestions import SUGGEST, SuggestionCase  # noqa: E402
from test_review_stages_pipeline import md_i, pipeline  # noqa: E402
from extraction_cache import CapacityUnavailable  # noqa: E402


class NoTextTests(SuggestionCase):
    def snapshot(self, ids):
        self.ids = ids
        self.snap.write_text(json.dumps({'bills': [{'id': i} for i in ids]}), 'utf-8')

    def queue(self):
        return json.loads((self.cache / 'queue.json').read_text('utf-8'))

    def test_bills_without_posted_text_do_not_stop_the_run_or_the_second_pass(self):
        waiting = ['HB2', 'HB3', 'HB4', 'HB5', 'HB6', 'HB7']  # more than OUTAGE_LIMIT, all before the one with text
        self.assertGreater(len(waiting), pipeline.OUTAGE_LIMIT)
        self.snapshot(waiting + ['HB1'])
        self.put('HB1', 'I', md_i('HB1'))
        out = self.run_once()
        self.assertNotIn('repeated new failures', out)
        self.assertIn('Topic suggestions checked for 1 bills', out)
        queue = self.queue()
        self.assertEqual(queue['seen'], ['HB1'])
        self.assertEqual({b: f['stage'] for b, f in queue['failed'].items()}, {b: 'download' for b in waiting})
        # Text posted later: the bill is reviewed and leaves the failed list.
        self.put('HB4', 'I', md_i('HB4'))
        self.run_once()
        self.assertIn('HB4', self.queue()['seen'])
        self.assertNotIn('HB4', self.queue()['failed'])

    def test_a_missing_text_tree_still_stops_as_an_outage(self):
        self.snapshot(['HB2', 'HB3', 'HB4', 'HB5', 'HB6', 'HB7', 'HB1'])  # no live/text folder at all
        out = self.run_once()
        self.assertIn('Stopped: repeated new failures', out)
        self.assertNotIn('Topic suggestions checked', out)

    def test_a_reviewed_bill_losing_its_text_still_counts(self):
        ids = ['HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6']
        self.snapshot(ids)
        for bill in ids:
            self.put(bill, 'I', md_i(bill))
        self.run_once(suggest=False)
        for bill in ids:  # every reviewed bill's text vanishes, which is not "not posted yet"
            for f in (self.text / bill).iterdir():
                f.unlink()
            (self.text / bill).rmdir()
        out = self.run_once()
        self.assertIn('Stopped: repeated new failures', out)


class RefusedOrderTests(SuggestionCase):
    def refused_file(self):
        return self.cache / pipeline.RefusedBills.FILE

    def test_refused_bills_go_after_every_other_bill_votes_included_and_clear_when_answered(self):
        self.cache.mkdir(parents=True, exist_ok=True)
        self.refused_file().write_text(json.dumps({'bills': {'Topic suggestions': ['HB1']}}), 'utf-8')
        self.seed(['HB1', 'HB2', 'HB3'])
        mark = len(self.sdk.requests)
        self.run_once()
        order = [b for b, n in self.sdk.requests[mark:] if n == SUGGEST]
        # Vote 1 then vote 2 for the bills that can proceed, then the earlier-refused bill's votes.
        self.assertEqual(order, ['HB2', 'HB3', 'HB2', 'HB3', 'HB1', 'HB1'])
        self.assertEqual(json.loads(self.refused_file().read_text('utf-8'))['bills']['Topic suggestions'], [])


class SecondPassStopTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.cache = Path(temp.name)
        self.args = type('Args', (), {'execute': True})()
        self.saved = []

    def job(self, bill, refuse):
        def call():
            if refuse:
                raise CapacityUnavailable(0)
            return {'action': 'submitted'}
        return bill, call, lambda report, b=bill: self.saved.append(b)

    def refused(self, bills=()):
        r = pipeline.RefusedBills(self.cache, 'Topic suggestions')
        for b in bills:
            r.add(b)
        return pipeline.RefusedBills(self.cache, 'Topic suggestions')  # as a later run reads it

    def run_pass(self, jobs, refused):
        return pipeline._second_pass('Topic suggestions', iter(jobs), self.args, float('inf'), refused)

    def test_bills_refused_in_an_earlier_run_do_not_end_the_pass(self):
        # The 16:40 run: the same three bills refused again, each first in line, ended the pass with 0 checked.
        refused = self.refused(['HB507', 'HB370', 'HB368'])
        jobs = [self.job(b, True) for b in ('HB507', 'HB370', 'HB368')] + [self.job('HB301', False)]
        self.assertEqual(self.run_pass(jobs, refused), 1)
        self.assertEqual(self.saved, ['HB301'])

    def test_three_new_refusals_in_a_row_still_end_the_pass_and_are_recorded(self):
        refused = self.refused()
        jobs = [self.job(b, True) for b in ('HB1', 'HB2', 'HB3')] + [self.job('HB4', False)]
        self.assertEqual(self.run_pass(jobs, refused), 0)
        self.assertEqual(self.saved, [])
        self.assertEqual(sorted(self.refused().bills), ['HB1', 'HB2', 'HB3'])

    def test_an_answer_clears_the_refusal(self):
        refused = self.refused(['HB9'])
        self.run_pass([self.job('HB9', False)], refused)
        self.assertNotIn('HB9', self.refused())

    def test_without_tracking_the_pass_behaves_as_before(self):
        jobs = [self.job(b, True) for b in ('HB1', 'HB2', 'HB3')] + [self.job('HB4', False)]
        self.assertEqual(self.run_pass(jobs, None), 0)
        self.assertFalse((self.cache / pipeline.RefusedBills.FILE).exists())


if __name__ == '__main__':
    unittest.main()
