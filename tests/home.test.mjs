import test from 'node:test';
import assert from 'node:assert/strict';
import {nextVisit, changedSince, newestReviewed} from '../src/features/home/model.js';
import {parseHash, buildHash, VIEWS} from '../src/prefs.js';

test('a bare address opens the dashboard; any other address keeps its view, and an unknown one is the explorer', () => {
  assert.ok(VIEWS.includes('home'));
  assert.equal(parseHash('').view, 'home');
  assert.equal(parseHash('#').view, 'home');
  assert.equal(parseHash('#home').view, 'home');
  assert.equal(buildHash('home', {}), '#home');
  for (const hash of ['#all', '#?query=water', '#?list=HB1,SB2', '#?sync=abcdefghijklmnopqrstuv', '#nowhere']) assert.equal(parseHash(hash).view, 'all', hash);
  assert.equal(parseHash('#?query=water').filters.query, 'water');
  assert.equal(parseHash('#today').view, 'today');
});

test('the dashboard search hands its words to the explorer', () => {
  assert.equal(buildHash('all', {query: 'cemetery plot owners'}), '#all?query=cemetery%20plot%20owners');
  assert.equal(parseHash(buildHash('all', {query: '"plot owners"'})).filters.query, '"plot owners"');
});

test('the visit stamp: a first visit has no previous day; a new day moves the last day back; a reload keeps it', () => {
  assert.deepEqual(nextVisit(null, '2026-11-12'), {prev: null, store: {day: '2026-11-12', prev: null}});
  assert.deepEqual(nextVisit({day: '2026-11-10', prev: null}, '2026-11-12'), {prev: '2026-11-10', store: {day: '2026-11-12', prev: '2026-11-10'}});
  assert.deepEqual(nextVisit({day: '2026-11-12', prev: '2026-11-10'}, '2026-11-12'), {prev: '2026-11-10', store: {day: '2026-11-12', prev: '2026-11-10'}});
  assert.deepEqual(nextVisit({day: 'yesterday', prev: 5}, '2026-11-12').prev, null);
  assert.deepEqual(nextVisit('garbage', '2026-11-12').prev, null);
});

const bill = (id, day) => ({id, last_action: 'Filed', last_action_date: day, actions: [], topics: []});

test('changed since: an action on the day of the last visit still counts, older ones do not, future ones never', () => {
  const bills = [bill('HB1', '2026-11-09'), bill('HB2', '2026-11-10'), bill('HB3', '2026-11-11'), bill('HB4', '2026-11-20'), bill('HB5', '')];
  assert.deepEqual(changedSince(bills, '2026-11-10', '2026-11-12').map(r => [r.bill.id, r.day]), [['HB3', '2026-11-11'], ['HB2', '2026-11-10']]);
  assert.deepEqual(changedSince(bills, null, '2026-11-12').map(r => r.bill.id), ['HB3', 'HB2', 'HB1']);
});

test('newest reviewed first; bills without a review are left out', () => {
  const bills = [{id: 'HB2', luna: {reviewed_at: '2026-11-10T01:00:00Z'}}, {id: 'HB1'}, {id: 'HB3', luna: {reviewed_at: '2026-11-12T01:00:00Z'}}, {id: 'HB4', luna: {}}];
  assert.deepEqual(newestReviewed(bills).map(b => b.id), ['HB3', 'HB2']);
});
