"""The crawl checker's rules (SEO chunk 1), and fixture mode over share pages built from the golden capture."""
from pathlib import Path
import io
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_pages as cp  # noqa: E402

URL = 'https://billatlas.org/bill/HB1'


def page(title='HB 1: Relating to x. · Texas Bill Atlas', description='Relating to x.', canonical=URL,
         robots=None, body='<main><h1>HB 1</h1><p>Relating to x.</p></main>'):
    head = [f'<title>{title}</title>' if title is not None else '',
            f'<meta name="description" content="{description}">' if description is not None else '',
            f'<link rel="canonical" href="{canonical}">' if canonical is not None else '',
            f'<meta name="robots" content="{robots}">' if robots else '',
            '<meta property="og:url" content="https://billatlas.org/bill/HB1?c=abc">',
            '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Legislation"}</script>']
    return f'<!doctype html><html><head>{"".join(head)}</head><body><nav>Menu</nav>{body}<script>var x=1</script></body></html>'


class Rules(unittest.TestCase):
    def test_a_good_page_passes_and_reports_its_facts(self):
        facts = cp.inspect(page(), URL)
        self.assertEqual(facts['failures'], [])
        self.assertEqual(facts['title'], 'HB 1: Relating to x. · Texas Bill Atlas')
        self.assertEqual(facts['description'], 'Relating to x.')
        self.assertEqual(facts['canonical'], URL)
        self.assertEqual(facts['og_url'], 'https://billatlas.org/bill/HB1?c=abc')
        self.assertEqual(facts['jsonld'], ['Legislation'])
        self.assertEqual(facts['text_length'], len('HB 1 Relating to x.'))  # Inside <main>, no nav, no script.

    def test_missing_title_and_description_fail(self):
        self.assertIn('no title', cp.inspect(page(title=None), URL)['failures'])
        self.assertIn('no title', cp.inspect(page(title='  '), URL)['failures'])
        self.assertIn('no description', cp.inspect(page(description=None), URL)['failures'])
        self.assertIn('no description', cp.inspect(page(description=' '), URL)['failures'])

    def test_fragment_canonical_fails(self):
        failures = cp.inspect(page(canonical='https://billatlas.org/#chapter?law=PE&ch=46'), URL)['failures']
        self.assertEqual(failures, ['fragment canonical https://billatlas.org/#chapter?law=PE&ch=46'])

    def test_canonical_elsewhere_fails_but_query_and_case_do_not(self):
        self.assertEqual(cp.inspect(page(canonical='https://billatlas.org/'), URL)['failures'],
                         ['canonical is https://billatlas.org/, not this address'])
        self.assertEqual(cp.inspect(page(), URL + '?c=abc')['failures'], [])
        self.assertEqual(cp.inspect(page(canonical='HTTPS://BillAtlas.org/bill/HB1'), URL)['failures'], [])
        self.assertEqual(cp.inspect(page(canonical='/bill/HB1'), URL)['failures'], [])  # Relative, resolved.

    def test_noindex_or_error_pages_are_not_held_to_the_rules(self):
        self.assertEqual(cp.inspect(page(title=None, robots='noindex'), URL)['failures'], [])
        self.assertEqual(cp.inspect(page(title=None), URL, robots_header='noindex')['failures'], [])
        self.assertEqual(cp.inspect(page(title=None), URL, status=404)['failures'], [])

    def test_text_length_falls_back_to_body_without_main(self):
        facts = cp.inspect(page(body='<h1>HB 1</h1>'), URL)
        self.assertEqual(facts['text_length'], len('Menu HB 1'))

    def test_different_html_per_user_agent_fails_whitespace_and_nonces_do_not(self):
        same = {'desktop': cp.inspect(page(), URL), 'googlebot': cp.inspect(page().replace('><', '>\n  <'), URL),
                'phone': cp.inspect(page().replace('<script>', '<script nonce="r4nd0m">'), URL)}
        self.assertEqual(cp.compare_agents(same), [])
        split = {'desktop': cp.inspect(page(canonical='https://billatlas.org/'), URL), 'googlebot': cp.inspect(page(), URL)}
        self.assertEqual(cp.compare_agents(split), ['different HTML per user agent: desktop vs googlebot'])

    def test_jsonld_types_from_lists_graphs_and_bad_json(self):
        self.assertEqual(cp.ld_types(['[{"@type":"A"},{"@graph":[{"@type":["B","C"]}]}]', '{oops']),
                         ['A', 'B', 'C', '(invalid JSON-LD)'])


class Network(unittest.TestCase):
    def test_each_address_is_fetched_as_every_agent_throttled_and_live_files_skipped(self):
        seen, sleeps = [], []

        def getter(url, agent):
            seen.append((url, agent))
            # Crawlers get the section page, browsers the app shell: the /law/ split of 2026-11-19.
            bot = 'Googlebot' in agent or 'Discordbot' in agent
            return 200, url, page() if bot else page(canonical='https://billatlas.org/'), ''
        reports = cp.check_network(['/bill/HB1', '/live/bills.json'], cp.SITE, 1.0, getter, sleeps.append)
        self.assertEqual(len(reports), 1)
        self.assertEqual(len(seen), 4)
        self.assertTrue(all(cp.CHECKER in agent for _, agent in seen))
        self.assertEqual(sleeps, [1.0, 1.0, 1.0])
        failures = cp.all_failures(reports[0])
        self.assertIn('different HTML per user agent: desktop+phone vs googlebot+discordbot', failures)
        self.assertIn('desktop: canonical is https://billatlas.org/, not this address', failures)

    def test_a_failed_fetch_is_a_failure_not_a_crash(self):
        def getter(url, agent):
            raise OSError('timed out')
        report = cp.check_network(['/bill/HB1'], cp.SITE, 0, getter, lambda s: None)[0]
        self.assertIn('desktop: fetch failed: timed out', cp.all_failures(report))

    def test_sitemap_sample_spreads_and_skips_data_files(self):
        xml = ''.join(f'<url><loc>https://billatlas.org/bill/HB{i}</loc></url>' for i in range(10))
        xml += '<url><loc>https://billatlas.org/live/bills.json</loc></url>'
        self.assertEqual(cp.sitemap_sample(xml, 2), ['https://billatlas.org/bill/HB2', 'https://billatlas.org/bill/HB7'])
        self.assertEqual(cp.sitemap_sample(xml, 0), [])


class Fixtures(unittest.TestCase):
    def test_addresses_follow_the_gateway(self):
        root = Path('/share')
        self.assertEqual(cp.fixture_address(root / 'HB1.html', root, cp.SITE), 'https://billatlas.org/bill/HB1')
        self.assertEqual(cp.fixture_address(root / 'law/PE/46.06.html', root, cp.SITE), 'https://billatlas.org/law/PE/46.06')
        self.assertIsNone(cp.fixture_address(root / 'law/PE/46.html', root, cp.SITE))  # Chapter page, not served yet.
        self.assertIsNone(cp.fixture_address(root / 'law/PE/46A.html', root, cp.SITE))

    def test_generated_share_pages_pass(self):
        """The data run's bill and law pages from the golden capture, as production builds them."""
        capture = ROOT / 'tests' / 'e2e' / 'fixtures' / 'live'
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # A private copy: the data run writes some outputs (sitemap, og, brackets) beside the snapshot.
            live = tmp / 'live'
            live.mkdir()
            for name in ('bills.json', 'members.json', 'luna', 'text'):
                source = capture / name
                (shutil.copytree if source.is_dir() else shutil.copyfile)(source, live / name)
            shell = tmp / 'shell.html'
            subprocess.run([sys.executable, '-c', 'import sys,types;sys.path.insert(0,"scripts");'
                            'sys.modules.setdefault("fcntl",types.ModuleType("fcntl"));import deploy_static as d;'
                            'from pathlib import Path;sys.stdout.buffer.write(d.shell_page(Path("index.html").read_bytes()))'],
                           cwd=ROOT, check=True, stdout=shell.open('wb'))
            # Inside the deployed shell; law pages are standalone either way.
            for name, extra in (('shell', ['--shell', str(shell)]),):
                share = tmp / name
                subprocess.run([sys.executable, 'scripts/build_feeds.py', '--snapshot', str(live / 'bills.json'),
                                '--out', str(tmp / f'feeds-{name}'), '--share', str(share), '--statutes',
                                str(tmp / f'statutes-{name}'), '--today', '2026-11-19', '--no-indexnow', *extra],
                               cwd=ROOT, check=True, capture_output=True)
                reports, skipped = cp.check_fixtures(share, cp.SITE)
                with self.subTest(name):
                    kinds = {r['address'].split('/')[3] for r in reports}
                    self.assertEqual(kinds, {'bill', 'law'})
                    self.assertGreater(len(reports), 100)
                    failing = [(r['address'], cp.all_failures(r)) for r in reports if cp.all_failures(r)]
                    self.assertEqual(failing, [])
                    self.assertTrue(all(cp.CHAPTER_FILE.fullmatch(Path(s).stem) for s in skipped))

    def test_main_exits_nonzero_on_a_failing_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'HB1.html').write_text(page(), encoding='utf-8')
            self.assertEqual(cp.main(['--fixtures', tmp]), 0)
            Path(tmp, 'HB2.html').write_text(page(), encoding='utf-8')  # Canonical says HB1.
            out = io.StringIO()
            sys.stdout, saved = out, sys.stdout
            try:
                code = cp.main(['--fixtures', tmp])
            finally:
                sys.stdout = saved
            self.assertEqual(code, 1)
            self.assertIn('FAIL https://billatlas.org/bill/HB2', out.getvalue())
            self.assertNotIn('https://billatlas.org/bill/HB1\n', out.getvalue())  # Fixture mode prints failures only.


if __name__ == '__main__':
    unittest.main()
