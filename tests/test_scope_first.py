"""--scope-first: bills whose current text could carry an all-agencies quote get their topics call and scope votes
before every other later pass, in a bounded share of the time left; the other bills are still voted, later, in the
topics pass. Real main / FlexBoundary / ledger; only the OpenAI SDK is faked."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_later_pass_slots import FALSE, SlotCase  # noqa: E402
from test_second_pass_scope import AGENCY_LINE, with_line  # noqa: E402
from test_review_stages_pipeline import md_i, pipeline  # noqa: E402

import topic_suggestions  # noqa: E402  (scripts/ is on the path via test_review_stages_pipeline)

TEXTS = {
    'HB1': md_i('HB1'),                                                # no agency wording
    'HB2': with_line(md_i('HB2')),                                     # "Each state agency shall ..."
    'HB3': with_line(md_i('HB3'), '<del>' + AGENCY_LINE + '</del>'),   # the wording is being deleted
    'HB4': with_line(md_i('HB4'), 'A governmental body shall post the notice.'),
}
CANDIDATES = {'HB2', 'HB4'}


def pipeline_suggest():
    from test_later_pass_slots import SUGGEST
    return SUGGEST


class ScopeFirst(SlotCase):
    def prepare_texts(self):
        self.seed(list(TEXTS))
        for bill, text in TEXTS.items():
            self.put(bill, 'I', text)
        self.run_once(suggest=False)

    def status(self):
        return json.loads((self.tags.parent / 'status.json').read_text('utf-8'))

    def test_the_pattern_reads_current_text_only(self):
        self.prepare_texts()
        found = {b for b in TEXTS
                 if topic_suggestions.agency_candidate(json.loads((self.cache / 'reviews' / (b + '.json')).read_text('utf-8')))}
        self.assertEqual(found, CANDIDATES)
        self.assertFalse(topic_suggestions.agency_candidate(None))
        self.assertFalse(topic_suggestions.agency_candidate({'document': None}))

    def test_candidates_are_voted_first_and_every_other_bill_still_is(self):
        self.prepare_texts()
        self.answers = {1: FALSE, 2: FALSE}
        self.later('--scope-first', '--later-workers', '2')
        first_other = next(i for i, (b, _v) in enumerate(self.calls) if b not in CANDIDATES)
        self.assertEqual(sorted(self.calls[:first_other]), [('HB2', 1), ('HB2', 2), ('HB4', 1), ('HB4', 2)])
        self.assertEqual({b for b, _v in self.calls}, set(TEXTS))  # ordering only: nobody is skipped
        for bill in TEXTS:
            self.assertEqual([v for b, v in self.calls if b == bill], [1, 2])  # never asked twice
            self.assertEqual(self.marker(bill), {'applies': False, 'explanation': ''})
        passes = self.status()['passes']
        self.assertEqual(passes['scope'], {'due': 0, 'checked': 2})
        self.assertEqual(passes['topics'], {'due': 0, 'checked': 2})
        self.assertEqual(self.ledger_pending(), [])

    def test_topics_is_recounted_when_it_starts_so_the_candidates_already_voted_are_not_in_it(self):
        self.prepare_texts()
        self.answers = {1: FALSE, 2: FALSE}
        seen = {}
        reply = self.reply

        def watch(bill, text):
            status = self.status()
            seen.setdefault(status['pass'], status['passes'][status['pass']]['due'])
            return reply(bill, text)
        self.overrides[pipeline_suggest()] = watch
        self.later('--scope-first', '--later-workers', '2')
        self.assertEqual(seen, {'scope': 2, 'topics': 2})  # not 4: HB2 and HB4 were decided in the scope pass

    def test_one_slot_keeps_the_same_order(self):
        self.prepare_texts()
        self.answers = {1: FALSE, 2: FALSE}
        self.later('--scope-first', '--later-workers', '1')
        first_other = next(i for i, (b, _v) in enumerate(self.calls) if b not in CANDIDATES)
        self.assertEqual({b for b, _v in self.calls[:first_other]}, CANDIDATES)
        self.assertEqual({b for b, _v in self.calls}, set(TEXTS))

    def test_without_the_flag_there_is_no_scope_pass(self):
        self.prepare_texts()
        self.answers = {1: FALSE, 2: FALSE}
        self.later('--later-workers', '2')
        self.assertNotIn('scope', self.status()['passes'])
        self.assertEqual({b for b, _v in self.calls}, set(TEXTS))

    def test_the_scope_pass_gets_at_most_half_the_time_left(self):
        seen = {}

        def capture(args, queue, budget, deadline, **kw):
            seen['deadline'], seen['kw'] = deadline, kw
            return 0
        now = time.monotonic()
        with patch.object(pipeline, 'suggest_topics', side_effect=capture):
            pipeline.scope_votes(None, {}, None, now + 100)
        self.assertLessEqual(seen['deadline'], time.monotonic() + 50)
        self.assertGreater(seen['deadline'], now + 49)
        self.assertEqual(seen['kw'], {'label': 'All-agencies votes', 'only_candidates': True})
        with patch.object(pipeline, 'suggest_topics', side_effect=capture):
            pipeline.scope_votes(None, {}, None, now - 5)  # already past the run limit: no extra time
        self.assertLessEqual(seen['deadline'], now - 5)


if __name__ == '__main__':
    unittest.main()
