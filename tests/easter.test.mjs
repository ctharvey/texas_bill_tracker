import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {SINE_DIE, austinDate, isSineDieDay, asksSineDie, isBluebonnetSeason, gavelPress, GAVEL_WINDOW_MS,
  armadilloVisits, armadilloDelayMs, asksForWarbler, asksForMockingbird, BIRD_BILLS} from '../src/features/easter/model.js';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('sine die is day 140 of a session that convenes Jan 12, 2027, in Austin time', () => {
  const day140 = new Date(Date.UTC(2027, 0, 12) + 139 * 86400000).toISOString().slice(0, 10);
  assert.equal(SINE_DIE, day140);
  assert.equal(isSineDieDay(new Date('2027-05-31T17:00:00Z')), true);
  // Late on May 31 in Austin is already June 1 in UTC, and early June 1 UTC is still May 31 there.
  assert.equal(isSineDieDay(new Date('2027-06-01T03:00:00Z')), true);
  assert.equal(isSineDieDay(new Date('2027-06-01T12:00:00Z')), false);
  assert.equal(austinDate(new Date('2027-01-12T06:00:00Z')), '2027-01-12');
});

test('only a search for "sine die" itself sets off the petals', () => {
  for (const q of ['sine die', 'Sine Die', '  SINE   DIE ', 'sine-die']) assert.equal(asksSineDie(q), true, q);
  for (const q of ['', 'sine', 'die', 'sine die resolution', 'HB 1', null, undefined]) assert.equal(asksSineDie(q), false, String(q));
});

test('bluebonnets bloom in March and April', () => {
  assert.equal(isBluebonnetSeason(new Date('2027-03-01T12:00:00Z')), true);
  assert.equal(isBluebonnetSeason(new Date('2027-04-30T12:00:00Z')), true);
  assert.equal(isBluebonnetSeason(new Date('2027-02-28T12:00:00Z')), false);
  assert.equal(isBluebonnetSeason(new Date('2027-05-01T12:00:00Z')), false);
});

test('five presses inside the window bring the gavel down, and slow presses never do', () => {
  let presses = [];
  for (let i = 0; i < 4; i++) presses = gavelPress(presses, 1000 + i * 300);
  assert.equal(presses.length, 4);
  assert.deepEqual(gavelPress(presses, 2300), []);  // the fifth: the gavel falls and the count starts over
  presses = [];
  for (let i = 0; i < 10; i++) {
    presses = gavelPress(presses, i * (GAVEL_WINDOW_MS / 3));
    assert.ok(presses.length > 0 && presses.length < 5);
  }
});

test('the armadillo visits rarely, at most once a session, 15 to 60 seconds in', () => {
  assert.equal(armadilloVisits(0.01, false), true);
  assert.equal(armadilloVisits(0.01, true), false);
  assert.equal(armadilloVisits(0.5, false), false);
  assert.equal(armadilloDelayMs(0), 15000);
  assert.equal(armadilloDelayMs(1), 60000);
  for (const odd of [-1, 2, NaN]) assert.ok(armadilloDelayMs(odd) >= 15000 && armadilloDelayMs(odd) <= 60000);
});

test('every easter egg layer ignores the pointer and stays still under reduced motion', () => {
  const css = read('src/styles.css');
  assert.match(css, /\.petal-sky,\.gavel-sky,\.dillo-sky\{position:fixed;inset:0;overflow:hidden;pointer-events:none/);
  assert.match(css, /prefers-reduced-motion:reduce\)\{\.tumbleweed-lane,\.petal-sky,\.gavel-sky,\.dillo-sky\{display:none\}/);
  assert.match(read('src/app.js'), /state\.view==='watchlist'\?'':TUMBLEWEED/);
});

test('searching for the bird bills or the bird sends the warbler', () => {
  for (const q of ['HB 309', 'hb309', 'H.B. 433', 'HB-433', 'warbler', 'Golden-cheeked warbler', 'golden cheeked warblers', 'state bird'])
    assert.equal(asksForWarbler(q), true, q);
  for (const q of ['HB 3090', 'HB 30', 'SB 309', 'warbler habitat', 'bird', '', undefined]) assert.equal(asksForWarbler(q), false, String(q));
  assert.deepEqual(BIRD_BILLS, ['HB 309', 'HB 433']);
});

test('searching for the mockingbird sends the mockingbird', () => {
  for (const q of ['mockingbird', 'Mockingbirds', 'northern mockingbird', 'mockinbird']) assert.equal(asksForMockingbird(q), true, q);
  for (const q of ['mocking', 'mockingbird habitat', 'bird', '', undefined]) assert.equal(asksForMockingbird(q), false, String(q));
  assert.equal(asksForWarbler('mockingbird'), false);
});
