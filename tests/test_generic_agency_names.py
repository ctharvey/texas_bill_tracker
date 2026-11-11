"""Publish-time mapping of generic agency names ("the department") from the amended code chapter's definition."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import review_pipeline as pipeline

NAMES = {'txdot': 'Texas Department of Transportation', 'txdmv': 'Texas Department of Motor Vehicles',
         'tea': 'Texas Education Agency'}
HEADER_225 = 'SECTION 1.  Subchapter B, Chapter 225, Transportation Code, is amended by adding Section 225.300 to read as follows:'
DUTY = 'Sec. 225.300.  MARKERS.  The department shall build markers.'


def document(*texts):
    return {'spans': {f'P{i + 2:03d}S001': {'page': i + 2, 'start': 0, 'end': len(t), 'text': t}
                      for i, t in enumerate(texts)}}


def agency(span='P003S001', quote='The department shall build markers.', name='the department', registry_id=None):
    return {'registry_id': registry_id, 'name': name, 'impact': 'direct', 'explanation': 'e',
            'evidence': [{'span_id': span, 'quote': quote}]}


class GenericAgencyIdTests(unittest.TestCase):
    def test_maps_by_the_last_header_before_the_evidence(self):
        self.assertEqual(pipeline.generic_agency_id(agency(), document(HEADER_225, DUTY), NAMES), 'txdot')

    def test_header_after_the_evidence_does_not_count(self):
        later = 'SECTION 2.  Section 501.174, Transportation Code, is amended to read as follows:'
        doc = document(HEADER_225, DUTY, later, 'The department shall issue titles.')
        self.assertEqual(pipeline.generic_agency_id(agency(), doc, NAMES), 'txdot')
        self.assertEqual(pipeline.generic_agency_id(agency(span='P005S001', quote='The department shall issue titles.'),
                                                    doc, NAMES), 'txdmv')

    def test_header_listing_several_sections_is_read(self):
        header = 'SECTION 1.  Sections 29.001 and 29.002, Education Code, are amended to read as follows:'
        doc = document(header, 'The agency shall adopt rules.')
        self.assertEqual(pipeline.generic_agency_id(agency(quote='The agency shall adopt rules.', name='the agency'),
                                                    doc, NAMES), 'tea')

    def test_unlisted_chapter_or_term_stays_unmapped(self):
        header = 'SECTION 1.  Section 264.751, Family Code, is amended to read as follows:'
        self.assertIsNone(pipeline.generic_agency_id(agency(), document(header, DUTY), NAMES))
        self.assertIsNone(pipeline.generic_agency_id(agency(name='the board'), document(HEADER_225, DUTY), NAMES))

    def test_bill_defining_the_term_itself_stays_unmapped(self):
        doc = document(HEADER_225, '(1)  "Department" means the Texas Department of Insurance.', DUTY)
        self.assertIsNone(pipeline.generic_agency_id(agency(span='P004S001'), doc, NAMES))

    def test_no_header_named_or_already_mapped_or_unknown_registry_stays_unmapped(self):
        self.assertIsNone(pipeline.generic_agency_id(agency(span='P002S001'), document(DUTY), NAMES))
        self.assertIsNone(pipeline.generic_agency_id(agency(name='Texas Department of Transportation'),
                                                     document(HEADER_225, DUTY), NAMES))
        self.assertIsNone(pipeline.generic_agency_id(agency(registry_id='dps'), document(HEADER_225, DUTY), NAMES))
        self.assertIsNone(pipeline.generic_agency_id(agency(), document(HEADER_225, DUTY), {'tea': 'TEA'}))


class PublishedAgencyTests(unittest.TestCase):
    def bundle(self, agencies, *texts):
        return {'bill_id': 'HB1', 'status': 'needs_review', 'document': document(*texts),
                'result': {'agencies': agencies},
                'validation': {'verified_citations': [{'claim': f'agencies:{i}', 'status': 'resolved'}
                                                      for i in range(len(agencies))]}}

    def test_public_entry_publishes_the_registry_id_and_name(self):
        entry = pipeline.public_entry(self.bundle([agency()], HEADER_225, DUTY), 'now', None, NAMES)
        self.assertEqual(entry['agencies'], [{'id': 'txdot', 'name': 'Texas Department of Transportation',
                                              'impact': 'direct', 'explanation': 'e'}])

    def test_mapped_duplicate_of_a_listed_agency_is_dropped(self):
        listed = agency(name='Texas Department of Transportation', registry_id='txdot')
        entry = pipeline.public_entry(self.bundle([agency(), listed], HEADER_225, DUTY), 'now', None, NAMES)
        self.assertEqual([a['id'] for a in entry['agencies']], ['txdot'])
        self.assertEqual(entry['agencies'][0]['name'], 'Texas Department of Transportation')

    def test_without_registry_names_the_label_is_unchanged(self):
        entry = pipeline.public_entry(self.bundle([agency()], HEADER_225, DUTY), 'now')
        self.assertEqual((entry['agencies'][0]['id'], entry['agencies'][0]['name']), (None, 'the department'))

    def test_highlight_claim_carries_the_mapped_agency(self):
        bundle = self.bundle([agency()], HEADER_225, DUTY)
        bundle['validation']['verified_citations'] = [{'claim': 'agencies:0', 'status': 'resolved',
                                                       'source_type': 'bill', 'quote': 'The department shall build markers.'}]
        markdown = '# HB 1\n\n' + HEADER_225 + '\n\n' + DUTY + '\n'
        claims = pipeline.highlight_entry(bundle, 'now', markdown, 'I', None, NAMES)['claims']
        self.assertEqual((claims[0]['agency_id'], claims[0]['label']), ('txdot', 'Texas Department of Transportation'))


if __name__ == '__main__':
    unittest.main()
