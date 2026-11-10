"""Luna highlight files: plain projection, quote relocation, claim mapping and publishing."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import review_pipeline as pipeline

MARKDOWN = "\n\n".join([
    "# HB 1001 - Introduced",
    r"AN ACT relating to the \[state\] highway fund.",
    "### SECTION 1.",
    "Section 2 applies to <ins>the Texas Department of Transportation, which shall adopt rules</ins> and may "
    "impose penalties.",
    "<del>\\[old language\\]</del> Funds are appropriated for the program",
    "and the program expires in 2030. Duplicate sentence.",
    "Duplicate sentence.",
]) + "\n"
PARAS = pipeline.plain_paragraphs(MARKDOWN)


def cite(claim, quote, status='resolved', source_type='bill'):
    return {'claim': claim, 'evidence_index': 0, 'requested_span_id': 'S_1', 'status': status,
            'source_type': source_type, 'quote': quote}


def bundle(citations, bill_id='HB1001', scope=None, version='introduced'):
    result = {'summary': {'text': 'Summary text', 'evidence': []},
              'policy_tags': [{'tag': 'Transportation', 'explanation': 'roads', 'evidence': []},
                              {'tag': 'Repeats', 'explanation': 'dup', 'evidence': []}],
              'agencies': [{'registry_id': 'txdot', 'name': 'TxDOT', 'impact': 'direct', 'explanation': 'a', 'evidence': []},
                           {'registry_id': 'tcole', 'name': 'TCOLE', 'impact': 'inferred', 'explanation': 'b', 'evidence': []}],
              'locations': [], 'affected_groups': [{'group': 'Drivers', 'explanation': 'g', 'evidence': []}],
              'major_effects': [{'effect': 'penalties', 'label': 'Penalties', 'explanation': 'p', 'evidence': []},
                                {'effect': 'reporting', 'label': 'Reports', 'explanation': 'r', 'evidence': []}],
              'all_state_agencies_scope': scope or {'applies': False, 'basis': 'not_applicable', 'explanation': 'x'},
              'uncertainties': []}
    return {'bill_id': bill_id, 'status': 'needs_review', 'document': {'version': version}, 'result': result,
            'validation': {'verified_citations': citations}}


class PlainTests(unittest.TestCase):
    def test_plain_projection(self):
        self.assertEqual(PARAS[0], 'HB 1001 - Introduced')
        self.assertEqual(PARAS[1], 'AN ACT relating to the [state] highway fund.')
        self.assertEqual(PARAS[2], 'SECTION 1.')
        self.assertNotIn('<ins>', PARAS[3])
        self.assertTrue(PARAS[4].startswith('[old language] Funds'))
        self.assertEqual(len(PARAS), 7)


class LocateTests(unittest.TestCase):
    def test_single_paragraph_range(self):
        quote = 'the Texas Department of Transportation, which shall adopt rules'
        (r,) = pipeline.locate_quote(quote, PARAS)
        self.assertEqual(r['p'], 3)
        self.assertEqual(PARAS[3][r['start']:r['end']], quote)

    def test_spans_two_paragraphs(self):
        ranges = pipeline.locate_quote('appropriated for the program and the program expires', PARAS)
        self.assertEqual([r['p'] for r in ranges], [4, 5])
        self.assertTrue(PARAS[4][ranges[0]['start']:ranges[0]['end']].startswith('appropriated'))
        self.assertTrue(PARAS[4][ranges[0]['start']:].endswith('program'))
        self.assertEqual(PARAS[5][ranges[1]['start']:ranges[1]['end']], 'and the program expires')

    def test_pdf_artifacts_need_strategy_two(self):
        quote = 'SECTIONA1.AASection 2 applies to'
        ranges = pipeline.locate_quote(quote, PARAS)
        self.assertEqual([r['p'] for r in ranges], [2, 3])
        self.assertEqual(PARAS[2][ranges[0]['start']:ranges[0]['end']], 'SECTION 1')  # Ends at the last alnum char.

    def test_ambiguous_missing_and_empty_quotes(self):
        self.assertIsNone(pipeline.locate_quote('Duplicate sentence', PARAS))
        self.assertIsNone(pipeline.locate_quote('not in the bill at all', PARAS))
        self.assertIsNone(pipeline.locate_quote('--- ...', PARAS))


class EntryTests(unittest.TestCase):
    def entry(self, citations, **kwargs):
        return pipeline.highlight_entry(bundle(citations, **kwargs), '2026-11-10T00:00:00Z', MARKDOWN, 'I')

    def test_claims_mapping_and_key_points(self):
        scope = {'applies': True, 'basis': 'direct', 'explanation': 'all agencies'}
        entry = self.entry([
            cite('summary', 'AN ACT relating to the [state] highway fund'),
            cite('all_state_agencies_scope', 'may impose penalties'),
            cite('policy_tags:0', 'highway fund'),
            cite('agencies:0', 'the Texas Department of Transportation'),
            cite('agencies:1', 'shall adopt rules'),
            cite('major_effects:0', 'may impose penalties'),
            cite('major_effects:1', 'and the program expires in 2030'),
            cite('affected_groups:0', 'Funds are appropriated'),
        ], scope=scope)
        self.assertEqual(entry['format'], 'texas-bill-luna-highlights-v1')
        self.assertEqual(entry['text_sha256'], hashlib.sha256(MARKDOWN.encode('utf-8')).hexdigest())
        self.assertEqual(entry['text_version'], 'I')
        self.assertEqual(entry['reviewed_at'], '2026-11-10T00:00:00Z')
        by_id = {c['id']: c for c in entry['claims']}
        self.assertEqual([c['id'] for c in entry['claims']],
                         ['summary', 'all_state_agencies_scope', 'policy_tags:0', 'affected_groups:0',
                          'major_effects:0', 'major_effects:1', 'agencies:0', 'agencies:1'])
        self.assertTrue(by_id['all_state_agencies_scope']['key_point'])
        self.assertEqual(by_id['all_state_agencies_scope']['kind'], 'scope')
        self.assertEqual(by_id['all_state_agencies_scope']['label'], 'All state agencies')
        self.assertFalse(by_id['summary']['key_point'])
        self.assertEqual(by_id['agencies:0']['agency_id'], 'txdot')
        self.assertEqual(by_id['agencies:0']['impact'], 'direct')
        self.assertTrue(by_id['agencies:0']['key_point'])
        self.assertFalse(by_id['agencies:1']['key_point'])
        self.assertEqual(by_id['agencies:1']['impact'], 'inferred')
        self.assertEqual((by_id['major_effects:0']['effect'], by_id['major_effects:0']['key_point']), ('penalties', True))
        self.assertEqual((by_id['major_effects:1']['effect'], by_id['major_effects:1']['key_point']), ('reporting', False))
        self.assertEqual(by_id['policy_tags:0']['kind'], 'topic')
        self.assertEqual(by_id['policy_tags:0']['label'], 'Transportation')
        self.assertIsNone(by_id['policy_tags:0']['agency_id'])
        self.assertEqual(entry['unlocated'], [])

    def test_scope_not_applied_is_omitted(self):
        entry = self.entry([cite('all_state_agencies_scope', 'may impose penalties')])
        self.assertEqual(entry['claims'], [])
        self.assertEqual(entry['unlocated'], [])

    def test_unlocated_and_unresolved(self):
        entry = self.entry([cite('policy_tags:1', 'Duplicate sentence'),
                            cite('policy_tags:0', 'highway fund', status='not_found'),
                            cite('agencies:0', 'nowhere to be found')])
        self.assertEqual(entry['claims'], [])
        self.assertEqual(entry['unlocated'], ['policy_tags:1', 'agencies:0'])  # Unresolved-only claim is in neither.

    def test_ranges_merge_across_citations_and_dedupe(self):
        entry = self.entry([cite('agencies:0', 'the Texas Department of Transportation'),
                            cite('agencies:0', 'the Texas Department of Transportation'),
                            cite('agencies:0', 'AN ACT relating to the state'),
                            cite('agencies:0', 'no such text')])
        (claim,) = entry['claims']
        self.assertEqual([r['p'] for r in claim['ranges']], [1, 3])
        self.assertEqual(len(claim['ranges']), 2)


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cache, self.text, self.out = root / 'cache', root / 'live' / 'text', root / 'live' / 'luna' / 'highlights'
        (self.cache / 'reviews').mkdir(parents=True)
        (self.text / 'HB1001').mkdir(parents=True)
        (self.text / 'HB1001' / 'I.md').write_text(MARKDOWN, 'utf-8', newline='\n')

    def put(self, name, value):
        text = value if isinstance(value, str) else json.dumps(value)
        (self.cache / 'reviews' / (name + '.json')).write_text(text, 'utf-8')

    def test_writes_once_skips_missing_text_and_survives_corruption(self):
        self.put('HB1001', bundle([cite('agencies:0', 'shall adopt rules')]))
        self.put('HB2', bundle([cite('agencies:0', 'shall adopt rules')], bill_id='HB2'))  # No I.md.
        self.put('HB3', '{broken')
        self.put('HB4', bundle([], bill_id='HB4', version='enrolled'))
        self.assertEqual(pipeline.publish_highlights(self.cache, self.text, self.out), 1)
        target = self.out / 'HB1001.json'
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ['HB1001.json'])
        raw = target.read_bytes()
        self.assertTrue(raw.endswith(b'\n'))
        self.assertEqual(json.loads(raw)['claims'][0]['id'], 'agencies:0')
        os.utime(target, (1_000_000, 1_000_000))
        self.assertEqual(pipeline.publish_highlights(self.cache, self.text, self.out), 1)
        self.assertEqual(target.stat().st_mtime, 1_000_000)  # Unchanged content is not rewritten.
        self.put('HB1001', bundle([cite('agencies:0', 'and may impose penalties')]))
        self.assertEqual(pipeline.publish_highlights(self.cache, self.text, self.out), 1)
        self.assertNotEqual(target.stat().st_mtime, 1_000_000)

    def test_publish_tags_output_is_unchanged(self):
        self.put('HB1001', bundle([cite('agencies:0', 'shall adopt rules'), cite('summary', 'highway fund')]))
        registry = [{'id': 'txdot', 'name': 'TxDOT'}]
        tags = Path(self.temp.name) / 'tags.json'
        pipeline.publish_tags(self.cache, tags, registry)
        before = json.loads(tags.read_text('utf-8'))
        pipeline.publish_highlights(self.cache, self.text, self.out)
        pipeline.publish_tags(self.cache, tags, registry)
        after = json.loads(tags.read_text('utf-8'))
        before.pop('generated_at'); after.pop('generated_at')
        self.assertEqual(json.dumps(before, sort_keys=True), json.dumps(after, sort_keys=True))
        self.assertEqual(before['bills']['HB1001']['text_version'], 'introduced')
        self.assertNotIn('ranges', json.dumps(after))


if __name__ == '__main__':
    unittest.main()
