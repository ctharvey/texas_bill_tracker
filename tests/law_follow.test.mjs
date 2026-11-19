import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {cleanSearches, applySearchOps, profileFile, parseProfileFile, searchFitsSync} from '../src/prefs.js';
import {isLawFollowQuery, lawFollowOf, lawFollowsOf, lawFollowSearch, lawFollowBills, lawFirstSeen, LAW_CODES, LAW_CODE_NAMES, statuteLabel} from '../src/features/statutes/model.js';
import {state} from '../src/core/state.js';
import {searchCounts, changeSearch} from '../src/features/sync/lists.js';
import {CLICK_ORDER} from '../src/core/dispatch.js';

const bill = (id, caption, day) => ({id, number: id.replace(/^([A-Z]+)/, '$1 '), caption, title: caption, topics: [], agencies: [], authors: [], impacts: [],
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
  // Before the index loads the count is unknown, not 0, and nothing is new (the pages redraw when it arrives).
  state.statutes = null;
  assert.deepEqual(searchCounts(follow), {total: null, fresh: 0});
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

test('a bill that starts changing a followed law counts as new from its first-seen day, the same day included', () => {
  const follow = lawFollowSearch('PE 46.06', 'Penal Code § 46.06', 'abcdefgh12', '2026-11-19');
  // HB9's last action is old; a late text added the section today (counterexample F1: no newer dated action).
  state.bills = [bill('HB9', 'Relating to weapons.', '2026-03-01'), bill('HB10', 'Relating to weapons.', '2026-03-01')];
  state.statutes = index({'PE 46.06': {h: 'X', b: [['HB9', 'm'], ['HB10', 'm']], f: {HB9: '2026-11-19'}}});
  assert.equal(lawFirstSeen(state.statutes, 'PE 46.06', 'HB9'), '2026-11-19');
  assert.equal(lawFirstSeen(state.statutes, 'PE 46.06', 'HB10'), '');
  assert.deepEqual(searchCounts(follow), {total: 2, fresh: 1});
  // Indexed later than the day it was opened: still new.
  state.statutes.sections['PE 46.06'].f = {HB9: '2026-11-21'};
  assert.deepEqual(searchCounts(follow), {total: 2, fresh: 1});
  // Indexed before it was opened: not new.
  state.statutes.sections['PE 46.06'].f = {HB9: '2026-11-18'};
  assert.deepEqual(searchCounts(follow), {total: 2, fresh: 0});
  // A malformed day is ignored; an ordinary search never uses first-seen days.
  state.statutes.sections['PE 46.06'].f = {HB9: 'soon', HB10: '2026-11-20'};
  assert.equal(lawFirstSeen(state.statutes, 'PE 46.06', 'HB9'), '');
  assert.deepEqual(searchCounts({...follow, filters: {query: 'weapons'}}), {total: 2, fresh: 0});
});

test('only section keys of known codes are follows, so a search like "PM 2.5" stays a text search', () => {
  assert.equal(LAW_CODES.size, 27);
  for (const q of ['PM 2.5', 'CO 2.0', 'HB 1.5']) assert.ok(!isLawFollowQuery(q), q);
  const smog = bill('SB4', 'Relating to PM 2.5 emissions.', '2026-11-10');
  state.bills = [smog];
  state.statutes = index({});
  assert.deepEqual(searchCounts({id: 'a', name: 'PM 2.5', filters: {query: 'PM 2.5'}, seen: '2026-11-01'}), {total: 1, fresh: 1});
});

test('the code names match the build script, and an unknown code still labels', () => {
  const py = readFileSync(new URL('../scripts/build_feeds.py', import.meta.url), 'utf8');
  const block = /CODE_ABBR = \{([\s\S]*?)\n\}/.exec(py);
  assert.ok(block, 'CODE_ABBR in build_feeds.py');
  const pyNames = Object.fromEntries([...block[1].matchAll(/"([^"]+)":\s*"([A-Z]{2})"/g)].map(m => [m[2], m[1]]));
  assert.deepEqual(pyNames, LAW_CODE_NAMES);
  assert.equal(statuteLabel('PE 46.06'), 'Penal Code § 46.06');
  assert.equal(statuteLabel('CR 42.12'), 'Code of Criminal Procedure Art. 42.12');
});

test('unfollowing removes every copy of a law follow; an import skips laws already followed', () => {
  const a = lawFollowSearch('PE 46.06', 'Penal Code § 46.06', 'aaaaaaaaaa', '2026-11-19');
  const b = lawFollowSearch('PE 46.06', 'Penal Code § 46.06', 'bbbbbbbbbb', '2026-11-18');
  const narrowed = {id: 'cccccccccc', name: 'x', filters: {query: 'PE 46.06', topic: 'Guns'}, seen: '2026-11-18'};
  assert.deepEqual(lawFollowsOf([a, narrowed, b], 'PE 46.06'), [a, b]);
  const lists = readFileSync(new URL('../src/features/sync/lists.js', import.meta.url), 'utf8');
  assert.match(lists, /const have=lawFollowsOf\(state\.searches,key\);\s*if\(have\.length\)\{for\(const s of have\)changeSearch\('delete-search',s\.id\)/);
  // The save is checked: another tab can fill the last slot first.
  assert.match(lists, /state\.searches\.some\(x=>x\.id===s\.id\)/);
  const actions = readFileSync(new URL('../src/features/watchlist/actions.js', import.meta.url), 'utf8');
  assert.match(actions, /if\(law\)\{if\(laws\.has\(law\)\)return false;laws\.add\(law\)\}/);
});

test('a save the list has no room for is not kept or sent to the sync link', () => {
  state.searches = [];
  for (let i = 0; i < 20; i++) changeSearch('save-search', {id: `s${String(i).padStart(9, '0')}`, name: `n${i}`, filters: {query: `q${i}`}, seen: null});
  assert.equal(state.searches.length, 20);
  const extra = lawFollowSearch('PE 46.06', 'Penal Code § 46.06', 'zzzzzzzzzz', '2026-11-19');
  changeSearch('save-search', extra);
  assert.ok(!state.searches.some(s => s.id === extra.id));
  const lists = readFileSync(new URL('../src/features/sync/lists.js', import.meta.url), 'utf8');
  assert.match(lists, /if\(op==='save-search'&&!state\.searches\.some\(s=>s\.id===id\)\)return;\s*\n\s*sync\.record\(/);
  for (const s of [...state.searches]) changeSearch('delete-search', s.id);
});

test('the statute page redraws after a sync pull or another tab, and its Follow button keeps focus', () => {
  const lists = readFileSync(new URL('../src/features/sync/lists.js', import.meta.url), 'utf8');
  assert.match(lists, /const FOLLOW_VIEWS=new Set\(\[[^\]]*'statute'[^\]]*\]\)/);
  const app = readFileSync(new URL('../src/app.js', import.meta.url), 'utf8');
  assert.match(app, /const FOCUS_KEYS=\[[^\]]*'data-follow-law'[^\]]*\]/);
});

test('an exact section query tells the reader while the index loads, if it failed, and when no bill changes it', () => {
  const view = readFileSync(new URL('../src/features/statutes/view.js', import.meta.url), 'utf8');
  assert.match(view, /Loading the bills that change/);
  assert.match(view, /none yet/);
  assert.match(view, /statutesFailed/);
});

test('unfollowing removes a copy another tab saved since this tab last read the list', async () => {
  const {toggleLawFollow, listStore} = await import('../src/features/sync/lists.js');
  const {searchesKey} = await import('../src/core/storage.js');
  const realDocument = globalThis.document;
  globalThis.document = {querySelector: () => null, querySelectorAll: () => []};  // No page: toasts and redraws find nothing.
  try {
    const mine = lawFollowSearch('PE 46.06', 'Penal Code § 46.06', 'aaaaaaaa11', '2026-11-19');
    const theirs = lawFollowSearch('PE 46.06', 'Penal Code § 46.06', 'bbbbbbbb22', '2026-11-19');
    listStore.setItem(searchesKey, JSON.stringify([mine, theirs]));  // The other tab wrote its copy too.
    state.searches = [mine];  // This tab has not seen it yet.
    try { toggleLawFollow('PE 46.06', 'Penal Code § 46.06'); } catch (error) { if (!/toast|classList|textContent/.test(String(error))) throw error; }
    assert.deepEqual(JSON.parse(listStore.getItem(searchesKey)), []);
    assert.deepEqual(state.searches, []);
  } finally {
    globalThis.document = realDocument;
  }
});
