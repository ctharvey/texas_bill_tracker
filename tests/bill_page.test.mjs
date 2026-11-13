import test from 'node:test';
import assert from 'node:assert/strict';
import {parseHash, buildHash, VIEWS} from '../src/prefs.js';
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
