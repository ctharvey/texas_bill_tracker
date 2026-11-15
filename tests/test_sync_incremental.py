"""Incremental history sync: a file is skipped only when its fingerprint AND the prior snapshot prove the data is held."""
import ftplib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_ftp

ROOT = '/bills/90r/billhistory/house_bills/HB00100_HB00199'


def files(n=4, stamp='11-10-26 02:00AM', updated='2026-11-10T02:00:00'):
    """{path: content}; content encodes the bill id and its lastUpdate."""
    return {f'{ROOT}/HB {100 + i}.xml': f'HB{100 + i}|{updated}' for i in range(n)}


def fake_parse(raw, path):
    text = raw.decode()
    if '|' not in text:
        return None
    bill_id, updated = text.split('|')
    return {'id': bill_id, 'source_path': path, 'source_updated': updated, 'title': bill_id}


class Server:
    def __init__(self, contents, stamps=None):
        self.contents = dict(contents)
        self.stamps = dict(stamps or {})
        self.fetched = []
        self.failing = set()

    def listing(self, conn=None):
        return {p: {'stamp': self.stamps.get(p, '11-10-26 02:00AM'), 'size': len(c.encode())}
                for p, c in sorted(self.contents.items())}

    def fetch(self, conn, path):
        self.fetched.append(path)
        if path in self.failing:
            raise ftplib.error_temp('421 try later')
        return self.contents[path].encode()


def run(server, prior, state, **kw):
    histories = {}
    server.fetched = []
    with mock.patch.object(sync_ftp, 'list_xml', server.listing), \
            mock.patch.object(sync_ftp, 'ftp_bytes', server.fetch), \
            mock.patch.object(sync_ftp, 'parse_bill_xml', fake_parse), \
            mock.patch('builtins.print'):
        snapshot, stats = sync_ftp.synchronize(object(), prior, 25000, histories, state,
                                               kw.get('max_histories'), kw.get('deadline'))
    return snapshot, stats


def commit(state):
    with tempfile.TemporaryDirectory() as tmp:
        sync_ftp.commit_state(state, Path(tmp) / 'state.json')
        return sync_ftp.load_state(Path(tmp) / 'state.json')


class Incremental(unittest.TestCase):
    def cycle(self, server, prior=None, state=None, **kw):
        state = {'paths': {}} if state is None else state
        snapshot, stats = run(server, prior or {'bills': []}, state, **kw)
        return snapshot, stats, commit(state)

    def settled(self, n=4):
        server = Server(files(n))
        snapshot, stats, state = self.cycle(server)
        self.assertEqual(stats['fetched'], n)
        return server, snapshot, state

    def test_unchanged_files_are_skipped_except_the_recheck_share(self):
        server, prior, state = self.settled(48)
        snapshot, stats, _ = self.cycle(server, prior, state)
        self.assertEqual(stats['fetched'], 2)  # ceil(48 / 24)
        self.assertEqual(stats['unchanged'], 46)
        self.assertEqual(snapshot['bills'], prior['bills'])
        self.assertEqual(snapshot['coverage_note'], prior['coverage_note'])

    def test_recheck_rotates_through_every_file(self):
        server, prior, state = self.settled(4)
        seen = set()
        for _ in range(4):
            time.sleep(0.002)  # 'fetched' has microsecond precision: each run's reads sort after the older ones
            prior, stats, state = self.cycle(server, prior, state)
            seen.update(server.fetched)
        self.assertEqual(len(seen), 4)

    def test_changed_stamp_is_read(self):
        server, prior, state = self.settled(4)
        changed = sorted(server.contents)[2]
        server.stamps[changed] = '11-11-26 02:00AM'
        server.contents[changed] = changed.rsplit('/', 1)[1].replace(' ', '').replace('.xml', '') + '|2026-11-11T02:00:00'
        snapshot, stats, _ = self.cycle(server, prior, state)
        self.assertIn(changed, server.fetched)
        self.assertEqual(server.fetched[0], changed)  # changed files come before the re-check share
        bill = next(b for b in snapshot['bills'] if b['source_path'] == changed)
        self.assertEqual(bill['source_updated'], '2026-11-11T02:00:00')

    def test_same_stamp_but_snapshot_does_not_hold_that_read_is_read_again(self):
        server, prior, state = self.settled(4)
        path = sorted(server.contents)[3]
        # An older snapshot restored over the live one: state says read, the snapshot holds something else.
        for bill in prior['bills']:
            if bill['source_path'] == path:
                bill['source_updated'] = '2026-11-01T00:00:00'
        _, stats, _ = self.cycle(server, prior, state)
        self.assertIn(path, server.fetched)

    def test_bill_missing_from_prior_is_read_again(self):
        server, prior, state = self.settled(4)
        path = sorted(server.contents)[3]
        prior = {**prior, 'bills': [b for b in prior['bills'] if b['source_path'] != path]}
        snapshot, _, _ = self.cycle(server, prior, state)
        self.assertIn(path, server.fetched)
        self.assertIn(path, {b['source_path'] for b in snapshot['bills']})

    def test_other_parser_version_is_read_after_changed_files_and_capped(self):
        server, prior, state = self.settled(48)
        stale = sorted(server.contents)[5]
        state['paths'][stale]['parser'] = 'old'
        changed = sorted(server.contents)[7]
        server.stamps[changed] = '11-11-26 02:00AM'
        _, stats, _ = self.cycle(server, prior, state, max_histories=2)
        self.assertEqual(server.fetched, [changed, stale])
        self.assertEqual(stats['deferred'], 2)  # the two re-check files wait

    def test_cap_defers_the_rest_to_the_next_run(self):
        server = Server(files(10))
        prior, stats, state = self.cycle(server, max_histories=4)
        self.assertEqual((stats['fetched'], stats['deferred']), (4, 6))
        self.assertEqual(len(prior['bills']), 4)
        prior, stats, state = self.cycle(server, prior, state, max_histories=4)
        prior, stats, state = self.cycle(server, prior, state, max_histories=4)
        self.assertEqual(len(prior['bills']), 10)

    def test_deadline_passed_reads_nothing_and_keeps_the_snapshot(self):
        server, prior, state = self.settled(4)
        server.stamps[sorted(server.contents)[0]] = '11-12-26 02:00AM'
        snapshot, stats, after = self.cycle(server, prior, state, deadline=time.monotonic() - 1)
        self.assertEqual(stats['fetched'], 0)
        self.assertEqual(snapshot['bills'], prior['bills'])
        self.assertEqual(after['paths'], state['paths'])

    def test_failed_transfer_is_not_recorded_and_is_read_next_run(self):
        server, prior, state = self.settled(4)
        path = sorted(server.contents)[1]
        server.stamps[path] = '11-12-26 02:00AM'
        server.failing.add(path)
        prior, stats, state = self.cycle(server, prior, state)
        self.assertEqual(stats['transfer_errors'], 1)
        self.assertFalse(stats['incomplete'])  # one failure in an incremental run is not an outage
        server.failing.clear()
        _, _, _ = self.cycle(server, prior, state)
        self.assertIn(path, server.fetched)

    def test_many_failed_transfers_in_an_incremental_run_are_incomplete(self):
        server, prior, state = self.settled(10)
        for path in server.contents:
            server.stamps[path] = '11-12-26 02:00AM'
        server.failing.update(sorted(server.contents)[:3])
        snapshot, stats, _ = self.cycle(server, {**prior, 'generated_at': '2026-11-01T00:00:00Z'}, state)
        self.assertTrue(stats['incomplete'])
        self.assertEqual(snapshot['generated_at'], '2026-11-01T00:00:00Z')

    def test_mostly_failed_incremental_read_leaves_the_snapshot_untouched(self):
        server, prior, state = self.settled(10)
        for path in sorted(server.contents)[:5]:
            server.stamps[path] = '11-12-26 02:00AM'
            server.failing.add(path)
        with self.assertRaises(RuntimeError):
            self.cycle(server, prior, state)

    def test_size_mismatch_is_read_again(self):
        server, prior, state = self.settled(4)
        path = sorted(server.contents)[0]
        server.stamps[path] = '11-12-26 02:00AM'
        listing = server.listing

        def short_listing(conn=None):
            data = listing()
            data[path] = {**data[path], 'size': data[path]['size'] + 7}  # still being written when listed
            return data

        server.listing = short_listing
        prior, _, state = self.cycle(server, prior, state)
        self.assertIsNone(state['paths'][path]['fp'])
        server.listing = listing
        self.cycle(server, prior, state)
        self.assertIn(path, server.fetched)

    def test_recheck_counts_drift_when_content_moved_without_a_new_stamp(self):
        server, prior, state = self.settled(1)
        path = next(iter(server.contents))
        server.contents[path] = 'HB100|2026-11-12T02:00:00'  # same length, same stamp, new lastUpdate
        snapshot, stats, _ = self.cycle(server, prior, state)
        self.assertEqual(stats['recheck_drift'], 1)
        self.assertEqual(snapshot['bills'][0]['source_updated'], '2026-11-12T02:00:00')

    def test_paths_no_longer_listed_are_dropped_from_state(self):
        server, prior, state = self.settled(4)
        gone = sorted(server.contents)[0]
        del server.contents[gone]
        _, _, after = self.cycle(server, prior, state)
        self.assertNotIn(gone, after['paths'])

    def test_unreadable_list_format_falls_back_to_reading_everything(self):
        server, prior, state = self.settled(4)

        def bad(conn):
            raise sync_ftp.ListingFormatError('odd line')

        with mock.patch.object(sync_ftp, 'list_xml', bad), \
                mock.patch.object(sync_ftp, 'enumerate_xml', lambda conn: sorted(server.contents)), \
                mock.patch.object(sync_ftp, 'ftp_bytes', server.fetch), \
                mock.patch.object(sync_ftp, 'parse_bill_xml', fake_parse), \
                mock.patch('builtins.print'):
            server.fetched = []
            _, stats = sync_ftp.synchronize(object(), prior, 25000, {}, state)
        self.assertEqual(len(server.fetched), 4)
        self.assertFalse(stats['fingerprinted'])


class ListParsing(unittest.TestCase):
    class Conn:
        def __init__(self, tree):
            self.tree = tree

        def retrlines(self, cmd, callback):
            path = cmd[len('LIST '):]
            if path not in self.tree:
                raise ftplib.error_perm('550 The system cannot find the file specified.')
            for line in self.tree[path]:
                callback(line)

    def test_iis_lines_with_spaces_in_names(self):
        top = f'{sync_ftp.ROOT}/house_bills'
        conn = self.Conn({
            top: ['11-09-26  10:00AM       <DIR>          HB00100_HB00199'],
            f'{top}/HB00100_HB00199': ['11-10-26  02:00AM                 2055 HB 101.xml',
                                       '11-10-26  02:00AM                   10 notes.txt'],
        })
        listing = sync_ftp.list_xml(conn)
        self.assertEqual(listing, {f'{top}/HB00100_HB00199/HB 101.xml': {'stamp': '11-10-26 02:00AM', 'size': 2055}})

    def test_unix_lines_are_understood(self):
        entries = sync_ftp._list_entries(self.Conn({'/x': ['-rw-r--r--   1 ftp ftp   2055 Nov 10 02:00 HB 101.xml']}), '/x')
        self.assertEqual(entries, [('HB 101.xml', False, 2055, 'Nov 10 02:00')])

    def test_unknown_line_raises(self):
        with self.assertRaises(sync_ftp.ListingFormatError):
            sync_ftp._list_entries(self.Conn({'/x': ['something else entirely']}), '/x')

    def test_missing_folder_is_empty(self):
        self.assertEqual(sync_ftp._list_entries(self.Conn({}), '/nope'), [])


class MainOrdering(unittest.TestCase):
    """State advances only after the snapshot and history files hold what the read produced."""

    def run_main(self, history_counts):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        out = base / 'bills.json'
        entry = {'fp': 'a|1', 'bill': 'HB1', 'source_updated': 'x', 'parser': sync_ftp.PARSER_VERSION, 'fetched': 'now'}

        def fake_sync(conn, prior, max_files, histories, state, *rest):
            state['paths'] = {}
            state['pending'] = {'/p/HB 1.xml': entry}
            return {'generated_at': '', 'bills': [{'id': 'HB1'}]}, {'listed': 1, 'transfer_errors': 0, 'incomplete': False}

        argv = ['sync_ftp.py', '--out', str(out), '--failures-file', str(base / 'failures')]
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(sync_ftp.ftplib, 'FTP'), \
                mock.patch.object(sync_ftp, 'synchronize', fake_sync), \
                mock.patch.object(sync_ftp, 'sync_history', lambda *a: history_counts), \
                mock.patch.object(sync_ftp, 'sync_texts', lambda *a: {}), \
                mock.patch.object(sync_ftp, 'sync_documents', lambda *a: {}), \
                mock.patch.object(sync_ftp, 'sync_witnesses', lambda *a: {}), \
                mock.patch('builtins.print'):
            sync_ftp.main()
        return sync_ftp.load_state(base / 'ftp-history-state.json')['paths']

    def test_pending_is_committed_after_a_clean_history_write(self):
        self.assertIn('/p/HB 1.xml', self.run_main({'written': 1, 'failed': 0}))

    def test_pending_is_dropped_when_a_history_write_failed(self):
        self.assertEqual(self.run_main({'written': 0, 'failed': 1}), {})


class StoredHistories(unittest.TestCase):
    def test_skipped_bills_get_their_stored_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'HB1').mkdir()
            (base / 'HB1' / 'history.json').write_text(json.dumps(
                {'format': sync_ftp.HISTORY_FORMAT, 'bill': 'HB1', 'source_updated': 'x',
                 'events': [{'code': 'H215'}], 'documents': [{'type': 'analysis'}]}), encoding='utf-8')
            (base / 'HB2').mkdir()
            (base / 'HB2' / 'history.json').write_text(json.dumps({'format': 'other', 'bill': 'HB2'}), encoding='utf-8')
            histories = {'HB3': {'events': ['fresh']}}
            loaded = sync_ftp.load_stored_histories([{'id': 'HB1'}, {'id': 'HB2'}, {'id': 'HB3'}, {'id': '../x'}],
                                                    histories, base)
            self.assertEqual(loaded, 1)
            self.assertEqual(histories['HB1']['events'], [{'code': 'H215'}])
            self.assertEqual(histories['HB3'], {'events': ['fresh']})  # a fresh read is never replaced
            self.assertNotIn('HB2', histories)

    def test_stored_history_round_trips_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = {'HB1': {'events': [{'code': 'H215', 'date': '', 'text': 'a'}], 'documents': [], 'source_updated': 'x'}}
            sync_ftp.sync_history(first, base)
            again = {}
            sync_ftp.load_stored_histories([{'id': 'HB1'}], again, base)
            counts = sync_ftp.sync_history(again, base)
            self.assertEqual((counts['written'], counts['unchanged']), (0, 1))


if __name__ == '__main__':
    unittest.main()
