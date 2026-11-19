"""The data run survives the FTP server answering out of step ("200 Type set to I.") or dropping the connection: the
listing or the one file is read again on a new connection, a bounded number of times per run."""
import ftplib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_ftp

PATHS = [f'/x/HB{i:05}.xml' for i in range(1, 10)]
BREAK_AT = 6  # the first connection serves PATHS[:6], then goes out of step for good
STRAY = ftplib.error_reply('200 Type set to I.')


class Conn:
    """One control connection. `broken` connections fail every transfer with `error`."""
    made = 0

    def __init__(self, broken=False, error=STRAY):
        Conn.made += 1
        self.name, self.broken, self.error, self.closed = Conn.made, broken, error, False

    def close(self):
        self.closed = True


def run(first, fetch, reconnect=None, listing=None):
    listing = listing or (lambda conn: {p: None for p in PATHS})
    with mock.patch.object(sync_ftp, 'list_xml', listing), \
            mock.patch.object(sync_ftp, 'ftp_bytes', fetch), \
            mock.patch.object(sync_ftp, 'parse_bill_xml', lambda raw, path: {'id': Path(path).stem}), \
            mock.patch('builtins.print'):
        return sync_ftp.synchronize(first, {'bills': []}, 25000, {}, {'paths': {}}, None, None, reconnect)


def fetch_on(conn, path):
    if conn.broken:
        raise conn.error
    return path.encode()


def breaks_midway(first):
    def fetch(conn, path):
        if conn is first and path == PATHS[BREAK_AT]:
            first.broken = True
        return fetch_on(conn, path)
    return fetch


class Reconnect(unittest.TestCase):
    def test_stray_reply_mid_run_reads_the_file_again_on_a_new_connection(self):
        first, fresh = Conn(), []
        failed_once = []

        def fetch(conn, path):
            if conn is first and path == PATHS[2]:
                failed_once.append(path)
                first.broken = True  # every later command on it is out of step too
            return fetch_on(conn, path)

        def reconnect():
            fresh.append(Conn())
            return fresh[-1]

        snapshot, stats = run(first, fetch, reconnect)
        self.assertEqual(failed_once, [PATHS[2]])
        self.assertEqual(stats['transfer_errors'], 0)
        self.assertEqual(stats['reconnects'], 1)
        self.assertEqual(len(snapshot['bills']), 9)
        self.assertTrue(first.closed)       # the out-of-step connection is dropped
        self.assertTrue(fresh[0].closed)    # and the one opened here is closed before returning

    def test_without_a_reconnect_the_stray_reply_is_a_transfer_error_not_a_failed_run(self):
        first = Conn()
        snapshot, stats = run(first, breaks_midway(first), reconnect=None)  # raised error_reply out of the run before
        self.assertEqual(stats['transfer_errors'], 3)
        self.assertEqual(len(snapshot['bills']), 6)
        self.assertEqual(stats['reconnects'], 0)

    def test_dropped_connection_mid_run_is_recovered(self):
        first = Conn()

        def fetch(conn, path):
            if conn is first and path >= PATHS[1]:
                raise EOFError()  # the 2026-11-19 04:18 run: 32 of 69 transfers failed after the connection died
            return path.encode()

        _, stats = run(first, fetch, Conn)
        self.assertEqual((stats['transfer_errors'], stats['reconnects']), (0, 1))

    def test_stray_reply_on_the_listing_lists_again(self):
        first = Conn()

        def listing(conn):
            if conn is first:
                raise STRAY
            return {p: None for p in PATHS}

        snapshot, stats = run(first, fetch_on, Conn, listing)
        self.assertEqual((stats['listed'], stats['reconnects'], stats['transfer_errors']), (9, 1, 0))

    def test_reconnects_are_capped_per_run(self):
        made = []

        def reconnect():
            made.append(Conn(broken=True))
            return made[-1]

        first = Conn()
        _, stats = run(first, breaks_midway(first), reconnect)  # every new connection is out of step too
        self.assertEqual(len(made), sync_ftp.MAX_RECONNECTS)
        self.assertEqual(stats['reconnects'], sync_ftp.MAX_RECONNECTS)
        self.assertEqual(stats['transfer_errors'], 3)
        self.assertTrue(stats['incomplete'])

    def test_a_failed_reconnect_keeps_the_old_connection_and_records_the_file(self):
        first = Conn()

        def reconnect():
            raise OSError('connection refused')

        _, stats = run(first, breaks_midway(first), reconnect)  # no AttributeError from a closed connection
        self.assertFalse(first.closed)
        self.assertEqual(stats['transfer_errors'], 3)

    def test_missing_file_is_not_a_connection_problem(self):
        first = Conn(error=ftplib.error_perm('550 not found'))
        calls = []
        _, stats = run(first, breaks_midway(first), lambda: calls.append(1) or Conn())
        self.assertEqual(calls, [])
        self.assertEqual(stats['transfer_errors'], 3)


class Status(unittest.TestCase):
    def test_each_published_run_writes_its_status_beside_the_snapshot(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        out = Path(folder.name) / 'bills.json'
        snapshot = {'generated_at': '2026-11-19T08:18:56Z', 'bills': []}
        stats = {'listed': 1651, 'transfer_errors': 0, 'incomplete': False, 'reconnects': 1}
        argv = ['sync_ftp.py', '--out', str(out)]
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(sync_ftp.ftplib, 'FTP'), \
                mock.patch.object(sync_ftp, 'synchronize', lambda *a: (snapshot, stats)), \
                mock.patch.object(sync_ftp, 'sync_history', lambda *a: {}), \
                mock.patch.object(sync_ftp, 'sync_texts', lambda *a: {}), \
                mock.patch.object(sync_ftp, 'sync_documents', lambda *a: {}), \
                mock.patch.object(sync_ftp, 'sync_witnesses', lambda *a: {}), \
                mock.patch('builtins.print'):
            self.assertEqual(sync_ftp.main(), 0)
        status = json.loads((out.parent / 'sync-status.json').read_text('utf-8'))
        self.assertEqual(status['format'], 'texas-bill-sync-status-v1')
        self.assertEqual(status['generated_at'], snapshot['generated_at'])
        self.assertTrue(status['checked_at'].endswith('Z'))
        self.assertEqual((status['listed'], status['reconnects'], status['failures']), (1651, 1, []))

    def test_status_stays_outside_the_purged_paths(self):
        import purge_cache
        self.assertFalse(any(sync_ftp.STATUS_NAME.startswith(p) for p in purge_cache.PATHS))


if __name__ == '__main__':
    unittest.main()
