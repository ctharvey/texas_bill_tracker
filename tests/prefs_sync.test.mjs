import test from 'node:test';
import assert from 'node:assert/strict';
import {parseHash, buildHash, parseWatchlistFile, watchlistFile, applyOps, cleanFilters, FILTER_DEFAULTS} from '../src/prefs.js';
import {createSyncClient} from '../src/sync.js';

test('URL state round-trips filters, shared list and open bill, omitting defaults', () => {
  const filters = {...FILTER_DEFAULTS, topic: 'Energy & utilities', query: 'data center', sort: 'latest', onlyWatch: true};
  const hash = buildHash('all', filters, {list: ['HB5', 'SB12'], bill: 'HB5'});
  assert.ok(!hash.includes('chamber='));
  const parsed = parseHash(hash);
  assert.equal(parsed.view, 'all');
  assert.deepEqual(parsed.filters, {query: 'data center', topic: 'Energy & utilities', sort: 'latest', onlyWatch: true});
  assert.deepEqual([parsed.list, parsed.bill], [['HB5', 'SB12'], 'HB5']);
  assert.equal(buildHash('agencies', filters), '#agencies');
});

test('the saving page has its own linkable view', () => {
  assert.equal(parseHash('#saving').view, 'saving');
  assert.equal(buildHash('saving', {...FILTER_DEFAULTS, topic: 'Water'}), '#saving');
});

test('hash parsing rejects junk and unknown views', () => {
  const p = parseHash('#nope?list=HB5,<script>,hb 7,HB5&bill=../x&sync=short&topic=' + 'x'.repeat(300));
  assert.equal(p.view, 'all');
  assert.deepEqual(p.list, ['HB5', 'HB7']);
  assert.equal(p.bill, null);
  assert.equal(p.sync, null);
  assert.equal(p.filters.topic.length, 200);
  assert.equal(parseHash('#watchlist?sync=abcdefghijklmnopqrstuv').sync, 'abcdefghijklmnopqrstuv');
  assert.equal(parseHash('').hasFilters, false);
});

test('watchlist files: our export, plain arrays, and pasted text', () => {
  const file = watchlistFile(['HB5', 'SB12'], new Date('2026-11-10T00:00:00Z'));
  assert.deepEqual(parseWatchlistFile(file), ['HB5', 'SB12']);
  assert.deepEqual(parseWatchlistFile('["hb5","SB12","nope"]'), ['HB5', 'SB12']);
  assert.deepEqual(parseWatchlistFile('id,title\nHB 5,"Water"\nSJR 9,"Maps"\nHB5,dupe'), ['HB5', 'SJR9']);
  assert.throws(() => parseWatchlistFile('{"bills": "HB5"}'), /no list of bills/);
  assert.throws(() => parseWatchlistFile('nothing here'), /No Texas bill numbers/);
});

test('pasted text keeps bill numbers followed by punctuation', () => {
  assert.deepEqual(parseWatchlistFile('Please watch HB 1002, sjr 9 and HJR 68.'), ['HB1002', 'SJR9', 'HJR68']);
});

test('remembered filters keep only known, well-typed fields', () => {
  assert.deepEqual(cleanFilters({topic: 'Taxes', onlyWatch: 'yes', evil: 1, sort: 'latest'}), {topic: 'Taxes', sort: 'latest'});
  assert.deepEqual(cleanFilters(null), {});
});

test('applyOps replays adds and removes in order', () => {
  assert.deepEqual(applyOps(['HB1', 'HB2'], [{op: 'remove', id: 'HB1'}, {op: 'add', id: 'HB3'}, {op: 'add', id: 'HB2'}]), ['HB2', 'HB3']);
});

function fakeServer() {
  const lists = new Map();  // key -> {view, version, watch}
  let n = 0;
  const server = {
    lists,
    async fetch(url, {method, headers, body}) {
      const reply = (status, data) => ({status, text: async () => (data === undefined ? '' : JSON.stringify(data))});
      if (url.endsWith('/health')) return reply(200, {ok: true});
      const key = headers['X-Sync-Key'];
      if (method === 'POST') {
        const edit = `edit${String(++n).padStart(18, '0')}`, view = `view${String(n).padStart(18, '0')}`;
        lists.set(edit, {view, version: 1, watch: JSON.parse(body).data.watch});
        return reply(201, {edit_key: edit, view_key: view, version: 1});
      }
      const entry = lists.get(key) || [...lists.values()].find(l => l.view === key);
      if (!entry) return reply(404, {error: 'unknown'});
      const mode = lists.has(key) ? 'edit' : 'view';
      if (method === 'GET') return reply(200, {mode, version: entry.version, data: {watch: entry.watch}, ...(mode === 'edit' ? {view_key: entry.view} : {})});
      if (mode !== 'edit') return reply(403, {error: 'edit link required'});
      if (method === 'DELETE') { lists.delete(key); return reply(204); }
      const request = JSON.parse(body);
      if (request.version !== entry.version) return reply(409, {version: entry.version, data: {watch: entry.watch}});
      Object.assign(entry, {version: entry.version + 1, watch: request.data.watch});
      return reply(200, {version: entry.version, data: {watch: entry.watch}});
    },
  };
  return server;
}

const memoryStorage = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, v), removeItem: k => m.delete(k)}; };

test('two devices editing the same list both keep their changes', async () => {
  const server = fakeServer();
  let phone = ['HB1'], laptop = [];
  const a = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => phone, debounceMs: 0});
  const b = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => laptop, debounceMs: 0});
  const {editKey, viewKey} = await a.create(phone);
  b.connect(editKey);
  laptop = (await b.pull()).watch;
  assert.deepEqual(laptop, ['HB1']);
  // Phone adds HB2 and saves; the laptop, still on version 1, removes HB1.
  phone = [...phone, 'HB2']; a.record('add', 'HB2'); phone = await a.flush();
  laptop = laptop.filter(x => x !== 'HB1'); b.record('remove', 'HB1'); laptop = await b.flush();
  assert.deepEqual(laptop, ['HB2']);  // Conflict replayed the removal onto the phone's newer list.
  assert.deepEqual((await a.pull()).watch, ['HB2']);
  // The view link sees the list but cannot change it.
  const viewer = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], debounceMs: 0});
  viewer.connect(viewKey);
  assert.deepEqual(await viewer.pull(), {mode: 'view', watch: ['HB2']});
  viewer.record('add', 'HB9');
  assert.equal(viewer.linked.pending, 0);
  await assert.rejects(viewer.remove(), /Only the edit link/);
});

test('a deleted list unlinks every device', async () => {
  const server = fakeServer();
  const storage = memoryStorage();
  const a = createSyncClient({fetchImpl: server.fetch, storage, getWatch: () => ['HB1'], debounceMs: 0});
  const {editKey} = await a.create(['HB1']);
  const b = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], debounceMs: 0});
  b.connect(editKey);
  await a.remove();
  assert.equal(a.linked, null);
  assert.equal(storage.getItem('tx-bill-atlas-sync-v1'), null);
  await assert.rejects(b.pull(), /no longer exists/);
  assert.equal(b.linked, null);
});

test('unavailable server is detected, not thrown', async () => {
  const client = createSyncClient({fetchImpl: async () => ({status: 404, text: async () => '<html>'}), storage: memoryStorage(), getWatch: () => []});
  assert.equal(await client.isAvailable(), false);
  const offline = createSyncClient({fetchImpl: async () => { throw TypeError('network'); }, storage: memoryStorage(), getWatch: () => []});
  assert.equal(await offline.isAvailable(), false);
});

test('member pages keep their code in the address; bad codes and other views drop it', () => {
  assert.equal(buildHash('member', {}, {member: 'A4875'}), '#member?code=A4875');
  assert.equal(buildHash('member', {}, {member: 'A4875', bill: 'HB5'}), '#member?code=A4875&bill=HB5');
  assert.deepEqual([parseHash('#member?code=a4875').view, parseHash('#member?code=a4875').member], ['member', 'A4875']);
  assert.equal(parseHash('#member?code=A4875&bill=HB5').bill, 'HB5');
  assert.equal(parseHash('#member?code=<script>').member, null);
  assert.equal(parseHash('#all?code=A4875').member, null);
  assert.equal(buildHash('all', {}, {member: 'A4875'}), '#all');
  assert.equal(buildHash('member', {}, {member: 'X1'}), '#member');
});
