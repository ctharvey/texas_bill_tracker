import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {cleanSearches, applySearchOps, profileFile, parseProfileFile, searchFitsSync} from '../src/prefs.js';
import {isLawFollowQuery, lawFollowOf, lawFollowSearch, lawFollowBills} from '../src/features/statutes/model.js';
import {state} from '../src/core/state.js';
import {searchCounts} from '../src/features/sync/lists.js';
import {CLICK_ORDER} from '../src/core/dispatch.js';

const bill = (id, caption, day) => ({id, number: id.replace(/^([A-Z]+)/, '$1 '), caption, title: caption, topics: [], agencies: [],
  chamber: id.startsWith('H') ? 'House' : 'Senate', status: 'Filed', actions: ['Filed'], action_dates: [day], last_action_date: day});
const index = sections => ({format: 'texas-bill-statutes-v1', codes: {PE: 'Penal Code'}, sections, bills: {}});

test('following a law is a saved search for the section key, which every saved-search layer keeps', () => {
  const s = lawFollowSearch('PE 46.06', 'Penal Code § 46.06', 'abcdefgh12', '2026-11-19');
  assert.deepEqual(s, {id: 'abcdefgh12', name: 'Penal Code § 46.06', filters: {query: 'PE 46.06'}, seen: '2026-11-19'});
  assert.ok(searchFitsSync(s.filters));
  assert.deepEqual(cleanSearches([s]), [s]);
  assert.deepEqual(applySearchOps([], [{op: 'save-search', id: s.id, value: s}]), [s]);
  const file = profileFile({watch: [], follows: [], searches: [s]});
  assert.deepEqual(parseProfileFile(file).searches, [s]);
  assert.equal(lawFollowOf([{id: 'x', filters: {query: 'PE 46.06', topic: 'Guns'}}, s], 'PE 46.06'), s);
  assert.equal(lawFollowOf([s], 'PE 46.07'), null);
});

test('only an exact section key is a follow query', () => {
  for (const q of ['PE 46.06', 'ED 30A.151', 'CR 42.12']) assert.ok(isLawFollowQuery(q), q);
  for (const q of ['Penal Code 46.06', 'pe 46.06', '46.06', ' PE 46.06', 'PE 46.06 guns', null]) assert.ok(!isLawFollowQuery(q), String(q));
  assert.deepEqual(lawFollowBills(index({'PE 46.06': {h: 'X', b: [['HB9', 'm']]}}), 'PE 46.06'), ['HB9']);
  assert.deepEqual(lawFollowBills(index({}), 'PE 46.06'), []);
  assert.deepEqual(lawFollowBills(null, 'PE 46.06'), []);
});

test('a followed section with no bills shows new once a bill amending it appears, and never counts text matches', () => {
  const follow = lawFollowSearch('PE 46.06', 'Penal Code § 46.06', 'abcdefgh12', '2026-11-01');
  // "people" and "46.06" both appear in this caption; a free-text search would find it.
  const lookalike = bill('SB3', 'Relating to people and Section 46.06, Education Code.', '2026-11-10');
  state.bills = [lookalike];
  state.statutes = index({'ED 46.06': {h: 'Y', b: [['SB3', 'm']]}});
  assert.deepEqual(searchCounts(follow), {total: 0, fresh: 0});
  // The next data run: HB9 amends Penal Code 46.06.
  state.bills = [lookalike, bill('HB9', 'Relating to the transfer of weapons.', '2026-11-10')];
  state.statutes = index({'ED 46.06': {h: 'Y', b: [['SB3', 'm']]}, 'PE 46.06': {h: 'X', b: [['HB9', 'm']]}});
  assert.deepEqual(searchCounts(follow), {total: 1, fresh: 1});
  // Opened today: nothing new until the next action.
  assert.deepEqual(searchCounts({...follow, seen: '2026-11-10'}), {total: 1, fresh: 0});
  // Before the index loads a follow counts nothing (the home page redraws when it arrives).
  state.statutes = null;
  assert.deepEqual(searchCounts(follow), {total: 0, fresh: 0});
});

test('the statute page offers Follow, the home page redraws when the index arrives, and clicks are ordered', () => {
  const view = readFileSync(new URL('../src/features/statutes/view.js', import.meta.url), 'utf8');
  assert.match(view, /data-follow-law="\$\{esc\(key\)\}"/);
  assert.match(view, /else if\(state\.view==='home'\)refreshHome\(\);/);
  assert.match(view, /can be missed/);
  const app = readFileSync(new URL('../src/app.js', import.meta.url), 'utf8');
  assert.match(app, /clickOn\('follow-law','\[data-follow-law\]'/);
  assert.ok(CLICK_ORDER.indexOf('follow-law') > CLICK_ORDER.indexOf('save-search'));
  assert.ok(CLICK_ORDER.indexOf('follow-law') < CLICK_ORDER.indexOf('card'));
});
