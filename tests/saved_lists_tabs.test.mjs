// Several open tabs share one storage. A tab holding an old copy in memory must not erase what another tab saved,
// and the sync client must not write over a link another tab changed while its request was out.
import test from 'node:test';
import assert from 'node:assert/strict';
import {changeWatchList, changeFollowList, changeSearchList, readWatch, readFollows, readSearches} from '../src/core/lists.js';
import {createSyncClient} from '../src/sync.js';

const W = 'tx-bill-atlas-watch-90r', F = 'tx-bill-atlas-follow-90r', S = 'tx-bill-atlas-searches-90r', SYNC = 'tx-bill-atlas-sync-v1';
const memoryStorage = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k)}; };
const search = (id, name) => ({id, name, filters: {topic: 'Taxes'}, seen: '2026-11-10'});

test('a stale tab starring a bill keeps the bill another tab saved', () => {
  const storage = memoryStorage();
  storage.setItem(W, JSON.stringify(['HB1']));
  const staleTab = new Set(readWatch(storage, W));        // Opened earlier; never saw HB2.
  changeWatchList(storage, W, 'add', ['HB2']);              // The other tab.
  const {list, changed} = changeWatchList(storage, W, 'add', ['HB3']);
  assert.deepEqual(staleTab, new Set(['HB1']));
  assert.deepEqual(list, ['HB1', 'HB2', 'HB3']);
  assert.deepEqual(changed, ['HB3']);
  assert.deepEqual(changeWatchList(storage, W, 'remove', ['HB1', 'HB9']), {list: ['HB2', 'HB3'], changed: ['HB1']});
});

test('stale tabs keep each other\'s follows and saved searches', () => {
  const storage = memoryStorage();
  changeFollowList(storage, F, 'follow', ['A1001'], 200);
  assert.deepEqual(changeFollowList(storage, F, 'follow', ['A1002', 'A1001'], 200), {list: ['A1001', 'A1002'], changed: ['A1002']});
  assert.deepEqual(changeFollowList(storage, F, 'follow', ['A1003'], 2).changed, []);  // At the cap.
  assert.deepEqual(changeFollowList(storage, F, 'unfollow', ['A1001'], 200).list, ['A1002']);
  changeSearchList(storage, S, 'save-search', search('aaaa1111', 'Water'));
  changeSearchList(storage, S, 'save-search', search('bbbb2222', 'Energy'));
  assert.deepEqual(readSearches(storage, S).map(s => s.id), ['aaaa1111', 'bbbb2222']);
  assert.deepEqual(changeSearchList(storage, S, 'delete-search', 'aaaa1111').map(s => s.id), ['bbbb2222']);
});

test('junk in storage reads as empty lists, not a crash', () => {
  const storage = memoryStorage();
  storage.setItem(W, '{"HB1":true}'); storage.setItem(F, 'not json'); storage.setItem(S, '"x"');
  assert.deepEqual([readWatch(storage, W), readFollows(storage, F), readSearches(storage, S)], [[], [], []]);
  storage.setItem(W, JSON.stringify(['HB1', 7, 'HB1']));
  assert.deepEqual(readWatch(storage, W), ['HB1']);
});

// A sync server whose replies can be held back to stage interleavings.
function server() {
  const lists = new Map(), held = [];
  let n = 0, hold = false, down = false;
  const s = {
    lists, set hold(v) { hold = v; }, set down(v) { down = v; },
    release() { while (held.length) held.shift()(); },
    async fetch(url, {method, headers, body}) {
      if (down) throw TypeError('network');
      const reply = (status, data) => ({status, text: async () => (data === undefined ? '' : JSON.stringify(data))});
      const answer = () => {
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
      };
      if (!hold) return answer();
      return new Promise(resolve => held.push(() => resolve(answer())));
    },
  };
  return s;
}
const tick = () => new Promise(r => setTimeout(r, 0));
const client = (srv, storage, watch = () => readWatch(storage, W)) => createSyncClient({fetchImpl: srv.fetch, storage, getWatch: watch, debounceMs: 60000});

test('a join whose first pull failed still merges this browser\'s bills after a restart', async () => {
  const srv = server(), phone = memoryStorage(), laptop = memoryStorage();
  const {editKey} = await client(srv, phone).create(['HB1']);
  laptop.setItem(W, JSON.stringify(['HB7']));
  const first = client(srv, laptop);
  first.connect(editKey);
  srv.down = true;
  await assert.rejects(first.pull());
  changeWatchList(laptop, W, 'add', ['HB8']);  // Starred while the join had not gone through.
  srv.down = false;
  const restarted = client(srv, laptop);
  assert.equal(restarted.linked.joinPending, true);  // Survives the restart: the next pull is still a join.
  // What the app's pullSync does while joinPending: adopt the link's list, then add this browser's own bills.
  const local = readWatch(laptop, W), pulled = await restarted.pull();
  laptop.setItem(W, JSON.stringify(pulled.watch));
  for (const id of changeWatchList(laptop, W, 'add', local.filter(id => !pulled.watch.includes(id))).changed) restarted.record('add', id);
  restarted.joinDone();
  assert.equal(restarted.linked.joinPending, false);
  await restarted.flush();
  assert.deepEqual(srv.lists.get(editKey).data.watch.sort(), ['HB1', 'HB7', 'HB8']);
});

test('an op queued by one tab is sent by another tab\'s pull', async () => {
  const srv = server(), storage = memoryStorage();
  const {editKey} = await client(srv, storage).create(['HB1']);
  const a = client(srv, storage), b = client(srv, storage);
  changeWatchList(storage, W, 'add', ['HB1', 'HB2']);
  a.record('add', 'HB2');  // Tab A is closed before its debounced write.
  await b.pull();
  assert.deepEqual(srv.lists.get(editKey).data.watch, ['HB1', 'HB2']);
  assert.equal(client(srv, storage).linked.pending, 0);
});

test('a finished write keeps an op another tab queued while it was out', async () => {
  const srv = server(), storage = memoryStorage();
  await client(srv, storage).create([]);
  const a = client(srv, storage), b = client(srv, storage);
  changeWatchList(storage, W, 'add', ['HB1']); a.record('add', 'HB1');
  srv.hold = true;
  const out = a.flush(); await tick();
  changeWatchList(storage, W, 'add', ['HB2']); b.record('add', 'HB2');
  srv.hold = false; srv.release();
  await out;
  const left = JSON.parse(storage.getItem(SYNC)).pending;
  assert.deepEqual(left.map(o => o.id), ['HB2']);
});

test('a write that finishes after another tab forgot the link leaves storage alone', async () => {
  const srv = server(), storage = memoryStorage();
  await client(srv, storage).create([]);
  const a = client(srv, storage), b = client(srv, storage);
  a.record('add', 'HB1');
  srv.hold = true;
  const out = a.flush(); await tick();
  b.forget();
  srv.hold = false; srv.release();
  assert.equal(await out, null);
  assert.equal(storage.getItem(SYNC), null);
});

test('a pull that finishes after another tab joined a different link leaves that link alone', async () => {
  const srv = server(), storage = memoryStorage(), other = memoryStorage();
  await client(srv, storage).create(['HB1']);
  const {editKey: second} = await client(srv, other).create(['HB9']);
  const a = client(srv, storage), b = client(srv, storage);
  srv.hold = true;
  const out = a.pull(); await tick();
  b.connect(second);
  srv.hold = false; srv.release();
  assert.equal(await out, null);
  const stored = JSON.parse(storage.getItem(SYNC));
  assert.deepEqual([stored.key, stored.joinPending, stored.mode], [second, true, null]);
});

test('a 404 for a link another tab already replaced does not unlink the new one', async () => {
  const srv = server(), storage = memoryStorage(), other = memoryStorage();
  const {editKey: first} = await client(srv, storage).create([]);
  const {editKey: second} = await client(srv, other).create([]);
  srv.lists.delete(first);
  const a = client(srv, storage), b = client(srv, storage);
  srv.hold = true;
  const out = a.pull(); await tick();
  b.connect(second);
  srv.hold = false; srv.release();
  assert.equal(await out, null);
  assert.equal(JSON.parse(storage.getItem(SYNC)).key, second);
});
