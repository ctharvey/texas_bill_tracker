"""Texts stored before source_sha256 existed gain the official file's fingerprint, a few per run, without their
Markdown, its sha256 or generated_at changing (the review pipeline keys on sha256)."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import sync_ftp

TLC = 'ftp://ftp.legis.state.tx.us/bills/90R/billtext/HTML/house_bills/HB01000_HB01099/'
HTML = '<html><body><table><tr><td>&#xA0;</td><td>&#xA0;&#xA0;SECTION&#xA0;1.&#xA0;&#xA0;Text.</td></tr></table></body></html>'
STAMP = '20261110080006'


class Conn:
    def __init__(self):
        self.mdtm = []

    def sendcmd(self, cmd):
        self.mdtm.append(cmd)
        return f'213 {STAMP}'


def bill(number):
    return {'id': f'HB{number}', 'number': f'HB {number}', 'source_updated': 'a',
            'text_versions': [{'code': 'I', 'name': 'Introduced', 'html': f'{TLC}HB0{number}I.HTM'}]}


OFF_TURN = next(t for t in range(24) if not any(sync_ftp.text_recheck_due(f'HB{n}', t) for n in (1001, 1002)))


class Backfill(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.text = Path(folder.name) / 'text'
        self.conn = Conn()
        self.bills = [bill(1001), bill(1002)]
        self.sync()  # first download, with source_sha256
        for b in self.bills:  # as written before source_sha256 existed
            index = self.index(b['id'])
            for version in index['versions']:
                del version['source_sha256']
            (self.text / b['id'] / 'index.json').write_text(json.dumps(index), 'utf-8')

    def index(self, bill_id):
        return json.loads((self.text / bill_id / 'index.json').read_text('utf-8'))

    def sync(self):
        reads = []

        def fetch(conn, path):
            reads.append(path)
            return HTML.encode()

        with mock.patch.object(sync_ftp, 'ftp_bytes', fetch), mock.patch('builtins.print'):
            counts = sync_ftp.sync_texts(self.conn, self.bills, self.text, 400, turn=OFF_TURN)
        return counts, reads

    def test_an_unfingerprinted_text_gains_the_official_hash_and_nothing_else_changes(self):
        before = {b['id']: (self.index(b['id'])['versions'][0], (self.text / b['id'] / 'I.md').read_bytes()) for b in self.bills}
        counts, reads = self.sync()
        self.assertEqual(counts['fingerprinted'], 2)
        self.assertEqual(counts['downloaded'], 0)
        self.assertEqual(len(reads), 2)
        for bill_id, (entry, markdown) in before.items():
            after = self.index(bill_id)['versions'][0]
            self.assertEqual(after['source_sha256'], hashlib.sha256(HTML.encode()).hexdigest())
            self.assertEqual({k: v for k, v in after.items() if k != 'source_sha256'}, entry)
            self.assertEqual((self.text / bill_id / 'I.md').read_bytes(), markdown)

    def test_a_fingerprinted_unchanged_bill_costs_no_ftp_call_again(self):
        self.sync()
        self.conn.mdtm.clear()
        counts, reads = self.sync()
        self.assertEqual((reads, self.conn.mdtm, counts['fingerprinted']), ([], [], 0))
        self.assertEqual(counts['skipped_bills'], 2)

    def test_each_run_fingerprints_at_most_its_share(self):
        with mock.patch.object(sync_ftp, 'SOURCE_BACKFILL_PER_RUN', 1):
            counts, reads = self.sync()
            self.assertEqual((counts['fingerprinted'], len(reads)), (1, 1))
            self.assertEqual(counts['skipped_bills'], 1)  # waits its turn without an MDTM call
            self.assertEqual(len(self.conn.mdtm), 2 + 1)  # setUp's two, then one this run
            counts, reads = self.sync()
            self.assertEqual((counts['fingerprinted'], len(reads)), (1, 1))
        self.assertTrue(all('source_sha256' in self.index(b['id'])['versions'][0] for b in self.bills))


if __name__ == '__main__':
    unittest.main()
