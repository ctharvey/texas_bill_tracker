import test from 'node:test';
import assert from 'node:assert/strict';
import {parseStaticView, staticMatches, takeover} from '../src/core/static_page.js';
import {parseLocation, buildUrl} from '../src/prefs.js';

test('a static view is a kind and a key', () => {
  assert.deepEqual(parseStaticView('bill:HB1094'), {kind: 'bill', key: 'HB1094'});
  assert.deepEqual(parseStaticView('law:PE 46.06'), {kind: 'law', key: 'PE 46.06'});
  assert.deepEqual(parseStaticView('chapter:PE 46'), {kind: 'chapter', key: 'PE 46'});
});

test('anything else is no static view', () => {
  for (const value of [null, undefined, '', 'bill:', 'bill:HB0', 'bill:HB109400', 'bill:XY12', 'home:HB1', 'law:', 'PE 46.06', {}]) {
    assert.equal(parseStaticView(value), null, String(value));
  }
});

test('a static page matches the address it was built for', () => {
  const bill = parseStaticView('bill:HB1094');
  const law = parseStaticView('law:PE 46.06');
  const chapter = parseStaticView('chapter:PE 46');
  assert.equal(staticMatches(bill, parseLocation('/bill/HB1094', '')), true);
  assert.equal(staticMatches(law, parseLocation('/', '#statute?law=PE&sec=46.06')), true);
  assert.equal(staticMatches(chapter, parseLocation('/', '#chapter?law=PE&ch=46')), true);
  assert.equal(staticMatches(bill, parseLocation('/bill/SB2', '')), false);
  assert.equal(staticMatches(law, parseLocation('/', '#statute?law=PE&sec=46.02')), false);
  assert.equal(staticMatches(chapter, parseLocation('/', '#statute?law=PE&sec=46')), false);
  assert.equal(staticMatches(bill, parseLocation('/', '#all')), false);
  assert.equal(staticMatches(null, parseLocation('/', '#all')), false);
});

test('takeover keeps a static page only when the data did not load', () => {
  const view = parseStaticView('bill:HB1094');
  assert.equal(takeover(null, {loaded: true, matches: true}), 'none');
  assert.equal(takeover(null, {loaded: false, matches: false}), 'none');
  assert.equal(takeover(view, {loaded: false, matches: true}), 'keep');
  assert.equal(takeover(view, {loaded: false, matches: false}), 'keep');
  assert.equal(takeover(view, {loaded: true, matches: true}), 'replace');
  assert.equal(takeover(view, {loaded: true, matches: false}), 'replace');
});

test('a matching bill page keeps its address, so the app does not rewrite it', () => {
  assert.equal(buildUrl('bill', {}, {bill: 'HB1094'}), '/bill/HB1094');
});

test('a member page is taken over by the member it was built for', () => {
  const member = parseStaticView('member:A4395');
  assert.deepEqual(member, {kind: 'member', key: 'A4395'});
  for (const value of ['member:', 'member:a4395', 'member:A12', 'member:A4395/x', 'member:B4395']) {
    assert.equal(parseStaticView(value), null, value);
  }
  assert.equal(staticMatches(member, parseLocation('/member/A4395/daniel-alders', '')), true);
  assert.equal(staticMatches(member, parseLocation('/member/A4395', '')), true);
  assert.equal(staticMatches(member, parseLocation('/member/A2150/rafael-anchia', '')), false);
  assert.equal(staticMatches(member, parseLocation('/bill/HB1094', '')), false);
});

test('agency and topic pages are taken over by the key they were built for', () => {
  const agency = parseStaticView('agency:tceq'), topic = parseStaticView('topic:energy-and-utilities');
  assert.deepEqual(agency, {kind: 'agency', key: 'tceq'});
  assert.deepEqual(topic, {kind: 'topic', key: 'energy-and-utilities'});
  for (const value of ['agency:', 'agency:TCEQ', 'agency:-x', 'agency:a/b', 'topic:', 'topic:Energy', 'topic:-x', `topic:${'a'.repeat(81)}`]) {
    assert.equal(parseStaticView(value), null, value);
  }
  assert.equal(staticMatches(agency, parseLocation('/agency/tceq', '')), true);
  assert.equal(staticMatches(agency, parseLocation('/agency/TCEQ/', '')), true);
  assert.equal(staticMatches(agency, parseLocation('/agency/tdi', '')), false);
  assert.equal(staticMatches(agency, parseLocation('/topic/tceq', '')), false);
  assert.equal(staticMatches(topic, parseLocation('/topic/energy-and-utilities', '')), true);
  assert.equal(staticMatches(topic, parseLocation('/topic/taxes', '')), false);
  assert.equal(staticMatches(topic, parseLocation('/agency/energy-and-utilities', '')), false);
});
