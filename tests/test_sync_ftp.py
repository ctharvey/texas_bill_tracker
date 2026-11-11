import datetime as dt
import ftplib
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import sync_ftp
from sync_ftp import parse_bill_xml, parse_bill_number, infer_status, normalize_date, synchronize, choose_generated_at
from sync_ftp import bill_text_markdown, plain_paragraphs, sync_texts


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

    def test_bill_order_compares_numbers(self):
        from sync_ftp import bill_order
        self.assertEqual(sorted(['HB100', 'HB99', 'SB2', 'HB9', 'HJR10'], key=bill_order), ['HB9', 'HB99', 'HB100', 'HJR10', 'SB2'])

    def test_official_subjects_parsed_without_codes(self):
        xml = b'''<billhistory bill="90(R) HB 280"><caption>Relating to dynamic pricing.</caption><subjects>
          <subject>Artificial Intelligence (IQ7C5)</subject><subject>Business &amp; Commerce--General (I0050)</subject>
          <subject>Artificial Intelligence (IQ7C5)</subject></subjects></billhistory>'''
        bill = parse_bill_xml(xml, 'HB 280.xml')
        self.assertEqual(bill['subjects'], ['Artificial Intelligence', 'Business & Commerce--General'])
        self.assertEqual(parse_bill_xml(b'<billhistory bill="90(R) HB 281"><caption>Relating to water.</caption><subjects /></billhistory>', 'HB 281.xml')['subjects'], [])
        self.assertNotIn('subjects', parse_bill_xml(b'<billhistory bill="90(R) HB 282"><caption>Relating to water.</caption></billhistory>', 'HB 282.xml'))

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


FIXTURE=Path(__file__).resolve().parent/'fixtures'/'HB01001I.HTM'
TLC='ftp://ftp.legis.state.tx.us/bills/90R/billtext/HTML/house_bills/HB01000_HB01099/'


def rows(*cells):
    return '<html><body><table>'+''.join(f'<tr><td>&#xA0;</td><td>{c}</td></tr>' for c in cells)+'</table></body></html>'


class BillTextMarkdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.md=bill_text_markdown(FIXTURE.read_text(encoding='utf-8'),'HB 1001','Introduced')
        cls.paragraphs=cls.md.split('\n\n')

    def test_fixture_structure(self):
        self.assertEqual(self.paragraphs[0],'# HB 1001 - Introduced')
        self.assertIn('### SECTION 1.',self.paragraphs)
        self.assertIn('Section 614.015, Government Code, is amended to read as follows:',self.paragraphs)
        self.assertIn(r'MENTAL HEALTH LEAVE FOR <ins>PUBLIC SAFETY EMPLOYEES</ins> \[<del>PEACE OFFICERS AND TELECOMMUNICATORS</del>\]',self.md)

    def test_no_markup_junk(self):
        for junk in ('PGLN','\xa0','&#','<td','<tr','<META','\r'):
            self.assertNotIn(junk,self.md)
        self.assertTrue(self.md.endswith('\n'))
        self.assertFalse(self.md.endswith('\n\n'))
        for paragraph in self.paragraphs[:-1]:
            self.assertTrue(paragraph)
            self.assertNotIn('\n',paragraph)
        self.assertNotIn('\n',self.paragraphs[-1].rstrip('\n'))
        self.assertNotIn('  ',self.md)

    def test_leading_lines(self):
        self.assertEqual(self.paragraphs[1],'90R1865 MP-D')
        self.assertIn('AN ACT',self.paragraphs)
        self.assertIn('relating to a mental health leave policy for certain public safety employees.',self.paragraphs)

    def test_ins_runs_merge_across_lines(self):
        html=rows('plain <u>one </u>','<u>two </u>','<u>three</u> end')
        self.assertEqual(bill_text_markdown(html,'HB 1','Introduced'),'# HB 1 - Introduced\n\nplain <ins>one two three</ins> end\n')

    def test_whitespace_between_different_kinds_stays_outside(self):
        md=bill_text_markdown(rows('<u>a </u><s>b</s>'),'HB 1','Introduced')
        self.assertEqual(md.split('\n\n')[1],'<ins>a</ins> <del>b</del>\n')

    def test_indent_starts_paragraph_and_center_isolated(self):
        html=rows('first line','continues','&#xA0;&#xA0;indented','<center>HEAD</center>','after head')
        self.assertEqual(bill_text_markdown(html,'HB 1','X').split('\n\n')[1:],
                         ['first line continues','indented','HEAD','after head\n'])

    def test_section_heading_split_with_markup(self):
        md=bill_text_markdown(rows('&#xA0;&#xA0;SECTION&#xA0;1A.&#xA0;&#xA0;This <u>Act</u>.'),'HB 1','X')
        self.assertEqual(md.split('\n\n')[1:],['### SECTION 1A.','This <ins>Act</ins>.\n'])

    def test_no_text_raises(self):
        with self.assertRaises(ValueError):
            bill_text_markdown('<html><body><table><tr><td>&#xA0;</td></tr></table></body></html>','HB 1','X')
        with self.assertRaises(ValueError):
            bill_text_markdown('','HB 1','X')

    def test_escape_and_projection_round_trip(self):
        original='1. a * b _ c [d] <e> `f` \\g'
        md=bill_text_markdown(rows(original.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')),'HB 1','X')
        paragraph=md.split('\n\n')[1].rstrip('\n')
        self.assertEqual(paragraph,r'1\. a \* b \_ c \[d\] \<e\> \`f\` \\g')
        self.assertEqual(plain_paragraphs(md)[1],original)
        for lead in ('# x','- x','+ x','= x','2) x'):
            md=bill_text_markdown(rows(lead),'HB 1','X')
            self.assertEqual(plain_paragraphs(md)[1],lead)
            self.assertIn('\\',md.split('\n\n')[1])

    def test_plain_paragraphs_on_fixture(self):
        plain=plain_paragraphs(self.md)
        self.assertEqual(plain[0],'HB 1001 - Introduced')
        joined='\n'.join(plain)
        for marker in ('<ins>','</ins>','<del>','</del>','\\['):
            self.assertNotIn(marker,joined)
        self.assertIn('[PEACE OFFICERS AND TELECOMMUNICATORS]',joined)
        self.assertIn('SECTION 1.',plain)


class TextVersionParseTests(unittest.TestCase):
    def test_versions_in_order_filtered(self):
        xml=f'''<billhistory bill="90(R) HB 1001" lastUpdate="11/10/2026 8:00:00 AM"><caption>Relating to leave policy.</caption>
          <billtext><docTypes>
            <bill><versions>
              <version><versionDescription>Introduced</versionDescription><FTPHTMLURL>{TLC}HB01001I.HTM</FTPHTMLURL></version>
              <version><versionDescription>Elsewhere</versionDescription><FTPHTMLURL>ftp://example.com/bills/90R/billtext/HTML/HB01001X.HTM</FTPHTMLURL></version>
              <version><versionDescription>Committee Report</versionDescription><FTPHTMLURL>{TLC}HB01001H.HTM</FTPHTMLURL></version>
            </versions></bill>
            <analysis><versions><version><versionDescription>Analysis</versionDescription><FTPHTMLURL>{TLC}HB01001A.HTM</FTPHTMLURL></version></versions></analysis>
            <fiscalNote><versions><version><versionDescription>Fiscal</versionDescription><FTPHTMLURL>{TLC}HB01001F.HTM</FTPHTMLURL></version></versions></fiscalNote>
          </docTypes></billtext></billhistory>'''.encode('utf-8')
        bill=parse_bill_xml(xml,'HB01001.xml')
        self.assertEqual(bill['text_versions'],[
            {'code':'I','name':'Introduced','html':f'{TLC}HB01001I.HTM'},
            {'code':'H','name':'Committee Report','html':f'{TLC}HB01001H.HTM'}])
        self.assertEqual(bill['source_updated'],'11/10/2026 8:00:00 AM')

    def test_absent_and_empty(self):
        self.assertNotIn('text_versions',parse_bill_xml(b'<billhistory bill="90(R) HB 5"><caption>Relating to water.</caption></billhistory>','HB00005.xml'))
        self.assertNotIn('source_updated',parse_bill_xml(b'<billhistory bill="90(R) HB 5"><caption>Relating to water.</caption></billhistory>','HB00005.xml'))
        bill=parse_bill_xml(b'<billhistory bill="90(R) HB 5"><caption>Relating to water.</caption><billtext><docTypes><bill><versions/></bill></docTypes></billtext></billhistory>','HB00005.xml')
        self.assertEqual(bill['text_versions'],[])


class SyncTextsTests(unittest.TestCase):
    HTML=rows('&#xA0;&#xA0;SECTION&#xA0;1.&#xA0;&#xA0;Text <u>new</u>.')

    def bills(self,updated='v1',codes=('I','H')):
        return [{'id':'HB1001','number':'HB 1001','source_updated':updated,
                 'text_versions':[{'code':c,'name':{'I':'Introduced','H':'Committee Report'}.get(c,c),'html':f'{TLC}HB01001{c}.HTM'} for c in codes]}]

    def run_sync(self,directory,bills,max_texts=400,side_effect=None):
        with mock.patch.object(sync_ftp,'ftp_bytes',side_effect=side_effect or (lambda conn,path:self.HTML.encode('utf-8'))) as patched:
            counts=sync_texts(object(),bills,Path(directory),max_texts)
        return counts,patched

    def test_writes_files_and_skips_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts,patched=self.run_sync(tmp,self.bills())
            self.assertEqual((counts['downloaded'],counts['failed']),(2,0))
            self.assertEqual({c.args[1] for c in patched.call_args_list},{'/bills/90R/billtext/HTML/house_bills/HB01000_HB01099/HB01001I.HTM','/bills/90R/billtext/HTML/house_bills/HB01000_HB01099/HB01001H.HTM'})
            md=(Path(tmp)/'HB1001'/'I.md').read_bytes()
            self.assertTrue(md.startswith(b'# HB 1001 - Introduced\n\n### SECTION 1.\n\nText <ins>new</ins>.\n'))
            index=json.loads((Path(tmp)/'HB1001'/'index.json').read_text(encoding='utf-8'))
            self.assertEqual(index['format'],'texas-bill-text-index-v1')
            self.assertEqual(index['bill_id'],'HB1001')
            self.assertEqual([v['code'] for v in index['versions']],['I','H'])
            self.assertEqual(index['versions'][0]['sha256'],hashlib.sha256(md).hexdigest())
            self.assertEqual(index['versions'][0]['source_modified'],'v1')
            self.assertEqual(index['versions'][0]['path'],'I.md')
            counts,patched=self.run_sync(tmp,self.bills())
            self.assertEqual((counts['downloaded'],counts['unchanged']),(0,2))
            patched.assert_not_called()
            counts,patched=self.run_sync(tmp,self.bills('v2'))
            self.assertEqual(counts['downloaded'],2)
            index=json.loads((Path(tmp)/'HB1001'/'index.json').read_text(encoding='utf-8'))
            self.assertEqual(index['versions'][1]['source_modified'],'v2')

    def test_max_texts_limits_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts,patched=self.run_sync(tmp,self.bills(),max_texts=1)
            self.assertEqual((counts['downloaded'],counts['deferred']),(1,1))
            self.assertEqual(patched.call_count,1)
            self.assertTrue((Path(tmp)/'HB1001'/'I.md').exists())
            self.assertFalse((Path(tmp)/'HB1001'/'H.md').exists())
            index=json.loads((Path(tmp)/'HB1001'/'index.json').read_text(encoding='utf-8'))
            self.assertEqual([v['code'] for v in index['versions']],['I'])
            counts,_=self.run_sync(tmp,self.bills(),max_texts=1)
            self.assertEqual((counts['downloaded'],counts['unchanged']),(1,1))
            index=json.loads((Path(tmp)/'HB1001'/'index.json').read_text(encoding='utf-8'))
            self.assertEqual([v['code'] for v in index['versions']],['I','H'])

    def test_failed_download_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_sync(tmp,self.bills(codes=('I',)))
            before=(Path(tmp)/'HB1001'/'I.md').read_bytes()
            def boom(conn,path):raise ftplib.error_temp('421 try later')
            counts,_=self.run_sync(tmp,self.bills('v2',codes=('I',)),side_effect=boom)
            self.assertEqual((counts['failed'],counts['downloaded']),(1,1))
            self.assertEqual((Path(tmp)/'HB1001'/'I.md').read_bytes(),before)
            index=json.loads((Path(tmp)/'HB1001'/'index.json').read_text(encoding='utf-8'))
            self.assertEqual(index['versions'][0]['source_modified'],'v1')
            counts,_=self.run_sync(tmp,self.bills('v3',codes=('I',)),side_effect=lambda conn,path:b'<html></html>')
            self.assertEqual(counts['failed'],1)
            self.assertEqual((Path(tmp)/'HB1001'/'I.md').read_bytes(),before)

    # Shape of TLC's placeholder: a Word page with one paragraph, line-wrapped mid-sentence.
    PLACEHOLDER=('<html xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta name=ProgId content=Word.Document>'
                 '<style><!-- p.MsoNormal {margin:0in;} --></style></head><body lang=EN-US><div class=WordSection1>'
                 '<p class=MsoNormal><span style=\'font-size:12.0pt\'>This version is not currently available, but is coming\n'
                 'soon. In the meantime, please see the PDF for the content of this bill.</span></p></div></body></html>')

    def test_placeholder_is_not_posted_not_failed(self):
        with self.assertRaises(sync_ftp.TextNotPosted):
            bill_text_markdown(self.PLACEHOLDER,'HB 1','X')
        with tempfile.TemporaryDirectory() as tmp:
            counts,_=self.run_sync(tmp,self.bills(codes=('I',)),side_effect=lambda conn,path:self.PLACEHOLDER.encode('cp1252'))
            self.assertEqual((counts['not_posted'],counts['failed']),(1,0))
            self.assertFalse((Path(tmp)/'HB1001').exists())
            self.run_sync(tmp,self.bills('v2',codes=('I',)))  # real text posted later is picked up
            self.assertTrue((Path(tmp)/'HB1001'/'I.md').exists())
            before=(Path(tmp)/'HB1001'/'I.md').read_bytes()
            counts,_=self.run_sync(tmp,self.bills('v3',codes=('I',)),side_effect=lambda conn,path:self.PLACEHOLDER.encode('cp1252'))
            self.assertEqual(counts['not_posted'],1)
            self.assertEqual((Path(tmp)/'HB1001'/'I.md').read_bytes(),before)  # a later placeholder keeps the text

    def test_cp1252_fallback_and_mdtm(self):
        class Conn:
            def sendcmd(self,cmd):
                self.cmd=cmd
                return '213 20261110123456'
        conn=Conn()
        bills=self.bills(updated='',codes=('I',))
        del bills[0]['source_updated']
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sync_ftp,'ftp_bytes',return_value=rows('caf\xe9').encode('cp1252')):
                counts=sync_texts(conn,bills,Path(tmp),5)
            self.assertEqual(counts['downloaded'],1)
            self.assertEqual(conn.cmd,'MDTM /bills/90R/billtext/HTML/house_bills/HB01000_HB01099/HB01001I.HTM')
            self.assertIn('caf\xe9',(Path(tmp)/'HB1001'/'I.md').read_text(encoding='utf-8'))
            index=json.loads((Path(tmp)/'HB1001'/'index.json').read_text(encoding='utf-8'))
            self.assertEqual(index['versions'][0]['source_modified'],'20261110123456')


if __name__=='__main__':unittest.main()
