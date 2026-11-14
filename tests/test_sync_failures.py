"""A refresh that reads too little, or whose secondary stages fail, still publishes but is reported as a failure."""
import ftplib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_ftp

PRIOR_STAMP = '2026-11-01T00:00:00Z'


def run_sync(failing: int, total: int = 20):
    paths = [f'/x/HB{i:05}.xml' for i in range(1, total + 1)]
    bad = set(paths[:failing])

    def fetch(conn, path):
        if path in bad:
            raise ftplib.error_temp('421 try later')
        return path.encode()

    prior = {'generated_at': PRIOR_STAMP, 'bills': [{'id': 'HB99999'}]}
    with mock.patch.object(sync_ftp, 'enumerate_xml', lambda conn: paths), \
            mock.patch.object(sync_ftp, 'ftp_bytes', fetch), \
            mock.patch.object(sync_ftp, 'parse_bill_xml', lambda raw, path: {'id': Path(path).stem}):
        return sync_ftp.synchronize(object(), prior)


class IncompleteRead(unittest.TestCase):
    def test_many_failed_transfers_keep_the_previous_generated_at(self):
        snapshot, stats = run_sync(failing=5)
        self.assertTrue(stats['incomplete'])
        self.assertEqual(snapshot['generated_at'], PRIOR_STAMP)

    def test_a_few_failed_transfers_are_not_incomplete(self):
        snapshot, stats = run_sync(failing=1)
        self.assertFalse(stats['incomplete'])
        self.assertNotEqual(snapshot['generated_at'], PRIOR_STAMP)  # bills changed, so a fresh stamp


class FailuresFile(unittest.TestCase):
    def run_main(self, stats, history_error=None):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        out, failures = base / 'bills.json', base / 'failures'
        snapshot = {'generated_at': PRIOR_STAMP, 'bills': []}

        def history(*a):
            if history_error:
                raise history_error
            return {}

        argv = ['sync_ftp.py', '--out', str(out), '--failures-file', str(failures)]
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(sync_ftp.ftplib, 'FTP'), \
                mock.patch.object(sync_ftp, 'synchronize', lambda *a: (snapshot, stats)), \
                mock.patch.object(sync_ftp, 'sync_history', history), \
                mock.patch.object(sync_ftp, 'sync_texts', lambda *a: {}), \
                mock.patch.object(sync_ftp, 'sync_documents', lambda *a: {}), \
                mock.patch.object(sync_ftp, 'sync_witnesses', lambda *a: {}), \
                mock.patch('builtins.print'):
            self.assertEqual(sync_ftp.main(), 0)
        self.assertEqual(json.loads(out.read_text('utf-8')), snapshot)  # the snapshot is written regardless
        return failures.read_text('utf-8')

    def test_clean_run_writes_an_empty_file(self):
        self.assertEqual(self.run_main({'listed': 20, 'transfer_errors': 0, 'incomplete': False}), '')

    def test_failed_stage_and_incomplete_read_are_listed(self):
        text = self.run_main({'listed': 20, 'transfer_errors': 5, 'incomplete': True}, OSError('disk full'))
        self.assertEqual(text.splitlines(), ['incomplete read: 5 of 20 transfers failed', 'history: disk full'])


if __name__ == '__main__':
    unittest.main()
