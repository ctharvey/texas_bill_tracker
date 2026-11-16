// Move hand-off: the window protocol (fake windows) and the receiver applying a move with a real sync client.
import test from 'node:test';
import assert from 'node:assert/strict';
import {sendMove, receiveMove, newNonce} from '../src/features/move/handoff.js';
import {applyMove} from '../src/features/move/apply.js';
import {collect, keepHeld, KEYS} from '../src/core/move.js';
import {readWatch, readFollows, readSearches, changeWatchList, changeFollowList, changeSearchList, adoptLists} from '../src/core/lists.js';
import {createSyncClient} from '../src/sync.js';
import {MAX_FOLLOWS} from '../src/prefs.js';
// Debounced sync writes wait 60 s in these tests (they flush by hand); don't let those timers hold the run open.
const realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms, ...rest) => { const t = realSetTimeout(fn, ms, ...rest); if (ms >= 1000) t.unref?.(); return t; };

const OLD = 'https://bills.ctharvey.me', NEW = 'https://billatlas.org';
const tick = () => new Promise(r => setTimeout(r, 0));

// A window that delivers posted messages asynchronously, stamped with the poster's origin, like a browser does.
function fakeWindow(origin) {
  const listeners = new Set();
  const w = {
    origin, closed: false,
    addEventListener: (t, f) => listeners.add(f), removeEventListener: (t, f) => listeners.delete(f),
    deliver(data, from, fromOrigin) { setTimeout(() => { for (const f of [...listeners]) f({data, source: from, origin: fromOrigin}); }, 0); },
    listening: () => listeners.size,
  };
  return w;
}
// `from` posts to `to`; the message arrives only if targetOrigin matches the receiver's origin.
function link(from, to) {
  from.peer = to;
  return (data, targetOrigin) => { if (targetOrigin === to.origin) to.deliver(structuredClone(data), from, from.origin); };
}
function pair() {
  const oldWin = fakeWindow(OLD), newWin = fakeWindow(NEW);
  newWin.postMessage = link(oldWin, newWin);   // What the old page calls on the window it opened.
  oldWin.postMessage = link(newWin, oldWin);   // What the new page calls on its opener.
  return {oldWin, newWin};
}

test('a move completes when both sides see the window and origin they expect', async () => {
  const {oldWin, newWin} = pair();
  const sending = sendMove({self: oldWin, win: newWin, target: NEW, getPayload: async () => ({v: 1, items: {[KEYS.watch]: '["HB1"]'}})});
  let got = null;
  const nonce = newNonce();
  const receiving = receiveMove({self: newWin, opener: oldWin, source: OLD, nonce, apply: async p => { got = p; return {ok: true, counts: {watch: 1}}; }});
  assert.deepEqual(await receiving, {ok: true, counts: {watch: 1}});
  assert.deepEqual(await sending, {ok: true, counts: {watch: 1}});
  assert.deepEqual(got.items, {[KEYS.watch]: '["HB1"]'});
  assert.equal(oldWin.listening() + newWin.listening(), 0);
});

test('the sender ignores other windows, other origins and itself, and sends only once', async () => {
  const {oldWin, newWin} = pair();
  const decoy = fakeWindow(NEW);
  let reads = 0;
  const sending = sendMove({self: oldWin, win: newWin, target: NEW, timeoutMs: 200, pollMs: 10, getPayload: async () => { reads++; return {v: 1, items: {}}; }});
  const nonce = newNonce();
  oldWin.deliver({type: 'move-ready', nonce}, decoy, NEW);               // Another window from the right origin.
  oldWin.deliver({type: 'move-ready', nonce}, newWin, 'https://evil.example');  // The right window, wrong origin.
  oldWin.deliver({type: 'move-ready', nonce}, oldWin, OLD);              // Its own window (an extension, say).
  oldWin.deliver({type: 'move-ready', nonce: 'short'}, newWin, NEW);
  await tick(); await tick();
  assert.equal(reads, 0);
  oldWin.deliver({type: 'move-ready', nonce}, newWin, NEW);
  oldWin.deliver({type: 'move-ready', nonce}, newWin, NEW);              // Duplicate ready.
  oldWin.deliver({type: 'move-done', nonce: 'x'.repeat(32), ok: true}, newWin, NEW);  // Wrong nonce.
  await tick(); await tick();
  assert.equal(reads, 1);
  oldWin.deliver({type: 'move-done', nonce, ok: true, counts: {watch: 2}}, newWin, NEW);
  assert.deepEqual(await sending, {ok: true, counts: {watch: 2}});
});

test('the receiver takes one data message, with its nonce, from its opener and origin only', async () => {
  const {oldWin, newWin} = pair();
  const nonce = newNonce(), applied = [];
  const receiving = receiveMove({self: newWin, opener: oldWin, source: OLD, nonce, apply: async p => { applied.push(p); return {ok: true, counts: {}}; }});
  const stranger = fakeWindow(OLD);
  newWin.deliver({type: 'move-data', nonce, payload: 'stranger'}, stranger, OLD);
  newWin.deliver({type: 'move-data', nonce, payload: 'wrong origin'}, oldWin, 'https://evil.example');
  newWin.deliver({type: 'move-data', nonce: newNonce(), payload: 'wrong nonce'}, oldWin, OLD);
  newWin.deliver({type: 'move-data', nonce, payload: 'first'}, oldWin, OLD);
  newWin.deliver({type: 'move-data', nonce, payload: 'late duplicate'}, oldWin, OLD);
  await receiving; await tick(); await tick();
  assert.deepEqual(applied, ['first']);
});

test('a closed or silent receiver ends the move as not done', async () => {
  const {oldWin, newWin} = pair();
  const closing = sendMove({self: oldWin, win: newWin, target: NEW, pollMs: 5, timeoutMs: 1000, getPayload: async () => ({})});
  newWin.closed = true;
  assert.deepEqual(await closing, {ok: false, reason: 'closed'});
  const {oldWin: o2, newWin: n2} = pair();
  assert.deepEqual(await sendMove({self: o2, win: n2, target: NEW, pollMs: 5, timeoutMs: 30, getPayload: async () => ({})}), {ok: false, reason: 'timeout'});
  const {oldWin: o3, newWin: n3} = pair();
  o3.postMessage = () => {};  // The opener never answers.
  assert.deepEqual(await receiveMove({self: n3, opener: o3, source: OLD, nonce: newNonce(), timeoutMs: 30, apply: async () => ({ok: true})}), {ok: false, reason: 'timeout'});
});

test('a failed apply is reported to the sender as not done', async () => {
  const {oldWin, newWin} = pair();
  const sending = sendMove({self: oldWin, win: newWin, target: NEW, getPayload: async () => ({})});
  await receiveMove({self: newWin, opener: oldWin, source: OLD, nonce: newNonce(), apply: async () => { throw Error('full'); }});
  assert.equal((await sending).ok, false);
});

// ---- Receiver applying a move, with the real sync client and list paths ----

function memory(initial = {}) {
  const m = new Map(Object.entries(initial).map(([k, v]) => [k, JSON.stringify(v)]));
  return {get length() { return m.size; }, key: i => [...m.keys()][i] ?? null, getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k)};
}
function server() {
  const lists = new Map();
  let n = 0;
  return {
    lists,
    async fetch(url, {method, headers, body}) {
      const reply = (status, data) => ({status, text: async () => (data === undefined ? '' : JSON.stringify(data))});
      if (url.endsWith('/health')) return reply(200, {ok: true});
      if (method === 'POST') {
        const edit = `edit${String(++n).padStart(18, '0')}`;
        lists.set(edit, {version: 1, data: JSON.parse(body).data});
        return reply(201, {edit_key: edit, view_key: `view${String(n).padStart(18, '0')}`, version: 1, data: lists.get(edit).data});
      }
      const entry = lists.get(headers['X-Sync-Key']);
      if (!entry) return reply(404, {error: 'unknown'});
      if (method === 'GET') return reply(200, {mode: 'edit', version: entry.version, data: entry.data});
      const request = JSON.parse(body);
      if (request.version !== entry.version) return reply(409, {version: entry.version, data: entry.data});
      entry.data = request.data; entry.version++;
      return reply(200, {version: entry.version, data: entry.data});
    },
  };
}
// The app's list and sync paths, without the DOM: what src/app.js wires into applyMove.
function fakeApp(srv, storage) {
  // The same adopt and keep-aside callbacks app.js gives the client; the join merge lives in the client.
  const sync = createSyncClient({fetchImpl: srv.fetch, storage, getWatch: () => readWatch(storage, KEYS.watch),
    getFollows: () => readFollows(storage, KEYS.follows), getSearches: () => readSearches(storage, KEYS.searches), debounceMs: 60000,
    adopt: d => adoptLists(storage, KEYS, d), onDisplaced: held => { if (!keepHeld(storage, held)) throw Error('full'); }});
  const pullSync = () => sync.pull();
  const deps = {
    storage,
    current: () => ({watch: readWatch(storage, KEYS.watch), follows: readFollows(storage, KEYS.follows), searches: readSearches(storage, KEYS.searches),
      settings: {}, syncKey: JSON.parse(storage.getItem(KEYS.sync) || 'null')?.key || null}),
    addWatch: ids => { for (const id of changeWatchList(storage, KEYS.watch, 'add', ids).changed) sync.record('add', id); },
    addFollows: codes => { for (const c of changeFollowList(storage, KEYS.follows, 'follow', codes, MAX_FOLLOWS).changed) sync.record('follow', c); },
    addSearch: s => { changeSearchList(storage, KEYS.searches, 'save-search', s); sync.record('save-search', s.id, undefined, s); },
    setSettings: () => {},
    joinLink: async key => { sync.connect(key); await pullSync(); },
  };
  return {sync, pullSync, deps};
}
const search = (id, name) => ({id, name, filters: {topic: 'Taxes'}, seen: '2026-11-10'});

test('a receiver already on its own link keeps every moved item through the next pull', async () => {
  const srv = server(), newSite = memory(), oldSite = memory({[KEYS.watch]: ['HB5', 'HB6'], [KEYS.follows]: ['A1001'], [KEYS.searches]: [search('aaaa1111', 'Water')]});
  const app = fakeApp(srv, newSite);
  newSite.setItem(KEYS.watch, JSON.stringify(['SB1']));
  const {editKey} = await app.sync.create(['SB1'], [], []);
  const result = await applyMove(collect(oldSite), app.deps);
  assert.equal(result.ok, true);
  assert.deepEqual([result.counts.watch, result.counts.follows, result.counts.searches, result.counts.sync], [2, 1, 1, 'none']);
  await app.pullSync();  // The next start or focus.
  assert.deepEqual(readWatch(newSite, KEYS.watch).sort(), ['HB5', 'HB6', 'SB1']);
  assert.deepEqual(readFollows(newSite, KEYS.follows), ['A1001']);
  assert.deepEqual(readSearches(newSite, KEYS.searches).map(s => s.id), ['aaaa1111']);
  const stored = srv.lists.get(editKey).data;
  assert.deepEqual([stored.watch.sort(), stored.follows, stored.searches.map(s => s.id)], [['HB5', 'HB6', 'SB1'], ['A1001'], ['aaaa1111']]);
});

test('moving the same link this receiver already joined adds the old browser\'s items to it', async () => {
  const srv = server(), phone = memory(), newSite = memory();
  const {editKey} = await createSyncClient({fetchImpl: srv.fetch, storage: phone, getWatch: () => ['HB1']}).create(['HB1'], [], []);
  const app = fakeApp(srv, newSite);
  app.sync.connect(editKey); await app.pullSync();
  const oldSite = memory({[KEYS.watch]: ['HB1', 'HB2'], [KEYS.sync]: {key: editKey, mode: 'edit', version: 1, pending: []}});
  const result = await applyMove(collect(oldSite), app.deps);
  assert.deepEqual([result.ok, result.counts.sync, result.counts.watch], [true, 'same', 1]);
  await app.pullSync();
  assert.deepEqual(srv.lists.get(editKey).data.watch.sort(), ['HB1', 'HB2']);
});

test('a fresh receiver joins the moved link and keeps its own bills', async () => {
  const srv = server(), phone = memory(), newSite = memory({[KEYS.watch]: ['SB9']});
  const {editKey} = await createSyncClient({fetchImpl: srv.fetch, storage: phone, getWatch: () => ['HB1']}).create(['HB1'], [], []);
  const app = fakeApp(srv, newSite);
  const oldSite = memory({[KEYS.watch]: ['HB2'], [KEYS.sync]: {key: editKey, mode: 'edit'}});
  const result = await applyMove(collect(oldSite), app.deps);
  assert.deepEqual([result.ok, result.counts.sync], [true, 'join']);
  await app.pullSync();
  assert.deepEqual(srv.lists.get(editKey).data.watch.sort(), ['HB1', 'HB2', 'SB9']);
  assert.equal(app.sync.linked.joinPending, false);
});

test('a receiver on a different link keeps it and shows the moved one as a previous link', async () => {
  const srv = server(), newSite = memory(), other = memory();
  const app = fakeApp(srv, newSite);
  const {editKey: mine} = await app.sync.create([], [], []);
  const {editKey: theirs} = await createSyncClient({fetchImpl: srv.fetch, storage: other, getWatch: () => []}).create([], [], []);
  const result = await applyMove(collect(memory({[KEYS.watch]: ['HB3'], [KEYS.sync]: {key: theirs, mode: 'edit'}})), app.deps);
  assert.deepEqual([result.ok, result.counts.sync, result.previousKey], [true, 'keep-previous', theirs]);
  assert.equal(app.sync.linked.editKey, mine);
});

test('a window closed just after its last message still delivers that message', async () => {
  const {oldWin, newWin} = pair();
  const sending = sendMove({self: oldWin, win: newWin, target: NEW, pollMs: 5, graceMs: 50, getPayload: async () => ({})});
  await receiveMove({self: newWin, opener: oldWin, source: OLD, nonce: newNonce(), apply: async () => { newWin.closed = true; return {ok: true, counts: {watch: 1}}; }});
  assert.deepEqual(await sending, {ok: true, counts: {watch: 1}});
});

test('the sender waits for the receiver\'s apply from the moment it sends, not from opening the window', async () => {
  const {oldWin, newWin} = pair();
  const sending = sendMove({self: oldWin, win: newWin, target: NEW, timeoutMs: 40, applyMs: 400, pollMs: 5, getPayload: async () => ({})});
  const slow = () => new Promise(r => setTimeout(r, 120));  // Applying takes longer than the ready timeout.
  await receiveMove({self: newWin, opener: oldWin, source: OLD, nonce: newNonce(), apply: async () => { await slow(); return {ok: true, counts: {}}; }});
  assert.equal((await sending).ok, true);
});

test('a move whose join failed says so', async () => {
  const srv = server(), newSite = memory(), app = fakeApp(srv, newSite);
  // The old browser's link was deleted meanwhile: the join's pull gets a 404 and the link is forgotten.
  const result = await applyMove(collect(memory({[KEYS.watch]: ['HB1'], [KEYS.sync]: {key: 'gone00000000000000000a', mode: 'edit'}})), {...app.deps,
    joinLink: async key => { app.sync.connect(key); try { await app.pullSync(); } catch {} }});
  assert.deepEqual([result.ok, result.counts.why], [false, 'sync']);
  assert.deepEqual(readWatch(newSite, KEYS.watch), ['HB1']);  // The bills still arrived.
});
