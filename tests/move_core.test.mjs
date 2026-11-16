// Move core: what is collected, cleaned, added, held and verified when saved data moves to the new address.
import test from 'node:test';
import assert from 'node:assert/strict';
import {collect, receive, plan, verify, digest, hasMovable, moveNeeded, keepHeld, keepPreviousLink, previousLinks, moveTarget, moveSource,
  heldFile, heldCount, KEYS, HELD_KEY, MOVED_KEY, PREVIOUS_SYNC_KEY} from '../src/core/move.js';
import {parseProfileFile} from '../src/prefs.js';
import {MAX_LIST, MAX_FOLLOWS, MAX_SEARCHES} from '../src/prefs.js';

function storage(initial = {}, {failOn = null} = {}) {
  const m = new Map(Object.entries(initial).map(([k, v]) => [k, typeof v === 'string' ? v : JSON.stringify(v)]));
  return {
    get length() { return m.size; }, key: i => [...m.keys()][i] ?? null,
    getItem: k => m.get(k) ?? null, removeItem: k => m.delete(k),
    setItem(k, v) { if (failOn && failOn(k)) throw Error('QuotaExceededError'); m.set(k, String(v)); },
  };
}
const search = (id, name, filters = {topic: 'Taxes'}) => ({id, name, filters, seen: '2026-11-10'});
const KEY = 'abcdefghijklmnopqrstuv', OTHER = 'zyxwvutsrqponmlkjihgfe';
const here = (s = {}) => ({watch: [], follows: [], searches: [], settings: {}, syncKey: null, ...s});

// The receiver's apply step, as features/move does it (through the app's own paths) without the app.
function apply(store, planned, cur) {
  store.setItem(KEYS.watch, JSON.stringify([...cur.watch, ...planned.watch]));
  store.setItem(KEYS.follows, JSON.stringify([...cur.follows, ...planned.follows]));
  store.setItem(KEYS.searches, JSON.stringify([...cur.searches, ...planned.searches]));
  keepHeld(store, planned.held);
  if (planned.sync === 'join') store.setItem(KEYS.sync, JSON.stringify({key: planned.editKey, mode: null}));
  if (planned.sync === 'keep-previous') keepPreviousLink(store, planned.editKey);
}

test('origins are fixed: production pair and the *.localhost test pair only', () => {
  assert.equal(moveTarget('https://bills.ctharvey.me'), 'https://billatlas.org');
  assert.equal(moveSource('https://billatlas.org'), 'https://bills.ctharvey.me');
  assert.equal(moveTarget('http://old.localhost:8787'), 'http://new.localhost:8787');
  assert.equal(moveSource('http://new.localhost:8787'), 'http://old.localhost:8787');
  for (const o of ['https://billatlas.org', 'https://evil.example', 'http://127.0.0.1:8787', 'http://localhost:8787', 'http://old.localhost.evil.example', 'https://bills.ctharvey.me.evil', 'null'])
    assert.equal(moveTarget(o), null, o);
  assert.equal(moveSource('https://bills.ctharvey.me'), null);
});

test('collect takes own keys only and leaves move bookkeeping behind', () => {
  const s = storage({[KEYS.watch]: ['HB1'], 'texas-bill-atlas-near-you-v1': {house: 5}, 'other-site': 'x', [MOVED_KEY]: {digest: 'x'}, [HELD_KEY]: {}});
  assert.deepEqual(Object.keys(collect(s).items).sort(), [KEYS.watch, 'texas-bill-atlas-near-you-v1', HELD_KEY].sort());  // Kept-aside items move too.
});

test('receive cleans like the app does and keeps refused items for the held key', () => {
  const c = receive(collect(storage({
    [KEYS.watch]: ['hb 5', 'HB5', 'SJR9', 'nope', 7],
    [KEYS.follows]: ['A1001', 'A1001', 'B1', null],
    [KEYS.searches]: [search('aaaa1111', 'Water'), {id: 'BAD'}, {id: 'bbbb2222', name: 'No seen', filters: {topic: 'Energy'}}],
    [KEYS.prefs]: {theme: 'warbler', mode: 'dark', filters: {topic: 'Taxes', evil: 1}},
    [KEYS.near]: {house: '12', senate: 99, lat: 30.1, source: 'location'},
    [KEYS.agencySort]: 'count',
    [KEYS.sync]: {key: KEY, mode: 'edit', version: 9, pending: [{op: 'add', id: 'HB1'}], merged: {follows: true}},
  })));
  assert.deepEqual(c.watch, ['HB5', 'SJR9']);
  assert.deepEqual(c.refused.watch, ['nope', 7]);
  assert.deepEqual(c.follows, ['A1001']);
  assert.deepEqual(c.refused.follows, ['B1', null]);
  assert.deepEqual(c.searches.map(s => s.id), ['aaaa1111', 'bbbb2222']);
  assert.deepEqual(c.refused.searches, [{id: 'BAD'}]);
  assert.deepEqual(c.settings.filters, {topic: 'Taxes'});
  assert.equal(c.settings.theme, 'warbler');
  assert.equal(c.settings.mode, 'dark');
  assert.equal(c.settings.agencySort, 'count');
  assert.equal(c.settings.near.house, '12');
  assert.equal(c.settings.near.lat, undefined);  // Never coordinates.
  assert.equal(c.editKey, KEY);
  assert.equal(JSON.stringify(c).includes('pending'), false);
});

test('legacy and junk shapes: sync state with followsMerged, view links, bad JSON, wrong types', () => {
  const legacy = receive(collect(storage({[KEYS.sync]: {key: KEY, mode: 'edit', followsMerged: true}})));
  assert.equal(legacy.editKey, KEY);
  assert.equal(receive(collect(storage({[KEYS.sync]: {key: KEY, mode: 'view'}}))).editKey, null);
  assert.equal(receive(collect(storage({[KEYS.sync]: {key: 'short', mode: 'edit'}}))).editKey, null);
  const junk = receive(collect(storage({[KEYS.watch]: '{not json', [KEYS.follows]: '"A1001"', [KEYS.prefs]: '[1]'})));
  assert.deepEqual([junk.watch, junk.follows, junk.settings], [[], [], {}]);
  assert.deepEqual(receive(null).watch, []);
  assert.deepEqual(receive({items: {[KEYS.watch]: ['HB1']}}).watch, []);  // Values travel as stored text.
});

test('plan adds after this site\'s items, sets only missing settings, and joins or keeps the link', () => {
  const c = receive(collect(storage({[KEYS.watch]: ['HB1', 'HB2'], [KEYS.prefs]: {theme: 'warbler', mode: 'dark'}, [KEYS.sync]: {key: KEY, mode: 'edit'}})));
  const p = plan(here({watch: ['HB2', 'HB9'], settings: {theme: 'current'}}), c);
  assert.deepEqual(p.watch, ['HB1']);
  assert.deepEqual(p.settings, {mode: 'dark'});
  assert.equal(p.sync, 'join');
  assert.equal(plan(here({syncKey: KEY}), c).sync, 'same');
  assert.equal(plan(here({syncKey: OTHER}), c).sync, 'keep-previous');
  assert.equal(plan(here(), receive(collect(storage({[KEYS.watch]: ['HB1']})))).sync, 'none');
});

test('over a limit, the rest is held, never dropped', () => {
  const bills = Array.from({length: MAX_LIST + 5}, (_, i) => `HB${i + 1}`);
  const codes = Array.from({length: MAX_FOLLOWS + 3}, (_, i) => `A${1000 + i}`);
  const searches = Array.from({length: MAX_SEARCHES + 2}, (_, i) => search(`s${String(i).padStart(7, '0')}`, `S${i}`));
  const c = receive(collect(storage({[KEYS.watch]: bills, [KEYS.follows]: codes, [KEYS.searches]: searches})));
  const p = plan(here({watch: ['SB1']}), c);
  assert.equal(p.watch.length, MAX_LIST - 1);
  assert.equal(p.held.watch.length, 6);
  assert.equal(p.follows.length + p.held.follows.length, MAX_FOLLOWS + 3);
  assert.equal(p.searches.length + p.held.searches.length, MAX_SEARCHES + 2);
});

test('a full move verifies; a held key that grows across moves never loses items', () => {
  const old = storage({[KEYS.watch]: ['HB1', 'junk'], [KEYS.follows]: ['A1001'], [KEYS.searches]: [search('aaaa1111', 'W')], [KEYS.sync]: {key: KEY, mode: 'edit'}});
  const c = receive(collect(old));
  const s = storage({[KEYS.watch]: ['SB1']});
  const cur = here({watch: ['SB1']});
  const p = plan(cur, c);
  apply(s, p, cur);
  assert.deepEqual(verify(s, c, p).ok, true);
  keepHeld(s, {watch: ['other'], follows: [], searches: []});
  keepHeld(s, {watch: ['junk'], follows: [], searches: []});
  assert.deepEqual(JSON.parse(s.getItem(HELD_KEY)).watch, ['junk', 'other']);
});

test('verify fails when an item is missing, the link did not stick, or storage was full', () => {
  const c = receive(collect(storage({[KEYS.watch]: ['HB1', 'HB2'], [KEYS.sync]: {key: KEY, mode: 'edit'}})));
  const p = plan(here(), c);
  const partial = storage({[KEYS.watch]: ['HB1'], [KEYS.sync]: {key: KEY}});
  assert.deepEqual([verify(partial, c, p).ok, verify(partial, c, p).missing.watch], [false, 1]);
  const noLink = storage({[KEYS.watch]: ['HB1', 'HB2']});
  assert.deepEqual([verify(noLink, c, p).ok, verify(noLink, c, p).sync], [false, false]);
  const full = storage({}, {failOn: k => k === KEYS.watch});
  try { apply(full, p, here()); } catch {}
  assert.equal(verify(full, c, p).ok, false);
  const heldFull = storage({}, {failOn: k => k === HELD_KEY});
  assert.equal(keepHeld(heldFull, {watch: ['x'], follows: [], searches: []}), false);
});

test('digest ignores visit stamps, sync bookkeeping and search opens; changes with saved items', () => {
  const base = {[KEYS.watch]: ['HB1'], [KEYS.searches]: [search('aaaa1111', 'W')], [KEYS.sync]: {key: KEY, mode: 'edit', version: 1, pending: []}};
  const d = digest(receive(collect(storage(base))));
  const after = {...base, 'tx-bill-atlas-visit-v1': {day: '2026-11-16'},
    [KEYS.searches]: [{...search('aaaa1111', 'W'), seen: '2026-11-16'}], [KEYS.sync]: {key: KEY, mode: 'edit', version: 7, pending: [{op: 'add', id: 'HB1'}]}};
  assert.equal(digest(receive(collect(storage(after)))), d);
  assert.notEqual(digest(receive(collect(storage({...base, [KEYS.watch]: ['HB1', 'HB2']})))), d);
});

test('what counts as movable, and when the old site asks again', () => {
  assert.equal(hasMovable(storage({'tx-bill-atlas-disclaimer-v1': 'x', 'tx-bill-atlas-visit-v1': {}, 'tx-bill-atlas-warbler-flew': '1'})), false);
  assert.equal(hasMovable(storage({[KEYS.prefs]: {filters: {topic: 'Taxes'}}})), true);
  assert.equal(hasMovable(storage({[KEYS.near]: {house: 5}})), true);
  const s = storage({[KEYS.watch]: ['HB1']});
  assert.equal(moveNeeded(s), true);
  s.setItem(MOVED_KEY, JSON.stringify({digest: digest(receive(collect(s)))}));
  assert.equal(moveNeeded(s), false);
  s.setItem(KEYS.watch, JSON.stringify(['HB1', 'HB2']));
  assert.equal(moveNeeded(s), true);
});

test('a moved link this site did not join is kept beside earlier ones', () => {
  const s = storage();
  const c = receive(collect(storage({[KEYS.sync]: {key: KEY, mode: 'edit'}})));
  const p = plan(here({syncKey: OTHER}), c);
  keepPreviousLink(s, 'aaaaaaaaaaaaaaaaaaaaaa');
  apply(s, p, here());
  apply(s, p, here());
  assert.deepEqual(previousLinks(s), ['aaaaaaaaaaaaaaaaaaaaaa', KEY]);
  assert.equal(verify(s, c, p).ok, true);
  assert.equal(s.getItem(PREVIOUS_SYNC_KEY).includes(OTHER), false);
});

test('verify counts this site\'s own items too: one lost by a join is a failure, not ok', () => {
  const c = receive(collect(storage({[KEYS.watch]: ['HB1']})));
  const before = here({watch: ['SB1', 'SB2']});
  const p = plan(before, c);
  const s = storage({[KEYS.watch]: ['HB1', 'SB1']});  // SB2 vanished (say, a sync union cut it).
  const v = verify(s, c, p, before);
  assert.deepEqual([v.ok, v.missing.before, v.why], [false, 1, 'storage']);
  keepHeld(s, {watch: ['SB2'], follows: [], searches: []});
  assert.equal(verify(s, c, p, before).ok, true);  // Kept aside counts as kept.
});

test('verify reads back each moved setting', () => {
  const c = receive(collect(storage({[KEYS.prefs]: {theme: 'warbler', mode: 'dark'}, [KEYS.agencySort]: 'count'})));
  const p = plan(here(), c);
  const s = storage({[KEYS.prefs]: {theme: 'warbler'}, [KEYS.agencySort]: 'count'});
  assert.deepEqual([verify(s, c, p).ok, verify(s, c, p).missing.settings], [false, 1]);
  s.setItem(KEYS.prefs, JSON.stringify({theme: 'warbler', mode: 'dark'}));
  assert.equal(verify(s, c, p).ok, true);
});

test('filters left at the defaults are no setting: they neither move, block a move, nor change the digest', () => {
  const defaults = {query: '', topic: '', sort: 'newest', onlyWatch: false};
  assert.equal(hasMovable(storage({[KEYS.prefs]: {filters: defaults}})), false);
  const c = receive(collect(storage({[KEYS.watch]: ['HB1'], [KEYS.prefs]: {filters: {topic: 'Taxes'}}})));
  assert.deepEqual(plan(here({settings: {filters: defaults}}), c).settings, {filters: {topic: 'Taxes'}});
  const a = digest(receive(collect(storage({[KEYS.watch]: ['HB1'], [KEYS.prefs]: {filters: {topic: 'Water'}}}))));
  assert.equal(digest(c), a);
});

test('items the old site kept aside move into this site\'s kept-aside items', () => {
  const old = storage({[KEYS.watch]: ['HB1'], [HELD_KEY]: {watch: ['HB9'], follows: [], searches: [search('zzzz0001', 'Old')]}});
  assert.equal(hasMovable(storage({[HELD_KEY]: {watch: ['HB9'], follows: [], searches: []}})), true);
  const c = receive(collect(old)), s = storage(), p = plan(here(), c);
  apply(s, p, here());
  assert.equal(verify(s, c, p).ok, true);
  assert.deepEqual(JSON.parse(s.getItem(HELD_KEY)).watch, ['HB9']);
  assert.equal(heldCount(s), 2);
});

test('the kept-aside download is a profile file that Import file reads', () => {
  const s = storage({[HELD_KEY]: {watch: ['HB9', 'junk'], follows: ['A1001'], searches: [search('zzzz0001', 'Old')]}});
  const back = parseProfileFile(heldFile(s));
  assert.deepEqual([back.bills, back.follows, back.searches.map(x => x.id)], [['HB9'], ['A1001'], ['zzzz0001']]);
  assert.equal(heldFile(storage()), null);
});
