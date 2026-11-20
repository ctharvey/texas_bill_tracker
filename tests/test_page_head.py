"""Head tags and JSON-LD builders for the static pages (SEO chunk 6)."""
from pathlib import Path
import json
import re
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))  # Linux-only lock; unused here.
import page_head as ph  # noqa: E402
import build_feeds as bf  # noqa: E402
import deploy_static as deploy  # noqa: E402
import html  # noqa: E402

FIXTURE = json.loads((ROOT / 'tests' / 'fixtures' / 'page_heads.json').read_text(encoding='utf-8'))

SITE = 'https://billatlas.org/'


def blocks(html):
    return [json.loads(t) for t in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


class Head(unittest.TestCase):
    def test_head_has_title_canonical_meta_and_jsonld_in_order(self):
        html = ph.head_html(title='HB 1: Water', description='Relating to water.', url=SITE + 'bill/HB1',
                            image=SITE + 'social-card.png', og_url=SITE + 'bill/HB1?c=abc',
                            links=('<link rel="alternate" href="x">',), jsonld=({'@type': 'Legislation'},))
        self.assertTrue(html.startswith('\n<title>HB 1: Water · Texas Bill Atlas</title>\n'
                                        '<link rel="canonical" href="https://billatlas.org/bill/HB1">\n'
                                        '<link rel="alternate" href="x">\n' + ph.SHELL_ICONS))
        self.assertIn('<meta property="og:url" content="https://billatlas.org/bill/HB1?c=abc">', html)
        self.assertIn('<meta name="twitter:title" content="HB 1: Water">', html)
        self.assertIn('<meta name="description" content="Relating to water.">', html)
        self.assertEqual(blocks(html), [{'@type': 'Legislation'}])
        self.assertLess(html.index('name="description"'), html.index('application/ld+json'))

    def test_og_url_defaults_to_the_canonical_and_icons_can_be_left_out(self):
        html = ph.head_html(title='T', description='D', url=SITE + 'today', image='i', icons=False)
        self.assertIn('<meta property="og:url" content="https://billatlas.org/today">', html)
        self.assertNotIn('favicon', html)

    def test_attributes_and_title_are_escaped_apostrophes_kept(self):
        html = ph.head_html(title='A "q" <b> & it\'s', description='"d"', url=SITE, image='i')
        self.assertIn('<title>A "q" &lt;b&gt; &amp; it\'s · Texas Bill Atlas</title>', html)
        self.assertIn('content="A &quot;q&quot; &lt;b&gt; &amp; it\'s"', html)

    def test_jsonld_cannot_close_its_script_and_holds_no_raw_ampersand(self):
        html = ph.jsonld_script({'name': '</script><script>x()</script>', 'url': 'https://a.example/?a=1&b=2'})
        self.assertEqual(html.count('</script>'), 1)
        self.assertNotIn('&', html)
        self.assertEqual(blocks(html), [{'name': '</script><script>x()</script>', 'url': 'https://a.example/?a=1&b=2'}])


class StructuredData(unittest.TestCase):
    def test_breadcrumbs_start_at_home_and_end_at_the_page(self):
        data = ph.breadcrumbs(SITE, [('Agencies', SITE + 'agencies'), ('TEA', SITE + 'agency/tea')])
        self.assertEqual(data['@type'], 'BreadcrumbList')
        self.assertEqual([(i['position'], i['name'], i['item']) for i in data['itemListElement']],
                         [(1, 'Home', SITE), (2, 'Agencies', SITE + 'agencies'), (3, 'TEA', SITE + 'agency/tea')])

    def test_law_section_and_chapter(self):
        section = ph.law_section(name='Penal Code § 46.06: Transfer', label='Penal Code § 46.06',
                                 url=SITE + 'law/PE/46.06', official='https://statutes.capitol.texas.gov/x',
                                 chapter_name='Penal Code Chapter 46', chapter_url=SITE + 'law/PE/46')
        self.assertEqual(section['@type'], 'Legislation')
        self.assertEqual(section['legislationJurisdiction'], {'@type': 'AdministrativeArea', 'name': 'Texas'})
        self.assertEqual(section['isPartOf'], {'@type': 'Legislation', 'name': 'Penal Code Chapter 46',
                                               'url': SITE + 'law/PE/46'})
        chapter = ph.law_chapter(name='C', label='C', url=SITE + 'law/PE/46', official='o',
                                 sections=[('Sec. 46.06', SITE + 'law/PE/46.06')])
        self.assertEqual(chapter['hasPart'], [{'@type': 'Legislation', 'name': 'Sec. 46.06', 'url': SITE + 'law/PE/46.06'}])
        self.assertNotIn('hasPart', ph.law_chapter(name='C', label='C', url='u', official='o', sections=[]))

    def test_member_profile_states_only_what_is_given(self):
        full = ph.member_profile(name='Daniel Alders', url=SITE + 'member/A1/daniel-alders', house=True, district='6',
                                 party='Republican', same_as=['https://capitol.texas.gov/x'])
        person = full['mainEntity']
        self.assertEqual(full['@type'], 'ProfilePage')
        self.assertEqual(person['jobTitle'], 'State Representative')
        self.assertEqual(person['memberOf']['name'], 'Texas House of Representatives')
        self.assertEqual(person['workLocation']['name'], 'Texas House District 6')
        self.assertEqual(person['affiliation'], {'@type': 'Organization', 'name': 'Republican'})
        self.assertEqual(person['sameAs'], ['https://capitol.texas.gov/x'])
        bare = ph.member_profile(name='X', url='u', house=False, district='', party=None, same_as=[])['mainEntity']
        self.assertEqual(bare['jobTitle'], 'State Senator')
        for key in ('workLocation', 'affiliation', 'sameAs'):
            self.assertNotIn(key, bare)

    def test_collection_lists_its_bills(self):
        data = ph.collection(name='Water: Texas bills', url=SITE + 'topic/water', description='d',
                             items=[SITE + 'bill/HB1', SITE + 'bill/HB2'])
        self.assertEqual(data['@type'], 'CollectionPage')
        self.assertEqual(data['mainEntity']['numberOfItems'], 2)
        self.assertEqual([i['url'] for i in data['mainEntity']['itemListElement']], [SITE + 'bill/HB1', SITE + 'bill/HB2'])
        empty = ph.collection(name='n', url='u', description='d', about={'@type': 'GovernmentOrganization', 'name': 'TEA'})
        self.assertNotIn('mainEntity', empty)
        self.assertEqual(empty['about']['name'], 'TEA')

    def test_website_search_goes_to_the_explorer(self):
        data = ph.website(SITE)
        self.assertEqual(data['potentialAction']['target']['urlTemplate'],
                         'https://billatlas.org/explorer?query={search_term_string}')
        self.assertEqual(data['potentialAction']['query-input'], 'required name=search_term_string')


class SharedFixture(unittest.TestCase):
    """The titles (and bill descriptions) the static pages get; tests/head.test.mjs checks the app against the same."""

    def built(self, c):
        k = c['kind']
        if k == 'bill':
            return bf.share_page({'id': c['id'], 'caption': c['caption']}, headline=c['headline'])
        shell = deploy.shell_page((ROOT / 'index.html').read_bytes()).decode()
        if k == 'member':
            return bf.member_page({'code': c['code'], 'chamber': c['chamber'], 'full_name': c['full_name'], 'district': '6'},
                                  [], shell)
        if k in ('topic', 'agency'):
            return bf.group_page(k, c['key'], c['name'], [], {}, shell)
        if k == 'law':
            return bf.law_page(f"{c['code']} {c['number']}", {'h': c['h'], 'b': [['HB1', 'a']]}, c['code_name'], None)
        return bf.law_chapter_page(f"{c['code']} {c['chapter']}", {'whole': [], 'sections': {}}, c['h'])

    def test_static_pages_match_the_fixture(self):
        for c in FIXTURE['cases']:
            with self.subTest(c):
                page = self.built(c)
                self.assertEqual(html.unescape(re.search(r'<title>(.*?)</title>', page).group(1)), c['expected']['title'])
                if 'description' in c['expected']:
                    found = re.search(r'<meta name="description" content="([^"]*)">', page).group(1)
                    self.assertEqual(html.unescape(found), c['expected']['description'])


if __name__ == '__main__':
    unittest.main()
