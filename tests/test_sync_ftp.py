import datetime as dt
import ftplib
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from sync_ftp import parse_bill_xml, parse_bill_number, infer_status, normalize_date, synchronize, choose_generated_at


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

    def test_companions_parsed_and_absent_tag_left_out(self):
        xml = '''<billhistory bill="90(R) HB 267"><caption>Relating to water.</caption>
          <companions>SB 132 by Menéndez, Identical </companions></billhistory>'''.encode('utf-8')
        bill = parse_bill_xml(xml, 'HB00267.xml')
        self.assertEqual(bill['companions'], [{'id': 'SB132', 'author': 'Menéndez', 'relation': 'Identical'}])
        bill = parse_bill_xml(b'<billhistory bill="90(R) HB 268"><caption>Relating to water.</caption><companions /></billhistory>', 'HB00268.xml')
        self.assertEqual(bill['companions'], [])
        bill = parse_bill_xml(b'<billhistory bill="90(R) HB 269"><caption>Relating to water.</caption></billhistory>', 'HB00269.xml')
        self.assertNotIn('companions', bill)

    def test_companions_self_reference_dropped(self):
        xml = b'<billhistory bill="90(R) HB 5"><caption>Relating to x.</caption><companions>HB 5 by Cole; HJR 5 by Cole, Similar</companions></billhistory>'
        bill = parse_bill_xml(xml, 'HB00005.xml')
        self.assertEqual([c['id'] for c in bill['companions']], ['HJR5'])
        self.assertEqual(bill['companions'][0]['relation'], 'Similar')

    def test_namespace_and_committee(self):
        xml=b'''<History xmlns="urn:test"><bill_number>SB00036</bill_number><caption_text>Relating to tax incentives for data centers.</caption_text><committee_name>Business &amp; Commerce</committee_name></History>'''
        bill=parse_bill_xml(xml,'SB00036.xml')
        self.assertEqual(bill['id'],'SB36')
        self.assertEqual(bill['status'],'Referred')

    def test_official_history_authors_and_filing_action(self):
        xml = '''<billhistory bill="90(R) SJR 9">
          <lastaction>11/10/2026 S Referred to committee</lastaction>
          <caption>Proposing a constitutional amendment establishing the Texas Redistricting Commission.</caption>
          <authors>Men\u00e9ndez | Gutierrez</authors><coauthors />
          <actions>
            <action><actionNumber>S000</actionNumber><date>11/9/2026</date>
              <description>Received by the Secretary of the Senate</description></action>
            <action><actionNumber>S001</actionNumber><date>11/9/2026</date><description>Filed</description></action>
            <action><date>11/10/2026</date><description>Referred to committee</description></action>
          </actions></billhistory>'''.encode('utf-8')
        bill = parse_bill_xml(xml, 'SJR 9.xml')
        self.assertEqual(bill['author'], 'Men\u00e9ndez | Gutierrez')
        self.assertEqual(bill['filed_at'], '2026-11-09')
        self.assertEqual(bill['last_action_date'], '2026-11-10')
        self.assertEqual(bill['status'], 'Referred')
        self.assertEqual(bill['actions'][-1], 'Referred to committee')

    def test_does_not_substitute_unrelated_action_date_for_filing(self):
        xml = b'''<billhistory><caption>Relating to tax incentives for data centers.</caption>
          <authors>Example</authors><actions><action><date>11/10/2026</date>
          <description>Committee report filed</description></action></actions></billhistory>'''
        bill = parse_bill_xml(xml, 'SB99.xml')
        self.assertEqual(bill['filed_at'], '')
        self.assertEqual(bill['last_action_date'], '2026-11-10')

    def test_member_roles_are_separate_and_names_are_deduplicated(self):
        xml = b'''<billhistory><caption>Relating to tax incentives for data centers.</caption>
          <authors>Primary | Joint</authors><coauthors>One | Two | One | </coauthors>
          <sponsors>Other chamber</sponsors><cosponsors>Three | Four</cosponsors></billhistory>'''
        bill = parse_bill_xml(xml, 'SB99.xml')
        self.assertEqual(bill['author'], 'Primary | Joint')
        self.assertEqual(bill['authors'], ['Primary', 'Joint'])
        self.assertEqual(bill['coauthors'], ['One', 'Two'])
        self.assertEqual(bill['sponsors'], ['Other chamber'])
        self.assertEqual(bill['cosponsors'], ['Three', 'Four'])

    def test_empty_official_member_roles_are_empty_lists(self):
        xml = b'''<billhistory><caption>Relating to tax incentives for data centers.</caption>
          <authors>Primary</authors><coauthors /><sponsors /><cosponsors /></billhistory>'''
        bill = parse_bill_xml(xml, 'SB99.xml')
        self.assertEqual(bill['authors'], ['Primary'])
        for role in ('coauthors', 'sponsors', 'cosponsors'):
            self.assertEqual(bill[role], [])

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

    def test_hearing_status_order(self):
        self.assertEqual(infer_status(['Filed','Scheduled for public hearing on 3/2'],['State Affairs']),'Scheduled')
        self.assertEqual(infer_status(['Considered in public hearing'],[]),'Heard')
        self.assertEqual(infer_status(['Public hearing held'],[]),'Heard')
        self.assertEqual(infer_status(['Scheduled for public hearing','Public hearing held'],['State Affairs']),'Heard')
        self.assertEqual(infer_status(['Public hearing'],['State Affairs']),'Referred')

    def test_generated_at_heartbeat(self):
        now=dt.datetime(2026,11,9,12,0,tzinfo=dt.timezone.utc)
        def stamp(hours):
            return (now-dt.timedelta(hours=hours)).isoformat().replace('+00:00','Z')
        payload={'generated_at':'','bills':[{'id':'HB1'}]}
        prev=lambda hours,bills=None:{'generated_at':stamp(hours),'bills':bills or [{'id':'HB1'}]}
        self.assertEqual(choose_generated_at(prev(2),payload,now),stamp(2))
        self.assertEqual(choose_generated_at(prev(7),payload,now),'2026-11-09T12:00:00Z')
        self.assertEqual(choose_generated_at(prev(2,[{'id':'HB2'}]),payload,now),'2026-11-09T12:00:00Z')
        self.assertEqual(choose_generated_at(None,payload,now),'2026-11-09T12:00:00Z')
        self.assertEqual(choose_generated_at({'bills':[]},payload,now),'2026-11-09T12:00:00Z')

    def test_temp_error_counts_as_transfer_error(self):
        class FakeFTP:
            def nlst(self,path):
                return ['/x/HB00001.xml'] if path.endswith('house_bills') else []
            def retrbinary(self,*a,**k):raise ftplib.error_temp('421 try later')
        with self.assertRaises(RuntimeError) as ctx:
            synchronize(FakeFTP(),{'bills':[]})
        self.assertIn('421',str(ctx.exception))

    def test_refuse_empty_snapshot(self):
        class FakeFTP:
            def nlst(self,path):return []
        with self.assertRaises(RuntimeError):
            synchronize(FakeFTP(),{'bills':[{'id':'HB1'}]})


if __name__=='__main__':unittest.main()
