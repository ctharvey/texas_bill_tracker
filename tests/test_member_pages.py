"""Member pages inside the site shell: one full page per legislator at /member/<code>/<slug>, taken over by the app in
place (SEO chunk 5, phase 1)."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))  # Linux-only lock; unused by these tests.
import build_feeds as bf
import deploy_static as deploy

SHELL = deploy.shell_page((ROOT / 'index.html').read_text(encoding='utf-8').encode()).decode()
ALDERS = {'chamber': 'house', 'code': 'A4395', 'display_name': 'Alders', 'full_name': 'Daniel Alders',
          'party': 'Republican', 'party_source': 'Texas Legislative Reference Library, latest recorded service',
          'party_basis': 'service', 'district': '6',
          'service': [{'chamber': 'house', 'district': '6', 'years': '2025 - 2027', 'legislatures': '89th - 89th', 'party': 'R'}],
          'links': {'tlo': 'https://capitol.texas.gov/Members/MemberInfo.aspx?Leg=90&Chamber=H&Code=A4395',
                    'lrl': 'javascript:alert(1)'}}
ANCHIA = {'chamber': 'house', 'code': 'A2150', 'display_name': 'Anchía', 'full_name': 'Rafael Anchía',
          'party': 'Democratic', 'district': '103', 'service': [], 'links': {}}
ROSTER = {'house|Alders': ALDERS, 'house|Anchía': ANCHIA}
SNAPSHOT = {'bills': [
    {'id': 'HB7', 'caption': 'Relating to <water> & wells.', 'authors': ['Alders'], 'last_action_date': '2026-11-10'},
    {'id': 'HB12', 'caption': 'Relating to roads.', 'authors': ['Alders'], 'last_action_date': '2026-11-14'},
    {'id': 'HB9', 'caption': 'Relating to schools.', 'authors': ['Anchía'], 'coauthors': ['Alders'],
     'last_action_date': '2026-11-12'},
    {'id': 'SB3', 'caption': 'Relating to taxes.', 'authors': ['Hughes'], 'sponsors': ['Alders'],
     'last_action_date': '2026-11-13'},
]}


def content(page: str) -> str:
    return page.split('<!--content-->', 1)[1].split('<!--/content-->', 1)[0]


class MemberPages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.counts = bf.write_member_pages(SNAPSHOT, ROSTER, self.tmp, shell=SHELL)
        self.alders = (self.tmp / 'A4395.html').read_text('utf-8')

    def test_one_page_per_member_bills_or_not(self):
        self.assertEqual(self.counts, (2, 0, 0))
        self.assertIn('data-static-view="member:A4395"', self.alders)
        anchia = (self.tmp / 'A2150.html').read_text('utf-8')
        self.assertIn('<h1>Rep. Rafael Anchía</h1>', anchia)
        self.assertIn('Member-elect; no prior service on record.', anchia)
        self.assertNotIn('No bills by this member', anchia)  # HB9.

    def test_canonical_is_the_apps_address(self):
        self.assertIn('<link rel="canonical" href="https://billatlas.org/member/A4395/daniel-alders">', self.alders)
        self.assertIn('<link rel="canonical" href="https://billatlas.org/member/A2150/rafael-anchia">',
                      (self.tmp / 'A2150.html').read_text('utf-8'))

    def test_bills_by_role_newest_action_first_linked_to_bill_pages(self):
        body = content(self.alders)
        self.assertLess(body.index('<h2>Author (2)</h2>'), body.index('<h2>Coauthor (1)</h2>'))
        self.assertLess(body.index('<h2>Coauthor (1)</h2>'), body.index('<h2>Sponsor (1)</h2>'))
        self.assertLess(body.index('bill/HB12'), body.index('bill/HB7'))
        self.assertIn('<a href="https://billatlas.org/bill/SB3">SB 3</a>', body)
        self.assertIn('Relating to &lt;water&gt; &amp; wells.', body)

    def test_who_they_are_with_the_party_source(self):
        body = content(self.alders)
        self.assertIn('<h1>Rep. Daniel Alders</h1>', body)
        self.assertIn('<p>Texas House · District 6 · Republican</p>', body)
        self.assertIn('Party as recorded by Texas Legislative Reference Library, latest recorded service.', body)
        self.assertIn('House District 6, 2025 - 2027 (89th Legislature)', body)
        self.assertIn('capitol.texas.gov', body)
        self.assertNotIn('javascript:', body)
        self.assertIn('https://billatlas.org/live/feeds/members/A4395.xml', body)

    def test_no_bills_says_so(self):
        bf.write_member_pages({'bills': []}, ROSTER, self.tmp, shell=SHELL)
        self.assertIn('No bills by this member in this snapshot yet.', (self.tmp / 'A4395.html').read_text('utf-8'))

    def test_rewrites_only_changes_and_removes_departed_members(self):
        (self.tmp / 'A9999.html').write_text('old', 'utf-8')
        (self.tmp / 'notes.txt').write_text('keep', 'utf-8')
        self.assertEqual(bf.write_member_pages(SNAPSHOT, ROSTER, self.tmp, shell=SHELL), (0, 2, 1))
        self.assertFalse((self.tmp / 'A9999.html').exists())
        self.assertTrue((self.tmp / 'notes.txt').exists())

    def test_without_a_shell_or_a_roster_nothing_changes(self):
        self.assertEqual(bf.write_member_pages(SNAPSHOT, ROSTER, self.tmp, shell=None), (0, 0, 0))
        self.assertEqual(bf.write_member_pages(SNAPSHOT, {}, self.tmp, shell=SHELL), (0, 0, 0))
        self.assertTrue((self.tmp / 'A4395.html').exists())

    def test_sitemap_lists_member_addresses(self):
        xml = bf.sitemap(SNAPSHOT, members=list(ROSTER.values()) + [{'code': 'x'}])
        self.assertIn('<loc>https://billatlas.org/member/A2150/rafael-anchia</loc>', xml)
        self.assertLess(xml.index('member/A2150'), xml.index('member/A4395'))
        self.assertNotIn('member/x', xml)
        self.assertNotIn('/member/', bf.sitemap(SNAPSHOT))


class SlugMatchesTheApp(unittest.TestCase):
    NAMES = ['Daniel Alders', 'Rafael Anchía', 'José Menéndez', "Tan Parker", 'Mary González', 'Ana-María Rodríguez Ramos',
             "D'Wayne Example, Jr.", '  ', '', 'x' * 70, 'A ' * 40]

    def test_known_slugs(self):
        self.assertEqual(bf.slugify('Rafael Anchía'), 'rafael-anchia')
        self.assertEqual(bf.member_path({'code': 'A1', 'full_name': '  '}), 'member/A1')

    def test_same_as_routes_js_for_every_roster_name(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        roster = json.loads((ROOT / 'data' / 'members.json').read_text('utf-8'))['members'].values()
        names = self.NAMES + [m.get('full_name') or m.get('display_name') or '' for m in roster]
        script = ("import {slugify} from './src/core/routes.js';"
                  "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>"
                  "process.stdout.write(JSON.stringify(JSON.parse(s).map(slugify))));")
        done = subprocess.run([node, '--input-type=module', '-e', script], input=json.dumps(names), cwd=ROOT,
                              capture_output=True, text=True, encoding='utf-8', check=True)
        self.assertEqual(json.loads(done.stdout), [bf.slugify(n) for n in names])


if __name__ == '__main__':
    unittest.main()
