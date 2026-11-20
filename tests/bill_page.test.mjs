import test from 'node:test';
import assert from 'node:assert/strict';
import {parseHash, buildHash, parseLocation, buildUrl, VIEWS} from '../src/prefs.js';
import {CLICK_ORDER} from '../src/core/dispatch.js';

test('a bill page is the bill view with an id', () => {
  assert.ok(VIEWS.includes('bill'));
  const p = parseHash('#bill?id=hb1051');
  assert.equal(p.view, 'bill');
  assert.equal(p.bill, 'HB1051');
  assert.equal(buildHash('bill', {}, {bill: 'HB1051'}), '#bill?id=HB1051');
  assert.deepEqual(parseHash(buildHash('bill', {}, {bill: 'SJR4'})), {...parseHash('#bill?id=SJR4')});
});

test('a bill page keeps a shared list and a view-only sync key, and never writes filters', () => {
  const hash = buildHash('bill', {query: 'water', topic: 'Energy'}, {bill: 'HB5', list: ['HB5', 'SB2'], sync: 'abcdefghijklmnopqrstuv'});
  assert.equal(hash, '#bill?id=HB5&list=HB5,SB2&sync=abcdefghijklmnopqrstuv');
  const p = parseHash(hash);
  assert.deepEqual([p.view, p.bill, p.list, p.sync], ['bill', 'HB5', ['HB5', 'SB2'], 'abcdefghijklmnopqrstuv']);
});

test('old bill links still parse: bill= on any view, and on the bill view itself', () => {
  const old = parseHash('#all?topic=Water&bill=hb1');
  assert.deepEqual([old.view, old.bill, old.filters.topic], ['all', 'HB1', 'Water']);
  assert.equal(parseHash('#bill?bill=HB2').bill, 'HB2');
  assert.equal(parseHash('#bill?id=HB3&bill=HB4').bill, 'HB3');
});

test('a bad or missing id is no bill', () => {
  for (const hash of ['#bill', '#bill?id=', '#bill?id=XY12', '#bill?id=HB0', '#bill?id=HB1%3Cscript%3E']) assert.equal(parseHash(hash).bill, null, hash);
  assert.equal(buildHash('bill', {}, {bill: null}), '#bill');
});

test('the bill page Back button has a click slot where the drawer close button was', () => {
  assert.ok(CLICK_ORDER.includes('bill-back'));
  assert.ok(!CLICK_ORDER.includes('drawer-close'));
  assert.ok(CLICK_ORDER.indexOf('bill-back') < CLICK_ORDER.indexOf('card'));
});

test('a bill page lives at /bill/<ID>; its list or view-only sync context rides in the fragment', () => {
  assert.equal(buildUrl('bill', {}, {bill: 'HB5'}), '/bill/HB5');
  assert.equal(buildUrl('bill', {topic: 'Water'}, {bill: 'HB5', list: ['HB5', 'SB2'], sync: 'abcdefghijklmnopqrstuv'}),
    '/bill/HB5#list=HB5,SB2&sync=abcdefghijklmnopqrstuv');
  const p = parseLocation('/bill/HB5', '#list=HB5,SB2&sync=abcdefghijklmnopqrstuv');
  assert.deepEqual([p.view, p.bill, p.list, p.sync], ['bill', 'HB5', ['HB5', 'SB2'], 'abcdefghijklmnopqrstuv']);
  assert.equal(parseLocation('/bill/hb5', '').bill, 'HB5');
  // The path names the bill; an id in the fragment cannot replace it.
  assert.equal(parseLocation('/bill/HB5', '#id=SB1&bill=SB2').bill, 'HB5');
  assert.equal(parseLocation('/bill/XX5', '').view, 'all');
});

test('other views have their own paths, and old bill addresses still parse at the root', () => {
  assert.equal(buildUrl('all', {topic: 'Water'}), '/explorer?topic=Water');
  assert.equal(buildUrl('bill', {}, {bill: null}), '/#bill');
  assert.equal(buildUrl('member', {}, {member: 'A4875'}), '/member/A4875');
  for (const hash of ['#bill?id=HB5', '#all?topic=Water&bill=HB5', '#today?bill=hb5']) {
    const p = parseLocation('/', hash);
    assert.equal(p.bill, 'HB5', hash);
    assert.equal(buildUrl('bill', {}, {bill: p.bill}), '/bill/HB5');
  }
  assert.equal(parseLocation('/', '#watchlist').view, 'watchlist');
  assert.equal(parseLocation('/index.html', '').view, 'home');
});
