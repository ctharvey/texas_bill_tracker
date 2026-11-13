"""2-of-3 vote for the "all state agencies" marker: each vote is its own request, cache entry and ledger row, bound
to the review and text it answered. End to end with only the OpenAI SDK faked; no network, no paid calls."""
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_second_pass_scope import AGENCY_LINE, with_line  # noqa: E402
from test_topic_suggestions import SUGGEST, SuggestionCase  # noqa: E402
from test_review_stages_pipeline import body, md_i, pipeline  # noqa: E402
from test_flex_boundary import Err  # noqa: E402
import topic_suggestions  # noqa: E402

TRUE = {'applies': True, 'explanation': 'Every state agency must adopt a policy.', 'quotes': [AGENCY_LINE]}
FALSE = {'applies': False, 'explanation': '', 'quotes': []}
UNVERIFIED = {**TRUE, 'quotes': ['Each state agency shall file a gadget report with the governor.']}


class VoteTests(SuggestionCase):
    def setUp(self):
        super().setUp()
        self.answers = {}  # vote -> scope or exception
        self.overrides[SUGGEST] = self.reply

    def start(self):
        self.seed()
        self.put('HB1', 'I', with_line(md_i('HB1')))
        return self.run_once()

    def second_pass_only(self):
        with patch.object(pipeline, 'queue_candidates', lambda *a, **k: []):  # no re-review; only the pass runs
            return self.run_once()

    def published(self, bill='HB1'):
        return json.loads(self.tags.read_text('utf-8'))['bills'].get(bill)

    def reply(self, bill, text):
        found = re.search(r'RUN: (\d)', text)
        answer = self.answers.get(int(found[1]) if found else 1, TRUE)
        return answer if isinstance(answer, BaseException) else body({**self.second_pass(), 'all_state_agencies': answer})

    def votes_sent(self, since=0):
        return [n for _, n in self.sdk.requests[since:]].count(SUGGEST)

    def marker(self):
        return (self.published() or {}).get('all_state_agencies')

    def test_true_false_true_publishes_true(self):
        self.answers = {1: TRUE, 2: FALSE, 3: TRUE}
        self.start()
        self.assertEqual(self.votes_sent(), 3)
        self.assertTrue(self.marker()['applies'])

    def test_true_false_false_publishes_false(self):
        self.answers = {1: TRUE, 2: FALSE, 3: FALSE}
        self.start()
        self.assertEqual(self.marker(), {'applies': False, 'explanation': ''})

    def test_two_agreeing_votes_send_no_third(self):
        self.answers = {1: FALSE, 2: FALSE}
        self.start()
        self.assertEqual(self.votes_sent(), 2)
        self.assertFalse(self.marker()['applies'])

    def test_one_true_vote_publishes_nothing(self):
        self.answers = {1: TRUE, 2: Err(429, 'flex_unavailable')}
        self.start()
        self.assertIsNone(self.marker())

    def test_unverified_true_abstains(self):
        self.answers = {1: UNVERIFIED, 2: UNVERIFIED, 3: TRUE}
        self.start()
        self.assertIsNone(self.marker())  # one verified true is not two
        self.assertEqual(topic_suggestions.decision({1: {**UNVERIFIED, 'verified': False}, 2: FALSE, 3: FALSE}),
                         {'applies': False, 'explanation': '', 'quotes': []})

    def test_capacity_on_vote_2_keeps_extras_and_asks_only_the_missing_vote_next_run(self):
        self.answers = {1: TRUE, 2: Err(429, 'flex_unavailable')}
        self.start()
        self.assertEqual(self.record()['headline'], 'Sets rules for water wells.')  # vote 1 saved its extras
        self.assertIsNone(self.marker())
        self.assertNotIn('pending', self.ledger_states())
        mark = len(self.sdk.requests)
        self.answers = {1: TRUE, 2: TRUE}
        self.run_once()
        self.assertEqual(self.votes_sent(mark), 1)  # vote 2 only; vote 1 is not re-sent
        self.assertTrue(self.marker()['applies'])

    def test_a_decided_bill_sends_nothing_on_rerun(self):
        self.answers = {1: TRUE, 2: FALSE, 3: TRUE}
        self.start()
        rows = len(self.ledger_states())
        mark = len(self.sdk.requests)
        self.run_once()
        self.assertEqual(self.votes_sent(mark), 0)
        self.assertEqual(len(self.ledger_states()), rows)

    def test_votes_from_an_earlier_review_never_count(self):
        self.answers = {1: TRUE, 2: TRUE}
        self.start()
        self.assertTrue(self.marker()['applies'])
        review = self.cache / 'reviews' / 'HB1.json'
        bundle = json.loads(review.read_text('utf-8'))
        bundle['result']['summary']['text'] = 'A different summary MARKER-HB1.'
        review.write_text(json.dumps(bundle), 'utf-8')
        # The old vote 2 (true) must not pair with anything: the new review is asked votes 1 and 2 afresh.
        self.answers = {1: FALSE, 2: FALSE}
        mark = len(self.sdk.requests)
        self.second_pass_only()
        self.assertEqual(self.votes_sent(mark), 2)
        self.assertEqual(self.marker(), {'applies': False, 'explanation': ''})
        current = topic_suggestions.scope_hash(json.loads(review.read_text('utf-8')))
        self.assertEqual({e['scope']['input_sha256'] for e in self.record()['votes'].values()}, {current})

    def test_votes_asked_under_an_earlier_prompt_never_count(self):
        # Old prompt: false, false. After a prompt change, vote 1 is due again (its request changed); the old vote 2
        # must not pair with it, so a new true, true publishes true instead of an old false outvoting it.
        self.answers = {1: FALSE, 2: FALSE}
        self.start()
        self.assertFalse(self.marker()['applies'])
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / 'scripts' / 'topic_suggestions_prompt.txt'
            prompt.parent.mkdir()
            prompt.write_text((topic_suggestions.ROOT / 'scripts' / 'topic_suggestions_prompt.txt')
                              .read_text('utf-8') + '\nA revised rule.\n', 'utf-8')
            with patch.object(topic_suggestions, 'ROOT', Path(tmp)):
                # Mixed with the old vote 2 (false), the new vote 1 would split and vote 3 (false) would decide.
                self.answers = {1: TRUE, 2: TRUE, 3: FALSE}
                mark = len(self.sdk.requests)
                self.second_pass_only()
                self.assertEqual(self.votes_sent(mark), 2)
                self.assertTrue(self.marker()['applies'])

    def test_each_vote_is_its_own_request_and_vote_1_is_unchanged(self):
        self.answers = {1: TRUE, 2: TRUE}
        self.start()
        bundle = json.loads((self.cache / 'reviews' / 'HB1.json').read_text('utf-8'))
        topics = pipeline.classification.load_policy_tags()
        one, two, three = (topic_suggestions.build_request(bundle, topics, v) for v in (1, 2, 3))
        self.assertEqual(topic_suggestions.build_request(bundle, topics), one)
        self.assertEqual(two['input'][1]['content'][:-1], one['input'][1]['content'])
        self.assertEqual(two['input'][0], one['input'][0])  # shared prompt-cache prefix
        keys = {pipeline.ResponseCache.key(r) for r in (one, two, three)}
        self.assertEqual(len(keys), 3)
        record = self.record()
        self.assertEqual(record['request_key'], record['votes']['1']['request_key'])
        self.assertNotEqual(record['votes']['1']['request_key'], record['votes']['2']['request_key'])


if __name__ == '__main__':
    unittest.main()
