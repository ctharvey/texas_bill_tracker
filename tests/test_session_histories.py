"""Real 89R histories: status, committees and hearings as the 90R session will produce them."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sync_ftp import parse_bill_xml, infer_status, hearing_stage  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def parse(bill):
    return parse_bill_xml((FIXTURES / f'89R-{bill}.xml').read_bytes(),
                          f'/bills/89r/billhistory/x/{bill}.xml')


class SessionHistoryTests(unittest.TestCase):
    def test_final_outcomes(self):
        cases = {'SB3': 'Vetoed', 'HB2516': 'Enacted', 'HB2': 'Enacted', 'HJR2': 'Passed',
                 'HB1232': 'Advanced', 'HB1001': 'Referred'}
        for bill, status in cases.items():
            self.assertEqual(parse(bill)['status'], status, bill)

    def test_status_wording(self):
        self.assertEqual(infer_status(['Passed', 'Signed by the Governor/line item veto'], []), 'Enacted')
        self.assertEqual(infer_status(['Passed', 'Sent to the Governor'], []), 'Passed')
        self.assertEqual(infer_status(['Passed', 'Sent to the Governor', 'Effective on 9/1/25'], []), 'Enacted')
        self.assertEqual(infer_status(['Read 2nd time', 'Failed to pass to engrossment'], ['State Affairs']), 'Referred')
        self.assertEqual(infer_status(['Left pending in committee'], []), 'Heard')
        self.assertEqual(infer_status(['Considered by s/c in public hearing'], []), 'Heard')
        # 89R HB 1530: "Transmitted to the Governor" right after filing; not passage.
        self.assertEqual(infer_status(['Filed', 'Transmitted to the Governor', 'Referred to Natural Resources'], []),
                         'Referred')
        # 89R HB 2100: the hearing was scheduled, then the committee took no action; it was never heard.
        actions = ['Referred to Judiciary', 'Scheduled for public hearing on . . .', 'No action taken in committee']
        self.assertEqual(infer_status(actions, []), 'Scheduled')
        self.assertEqual(hearing_stage(actions), 'scheduled')

    def test_committees_come_from_attributes(self):
        referred = parse('HB1001')
        self.assertEqual(referred['committee'], 'Elections')
        self.assertEqual(referred['committees'], [{'chamber': 'House', 'name': 'Elections', 'status': 'In committee'}])
        reported = parse('HB1232')
        self.assertEqual(reported['committees'][0]['votes'], {'aye': 15, 'nay': 0, 'present': 0, 'absent': 0})
        self.assertEqual(reported['committees'][0]['status'], 'Out of committee')
        both = parse('HB2')['committees']
        self.assertEqual([c['chamber'] for c in both], ['House', 'Senate'])

    def test_hearing_uses_the_full_history(self):
        bill = parse('HB1232')
        self.assertEqual(bill['hearing'], 'heard')
        self.assertEqual(len(bill['actions']), 12)
        self.assertFalse(any('public hearing' in a.lower() or 'testimony' in a.lower() for a in bill['actions']))
        self.assertEqual(parse('HB1001')['hearing'], 'none')

    def test_frontend_fixture_matches_the_parser(self):
        """session_histories.test.mjs reads 89R-bills.json; regenerate it when the parser's output changes."""
        stored = json.loads((FIXTURES / '89R-bills.json').read_text('utf-8'))
        for bill, record in stored.items():
            parsed = {k: v for k, v in parse(bill).items() if k not in ('events', 'documents')}
            self.assertEqual(parsed, record, bill)


if __name__ == '__main__':
    unittest.main()
