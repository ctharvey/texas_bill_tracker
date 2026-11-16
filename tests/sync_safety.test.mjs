// Sync never writes a whole list over the other side unless that side is known to be based on it, and never drops
// an item to fit a limit without keeping it aside. Each test is a counterexample from the 2026-11-16 review.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createSyncClient} from '../src/sync.js';
import {readWatch, readFollows, readSearches, changeWatchList, changeSearchList, adoptLists} from '../src/core/lists.js';
import {keepHeld, HELD_KEY} from '../src/core/move.js';

// Debounced writes wait 60 s here (tests flush by hand); don't let those timers hold the run open.
const realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms, ...rest) => { const t = realSetTimeout(fn, ms, ...rest); if (ms >= 1000) t.unref?.(); return t; };

const W = 'tx-bill-atlas-watch-90r', F = 'tx-bill-atlas-follow-90r', S = 'tx-bill-atlas-searches-90r', SYNC = 'tx-bill-atlas-sync-v1';
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k)}; };
const tick = () => new Promise(r => setTimeout(r, 0));

// Replace-on-write with versions, like scripts/sync_service.py (it rejects over-limit lists with a 400).
function server() {
  const lists = new Map(), held = [], fail = {};
  let n = 0, hold = false;
  const s = {
    lists, fail, set hold(v) { hold = v; },
    release() { while (held.length) held.shift()(); },
    async fetch(url, {method, headers, body}) {
      const reply = (status, data) => ({status, text: async () => (data === undefined ? '' : JSON.stringify(data))});
      const answer = () => {
        if (url.endsWith('/health')) return reply(200, {ok: true});
        if (fail[method]) { fail[method]--; return reply(503, {error: 'down'}); }
        if (method === 'POST') {
          const edit = `edit${String(++n).padStart(18, '0')}`;
          lists.set(edit, {version: 1, data: JSON.parse(body).data});
          return reply(201, {edit_key: edit, view_key: `view${String(n).padStart(18, '0')}`, version: 1, data: lists.get(edit).data});
        }
        const entry = lists.get(headers['X-Sync-Key']);
        if (!entry) return reply(404, {error: 'unknown'});
        if (method === 'DELETE') { lists.delete(headers['X-Sync-Key']); return reply(204); }
        if (method === 'GET') return reply(200, {mode: 'edit', version: entry.version, data: entry.data});
        const request = JSON.parse(body);
        if (request.version !== entry.version) return reply(409, {version: entry.version, data: entry.data});
        const d = request.data;
        if (d.watch.length > 500 || (d.follows || []).length > 200 || (d.searches || []).length > 20) return reply(400, {error: 'over the limit'});
        entry.data = d; entry.version++;
        return reply(200, {version: entry.version, data: entry.data});
      };
      const result = answer();
      return hold ? new Promise(resolve => held.push(() => resolve(result))) : result;
    },
  };
  return s;
}
const search = (id, name = id) => ({id, name, filters: {topic: 'Taxes'}, seen: '2026-11-10'});
const ids = n => Array.from({length: n}, (_, i) => `s${String(i).padStart(7, '0')}`);

// What src/app.js wires in: adopted lists go to storage, items that do not fit are kept aside.
const KEYS = {watch: W, follows: F, searches: S};
const appDevice = (srv, storage = memory()) => device(srv, storage, {adopt: d => adoptLists(storage, KEYS, d),
  onDisplaced: held => { if (!keepHeld(storage, held)) throw Error('could not keep aside'); }});
const heldOf = storage => JSON.parse(storage.getItem(HELD_KEY) || '{"watch":[],"follows":[],"searches":[]}');
function device(srv, storage = memory(), extra = {}) {
  return createSyncClient({fetchImpl: srv.fetch, storage, debounceMs: 60000,
    getWatch: () => readWatch(storage, W), getFollows: () => readFollows(storage, F), getSearches: () => readSearches(storage, S), ...extra});
}

test('a join whose merging write failed never lets the next star replace the link\'s list', async () => {
  const srv = server(), phone = memory(), laptop = memory();
  phone.setItem(W, JSON.stringify(['HB1']));
  const {editKey} = await device(srv, phone).create(['HB1'], [], []);
  laptop.setItem(W, JSON.stringify(['HB7'])); laptop.setItem(F, JSON.stringify(['A1001']));
  const client = device(srv, laptop);
  client.connect(editKey);
  srv.fail.PUT = 1;
  await assert.rejects(client.pull());
  changeWatchList(laptop, W, 'add', ['HB8']); client.record('add', 'HB8');
  await client.flush();
  assert.ok(srv.lists.get(editKey).data.watch.includes('HB1'), JSON.stringify(srv.lists.get(editKey).data.watch));
});

test('joining a link past the saved-search limit keeps this browser\'s extra searches aside, never drops them', async () => {
  const srv = server(), phone = memory(), laptop = memory();
  const linkSearches = ids(15).map(id => search(id)), own = ids(25).slice(15).map(id => search(`t${id.slice(1)}`));
  phone.setItem(S, JSON.stringify(linkSearches));
  const {editKey} = await appDevice(srv, phone).create([], [], linkSearches);
  laptop.setItem(S, JSON.stringify(own));
  const client = appDevice(srv, laptop);
  client.connect(editKey);
  await client.pull();
  const kept = new Set([...readSearches(laptop, S), ...heldOf(laptop).searches].map(x => x.id));
  assert.deepEqual(own.filter(x => !kept.has(x.id)), []);
  assert.equal(srv.lists.get(editKey).data.searches.length, 20);
  assert.equal(heldOf(laptop).searches.length, 5);
});

test('a bill starred while the link is being created reaches the link and stays', async () => {
  const srv = server(), storage = memory();
  storage.setItem(W, JSON.stringify(['HB1']));
  const client = appDevice(srv, storage);
  srv.hold = true;
  const creating = client.create(readWatch(storage, W), [], []); await tick();
  changeWatchList(storage, W, 'add', ['HB2']);  // No link yet: saved here only.
  srv.hold = false; srv.release();
  const {editKey} = await creating;
  await client.pull();
  assert.deepEqual([readWatch(storage, W), srv.lists.get(editKey).data.watch], [['HB1', 'HB2'], ['HB1', 'HB2']]);
});

test('a link created while another tab joined one leaves the joined link in place', async () => {
  const srv = server(), storage = memory(), other = memory();
  other.setItem(W, JSON.stringify(['HB9']));
  const {editKey: joined} = await appDevice(srv, other).create(['HB9'], [], []);
  const a = appDevice(srv, storage), b = appDevice(srv, storage);
  srv.hold = true;
  const creating = a.create([], [], []); await tick();
  b.connect(joined);
  srv.hold = false; srv.release();
  await assert.rejects(creating, /another sync link/);
  assert.equal(JSON.parse(storage.getItem(SYNC)).key, joined);
});

test('a new saved search that no longer fits the link after a conflict is kept aside, not dropped', async () => {
  const srv = server(), x = memory(), y = memory();
  const first = ids(18).map(id => search(id));
  x.setItem(S, JSON.stringify(first));
  const xc = appDevice(srv, x), {editKey} = await xc.create([], [], first);
  const yc = appDevice(srv, y);
  yc.connect(editKey); await yc.pull();
  for (const id of ['y0000001', 'y0000002']) { changeSearchList(y, S, 'save-search', search(id)); yc.record('save-search', id, undefined, search(id)); }
  await yc.flush();
  changeSearchList(x, S, 'save-search', search('x0000099')); xc.record('save-search', 'x0000099', undefined, search('x0000099'));
  await xc.flush();
  assert.equal(srv.lists.get(editKey).data.searches.length, 20);
  assert.deepEqual(heldOf(x).searches.map(s => s.id), ['x0000099']);
});

test('joining past 500 bills keeps the extra bills aside and the link keeps syncing', async () => {
  const srv = server(), phone = memory(), laptop = memory();
  const theirs = Array.from({length: 300}, (_, i) => `HB${i + 1}`), mine = Array.from({length: 300}, (_, i) => `SB${i + 1}`);
  phone.setItem(W, JSON.stringify(theirs));
  const {editKey} = await appDevice(srv, phone).create(theirs, [], []);
  laptop.setItem(W, JSON.stringify(mine));
  const client = appDevice(srv, laptop);
  client.connect(editKey);
  await client.pull();
  assert.equal(srv.lists.get(editKey).data.watch.length, 500);
  const kept = new Set([...readWatch(laptop, W), ...heldOf(laptop).watch]);
  assert.deepEqual(mine.filter(id => !kept.has(id)), []);
  changeWatchList(laptop, W, 'remove', ['HB1']); client.record('remove', 'HB1');
  await client.flush();  // No 400: the link is still writable.
  assert.equal(srv.lists.get(editKey).data.watch.includes('HB1'), false);
});

test('deleting a link leaves alone a link another tab joined meanwhile', async () => {
  const srv = server(), storage = memory(), other = memory();
  const {editKey: first} = await appDevice(srv, storage).create([], [], []);
  const {editKey: second} = await appDevice(srv, other).create([], [], []);
  const a = appDevice(srv, storage), b = appDevice(srv, storage);
  srv.hold = true;
  const removing = a.remove(); await tick();
  b.connect(second);
  srv.hold = false; srv.release();
  await removing;
  assert.equal(JSON.parse(storage.getItem(SYNC)).key, second);
  assert.equal(srv.lists.has(first), false);
});

test('a pull that overlaps another write never makes the next star erase a bill on the link', async () => {
  const srv = server(), storage = memory();
  storage.setItem(W, JSON.stringify(['HB1'])); storage.setItem(S, JSON.stringify([search('s0000001')]));
  const client = appDevice(srv, storage), {editKey} = await client.create(['HB1'], [], []);  // Searches not sent yet.
  const saved = JSON.parse(storage.getItem(SYNC)); saved.merged = {}; storage.setItem(SYNC, JSON.stringify(saved));
  srv.hold = true;
  const pulling = client.pull(); await tick();             // GET out; the link's searches lack this browser's.
  changeWatchList(storage, W, 'add', ['HB2']); client.record('add', 'HB2');
  const writing = client.flush(); await tick();           // A write out at the same time.
  srv.hold = false;
  for (let i = 0; i < 5; i++) { srv.release(); await tick(); }
  await Promise.all([pulling, writing]);
  changeWatchList(storage, W, 'add', ['HB3']); client.record('add', 'HB3');
  await client.flush(); await client.pull();
  assert.deepEqual(srv.lists.get(editKey).data.watch.sort(), ['HB1', 'HB2', 'HB3']);
  assert.deepEqual(readWatch(storage, W).sort(), ['HB1', 'HB2', 'HB3']);
});

test('a join stored by the previous version (mode null, no flag) still adds this browser\'s bills', async () => {
  const srv = server(), phone = memory(), laptop = memory();
  phone.setItem(W, JSON.stringify(['HB1']));
  const {editKey} = await appDevice(srv, phone).create(['HB1'], [], []);
  laptop.setItem(W, JSON.stringify(['HB7']));
  laptop.setItem(SYNC, JSON.stringify({key: editKey, mode: null, viewKey: null, version: 0, pending: [], merged: {}}));
  const client = appDevice(srv, laptop);
  assert.equal(client.linked.joinPending, true);
  await client.pull();
  assert.deepEqual([srv.lists.get(editKey).data.watch.sort(), readWatch(laptop, W).sort()], [['HB1', 'HB7'], ['HB1', 'HB7']]);
  assert.equal(client.linked.joinPending, false);
});

test('lists that cannot be saved are not marked as synced', async () => {
  const srv = server(), storage = memory(), phone = memory();
  phone.setItem(W, JSON.stringify(['HB1']));
  const {editKey} = await appDevice(srv, phone).create(['HB1'], [], []);
  const full = device(srv, storage, {adopt: () => { throw Error('QuotaExceededError'); }});
  full.connect(editKey);
  await assert.rejects(full.pull(), /Quota/);
  assert.equal(JSON.parse(storage.getItem(SYNC)).version, 0);
});
