"""Related-entities pass: a list-free Luna read naming every government body a bill involves; code matches the names
to the agency list and publishes only verified, listed bodies the review lacks. End to end through
review_pipeline.py with only the OpenAI SDK faked. No network, no paid calls."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_topic_suggestions import SuggestionCase, pipeline  # noqa: E402
from test_review_stages_pipeline import QUOTE_I, body  # noqa: E402

import extract_bill as detailed  # noqa: E402
import related_entities  # noqa: E402

ENTITIES = 'texas_bill_related_entities_v1'
REGISTRY = detailed.load_registry()
NAMES = {a['id']: a['name'] for a in REGISTRY}


def found(name, quote=QUOTE_I, impact='direct'):
    return {'name': name, 'impact': impact, 'explanation': f'{name} reports.', 'quote': quote}


class RequestTests(unittest.TestCase):
    def doc(self, text='The Texas Department of Transportation shall build markers.', sha='a' * 64):
        document = detailed.document_from_pages('HB1', '90R', 'introduced', [text])
        return {**document, 'text_sha256': sha}

    def test_the_request_carries_the_text_and_no_agency_list(self):
        request = related_entities.build_request('HB1', self.doc())
        prompt = json.dumps(request)
        self.assertIn('shall build markers', prompt)
        for name in ('Texas Cyber Command', 'Health and Human Services Commission', 'Texas Optometry Board'):
            self.assertNotIn(name, prompt)
        self.assertEqual(request['reasoning'], {'effort': 'medium'})

    def test_the_request_depends_only_on_the_bill_and_its_text(self):
        self.assertEqual(related_entities.build_request('HB1', self.doc()),
                         related_entities.build_request('HB1', self.doc()))
        self.assertNotEqual(related_entities.build_request('HB1', self.doc()),
                            related_entities.build_request('HB1', self.doc('Different text.')))
        self.assertNotEqual(related_entities.build_request('HB1', self.doc()),
                            related_entities.build_request('SB1', self.doc()))

    def test_quotes_are_checked_against_the_text(self):
        report = related_entities.validate({'entities': [
            found('Texas Department of Transportation', 'shall build markers'),
            found('Texas Cyber Command', 'not in the bill')]}, self.doc())
        self.assertEqual([e['quote_found'] for e in report['entities']], [True, False])


class PublishMergeTests(unittest.TestCase):
    def bundle(self, agencies=()):
        claims = [{'claim': f'agencies:{i}', 'status': 'resolved'} for i in range(len(agencies))]
        return {'bill_id': 'HB1', 'status': 'ready_for_review', 'document': {'version': 'introduced'},
                'result': {'summary': {'text': 'S.'}, 'agencies': list(agencies)},
                'validation': {'verified_citations': claims}}

    def agencies(self, bundle, entities):
        return [(a['id'], a['impact']) for a in pipeline.public_entry(bundle, 'T', None, NAMES, entities)['agencies']]

    def test_a_listed_body_the_review_lacks_is_added(self):
        reviewed = {'registry_id': 'hhsc', 'name': NAMES['hhsc'], 'impact': 'direct', 'explanation': 'x'}
        self.assertEqual(self.agencies(self.bundle([reviewed]),
                                       [found('Texas Department of Transportation', impact='inferred')]),
                         [('hhsc', 'direct'), ('txdot', 'inferred')])

    def test_bodies_already_listed_unlisted_or_generic_are_not_added(self):
        reviewed = {'registry_id': 'txdot', 'name': NAMES['txdot'], 'impact': 'direct', 'explanation': 'x'}
        entities = [found('Texas Department of Transportation'), found('Texas Transportation Commission'),
                    found('Travis County'), found('the department'), found('a federal agency')]
        self.assertEqual(self.agencies(self.bundle([reviewed]), entities), [('txdot', 'direct')])

    def test_a_body_named_twice_is_added_once_and_names_take_the_listed_name(self):
        entry = pipeline.public_entry(self.bundle(), 'T', None, NAMES,
                                      [found('state auditor'), found("State Auditor's Office")])
        self.assertEqual([(a['id'], a['name']) for a in entry['agencies']], [('sao', NAMES['sao'])])

    def test_no_entities_leaves_the_entry_unchanged(self):
        bundle = self.bundle()
        self.assertEqual(pipeline.public_entry(bundle, 'T', None, NAMES, None),
                         pipeline.public_entry(bundle, 'T', None, NAMES, []))
        self.assertEqual(pipeline.public_entry(bundle, 'T', None, NAMES)['agencies'], [])


class PassTests(SuggestionCase):
    def setUp(self):
        super().setUp()
        self.entities = [found('Texas Department of Transportation'), found('Texas Cyber Command', 'not in the bill'),
                         found('Travis County')]
        self.overrides[ENTITIES] = lambda bill, text: body({'entities': self.entities})
        # The stages harness publishes with an empty agency list; matching needs the real one.
        p = patch.object(pipeline.detailed, 'load_registry', return_value=REGISTRY); p.start(); self.addCleanup(p.stop)

    def run_scan(self, *extra):
        return self.run_once('--related-entities', *extra, suggest=False)

    def published(self):
        return json.loads((self.live / 'luna' / 'tags.json').read_text('utf-8'))['bills']

    def record(self, bill='HB1'):
        return json.loads((self.cache / 'entities' / (bill + '.json')).read_text('utf-8'))

    def test_verified_listed_bodies_are_published_and_the_rest_stay_private(self):
        self.seed(['HB1', 'HB2'])
        out = self.run_scan()
        self.assertEqual(self.count(ENTITIES), 2)
        self.assertIn('Related entities checked for 2 bills', out)
        record = self.record()
        self.assertEqual([e['quote_found'] for e in record['entities']], [True, False, True])
        self.assertEqual([a['id'] for a in self.published()['HB1']['agencies']], ['txdot'])
        published = (self.live / 'luna' / 'tags.json').read_text('utf-8')
        self.assertNotIn('Travis County', published)
        self.assertNotIn('cyber-command', json.dumps(self.published()))
        self.assertFalse((self.live / 'luna' / 'entities').exists())

    def test_a_repeat_run_sends_nothing(self):
        self.seed()
        self.run_scan()
        mark = len(self.sdk.requests)
        self.run_scan()
        self.assertEqual(self.count(ENTITIES, mark), 0)

    def test_without_the_flag_no_scan_is_sent(self):
        self.seed()
        self.run_once(suggest=False)
        self.assertEqual(self.count(ENTITIES), 0)

    def test_a_record_for_other_text_is_not_published(self):
        self.seed()
        self.run_scan()
        path = self.cache / 'entities' / 'HB1.json'
        record = self.record()
        path.write_text(json.dumps({**record, 'text_sha256': 'b' * 64}), 'utf-8')
        with patch.object(pipeline, 'scan_entities', lambda *a, **k: 0):
            self.run_scan()
        self.assertEqual(self.published()['HB1']['agencies'], [])

    def test_text_on_disk_that_differs_from_the_reviewed_text_is_skipped(self):
        self.seed()
        self.run_once(suggest=False)
        self.put('HB1', 'I', '# changed text MARKER-HB1\n\nSomething else entirely.\n')
        mark = len(self.sdk.requests)
        with patch.object(pipeline, 'queue_candidates', lambda *a, **k: []):
            self.run_scan()
        self.assertEqual(self.count(ENTITIES, mark), 0)


if __name__ == '__main__':
    unittest.main()
