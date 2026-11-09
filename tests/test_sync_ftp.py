import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from sync_ftp import parse_bill_xml, parse_bill_number, infer_status, normalize_date, synchronize


class BillParserTests(unittest.TestCase):
    def test_bill_id(self):
        self.assertEqual(parse_bill_number('HB00001.xml'),'HB1')
        self.assertEqual(parse_bill_number('Senate: SJR 38'),'SJR38')
        self.assertIsNone(parse_bill_number('history.xml'))

    def test_nested_xml(self):
        xml=b'''<Bill><BillNumber>HB 164</BillNumber><Caption>Relating to the education savings account program.</Caption><PrimaryAuthor>John Bucy</PrimaryAuthor><FiledDate>2026-11-09</FiledDate><Actions><Action><ActionDescription>Filed</ActionDescription></Action></Actions></Bill>'''
        bill=parse_bill_xml(xml,'/bills/90r/billhistory/house_bills/0100-0199/HB00164.xml')
        self.assertEqual(bill['id'],'HB164')
        self.assertEqual(bill['author'],'John Bucy')
        self.assertEqual(bill['status'],'Filed')
        self.assertEqual(bill['filed_at'],'2026-11-09')

    def test_namespace_and_committee(self):
        xml=b'''<History xmlns="urn:test"><bill_number>SB00036</bill_number><caption_text>Relating to tax incentives for data centers.</caption_text><committee_name>Business &amp; Commerce</committee_name></History>'''
        bill=parse_bill_xml(xml,'SB00036.xml')
        self.assertEqual(bill['id'],'SB36')
        self.assertEqual(bill['status'],'Referred')

    def test_invalid_xml_and_insufficient_caption_fail_closed(self):
        self.assertIsNone(parse_bill_xml(b'not xml','HB00001.xml'))
        self.assertIsNone(parse_bill_xml(b'<Bill><caption>Hi</caption></Bill>','HB00001.xml'))

    def test_dates(self):
        self.assertEqual(normalize_date('11/09/2026'),'2026-11-09')
        self.assertEqual(normalize_date('2026-11-09'),'2026-11-09')
        self.assertEqual(normalize_date('2026-40-41'),'')

    def test_status(self):
        self.assertEqual(infer_status(['Scheduled for hearing'],[]),'Scheduled')
        self.assertEqual(infer_status(['Reported favorably'],[]),'Advanced')

    def test_refuse_empty_snapshot(self):
        class FakeFTP:
            def nlst(self,path):return []
        with self.assertRaises(RuntimeError):
            synchronize(FakeFTP(),{'bills':[{'id':'HB1'}]})


if __name__=='__main__':unittest.main()
