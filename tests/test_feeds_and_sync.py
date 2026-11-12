"""Per-bill feeds, dated actions, and the private sync service (keys, versions, limits, feeds)."""
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_feeds
import sync_service as svc
from sync_ftp import parse_bill_xml

BILL = {'id': 'HB5', 'caption': 'Relating to <water> & "rights".', 'last_action_date': '2027-02-10',
        'actions': ['Filed', 'Referred to Natural Resources'], 'action_dates': ['2026-11-09', '2027-02-10']}


class DatedActionTests(unittest.TestCase):
    def test_parser_keeps_a_date_per_action(self):
        xml = b'''<billhistory><caption>Relating to tax incentives for data centers.</caption>
          <actions><action><date>11/9/2026</date><description>Filed</description></action>
          <action><date>11/10/2026</date><description>Referred to committee</description></action></actions>
          </billhistory>'''
        bill = parse_bill_xml(xml, 'SB99.xml')
        self.assertEqual(bill['action_dates'], ['2026-11-09', '2026-11-10'])
        self.assertEqual(len(bill['action_dates']), len(bill['actions']))


class FeedTests(unittest.TestCase):
    def test_items_are_dated_newest_first_and_escaped(self):
        root = ET.fromstring(build_feeds.bill_feed(BILL))
        items = root.findall('./channel/item')
        self.assertEqual([i.findtext('title') for i in items], ['HB5: Referred to Natural Resources', 'HB5: Filed'])
        self.assertIn('10 Feb 2027', items[0].findtext('pubDate'))
        self.assertEqual(items[0].findtext('description'), 'Relating to <water> & "rights".')
        self.assertTrue(items[0].findtext('link').endswith('#all?bill=HB5'))

    def test_guid_survives_the_twelve_action_window_sliding(self):
        before = build_feeds.bill_items(BILL)
        later = {**BILL, 'actions': BILL['actions'][1:] + ['Scheduled for public hearing'],
                 'action_dates': BILL['action_dates'][1:] + ['2027-02-20']}
        shared = {i['guid'] for i in before} & {i['guid'] for i in build_feeds.bill_items(later)}
        self.assertEqual(len(shared), 1)  # "Referred" keeps its identity, so readers do not re-show it.

    def test_old_snapshots_without_action_dates_still_build(self):
        items = build_feeds.bill_items({k: v for k, v in BILL.items() if k != 'action_dates'})
        self.assertEqual([i['date'] for i in items], ['2027-02-10', None])
        ET.fromstring(build_feeds.render_rss('t', 'l', 'd', items))

    def test_write_feeds_only_rewrites_changes_and_skips_bad_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'feeds'
            snapshot = {'bills': [BILL, {'id': '../evil', 'actions': ['x']}, {'id': 'SB1', 'actions': []}]}
            self.assertEqual(build_feeds.write_feeds(snapshot, out), (2, 0))
            self.assertEqual(build_feeds.write_feeds(snapshot, out), (0, 2))
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['HB5.xml', 'SB1.xml'])


ROSTER = {
    'house|Smith': {'code': 'A1001', 'chamber': 'house', 'display_name': 'Smith', 'full_name': 'Ann Smith'},
    'senate|Smith': {'code': 'A2002', 'chamber': 'senate', 'display_name': 'Smith', 'full_name': 'Bo Smith'},
    'senate|Jones': {'code': 'A2003', 'chamber': 'senate', 'display_name': 'Jones'},
    'house|Odd': {'code': '../evil', 'chamber': 'house', 'display_name': 'Odd'},
}


class MemberFeedTests(unittest.TestCase):
    def test_roles_join_like_the_site_by_chamber(self):
        # Authors/coauthors serve in the bill's chamber, sponsors/cosponsors in the other: a same-name member
        # of the other chamber never matches.
        hb = {'id': 'HB9', 'authors': ['Smith'], 'coauthors': [], 'sponsors': 'Jones; Smith', 'cosponsors': []}
        sb = {'id': 'SB9', 'authors': ['Smith', 'Jones'], 'coauthors': [], 'sponsors': [], 'cosponsors': ['Smith']}
        self.assertEqual(build_feeds.member_roles(hb, ROSTER), {'A1001': 'Author', 'A2003': 'Sponsor', 'A2002': 'Sponsor'})
        self.assertEqual(build_feeds.member_roles(sb, ROSTER), {'A2002': 'Author', 'A2003': 'Author', 'A1001': 'Cosponsor'})

    def test_member_feed_lists_actions_with_the_role_and_links_the_member_page(self):
        root = ET.fromstring(build_feeds.member_feed(ROSTER['house|Smith'], [(BILL, 'Coauthor')]))
        self.assertEqual(root.findtext('./channel/title'), 'Rep. Ann Smith · Texas Bill Atlas')
        self.assertTrue(root.findtext('./channel/link').endswith('#member?code=A1001'))
        items = root.findall('./channel/item')
        self.assertEqual([i.findtext('title') for i in items], ['HB5: Referred to Natural Resources', 'HB5: Filed'])
        self.assertTrue(items[0].findtext('description').startswith('Rep. Ann Smith · Coauthor. Relating to'))
        self.assertEqual(items[0].findtext('guid'), build_feeds.bill_items(BILL)[0]['guid'])

    def test_write_member_feeds_covers_every_coded_member_and_skips_bad_codes(self):
        hb = {**BILL, 'authors': ['Smith']}
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'members'
            self.assertEqual(build_feeds.write_member_feeds({'bills': [hb]}, ROSTER, out), (3, 0))
            self.assertEqual(build_feeds.write_member_feeds({'bills': [hb]}, ROSTER, out), (0, 3))
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['A1001.xml', 'A2002.xml', 'A2003.xml'])
            self.assertEqual(len(ET.parse(out / 'A1001.xml').findall('./channel/item')), 2)
            self.assertEqual(ET.parse(out / 'A2002.xml').findall('./channel/item'), [])

    def test_missing_or_malformed_roster_means_no_member_feeds(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / 'members.json'
            bad.write_text('not json', 'utf-8')
            self.assertEqual(build_feeds.load_roster(bad), {})
            self.assertEqual(build_feeds.load_roster(Path(temp) / 'missing.json'), {})
            self.assertEqual(build_feeds.write_member_feeds({'bills': [BILL]}, {}, Path(temp) / 'm'), (0, 0))

    def test_real_roster_matches_the_member_page_join(self):
        roster = build_feeds.load_roster(ROOT / 'data' / 'members.json')
        member = next(m for m in roster.values() if m.get('chamber') == 'house' and m.get('code'))
        bills = [{'id': 'HB1', 'authors': [member['display_name']]}, {'id': 'SB1', 'sponsors': [member['display_name']]},
                 {'id': 'SB2', 'authors': [member['display_name']]}]
        self.assertEqual([build_feeds.member_roles(b, roster).get(member['code']) for b in bills], ['Author', 'Sponsor', None])


class Headers(dict):
    def get(self, key, default=None):
        return next((v for k, v in self.items() if k.lower() == key.lower()), default)


class SyncAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        (base / 'bills.json').write_text(json.dumps({'bills': [BILL, {**BILL, 'id': 'SB7', 'actions': ['Filed'],
                                                                          'action_dates': ['2026-11-12']}]}), 'utf-8')
        self.db = base / 'sync.db'
        self.now = [1_800_000_000.0]
        store = svc.Store(self.db); self.addCleanup(store.close)
        self.app = svc.App(store, svc.Snapshot(base / 'bills.json'), clock=lambda: self.now[0])

    def call(self, method, path='/api/sync', body=None, key=None, peer='203.0.113.5', **headers):
        h = Headers(headers)
        if body is not None:
            h['Content-Type'] = 'application/json'; body = json.dumps(body).encode()
        if key:
            h['X-Sync-Key'] = key
        try:
            status, _, payload = self.app.handle(method, path, h, body, peer)
        except svc.Rejected as error:
            return error.status, {'error': error.message, **error.extra}
        return status, json.loads(payload) if payload and payload[:1] == b'{' else payload

    def create(self, watch=('HB5',), **filters):
        status, made = self.call('POST', body={'data': {'watch': list(watch), 'filters': filters}})
        self.assertEqual(status, 201)
        return made

    def test_edit_and_view_keys_have_different_powers(self):
        made = self.create(topic='Water')
        status, edit = self.call('GET', key=made['edit_key'])
        self.assertEqual((status, edit['mode'], edit['view_key']), (200, 'edit', made['view_key']))
        status, view = self.call('GET', key=made['view_key'])
        self.assertEqual((status, view['mode'], view['data']['filters']), (200, 'view', {'topic': 'Water'}))
        self.assertNotIn('view_key', view)
        self.assertEqual(self.call('PUT', body={'version': 1, 'data': {'watch': []}}, key=made['view_key'])[0], 403)
        self.assertEqual(self.call('DELETE', key=made['view_key'])[0], 403)

    def test_database_holds_no_usable_keys(self):
        made = self.create()
        dump = self.db.read_bytes() + b''.join(Path(str(self.db) + s).read_bytes()
                                               for s in ('-wal',) if Path(str(self.db) + s).exists())
        self.assertNotIn(made['edit_key'].encode(), dump)
        self.assertNotIn(made['view_key'].encode(), dump)
        self.assertNotEqual(svc.view_key_for(made['view_key']), made['edit_key'])

    def test_stale_writer_gets_conflict_with_current_state(self):
        made = self.create()
        key = made['edit_key']
        self.assertEqual(self.call('PUT', body={'version': 1, 'data': {'watch': ['HB5', 'SB7']}}, key=key)[1]['version'], 2)
        status, conflict = self.call('PUT', body={'version': 1, 'data': {'watch': []}}, key=key)
        self.assertEqual((status, conflict['version'], conflict['data']['watch']), (409, 2, ['HB5', 'SB7']))
        self.assertEqual(self.call('GET', key=key)[1]['data']['watch'], ['HB5', 'SB7'])

    def test_follows_sync_but_older_clients_and_view_links_never_touch_them(self):
        status, made = self.call('POST', body={'data': {'watch': ['HB5'], 'follows': ['A1001', 'A1001', 'A2002']}})
        self.assertEqual((status, made['data']['follows']), (201, ['A1001', 'A2002']))
        key = made['edit_key']
        # An old cached page sends only the watchlist: the stored follows survive, and the reply carries them.
        status, saved = self.call('PUT', body={'version': 1, 'data': {'watch': ['HB5', 'SB7']}}, key=key)
        self.assertEqual((status, saved['data']['follows']), (200, ['A1001', 'A2002']))
        self.assertEqual(self.call('GET', key=key)[1]['data']['follows'], ['A1001', 'A2002'])
        # An empty list is a real "none", unlike an absent one.
        self.assertEqual(self.call('PUT', body={'version': 2, 'data': {'watch': ['HB5'], 'follows': []}}, key=key)[1]['data']['follows'], [])
        self.assertEqual(self.call('PUT', body={'version': 3, 'data': {'watch': ['HB5']}}, key=key)[1]['data']['follows'], [])
        # A conflict hands back the follows, so the losing device can replay onto them.
        self.call('PUT', body={'version': 4, 'data': {'watch': ['HB5'], 'follows': ['A2002']}}, key=key)
        status, conflict = self.call('PUT', body={'version': 1, 'data': {'watch': []}}, key=key)
        self.assertEqual((status, conflict['data']['follows']), (409, ['A2002']))
        # View-only links and the watchlist feed never reveal who the owner follows.
        status, view = self.call('GET', key=made['view_key'])
        self.assertEqual((status, set(view['data'])), (200, {'watch', 'filters'}))
        status, feed = self.call('GET', path=f"/api/sync/feed/{made['view_key']}.xml")
        self.assertEqual(status, 200)
        self.assertNotIn(b'A2002', feed)

    def test_saved_searches_sync_but_older_clients_and_view_links_never_touch_them(self):
        saved = [{'id': 'abcd1234', 'name': ' Taxes ', 'filters': {'topic': 'Taxes', 'onlyWatch': True}, 'seen': '2026-11-12'},
                 {'id': 'abcd1234', 'name': 'dupe', 'filters': {}, 'seen': None}]
        status, made = self.call('POST', body={'data': {'watch': [], 'follows': ['A1001'], 'searches': saved}})
        self.assertEqual((status, made['data']['searches']),
                         (201, [{'id': 'abcd1234', 'name': 'Taxes', 'filters': {'topic': 'Taxes', 'onlyWatch': True}, 'seen': '2026-11-12'}]))
        key = made['edit_key']
        # A page from before saved searches (bills and follows only), then one from before follows (bills only).
        self.call('PUT', body={'version': 1, 'data': {'watch': ['HB5'], 'follows': []}}, key=key)
        status, kept = self.call('PUT', body={'version': 2, 'data': {'watch': ['HB5']}}, key=key)
        self.assertEqual((status, [s['name'] for s in kept['data']['searches']], kept['data']['follows']), (200, ['Taxes'], []))
        self.assertEqual(self.call('PUT', body={'version': 3, 'data': {'watch': [], 'searches': []}}, key=key)[1]['data']['searches'], [])
        status, view = self.call('GET', key=made['view_key'])
        self.assertEqual((status, set(view['data'])), (200, {'watch', 'filters'}))

    def test_saved_searches_are_validated(self):
        made = self.create()
        good = {'id': 'abcd1234', 'name': 'x', 'filters': {}, 'seen': None}
        bad = ['x', [{**good, 'id': 'AB'}], [{**good, 'name': '  '}], [{**good, 'name': 'n' * 81}], [{**good, 'seen': 'today'}],
               [{**good, 'filters': {'evil': 'x'}}], [{**good, 'extra': 1}], [{**good, 'filters': {'query': 'q' * 200, 'topic': 't' * 200, 'agency': 'a' * 200}}],
               [{**good, 'id': f'abcd{i:04d}'} for i in range(21)]]
        for searches in bad:
            status, _ = self.call('PUT', body={'version': 1, 'data': {'watch': [], 'searches': searches}}, key=made['edit_key'])
            self.assertEqual(status, 400, str(searches)[:80])
        self.assertEqual(self.call('PUT', body={'version': 1, 'data': {'watch': [], 'searches': [good]}}, key=made['edit_key'])[0], 200)

    def test_largest_valid_profile_fits_the_gateway_limit(self):
        searches = [{'id': f'abcd{i:04d}', 'name': 'n' * 80, 'filters': {'query': 'q' * 200, 'topic': 't' * 150, 'agency': 'a' * 150},
                     'seen': '2026-11-12'} for i in range(svc.MAX_SEARCHES)]
        body = {'version': 1, 'data': {'watch': [f'HB{i}' for i in range(10000, 10000 + svc.MAX_BILLS)],
                                       'follows': [f'A{i}' for i in range(10000, 10000 + svc.MAX_FOLLOWS)], 'searches': searches}}
        self.assertLess(len(json.dumps(body).encode()), svc.MAX_BODY)
        self.assertEqual(self.call('PUT', body=body, key=self.create()['edit_key'])[0], 200)

    def test_follows_are_validated(self):
        made = self.create()
        for follows in ('A1001', ['../x'], ['a1001'], [7], ['A1'], [f'A{1000 + i}' for i in range(201)]):
            status, _ = self.call('PUT', body={'version': 1, 'data': {'watch': [], 'follows': follows}}, key=made['edit_key'])
            self.assertEqual(status, 400, follows)
        self.assertEqual(self.call('POST', body={'data': {'watch': [], 'follows': {'A1001': 1}}})[0], 400)

    def test_delete_then_unknown(self):
        made = self.create()
        self.assertEqual(self.call('DELETE', key=made['edit_key'])[0], 204)
        self.assertEqual(self.call('GET', key=made['edit_key'])[0], 404)
        self.assertEqual(self.call('GET', key=made['view_key'])[0], 404)

    def test_validation_rejects_bad_payloads(self):
        bad = [{'data': {'watch': ['HB5; DROP']}}, {'data': {'watch': [f'HB{i}' for i in range(1, 502)]}},
               {'data': {'filters': {'evil': 'x'}}}, {'data': {'filters': {'query': 'x' * 201}}}, {'data': []}]
        for body in bad:
            self.assertEqual(self.call('POST', body=body)[0], 400, body)
        with self.assertRaises(svc.Rejected) as caught:
            self.app.handle('POST', '/api/sync', Headers({'Content-Type': 'text/plain'}), b'{"data": {}}', 'x')
        self.assertEqual(caught.exception.status, 415)
        self.assertEqual(self.call('GET', key='short')[0], 400)

    def test_edit_key_is_never_accepted_in_a_url(self):
        made = self.create()
        self.assertEqual(self.call('GET', path='/api/sync/' + made['edit_key'])[0], 404)
        self.assertEqual(self.call('GET', path=f"/api/sync/feed/{made['edit_key']}.xml")[0], 404)

    def test_watchlist_feed_by_view_key(self):
        made = self.create(watch=('HB5', 'SB7'))
        status, xml = self.call('GET', path=f"/api/sync/feed/{made['view_key']}.xml")
        self.assertEqual(status, 200)
        titles = [i.findtext('title') for i in ET.fromstring(xml).findall('./channel/item')]
        self.assertEqual(titles, ['HB5: Referred to Natural Resources', 'SB7: Filed', 'HB5: Filed'])

    def test_create_rate_limit_is_per_client(self):
        for _ in range(10):
            self.create()
        status, body = self.call('POST', body={'data': {}})
        self.assertEqual(status, 429); self.assertGreater(body['retry_after'], 0)
        self.assertEqual(self.call('POST', body={'data': {}}, peer='198.51.100.1')[0], 201)
        self.now[0] += 3600
        self.assertEqual(self.call('POST', body={'data': {}})[0], 201)

    def test_ipv6_rate_limit_is_per_64(self):
        for i in range(10):
            self.assertEqual(self.call('POST', body={'data': {}}, peer=f'2001:db8:1:2::{i + 1:x}')[0], 201)
        self.assertEqual(self.call('POST', body={'data': {}}, peer='2001:db8:1:2:ffff:ffff:ffff:fffe')[0], 429)
        self.assertEqual(self.call('POST', body={'data': {}}, peer='2001:db8:1:3::1')[0], 201)

    def test_ipv4_mapped_address_shares_the_ipv4_bucket(self):
        for _ in range(10):
            self.create()  # peer 203.0.113.5
        self.assertEqual(self.call('POST', body={'data': {}}, peer='::ffff:203.0.113.5')[0], 429)
        self.assertEqual(self.call('POST', body={'data': {}}, peer='203.0.113.6')[0], 201)

    def test_forwarded_ipv6_visitor_is_limited_per_64(self):
        self.app.trust_proxy = True
        for i in range(10):
            self.assertEqual(self.call('POST', body={'data': {}}, peer='10.0.0.2',
                                       **{'X-Forwarded-For': f'2001:db8:9:9::{i + 1:x}'})[0], 201)
        self.assertEqual(self.call('POST', body={'data': {}}, peer='10.0.0.2',
                                   **{'X-Forwarded-For': '2001:db8:9:9:abcd::1'})[0], 429)
        self.assertEqual(self.call('POST', body={'data': {}}, peer='10.0.0.2',
                                   **{'X-Forwarded-For': '2001:db8:9:a::1'})[0], 201)

    def test_foreign_origin_is_refused(self):
        self.assertEqual(self.call('POST', body={'data': {}}, Origin='https://evil.example')[0], 403)
        self.assertEqual(self.call('POST', body={'data': {}}, Origin='https://bills.ctharvey.me')[0], 201)

    def test_unused_lists_expire_after_a_year(self):
        old = self.create()
        self.now[0] += svc.RETENTION_SECONDS + 7200
        self.create()  # Creation runs the purge.
        self.assertEqual(self.call('GET', key=old['edit_key'])[0], 404)

    def test_regular_use_keeps_a_list_alive(self):
        kept = self.create()
        for _ in range(3):
            self.now[0] += svc.RETENTION_SECONDS / 2
            self.assertEqual(self.call('GET', key=kept['view_key'])[0], 200)
        self.create()
        self.assertEqual(self.call('GET', key=kept['edit_key'])[0], 200)


class SyncHttpTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        snapshot = Path(temp.name) / 'bills.json'; snapshot.write_text('{"bills": []}', 'utf-8')
        store = svc.Store(Path(temp.name) / 'sync.db'); self.addCleanup(store.close)
        app = svc.App(store, svc.Snapshot(snapshot))
        self.server = svc.ThreadingHTTPServer(('127.0.0.1', 0), svc.make_handler(app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def request(self, method, body=None, key=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + '/api/sync', data=data, method=method)
        if data is not None:
            req.add_header('Content-Type', 'application/json')
        if key:
            req.add_header('X-Sync-Key', key)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def test_round_trip_and_headers(self):
        status, headers, body = self.request('POST', {'data': {'watch': ['HB1']}})
        self.assertEqual(status, 201)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        made = json.loads(body)
        status, _, body = self.request('GET', key=made['edit_key'])
        self.assertEqual((status, json.loads(body)['data']['watch']), (200, ['HB1']))

    def test_oversized_body_is_refused_before_reading(self):
        status, _, _ = self.request('POST', raw=b'{"data": {"watch": []}, "pad": "' + b'x' * svc.MAX_BODY + b'"}')
        self.assertEqual(status, 413)

    def test_oversized_length_is_answered_before_any_body_is_sent(self):
        port = self.server.server_address[1]
        with socket.create_connection(('127.0.0.1', port), timeout=3) as client:
            client.sendall(b'POST /api/sync HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n'
                           b'Content-Length: %d\r\n\r\n' % (svc.MAX_BODY * 8))
            self.assertRegex(client.recv(64), rb'^HTTP/1\.[01] 413 ')


class ListenBacklogTests(unittest.TestCase):
    def test_burst_of_connections_waits_instead_of_being_dropped(self):
        # Nothing accepts yet, as when every handler thread is busy; socketserver's default backlog of 5 drops the rest.
        server = svc.Server(('127.0.0.1', 0), svc.make_handler(None)); self.addCleanup(server.server_close)
        clients = []
        try:
            for _ in range(64):
                clients.append(socket.create_connection(server.server_address, timeout=1))
        finally:
            for client in clients:
                client.close()
        self.assertEqual(len(clients), 64)


if __name__ == '__main__':
    unittest.main()
