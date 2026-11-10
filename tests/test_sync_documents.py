import ftplib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_ftp
from sync_ftp import (document_markdown, parse_witness_list, sync_documents, sync_witnesses,
                      witness_list_path)

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
BASE = 'ftp://ftp.legis.state.tx.us/bills/90R/'


def fixture_html(name: str) -> str:
    return sync_ftp._decode_html((FIXTURES / name).read_bytes())


class FakeConn:
    def __init__(self, modified='20260101000000', mdtm_error=None):
        self.modified = modified
        self.mdtm_error = mdtm_error
        self.commands = []

    def sendcmd(self, cmd):
        self.commands.append(cmd)
        if self.mdtm_error:
            raise self.mdtm_error
        return '213 ' + self.modified


def histories(documents=None, codes=()):
    return {'HB2': {
        'events': [{'code': c, 'date': '', 'text': ''} for c in codes],
        'documents': documents if documents is not None else [
            {'type': 'fiscal_note', 'code': 'H', 'name': 'Committee Report',
             'html': BASE + 'fiscalnotes/HTML/house_bills/HB00001_HB00099/HB00002H.htm'},
            {'type': 'analysis', 'code': 'H', 'name': 'Committee Report',
             'html': BASE + 'analysis/HTML/house_bills/HB00001_HB00099/HB00002H.htm'},
        ]}}


class MarkdownTests(unittest.TestCase):
    def test_fiscal_note(self):
        md = document_markdown(fixture_html('89R-HB2-fiscal-H.htm'), 'fiscal_note', 'HB 2', 'Committee Report')
        self.assertTrue(md.startswith('# Fiscal Note — HB 2 (Committee Report)\n\n'))
        self.assertIn('($7,757,076,290)', md)
        self.assertIn('Fiscal Year', md)

    def test_analysis(self):
        html = fixture_html('89R-HB2-analysis-H.htm')
        md = document_markdown(html, 'analysis', 'HB 2', 'Committee Report')
        self.assertTrue(md.startswith('# Bill Analysis'))
        self.assertIn('BACKGROUND AND PURPOSE', md)
        self.assertNotIn('<', md.replace('\\<', ''))
        self.assertLess(len(md), len(html) * 0.7)

    def test_structure_and_dedupe(self):
        md = document_markdown('<html><head><title>x</title></head><body><h2>Head</h2><ul><li>one</li></ul>'
                               '<p>a *b*</p><p>a *b*</p><table><tr><td>1</td><td>2</td></tr></table>'
                               '<script>bad()</script></body></html>')
        self.assertEqual(md, '# Fiscal Note\n\n### Head\n\n- one\n\na \\*b\\*\n\n1 | 2\n')
        with self.assertRaises(ValueError):
            document_markdown('<html></html>')


class WitnessParseTests(unittest.TestCase):
    def test_fixture(self):
        result = parse_witness_list(fixture_html('89R-HB2-witnesses-H.htm'))
        self.assertEqual(result['committee'], 'Public Education')
        self.assertTrue(result['hearing'].startswith('March 4, 2025'))
        witnesses = result['witnesses']
        self.assertGreaterEqual(len(witnesses), 20)
        self.assertIn({'name': 'Aleman, Steven', 'organization': 'Disability Rights Texas', 'position': 'for',
                       'testified': True, 'hearing': result['hearing']}, witnesses)
        self.assertTrue(any(not w['testified'] for w in witnesses))
        self.assertTrue(any(w['position'] == 'against' for w in witnesses))
        self.assertTrue(any(w['organization'] == 'Self' for w in witnesses))
        self.assertTrue(all('�' not in w['name'] + w['organization'] for w in witnesses))

    def test_no_list_raises(self):
        with self.assertRaises(ValueError):
            parse_witness_list('<html><body><p>nothing</p></body></html>')

    def test_paths(self):
        self.assertEqual(witness_list_path('HB2', 'H'),
                         '/bills/90R/witlistbill/html/house_bills/HB00001_HB00099/HB00002H.htm')
        self.assertEqual(witness_list_path('HJR150', 'S'),
                         '/bills/90R/witlistbill/html/house_joint_resolutions/HJ00100_HJ00199/HJ00150S.htm')
        with self.assertRaises(ValueError):
            witness_list_path('../x', 'H')


class SyncDocumentsTests(unittest.TestCase):
    def run_sync(self, tmp, conn=None, max_docs=10, docs=None, html=None):
        page = html or fixture_html('89R-HB2-fiscal-H.htm')
        with mock.patch.object(sync_ftp, 'ftp_bytes', return_value=page.encode('utf-8')) as patched:
            counts = sync_documents(conn or FakeConn(), histories(docs), Path(tmp), max_docs)
        return counts, patched

    def test_written_once_then_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts, _ = self.run_sync(tmp)
            self.assertEqual((counts['downloaded'], counts['written']), (2, 1))
            index = json.loads((Path(tmp) / 'HB2' / 'documents.json').read_text(encoding='utf-8'))
            self.assertEqual(index['format'], 'texas-bill-documents-v1')
            self.assertEqual({d['path'] for d in index['documents']}, {'fiscal_note-H.md', 'analysis-H.md'})
            self.assertTrue((Path(tmp) / 'HB2' / 'analysis-H.md').is_file())
            with mock.patch.object(sync_ftp, '_atomic_write') as writer:
                counts, patched = self.run_sync(tmp)
            writer.assert_not_called()
            patched.assert_not_called()
            self.assertEqual((counts['unchanged'], counts['downloaded']), (2, 0))
            counts, patched = self.run_sync(tmp, conn=FakeConn(modified='20270101000000'))
            self.assertEqual(counts['downloaded'], 2)

    def test_cap_defers(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts, patched = self.run_sync(tmp, max_docs=1)
            self.assertEqual((counts['downloaded'], counts['deferred']), (1, 1))
            self.assertEqual(patched.call_count, 1)

    def test_download_error_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sync_ftp, 'ftp_bytes', side_effect=ftplib.error_temp('421 later')):
                counts = sync_documents(FakeConn(), histories(), Path(tmp), 10)
            self.assertEqual(counts['failed'], 2)
            self.assertFalse((Path(tmp) / 'HB2' / 'documents.json').exists())

    def test_foreign_host_rejected(self):
        docs = [{'type': 'analysis', 'code': 'H', 'name': 'x',
                 'html': 'ftp://evil.example/bills/90R/analysis/HTML/x/HB00002H.htm'}]
        with tempfile.TemporaryDirectory() as tmp:
            counts, patched = self.run_sync(tmp, docs=docs)
            self.assertEqual(counts['failed'], 1)
            patched.assert_not_called()


class SyncWitnessesTests(unittest.TestCase):
    def run_sync(self, tmp, codes, conn=None, max_lists=10, side_effect=None):
        page = fixture_html('89R-HB2-witnesses-H.htm').encode('utf-8')
        with mock.patch.object(sync_ftp, 'ftp_bytes', return_value=page, side_effect=side_effect) as patched:
            counts = sync_witnesses(conn or FakeConn(), histories(codes=codes), Path(tmp), max_lists)
        return counts, patched

    def test_written_then_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts, patched = self.run_sync(tmp, ['H215'])
            self.assertEqual((counts['downloaded'], counts['written']), (1, 1))
            self.assertEqual(patched.call_args[0][1], '/bills/90R/witlistbill/html/house_bills/HB00001_HB00099/HB00002H.htm')
            data = json.loads((Path(tmp) / 'HB2' / 'witnesses-H.json').read_text(encoding='utf-8'))
            self.assertEqual((data['format'], data['bill'], data['chamber']), ('texas-bill-witnesses-v1', 'HB2', 'H'))
            self.assertEqual(data['ftp_modified'], '20260101000000')
            self.assertEqual(data['committee'], 'Public Education')
            counts, patched = self.run_sync(tmp, ['H215'])
            self.assertEqual(counts['unchanged'], 1)
            patched.assert_not_called()

    def test_senate_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts, _ = self.run_sync(tmp, ['S290'])
            self.assertEqual(counts['downloaded'], 1)
            self.assertTrue((Path(tmp) / 'HB2' / 'witnesses-S.json').is_file())

    def test_skipped_without_hearing_code(self):
        conn = FakeConn()
        with tempfile.TemporaryDirectory() as tmp:
            counts, patched = self.run_sync(tmp, ['H001', 'H228'], conn=conn)
        self.assertEqual(counts['lists'], 0)
        self.assertEqual(conn.commands, [])
        patched.assert_not_called()

    def test_550_is_missing_not_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts, patched = self.run_sync(tmp, ['H215'], conn=FakeConn(mdtm_error=ftplib.error_perm('550 no file')))
            self.assertEqual((counts['missing'], counts['failed']), (1, 0))
            patched.assert_not_called()
            counts, _ = self.run_sync(tmp, ['H215'], side_effect=ftplib.error_perm('550 no file'))
            self.assertEqual((counts['missing'], counts['failed']), (1, 0))

    def test_error_counted_and_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts, _ = self.run_sync(tmp, ['H215'], side_effect=ftplib.error_temp('421 later'))
            self.assertEqual(counts['failed'], 1)
            counts, patched = self.run_sync(tmp, ['H215', 'S260'], max_lists=1)
            self.assertEqual((counts['downloaded'], counts['deferred']), (1, 1))


if __name__ == '__main__':
    unittest.main()
