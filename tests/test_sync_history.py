import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_ftp
from sync_ftp import parse_bill_xml, parse_documents, parse_events, sync_history, synchronize

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / '89R-HB2.xml'
PATH = '/bills/90r/billhistory/house_bills/00001_00099/HB00002.xml'


def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes().replace(b'89R', b'90R')


class HistoryParserTests(unittest.TestCase):
    def test_events_from_fixture(self):
        bill = parse_bill_xml(fixture_bytes(), PATH)
        events = bill['events']
        self.assertEqual(len(events), 151)
        self.assertEqual(events[0], {'code': 'H001', 'date': '2025-02-20', 'text': 'Filed'})
        self.assertIn('E020', {e['code'] for e in events})

    def test_documents_from_fixture(self):
        docs = parse_bill_xml(fixture_bytes(), PATH)['documents']
        types = {d['type'] for d in docs}
        self.assertEqual(types, {'analysis', 'fiscal_note'})
        for kind in types:
            self.assertIn('H', {d['code'] for d in docs if d['type'] == kind})
        self.assertEqual(len({(d['type'], d['code']) for d in docs}), len(docs))
        self.assertTrue(all(d['html'].startswith('ftp://ftp.legis.state.tx.us/bills/90R/') for d in docs))

    def test_non_tlc_url_rejected(self):
        xml = ('<billtext><docTypes><analysis><versions>'
               '<version><versionDescription>Bad</versionDescription><FTPHTMLURL>ftp://evil.example/bills/90R/analysis/HTML/x/HB00002H.HTM</FTPHTMLURL></version>'
               '<version><versionDescription>Wrong path</versionDescription><FTPHTMLURL>ftp://ftp.legis.state.tx.us/bills/90R/billtext/HTML/x/HB00002H.HTM</FTPHTMLURL></version>'
               '<version><versionDescription>Good</versionDescription><FTPHTMLURL>ftp://ftp.legis.state.tx.us/bills/90R/analysis/HTML/x/HB00002E.HTM</FTPHTMLURL></version>'
               '</versions></analysis></docTypes></billtext>')
        docs = parse_documents(ET.fromstring(xml))
        self.assertEqual([d['code'] for d in docs], ['E'])

    def test_no_coded_actions_no_events(self):
        xml = (b'<Bill><BillNumber>HB 164</BillNumber><Caption>Relating to the education savings account program.</Caption>'
               b'<Actions><Action><ActionDescription>Filed</ActionDescription></Action></Actions></Bill>')
        bill = parse_bill_xml(xml, '/bills/90r/billhistory/house_bills/0100-0199/HB00164.xml')
        self.assertNotIn('events', bill)
        self.assertNotIn('documents', bill)
        self.assertEqual(parse_events(ET.fromstring(xml)), [])

    def test_events_capped_to_last_400(self):
        actions = ''.join(f'<action><actionNumber>H{i}</actionNumber><description>a{i}</description></action>' for i in range(450))
        events = parse_events(ET.fromstring(f'<bill>{actions}</bill>'))
        self.assertEqual(len(events), 400)
        self.assertEqual(events[-1]['text'], 'a449')
        self.assertEqual(events[0]['text'], 'a50')


class HistoryWriteTests(unittest.TestCase):
    def test_written_once_and_not_rewritten(self):
        bill = parse_bill_xml(fixture_bytes(), PATH)
        histories = sync_sync_pop([bill])
        with tempfile.TemporaryDirectory() as tmp:
            history_dir = Path(tmp)
            first = sync_history(histories, history_dir)
            self.assertEqual(first['written'], 1)
            target = history_dir / 'HB2' / 'history.json'
            data = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(data['format'], 'texas-bill-history-v1')
            self.assertEqual(data['bill'], 'HB2')
            self.assertEqual(len(data['events']), 151)
            with mock.patch.object(sync_ftp, '_atomic_write') as writer:
                second = sync_history(histories, history_dir)
            writer.assert_not_called()
            self.assertEqual(second['unchanged'], 1)
            self.assertEqual(second['written'], 0)

    def test_invalid_bill_id_skipped_and_failure_contained(self):
        histories = {'../x': {'events': [{'code': 'H1', 'date': '', 'text': 'a'}], 'documents': []},
                     'HB2': {'events': [{'code': 'H1', 'date': '', 'text': 'a'}], 'documents': []}}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sync_ftp, '_atomic_write', side_effect=OSError('disk full')):
                counts = sync_history(histories, Path(tmp))
            self.assertEqual(counts['failed'], 1)
            self.assertEqual(counts['bills'], 1)

    def test_snapshot_records_have_no_history_keys(self):
        histories = {}
        with mock.patch.object(sync_ftp, 'enumerate_xml', return_value=[PATH]), \
                mock.patch.object(sync_ftp, 'ftp_bytes', return_value=fixture_bytes()):
            snapshot, _ = synchronize(object(), {'bills': []}, 25000, histories)
        self.assertEqual(len(snapshot['bills']), 1)
        self.assertNotIn('events', snapshot['bills'][0])
        self.assertNotIn('documents', snapshot['bills'][0])
        self.assertEqual(len(histories['HB2']['events']), 151)
        self.assertTrue(histories['HB2']['documents'])


def sync_sync_pop(bills):
    return sync_ftp.pop_history(bills)


if __name__ == '__main__':
    unittest.main()
