"""Later passes in slots (--later-workers): several bills at once, one bill's calls never overlapping and its scope
votes run right after its vote 1, the main thread the only writer, stops that start nothing new but save what is in
flight. Real main / FlexBoundary / ledger; only the OpenAI SDK is faked. No network, no paid calls."""
import contextlib
import io
import json
from pathlib import Path
import re
import signal
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_flex_boundary import Err  # noqa: E402
from test_second_pass_scope import AGENCY_LINE, with_line  # noqa: E402
from test_topic_suggestions import SUGGEST, SuggestionCase  # noqa: E402
from test_review_stages_pipeline import body, md_i, pipeline  # noqa: E402

TRUE = {'applies': True, 'explanation': 'Every state agency must adopt a policy.', 'quotes': [AGENCY_LINE]}
FALSE = {'applies': False, 'explanation': '', 'quotes': []}
BILLS = ['HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6']


class SlotCase(SuggestionCase):
    def setUp(self):
        super().setUp()
        self.lock = threading.Lock()
        self.active = {}            # bill -> calls in flight
        self.peak = 0               # most bills in flight at once
        self.overlap = []           # a bill seen twice in flight
        self.calls = []             # (bill, vote) in the order sent
        self.answers = {}           # vote -> scope dict, or bill -> exception for every call of that bill
        self.gather = 0             # hold the first `gather` calls until that many are in flight
        self.overrides[SUGGEST] = self.reply
        self.addCleanup(pipeline.STOP_REQUESTED.clear)

    def prepare(self, bills):
        self.seed(bills)
        for bill in bills:
            self.put(bill, 'I', with_line(md_i(bill)))
        self.run_once(suggest=False)  # first pass only: reviews to work from

    def later(self, *extra):
        with patch.object(pipeline, 'queue_candidates', lambda *a, **k: []):  # only the later pass runs
            return self.run_once(*extra)

    def later_exit(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                self.later(*extra)
            except SystemExit as stop:
                return stop.code
        return None

    def reply(self, bill, text):
        found = re.search(r'RUN: (\d)', text)
        vote = int(found[1]) if found else 1
        with self.lock:
            self.calls.append((bill, vote))
            if self.active.get(bill):
                self.overlap.append(bill)
            self.active[bill] = self.active.get(bill, 0) + 1
            self.peak = max(self.peak, sum(1 for n in self.active.values() if n))
            waiting = self.gather > 0
            if waiting:
                self.gather -= 1
        try:
            if waiting:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with self.lock:
                        if self.peak >= 3:
                            break
                    time.sleep(0.01)
            time.sleep(0.005)
            answer = self.answers.get(bill, self.answers.get(vote, FALSE))
            return answer if isinstance(answer, BaseException) else body({**self.second_pass(),
                                                                          'all_state_agencies': answer})
        finally:
            with self.lock:
                self.active[bill] -= 1

    def marker(self, bill):
        bills = json.loads(self.tags.read_text('utf-8'))['bills']
        return (bills.get(bill) or {}).get('all_state_agencies')

    def ledger_pending(self):
        return [s for s in self.ledger_states() if s == 'pending']


class Slots(SlotCase):
    def test_three_bills_run_at_once_and_each_bill_decides_its_marker(self):
        self.prepare(BILLS[:3])
        self.gather, self.answers = 3, {1: TRUE, 2: FALSE, 3: TRUE}
        self.later('--later-workers', '3')
        self.assertGreaterEqual(self.peak, 3)
        self.assertEqual(self.overlap, [])
        for bill in BILLS[:3]:
            self.assertEqual([v for b, v in self.calls if b == bill], [1, 2, 3])  # its own votes, in order
            self.assertTrue(self.marker(bill)['applies'])
        self.assertEqual(self.ledger_pending(), [])

    def test_a_bills_votes_come_right_after_its_vote_1(self):
        self.prepare(BILLS)
        self.answers = {1: FALSE, 2: FALSE}
        self.later('--later-workers', '2')
        self.assertEqual(self.overlap, [])
        first_votes = [i for i, (b, v) in enumerate(self.calls) if v == 1]
        for bill in BILLS:
            mine = [i for i, (b, v) in enumerate(self.calls) if b == bill]
            self.assertEqual([self.calls[i][1] for i in mine], [1, 2])
            # Two slots: at most one other bill's vote 1 goes between this bill's vote 1 and vote 2.
            between = [i for i in first_votes if mine[0] < i < mine[1]]
            self.assertLessEqual(len(between), 1, (bill, self.calls))
        for bill in BILLS:
            self.assertEqual(self.marker(bill), {'applies': False, 'explanation': ''})

    def test_later_workers_1_keeps_todays_order(self):
        self.prepare(BILLS[:3])
        self.answers = {1: FALSE, 2: FALSE}
        self.later('--later-workers', '1')
        # Every bill's vote 1 first (headlines are not held back), then the scope votes.
        self.assertEqual(self.calls, [('HB3', 1), ('HB2', 1), ('HB1', 1), ('HB3', 2), ('HB2', 2), ('HB1', 2)]
                         if self.calls[0][0] == 'HB3' else
                         [('HB1', 1), ('HB2', 1), ('HB3', 1), ('HB1', 2), ('HB2', 2), ('HB3', 2)])
        self.assertEqual(self.peak, 1)

    def test_an_account_stop_in_one_slot_saves_the_others_and_starts_nothing_new(self):
        self.prepare(BILLS)
        self.gather = 3
        # The first bill sent hits the account stop; the two others in flight answer normally.
        first = []

        def stop_first(b, text):
            with self.lock:
                if not first:
                    first.append(b)
            if b == first[0]:
                self.answers[b] = Err(429, 'insufficient_quota')
            return self.reply(b, text)
        self.overrides[SUGGEST] = stop_first
        code = self.later_exit('--later-workers', '3')
        self.assertEqual(code, 2)
        started = {b for b, _ in self.calls}
        self.assertEqual(len(started), 3)  # nothing new after the stop
        others = started - set(first)
        for b in others:
            self.assertIsNotNone(self.record(b))  # in-flight answers were saved before the exit
        self.assertIsNone(self.record(first[0]))
        self.assertEqual(self.ledger_pending(), [])
        self.assertTrue((self.cache / pipeline.ACCOUNT_STOP).exists())

    def test_three_capacity_refusals_across_slots_end_the_pass(self):
        self.prepare(BILLS)
        self.gather = 3
        for bill in BILLS:
            self.answers[bill] = Err(429, 'flex_unavailable')
        out = self.later('--later-workers', '3')
        # A refusal frees its slot, which refills (as the one-at-a-time pass moves to the next bill); the third
        # refusal with no answer between ends the pass: at most 3 + (slots - 1) bills tried, never the sixth.
        started = {b for b, _ in self.calls}
        self.assertLessEqual(len(started), 5)
        self.assertGreaterEqual(len(started), 3)
        self.assertLess(len(started), len(BILLS))
        self.assertEqual(out.count('capacity unavailable 3 times with no answer between'), 1)
        self.assertEqual(self.ledger_pending(), [])

    def test_an_answer_between_refusals_resets_the_count(self):
        self.prepare(BILLS)
        refusing = {'HB1', 'HB3', 'HB5'}
        for bill in refusing:
            self.answers[bill] = Err(429, 'flex_unavailable')
        self.later('--later-workers', '1')
        self.assertEqual({b for b, _ in self.calls}, set(BILLS))  # never 3 refusals with no answer between

    def test_sigterm_finishes_bills_in_flight_and_starts_no_new_one(self):
        self.prepare(BILLS)
        self.gather = 3

        def stop_once(b, text):
            out = self.reply(b, text)
            pipeline.request_stop(signal.SIGTERM, None)
            return out
        self.overrides[SUGGEST] = stop_once
        self.later('--later-workers', '3')
        started = {b for b, _ in self.calls}
        self.assertEqual(len(started), 3)
        for bill in started:
            self.assertEqual([v for b, v in self.calls if b == bill], [1])  # no further vote after the stop
            self.assertIsNotNone(self.record(bill))
        self.assertEqual(self.ledger_pending(), [])

    def test_slots_default_to_workers_capped_at_3_and_only_on_flex(self):
        parse = lambda *a: pipeline.build_parser().parse_args(['--cache-dir', 'x', *a])
        self.assertEqual(pipeline.later_slots(parse('--transport', 'flex', '--workers', '6')), 3)
        self.assertEqual(pipeline.later_slots(parse('--transport', 'flex', '--workers', '2')), 2)
        self.assertEqual(pipeline.later_slots(parse('--transport', 'flex')), 1)
        self.assertEqual(pipeline.later_slots(parse('--transport', 'flex', '--later-workers', '5')), 5)
        self.assertEqual(pipeline.later_slots(parse('--transport', 'legacy', '--workers', '6')), 1)

    def test_later_workers_must_fit_the_crash_hold_allowance(self):
        for bad in (['--later-workers', '0'], ['--later-workers', str(pipeline.flex_crash_allowance() + 1)],
                    ['--later-workers', '2', '--transport', 'legacy']):
            with self.subTest(bad), patch.object(sys, 'argv', ['review_pipeline.py', '--cache-dir',
                                                               str(self.cache), *bad]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                pipeline.main()
            self.assertEqual(stop.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
