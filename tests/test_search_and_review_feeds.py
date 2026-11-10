"""Agent search (search_bills + the sync service route) and review items in per-bill and watchlist feeds."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_feeds
import search_bills
import sync_service as svc


def record(bill_id, title, **extra):
    base = {'id': bill_id, 'number': f"{bill_id[:2]} {bill_id[2:]}", 'title': title, 'caption': title, 'chamber': 'House',
            'status': 'Filed', 'filed_at': '2026-11-09', 'topics': [], 'agencies': [], 'impacts': [], 'affected_groups': [],
            'locations': [], 'actions': ['Filed'], 'people': {'authors': [{'name': 'Cole', 'full_name': 'Sheryl Cole'}]},
            'authorship_party': {'label': 'Democratic author'}, 'full_text_review': None,
            'last_action': {'category': 'Filed', 'date': '2026-11-09'}}
    return {**base, **extra}


AGENT_DATA = {'format': 'texas-bill-atlas-agent-v1', 'bill_data_as_of': '2026-11-10T18:00:00Z', 'tags_as_of': None,
              'coverage': {'bills': 4, 'full_text_reviewed': 1}, 'bills': [
    record('HB10', 'Relating to the sale of firearms at gun shows.', topics=['Public safety']),
    record('HB11', 'Relating to groundwater conservation districts.', topics=['Environment & water'],
           agencies=[{'id': 'twdb', 'name': 'Texas Water Development Board'}],
           full_text_review={'summary': 'Protects the Edwards aquifer and surface water rights.'},
           filed_at='2026-11-10', last_action={'category': 'Filed', 'date': '2026-11-10'}),
    record('SB3', 'Relating to data centers and electric reliability.', chamber='Senate',
           agencies=[{'id': 'puc', 'name': 'Public Utility Commission of Texas'}],
           people={'authors': [{'name': 'Hughes', 'full_name': 'Bryan Hughes'}]},
           authorship_party={'label': 'Republican author'}),
    record('HB12', 'Relating to school vouchers.', locations=[{'name': 'Harris County'}]),
]}


def index(data=AGENT_DATA):
    ix = search_bills.Index(Path('unused'))
    ix.load(data)
    return ix


def ids(query):
    found = search_bills.search(index(), search_bills.parse_params(query))
    return [r['id'] for *_, r, _ in found['results']], found


class SearchTests(unittest.TestCase):
    def test_word_forms_synonyms_and_summary_text(self):
        self.assertEqual(ids('q=firearm')[0], ['HB10'])          # "firearms" in the caption.
        self.assertEqual(ids('q=guns')[0], ['HB10'])             # Synonym plus plural.
        self.assertEqual(ids('q=aquifer')[0], ['HB11'])          # Only in the full-text summary.
        self.assertEqual(ids('q=%22water+rights%22')[0], ['HB11'])
        self.assertEqual(ids('q=%22rights+water%22')[0], [])     # A phrase keeps its order.

    def test_synonym_groups_work_in_both_directions(self):
        data = {**AGENT_DATA, 'bills': AGENT_DATA['bills'] + [
            record('HB20', 'Relating to rifle ranges.'),
            record('HB21', 'Relating to education savings accounts for students.')]}
        find = lambda q: sorted(r['id'] for *_, r, _ in search_bills.search(index(data), search_bills.parse_params(q))['results'])
        self.assertEqual(find('q=firearm'), find('q=gun'))
        self.assertEqual(find('q=firearm'), ['HB10', 'HB20'])
        self.assertEqual(find('q=vouchers'), ['HB12', 'HB21'])
        self.assertEqual(find('q=%22school+choice%22'), ['HB12', 'HB21'])
        self.assertEqual(find('q=%22education+savings+account%22'), ['HB12', 'HB21'])

    def test_or_cannabis_group_and_top_tier_fallback(self):
        data = {**AGENT_DATA, 'bills': AGENT_DATA['bills'] + [
            record('HB40', 'Relating to the regulation of hemp products.'),
            record('HB41', 'Relating to THC limits.'),
            record('HB42', 'Relating to property tax relief for homesteads.', chamber='Senate'),
            record('HB43', 'Relating to property tax appraisal.', chamber='Senate')]}
        find = lambda q: search_bills.search(index(data), search_bills.parse_params(q))
        self.assertEqual(sorted(r['id'] for *_, r, _ in find('q=thc+hemp+marijuana')['results']), ['HB40', 'HB41'])
        self.assertEqual(sorted(r['id'] for *_, r, _ in find('q=groundwater+OR+firearm')['results']), ['HB10', 'HB11'])
        self.assertEqual(find('q=groundwater+OR+firearm')['terms'], ['groundwater or firearm'])
        found = find('q=property+tax+homestead+zebra&chamber=senate')
        self.assertEqual((found['mode'], [r['id'] for *_, r, _ in found['results']]), ('any', ['HB42']))  # Top tier only.
        self.assertEqual([t['total'] for t in found['per_term']], [2, 2, 1, 0])
        text = search_bills.as_markdown(found, search_bills.parse_params('q=property+tax+homestead+zebra&chamber=senate'))
        self.assertIn('Each word on its own', text)
        self.assertIn('searched by caption', text)

    def test_member_did_you_mean_and_exact_agency_ids(self):
        data = {**AGENT_DATA, 'bills': AGENT_DATA['bills'] + [
            record('HB50', 'Relating to schools.', agencies=[{'id': 'tea', 'name': 'Texas Education Agency'}],
                   people={'authors': [{'name': 'Johnson', 'full_name': 'Ann Johnson', 'chamber': 'house', 'district': 134}]}),
            record('HB51', 'Relating to pensions.', agencies=[{'id': 'trs', 'name': 'Teacher Retirement System of Texas'}])]}
        found = search_bills.search(index(data), search_bills.parse_params('q=jonson'))
        self.assertEqual(found['members'], ['Ann Johnson (house district 134)'])
        self.assertIn('Did you mean a member?', search_bills.as_markdown(found, search_bills.parse_params('q=jonson')))
        found = search_bills.search(index(data), search_bills.parse_params('agency=tea'))
        self.assertEqual([r['id'] for *_, r, _ in found['results']], ['HB50'])
        found = search_bills.search(index(data), search_bills.parse_params('agency=teacher+retirement'))
        self.assertEqual([r['id'] for *_, r, _ in found['results']], ['HB51'])

    def test_location_filter(self):
        self.assertEqual(ids('location=harris')[0], ['HB12'])
        self.assertEqual(ids('q=school&location=dallas')[0], [])
        data = {**AGENT_DATA, 'bills': AGENT_DATA['bills'] + [record('HB30', 'Relating to flood control in Harris County.')]}
        found = search_bills.search(index(data), search_bills.parse_params('location=harris+county'))
        self.assertEqual(sorted(r['id'] for *_, r, _ in found['results']), ['HB12', 'HB30'])  # Review location or caption.
        found = search_bills.search(index(data), search_bills.parse_params('location=harr'))
        self.assertEqual(found['total'], 0)  # Whole words only.
        found = search_bills.search(index(), search_bills.parse_params('location=harris'))
        self.assertEqual(search_bills.as_json(found, search_bills.parse_params('location=harris'))['results'][0]['locations'],
                         ['Harris County'])

    def test_members_locations_and_bill_numbers(self):
        self.assertEqual(ids('q=hughes')[0], ['SB3'])
        self.assertEqual(ids('q=harris+county')[0], ['HB12'])
        found_ids, found = ids('q=HB+11+and+sb99')
        self.assertEqual(found_ids, ['HB11'])
        self.assertEqual(found['missing_ids'], ['SB99'])
        text = search_bills.as_markdown(found, search_bills.parse_params('q=HB+11+and+sb99'))
        self.assertIn('Not in the current data: SB99', text)

    def test_every_word_must_match_unless_none_does(self):
        self.assertEqual(ids('q=data+electric')[0], ['SB3'])
        both, found = ids('q=firearm+groundwater')
        self.assertEqual((found['mode'], set(both)), ('any', {'HB10', 'HB11'}))
        self.assertIn('No bill matches every word', search_bills.as_markdown(found, search_bills.parse_params('q=firearm+groundwater')))

    def test_filters_alone_and_with_words(self):
        self.assertEqual(ids('filed_from=2026-11-10')[0], ['HB11'])
        self.assertEqual(ids('q=data&agency=puc')[0], ['SB3'])
        self.assertEqual(ids('q=data&agency=twdb')[0], [])
        self.assertEqual(ids('chamber=senate')[0], ['SB3'])
        self.assertEqual(ids('party=republican')[0], ['SB3'])
        self.assertEqual(ids('reviewed=yes')[0], ['HB11'])
        self.assertEqual(ids('topic=water')[0], ['HB11'])

    def test_no_match_says_what_was_searched_and_suggests(self):
        found_ids, found = ids('q=groundwatr')
        self.assertEqual(found_ids, [])
        self.assertIn('groundwater', found['suggestions'])
        text = search_bills.as_markdown(found, search_bills.parse_params('q=groundwatr'))
        self.assertIn('0 bills matched', text)
        self.assertIn('only 1 of 4 bills have a full-text review', text)

    def test_paging_and_bad_input(self):
        many = {**AGENT_DATA, 'bills': [record(f'HB{i}', f'Relating to roads {i}.') for i in range(1, 121)]}
        params = search_bills.parse_params('q=roads&limit=50&offset=100')
        found = search_bills.search(index(many), params)
        self.assertEqual((found['total'], len(found['results'])), (120, 20))
        self.assertIsNone(search_bills.as_json(found, params)['next'])
        first = search_bills.search(index(many), search_bills.parse_params('q=roads'))
        self.assertIn('offset=50', search_bills.as_json(first, search_bills.parse_params('q=roads'))['next'])
        for bad in ('q=' + 'x' * 201, 'filed_from=yesterday', 'limit=lots'):
            with self.assertRaises(search_bills.BadQuery):
                search_bills.parse_params(bad)


class SearchRouteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        (base / 'bills.json').write_text('{"bills": []}', 'utf-8')
        self.data = base / 'agent.json'
        store = svc.Store(base / 'sync.db'); self.addCleanup(store.close)
        self.app = svc.App(store, svc.Snapshot(base / 'bills.json'), search=search_bills.Index(self.data))

    def get(self, path, **headers):
        try:
            return self.app.handle('GET', path, headers, None, '203.0.113.9')
        except svc.Rejected as error:
            return error.status, {}, error.message.encode()

    def test_markdown_json_usage_and_unavailable(self):
        self.assertEqual(self.get('/search?q=gun')[0], 503)  # Data not built yet: say so.
        self.data.write_text(json.dumps(AGENT_DATA), 'utf-8')
        status, headers, body = self.get('/search?q=gun')
        self.assertEqual((status, headers['Content-Type']), (200, 'text/markdown; charset=utf-8'))
        self.assertIn('HB10', body.decode())
        status, headers, body = self.get('/search.json?q=gun')
        self.assertEqual(json.loads(body)['results'][0]['id'], 'HB10')
        self.assertEqual(json.loads(self.get('/search?q=gun&format=json')[2])['total'], 1)
        self.assertIn('# Search Texas Bill Atlas', self.get('/search')[2].decode())
        self.assertEqual(self.get('/search?filed_from=bad')[0], 400)
        self.assertEqual(self.app.handle('GET', '/api/search?q=gun', {}, None, '203.0.113.9')[0], 200)
        with self.assertRaises(svc.Rejected):
            self.app.handle('POST', '/search', {}, b'', '203.0.113.9')

    def test_search_is_rate_limited_per_client(self):
        self.data.write_text(json.dumps(AGENT_DATA), 'utf-8')
        self.app.limiter.limits = {**svc.LIMITS, 'search': (2, 3600)}
        self.assertEqual([self.get('/search?q=gun')[0] for _ in range(3)], [200, 200, 429])


TAGS = {'format': 'texas-bill-luna-tags-v1', 'bills': {
    'HB5': {'reviewed_at': '2026-11-10T19:02:11Z', 'text_version': 'Introduced', 'summary': 'Changes groundwater rules.',
            'policy_tags': [{'tag': 'Water'}]}}}
BILL = {'id': 'HB5', 'caption': 'Relating to water.', 'actions': ['Filed'], 'action_dates': ['2026-11-09']}


class ReviewFeedTests(unittest.TestCase):
    def test_published_review_is_a_dated_feed_item(self):
        items = ET.fromstring(build_feeds.bill_feed(BILL, review=TAGS['bills']['HB5'])).findall('./channel/item')
        self.assertEqual([i.findtext('title') for i in items],
                         ['HB5: Full-text review published (Introduced text)', 'HB5: Filed'])
        self.assertIn('Changes groundwater rules. Topics: Water.', items[0].findtext('description'))
        self.assertIn('10 Nov 2026', items[0].findtext('pubDate'))

    def test_re_review_is_a_new_item_and_same_review_is_stable(self):
        first = build_feeds.review_items(BILL, TAGS['bills']['HB5'])[0]['guid']
        self.assertEqual(first, build_feeds.review_items(BILL, dict(TAGS['bills']['HB5']))[0]['guid'])
        again = build_feeds.review_items(BILL, {**TAGS['bills']['HB5'], 'reviewed_at': '2026-11-12T08:00:00Z'})[0]['guid']
        self.assertNotEqual(first, again)

    def test_write_feeds_picks_up_a_new_review_and_bad_tags_are_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            out, tags = base / 'feeds', base / 'tags.json'
            snap = {'bills': [BILL]}
            self.assertEqual(build_feeds.write_feeds(snap, out, reviews=build_feeds.load_reviews(tags)), (1, 0))
            tags.write_text(json.dumps(TAGS), 'utf-8')
            self.assertEqual(build_feeds.write_feeds(snap, out, reviews=build_feeds.load_reviews(tags)), (1, 0))
            self.assertIn('Full-text review published', (out / 'HB5.xml').read_text('utf-8'))
            tags.write_text('{"format": "other"}', 'utf-8')
            self.assertEqual(build_feeds.load_reviews(tags), {})

    def test_watchlist_feed_includes_reviews_as_they_publish(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        (base / 'bills.json').write_text(json.dumps({'bills': [BILL]}), 'utf-8')
        tags = base / 'tags.json'
        store = svc.Store(base / 'sync.db'); self.addCleanup(store.close)
        app = svc.App(store, svc.Snapshot(base / 'bills.json'), reviews=svc.Reviews(tags))
        made = json.loads(app.handle('POST', '/api/sync', {'Content-Type': 'application/json'},
                                     json.dumps({'data': {'watch': ['HB5']}}).encode(), '203.0.113.9')[2])
        feed = lambda: [i.findtext('title') for i in ET.fromstring(app.handle(
            'GET', f"/api/sync/feed/{made['view_key']}.xml", {}, None, '203.0.113.9')[2]).findall('./channel/item')]
        self.assertEqual(feed(), ['HB5: Filed'])
        tags.write_text(json.dumps(TAGS), 'utf-8')
        self.assertEqual(feed(), ['HB5: Full-text review published (Introduced text)', 'HB5: Filed'])


if __name__ == '__main__':
    unittest.main()
