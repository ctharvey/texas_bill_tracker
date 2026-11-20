"""Topic and agency pages inside the site shell: one page per topic and per agency with bills, built from the agent
build's lists (live/agent/data/pages.json), taken over by the app in place (SEO chunk 5, phase 2)."""
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
SNAPSHOT = {'bills': [{'id': f'HB{n}', 'caption': f'Relating to water {n}.', 'last_action_date': '2026-11-10'}
                      for n in range(1, 131)] + [{'id': 'SB2', 'caption': 'Relating to <roads> & bridges.'}]}
DATA = {'format': 'texas-bill-atlas-site-pages-v1', 'topics': [
    {'slug': 'environment-and-water', 'name': 'Environment & water', 'bills': [f'HB{n}' for n in range(130, 0, -1)]},
    {'slug': 'immigration', 'name': 'Immigration', 'bills': []},
    {'slug': '../etc', 'name': 'Bad', 'bills': ['HB1']},
], 'agencies': [
    {'id': 'txdot', 'name': 'Texas Department of Transportation', 'bills': ['SB2', 'HB9999', 'not-a-bill']},
    {'id': 'Bad Id', 'name': 'Bad', 'bills': ['SB2']},
]}


def content(page: str) -> str:
    return page.split('<!--content-->', 1)[1].split('<!--/content-->', 1)[0]


class GroupPages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.paths = bf.write_group_pages(DATA, SNAPSHOT, self.tmp, shell=SHELL)
        self.read = lambda rel: (self.tmp / rel).read_text('utf-8')

    def test_one_page_per_valid_entry(self):
        self.assertEqual(sorted(self.paths), ['agency/txdot', 'topic/environment-and-water', 'topic/immigration'])
        self.assertEqual(sorted(p.name for p in self.tmp.rglob('*.html')),
                         ['environment-and-water.html', 'immigration.html', 'txdot.html'])

    def test_topic_page(self):
        page = self.read('topic/environment-and-water.html')
        self.assertIn('data-static-view="topic:environment-and-water"', page)
        self.assertIn('<link rel="canonical" href="https://billatlas.org/topic/environment-and-water">', page)
        body = content(page)
        self.assertIn('<h1>Environment &amp; water</h1>', body)
        self.assertIn('130 bills in the 90th Texas Legislature about environment &amp; water.', body)
        self.assertIn('<h2>The 100 most recent of 130</h2>', body)
        self.assertEqual(body.count('<li>'), 100)
        self.assertLess(body.index('bill/HB130"'), body.index('bill/HB129"'))  # The agent's order is kept.
        self.assertNotIn('bill/HB30"', body)
        self.assertIn('href="https://billatlas.org/explorer?topic=Environment%20%26%20water">All of them', body)
        self.assertIn('Luna, the AI model', body)

    def test_empty_topic_says_so(self):
        body = content(self.read('topic/immigration.html'))
        self.assertIn('No bills about immigration in the 90th Texas Legislature yet.', body)
        self.assertNotIn('<ul>', body)

    def test_agency_page_skips_unknown_bills_and_labels_inference(self):
        body = content(self.read('agency/txdot.html'))
        self.assertIn('1 bill in the 90th Texas Legislature could affect the Texas Department of Transportation.', body)
        self.assertIn('<a href="https://billatlas.org/bill/SB2">SB 2</a>: Relating to &lt;roads&gt; &amp; bridges.', body)
        self.assertIn('not confirmed legal obligations', body)
        self.assertIn('explorer?agency=txdot', body)
        self.assertNotIn('HB9999', body)

    def test_stale_pages_removed_but_never_on_missing_input(self):
        (self.tmp / 'topic' / 'old-topic.html').write_text('old', 'utf-8')
        (self.tmp / 'agency' / 'notes.txt').write_text('keep', 'utf-8')
        for data, shell in ((None, SHELL), (DATA, None), ({'format': 'other'}, SHELL)):
            self.assertEqual(bf.write_group_pages(bf.load_site_pages(None) if data is None else data
                                                  if data.get('format') == bf.SITE_PAGES_FORMAT else None,
                                                  SNAPSHOT, self.tmp, shell=shell), [])
        self.assertTrue((self.tmp / 'topic' / 'old-topic.html').exists())
        bf.write_group_pages({**DATA, 'agencies': []}, SNAPSHOT, self.tmp, shell=SHELL)
        self.assertFalse((self.tmp / 'topic' / 'old-topic.html').exists())
        self.assertTrue((self.tmp / 'agency' / 'txdot.html').exists())  # No agencies listed: the folder is kept.
        self.assertTrue((self.tmp / 'agency' / 'notes.txt').exists())

    def test_load_site_pages(self):
        path = self.tmp / 'pages.json'
        self.assertIsNone(bf.load_site_pages(path))
        path.write_text('{', 'utf-8')
        self.assertIsNone(bf.load_site_pages(path))
        path.write_text(json.dumps({'format': 'x'}), 'utf-8')
        self.assertIsNone(bf.load_site_pages(path))
        path.write_text(json.dumps(DATA), 'utf-8')
        self.assertEqual(bf.load_site_pages(path)['format'], bf.SITE_PAGES_FORMAT)

    def test_sitemap_lists_group_paths(self):
        xml = bf.sitemap({'bills': []}, paths=self.paths)
        self.assertIn('<loc>https://billatlas.org/agency/txdot</loc>', xml)
        self.assertIn('<loc>https://billatlas.org/topic/immigration</loc>', xml)


class BillPagesLinkToTheirGroups(unittest.TestCase):
    def test_bill_groups_inverts_valid_entries_only(self):
        groups = bf.bill_groups(DATA)
        self.assertEqual(groups['SB2'], [('agency', 'txdot', 'Texas Department of Transportation')])
        self.assertEqual(groups['HB1'], [('topic', 'environment-and-water', 'Environment & water')])  # Not '../etc'.
        self.assertEqual(bf.bill_groups(None), {})

    def test_bill_page_in_shell_links_topics_and_agencies(self):
        bill = {'id': 'SB2', 'caption': 'Relating to roads.'}
        page = bf.share_page(bill, shell=SHELL, groups=[('topic', 'transportation', 'Transportation'),
                                                         ('agency', 'txdot', 'Texas Department of Transportation')])
        self.assertIn('<strong>Topics:</strong> <a href="https://billatlas.org/topic/transportation">Transportation</a>.',
                      page)
        self.assertIn('<a href="https://billatlas.org/agency/txdot">Texas Department of Transportation</a>', page)
        self.assertIn('possible, not confirmed', page)
        self.assertNotIn('<strong>Topics:</strong>', bf.share_page(bill, shell=SHELL))


ABOUT = [{'view': 'method', 'path': '/about/method', 'heading': ['How the atlas works.', 'Signals & uncertainty.'],
          'description': 'How Texas Bill Atlas reads the official record.', 'html': '<div class="method-grid"><p>Text</p></div>'},
         {'view': 'export', 'path': '/about/export', 'heading': ['x', 'y'], 'html': '<p>noindex view</p>'},
         {'view': 'data', 'path': '/elsewhere', 'heading': ['x', 'y'], 'html': '<p>wrong path</p>'},
         {'view': 'saving', 'path': '/about/saving', 'heading': ['Save your work.'], 'html': '<p>bad heading</p>'}]


class AboutPages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_only_valid_about_views_are_written_with_the_apps_heading(self):
        self.assertEqual(bf.write_about_pages({'about': ABOUT}, self.tmp, shell=SHELL), ['about/method'])
        self.assertEqual([p.name for p in (self.tmp / 'about').iterdir()], ['method.html'])
        page = (self.tmp / 'about' / 'method.html').read_text('utf-8')
        self.assertIn('data-static-view="about:method"', page)
        self.assertIn('<link rel="canonical" href="https://billatlas.org/about/method">', page)
        self.assertIn('<title>How the atlas works · Texas Bill Atlas</title>', page)
        self.assertIn('<!--heading--><h1 id="page-title">How the atlas works.</h1><p id="page-subtitle">Signals &amp; '
                      'uncertainty.</p><!--/heading-->', page)
        self.assertNotIn('class="page-heading" hidden', page)
        self.assertIn('<!--content-->\n<div class="method-grid"><p>Text</p></div>\n<!--/content-->', page)

    def test_missing_input_keeps_pages_and_a_dropped_view_is_removed(self):
        bf.write_about_pages({'about': ABOUT}, self.tmp, shell=SHELL)
        for data, shell in ((None, SHELL), ({'about': ABOUT}, None), ({'about': []}, SHELL)):
            self.assertEqual(bf.write_about_pages(data, self.tmp, shell=shell), [])
        self.assertTrue((self.tmp / 'about' / 'method.html').exists())
        (self.tmp / 'about' / 'data.html').write_text('old', 'utf-8')
        bf.write_about_pages({'about': ABOUT}, self.tmp, shell=SHELL)
        self.assertFalse((self.tmp / 'about' / 'data.html').exists())


VIEWS = [{'view': 'home', 'path': '/', 'heading': ['This session, at a glance.', 'What changed.'], 'html': '<div class="home-top">Home</div>'},
         {'view': 'today', 'path': '/today', 'heading': ['Today at the Lege.', 'Bills with a recorded action that day.'],
          'description': 'Every Texas bill with a recorded action today.', 'html': '<div class="section-head">Today</div>'},
         {'view': 'today', 'path': '/elsewhere', 'heading': ['x', 'y'], 'html': '<p>wrong path</p>'},
         {'view': 'explorer', 'path': '/explorer', 'heading': ['x', 'y'], 'html': '<p>not a static view</p>'}]


class HomeAndToday(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_home_keeps_the_shells_own_head(self):
        self.assertEqual(bf.write_view_pages({'views': VIEWS}, self.tmp, shell=SHELL), ['today'])
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ['home.html', 'today.html'])
        home = (self.tmp / 'home.html').read_text('utf-8')
        self.assertIn(bf.pages.slot_text(SHELL, 'head'), home)
        self.assertIn('<link rel="canonical" href="https://billatlas.org/">', home)
        self.assertIn('data-static-view="page:home"', home)
        self.assertIn('<h1 id="page-title">This session, at a glance.</h1>', home)
        self.assertIn('<div class="home-top">Home</div>', home)

    def test_today_has_its_own_head(self):
        bf.write_view_pages({'views': VIEWS}, self.tmp, shell=SHELL)
        today = (self.tmp / 'today.html').read_text('utf-8')
        self.assertIn('<link rel="canonical" href="https://billatlas.org/today">', today)
        self.assertIn('<title>Today at the Lege · Texas Bill Atlas</title>', today)
        self.assertIn('data-static-view="page:today"', today)
        self.assertEqual(today.count('rel="canonical"'), 1)

    def test_nothing_without_the_shell_or_the_file(self):
        self.assertEqual(bf.write_view_pages({'views': VIEWS}, self.tmp, shell=None), [])
        self.assertEqual(bf.write_view_pages(None, self.tmp, shell=SHELL), [])
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_checker_addresses(self):
        import check_pages as cp
        root = Path('/share')
        self.assertEqual(cp.fixture_address(root / 'home.html', root, cp.SITE), 'https://billatlas.org/')
        self.assertEqual(cp.fixture_address(root / 'today.html', root, cp.SITE), 'https://billatlas.org/today')
        self.assertEqual(cp.fixture_address(root / 'about/method.html', root, cp.SITE), 'https://billatlas.org/about/method')


class AgentListsFeedTheDataRun(unittest.TestCase):
    def test_agent_export_builds_pages_for_every_topic(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        script = ("import {buildPages} from './scripts/build_agent.mjs';import {readFileSync} from 'node:fs';"
                  "const r=p=>JSON.parse(readFileSync('tests/e2e/fixtures/live/'+p,'utf8'));"
                  "process.stdout.write(buildPages({snapshot:r('bills.json'),tags:r('luna/tags.json'),"
                  "roster:r('members.json'),minBills:1}).get('data/pages.json'));")
        done = subprocess.run([node, '--input-type=module', '-e', script], cwd=ROOT, capture_output=True, text=True,
                              encoding='utf-8', check=True)
        data = json.loads(done.stdout)
        snapshot = json.loads((ROOT / 'tests/e2e/fixtures/live/bills.json').read_text('utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            paths = bf.write_group_pages(data, snapshot, Path(tmp), shell=SHELL)
        self.assertEqual(len([p for p in paths if p.startswith('topic/')]), 24)
        self.assertGreater(len([p for p in paths if p.startswith('agency/')]), 10)
        self.assertIn('topic/energy-and-utilities', paths)


if __name__ == '__main__':
    unittest.main()
