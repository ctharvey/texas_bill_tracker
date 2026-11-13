import test from 'node:test';
import assert from 'node:assert/strict';
import {parseHash, buildHash, parseWatchlistFile, watchlistFile, applyOps, cleanFilters, FILTER_DEFAULTS, cleanFollows, MAX_FOLLOWS,
  applyFollowOps, profileFile, parseProfileFile, cleanSearches, applySearchOps, searchName, newSearchId, MAX_SEARCHES} from '../src/prefs.js';

test('followed legislators keep valid member codes only, unique, in order, capped', () => {
  assert.deepEqual(cleanFollows(['A2345', 'A2345', 'a2345', 'B1234', 7, null, '../x', 'A12', 'A123']), ['A2345', 'A123']);
  assert.deepEqual(cleanFollows('A2345'), []);
  assert.deepEqual(cleanFollows(null), []);
  assert.equal(cleanFollows(Array.from({length: 300}, (_, i) => `A${1000 + i}`)).length, MAX_FOLLOWS);
});
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

// Like sync_service.py after follows: a write without `follows` keeps the stored ones; view links get bills only.
function followsServer({keeps = true} = {}) {
  const lists = new Map();
  let n = 0;
  const server = {
    lists, puts: 0,
    // keeps=false acts like the server before follows: it stores and returns the watchlist only.
    set keeps(value) { keeps = value; },
    async fetch(url, {method, headers, body}) {
      const reply = (status, data) => ({status, text: async () => (data === undefined ? '' : JSON.stringify(data))});
      if (url.endsWith('/health')) return reply(200, {ok: true});
      const key = headers['X-Sync-Key'];
      if (method === 'POST') {
        const edit = `edit${String(++n).padStart(18, '0')}`, view = `view${String(n).padStart(18, '0')}`;
        const data = JSON.parse(body).data;
        lists.set(edit, {view, version: 1, data: {watch: data.watch, ...(data.follows && keeps ? {follows: data.follows} : {})}});
        return reply(201, {edit_key: edit, view_key: view, version: 1, data: lists.get(edit).data});
      }
      const entry = lists.get(key) || [...lists.values()].find(l => l.view === key);
      if (!entry) return reply(404, {error: 'unknown'});
      const mode = lists.has(key) ? 'edit' : 'view';
      if (method === 'GET') return reply(200, {mode, version: entry.version, data: mode === 'edit' ? entry.data : {watch: entry.data.watch}});
      if (mode !== 'edit') return reply(403, {error: 'edit link required'});
      server.puts++;
      const request = JSON.parse(body);
      if (request.version !== entry.version) return reply(409, {version: entry.version, data: entry.data});
      if (!keeps) { const {follows, ...rest} = request.data; request.data = rest; }
      entry.data = {...request.data, ...(request.data.follows || !entry.data.follows ? {} : {follows: entry.data.follows})};
      entry.version++;
      return reply(200, {version: entry.version, data: entry.data});
    },
  };
  return server;
}

test('follow ops replay separately from bill ops', () => {
  const ops = [{op: 'add', id: 'HB1'}, {op: 'follow', id: 'A1001'}, {op: 'unfollow', id: 'A2002'}, {op: 'remove', id: 'HB2'}];
  assert.deepEqual(applyOps(['HB2'], ops), ['HB1']);
  assert.deepEqual(applyFollowOps(['A2002', 'A3003'], ops), ['A3003', 'A1001']);
});

test('an old sync server that drops follows never clears them and is not rewritten every pull', async () => {
  const server = fakeServer();  // Stores only the watchlist, like the server before follows.
  let follows = ['A1001'];
  const phone = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => ['HB1'], getFollows: () => follows, debounceMs: 0});
  const {editKey} = await phone.create(['HB1']);
  assert.equal(phone.follows, null);  // Unknown, so the device keeps its own.
  const laptop = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], getFollows: () => ['A2002'], debounceMs: 0});
  laptop.connect(editKey);
  const first = await laptop.pull();
  assert.deepEqual([first.watch, first.follows], [['HB1'], null]);
  const versionAfterFirst = server.lists.get(editKey).version;
  await laptop.pull(); await laptop.pull();
  assert.equal(server.lists.get(editKey).version, versionAfterFirst);  // One merge attempt per session, not per pull.
  phone.record('follow', 'A3003'); follows = [...follows, 'A3003'];
  await phone.flush();
  assert.equal(phone.follows, null);
});

test('two devices bringing follows to one link keep both, then sync unfollows', async () => {
  const server = followsServer();
  let phoneFollows = ['A1001'], laptopFollows = ['A2002'];
  const phone = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => ['HB1'], getFollows: () => phoneFollows, debounceMs: 0});
  const laptop = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], getFollows: () => laptopFollows, debounceMs: 0});
  const {editKey, viewKey} = await phone.create(['HB1']);
  assert.deepEqual(phone.follows, ['A1001']);
  laptop.connect(editKey);
  const joined = await laptop.pull();
  assert.deepEqual([joined.watch, joined.follows], [['HB1'], ['A1001', 'A2002']]);  // Union, not replace.
  laptopFollows = joined.follows;
  phoneFollows = (await phone.pull()).follows;
  assert.deepEqual(phoneFollows, ['A1001', 'A2002']);
  // Once merged, the link's list wins: an unfollow on one device reaches the other.
  laptopFollows = ['A2002']; laptop.record('unfollow', 'A1001'); await laptop.flush();
  assert.deepEqual((await phone.pull()).follows, ['A2002']);
  // An old cached page writing only bills leaves follows alone.
  const entry = server.lists.get(editKey);
  await server.fetch('/api/sync', {method: 'PUT', headers: {'X-Sync-Key': editKey}, body: JSON.stringify({version: entry.version, data: {watch: ['HB9']}})});
  assert.deepEqual((await phone.pull()).follows, ['A2002']);
  // The view-only link sees bills, never follows.
  const viewer = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], debounceMs: 0});
  viewer.connect(viewKey);
  assert.deepEqual(await viewer.pull(), {mode: 'view', watch: ['HB9']});
});

test('devices that synced before the server kept follows still merge, not replace, after it is upgraded', async () => {
  const server = followsServer({keeps: false});
  const phoneStore = memoryStorage(), laptopStore = memoryStorage();
  let phoneFollows = ['A1001'], laptopFollows = ['A2002'];
  const open = (storage, get) => createSyncClient({fetchImpl: server.fetch, storage, getWatch: () => [], getFollows: get, debounceMs: 0});
  const {editKey} = await open(phoneStore, () => phoneFollows).create([]);
  const laptop = open(laptopStore, () => laptopFollows);
  laptop.connect(editKey);
  assert.equal((await laptop.pull()).follows, null);
  server.keeps = true;  // The sync service is updated; both devices reload the page.
  const phone2 = open(phoneStore, () => phoneFollows), laptop2 = open(laptopStore, () => laptopFollows);
  phoneFollows = (await phone2.pull()).follows;
  laptopFollows = (await laptop2.pull()).follows;
  assert.deepEqual(laptopFollows, ['A1001', 'A2002']);
  assert.deepEqual((await phone2.pull()).follows, ['A1001', 'A2002']);
});

test('concurrent follow changes on two devices both survive a conflict', async () => {
  const server = followsServer();
  let a = ['A1001', 'A2002'], b;
  const phone = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], getFollows: () => a, debounceMs: 0});
  const {editKey} = await phone.create([]);
  const laptop = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], getFollows: () => b, debounceMs: 0});
  b = [];
  laptop.connect(editKey);
  b = (await laptop.pull()).follows;
  a = [...a, 'A3003']; phone.record('follow', 'A3003'); await phone.flush();
  b = b.filter(c => c !== 'A1001'); laptop.record('unfollow', 'A1001'); await laptop.flush();  // Stale: conflicts.
  assert.deepEqual(laptop.follows, ['A2002', 'A3003']);
  assert.deepEqual((await phone.pull()).follows, ['A2002', 'A3003']);
});

test('profile files carry bills and follows; older watchlist files still import', () => {
  const file = profileFile({watch: new Set(['HB5', 'SB12']), follows: ['A1001', 'bad']}, new Date('2026-11-12T00:00:00Z'));
  const data = JSON.parse(file);
  assert.equal(data.format, 'texas-bill-atlas-profile-v1');
  assert.deepEqual(data.lists, [{id: 'main', name: 'Watchlist', bills: ['HB5', 'SB12']}]);
  assert.deepEqual(parseProfileFile(file), {bills: ['HB5', 'SB12'], follows: ['A1001'], searches: []});
  assert.deepEqual(parseProfileFile(watchlistFile(['HB5'])), {bills: ['HB5'], follows: [], searches: []});
  assert.deepEqual(parseProfileFile('HB 7 and SB 9'), {bills: ['HB7', 'SB9'], follows: [], searches: []});
  assert.deepEqual(parseProfileFile(profileFile({watch: [], follows: ['A1001']})), {bills: [], follows: ['A1001'], searches: []});
  assert.throws(() => parseProfileFile(profileFile({})), /no bills or legislators/);
});

// A sync server that stores the optional sections in `known` (as sync_service.py: a write omitting one keeps it;
// view links get bills only) and silently drops the rest, like a release that predates them.
function sectionsServer(known = ['follows', 'searches']) {
  const lists = new Map();
  let n = 0;
  const keep = data => Object.fromEntries(Object.entries(data).filter(([k]) => k === 'watch' || known.includes(k)));
  const server = {
    lists, writes: 0,
    set known(value) { known = value; },
    async fetch(url, {method, headers, body}) {
      const reply = (status, data) => ({status, text: async () => (data === undefined ? '' : JSON.stringify(data))});
      if (url.endsWith('/health')) return reply(200, {ok: true});
      const key = headers['X-Sync-Key'];
      if (method === 'POST') {
        const edit = `edit${String(++n).padStart(18, '0')}`, view = `view${String(n).padStart(18, '0')}`;
        lists.set(edit, {view, version: 1, data: keep(JSON.parse(body).data)});
        return reply(201, {edit_key: edit, view_key: view, version: 1, data: lists.get(edit).data});
      }
      const entry = lists.get(key) || [...lists.values()].find(l => l.view === key);
      if (!entry) return reply(404, {error: 'unknown'});
      const mode = lists.has(key) ? 'edit' : 'view';
      if (method === 'GET') return reply(200, {mode, version: entry.version, data: mode === 'edit' ? keep(entry.data) : {watch: entry.data.watch}});
      if (mode !== 'edit') return reply(403, {error: 'edit link required'});
      const request = JSON.parse(body);
      if (request.version !== entry.version) return reply(409, {version: entry.version, data: keep(entry.data)});
      server.writes++;
      const incoming = keep(request.data);
      entry.data = {...Object.fromEntries(known.filter(k => k in entry.data).map(k => [k, entry.data[k]])), ...incoming};
      entry.version++;
      return reply(200, {version: entry.version, data: keep(entry.data)});
    },
  };
  return server;
}
const search = (id, name, filters = {topic: 'Taxes'}, seen = '2026-11-10') => ({id, name, filters, seen});

test('saved searches: cleaning, ops, names and ids', () => {
  assert.deepEqual(cleanSearches([search('abcd1234', ' Taxes '), search('abcd1234', 'dupe'), {id: 'BAD', name: 'x'},
    {id: 'abcd5678', name: ''}, {...search('abcd9999', 'big'), filters: {query: 'x'.repeat(200), topic: 'y'.repeat(200), agency: 'z'.repeat(200)}}]),
  [search('abcd1234', 'Taxes')]);
  const ops = [{op: 'save-search', id: 'aaaa1111', value: search('aaaa1111', 'A')}, {op: 'add', id: 'HB1'},
    {op: 'save-search', id: 'bbbb2222', value: search('bbbb2222', 'B renamed')}, {op: 'delete-search', id: 'cccc3333'}];
  assert.deepEqual(applySearchOps([search('bbbb2222', 'B'), search('cccc3333', 'C')], ops).map(s => s.name), ['B renamed', 'A']);
  assert.deepEqual(applyOps(['HB2'], ops), ['HB2', 'HB1']);
  assert.equal(searchName({query: ' water ', topic: 'Energy', chamber: 'Senate', sort: 'latest'}), '“water” · Energy · Senate');
  assert.equal(searchName({}), 'All bills');
  assert.equal(searchName({chamber: 'House', party: 'Bipartisan'}), 'House · Bipartisan authors');
  assert.equal(buildHash('all', {...FILTER_DEFAULTS, party: 'Democratic'}), '#all?party=Democratic');
  assert.equal(parseHash('#all?party=Republican').filters.party, 'Republican');
  assert.equal(parseHash('#all?outlook=Not%20rated').filters.outlook, 'No hearing yet');  // links from before the rename
  assert.equal(cleanFilters({outlook: 'Not rated'}).outlook, 'No hearing yet');           // saved and remembered filters
  assert.match(newSearchId(), /^[a-z0-9]{10}$/);
  assert.equal(cleanSearches(Array.from({length: 30}, (_, i) => search(`id${String(i).padStart(6, '0')}`, `S${i}`))).length, MAX_SEARCHES);
});

test('profile files carry saved searches', () => {
  const file = profileFile({watch: ['HB5'], follows: [], searches: [search('abcd1234', 'Taxes')]});
  assert.deepEqual(parseProfileFile(file), {bills: ['HB5'], follows: [], searches: [search('abcd1234', 'Taxes')]});
  assert.deepEqual(parseProfileFile(profileFile({searches: [search('abcd1234', 'Taxes')]})).searches.length, 1);
});

test('profile files carry the colour theme when it is a theme id', () => {
  assert.equal(parseProfileFile(profileFile({watch: ['HB5'], theme: 'ranch'})).theme, 'ranch');
  assert.equal('theme' in JSON.parse(profileFile({watch: ['HB5'], theme: '../x'})), false);
  assert.equal('theme' in parseProfileFile(profileFile({watch: ['HB5']})), false);
  const forged = JSON.stringify({...JSON.parse(profileFile({watch: ['HB5']})), theme: '<b>'});
  assert.equal('theme' in parseProfileFile(forged), false);
});

test('the colour theme syncs last write wins; a device that never changed it does not overwrite it', async () => {
  const server = sectionsServer(['follows', 'searches', 'theme']);
  const phone = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], getTheme: () => 'bluebonnet', debounceMs: 0});
  const {editKey} = await phone.create([]);
  assert.equal(phone.theme, 'bluebonnet');
  const laptop = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => ['HB5'], getTheme: () => 'granite', debounceMs: 0});
  laptop.connect(editKey);
  assert.equal((await laptop.pull()).theme, 'bluebonnet');  // Joining takes the link's theme, not this device's.
  laptop.record('add', 'HB5'); await laptop.flush();        // A write without a theme change keeps the link's.
  assert.equal((await phone.pull()).theme, 'bluebonnet');
  laptop.record('theme', 'ranch'); await laptop.flush();
  assert.equal((await phone.pull()).theme, 'ranch');
  phone.record('theme', 'lone-star'); phone.record('theme', 'granite'); await phone.flush();
  assert.equal((await laptop.pull()).theme, 'granite');
});

test('a server that predates the theme drops it harmlessly', async () => {
  const server = sectionsServer(['follows', 'searches']);
  const phone = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => ['HB5'], getTheme: () => 'ranch', debounceMs: 0});
  await phone.create(['HB5']);
  assert.equal(phone.theme, null);
  phone.record('theme', 'bluebonnet'); await phone.flush();
  const pulled = await phone.pull();
  assert.deepEqual([pulled.watch, pulled.theme, phone.linked.pending], [['HB5'], null, 0]);
});

test('a server that keeps follows but not searches never clears saved searches and is not rewritten every pull', async () => {
  const server = sectionsServer(['follows']);  // The release before saved searches.
  let mine = [search('aaaa1111', 'Mine')];
  const phone = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], getFollows: () => ['A1001'], getSearches: () => mine, debounceMs: 0});
  const {editKey} = await phone.create([]);
  assert.deepEqual([phone.follows, phone.searches], [['A1001'], null]);
  const laptop = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], getSearches: () => [search('bbbb2222', 'Theirs')], debounceMs: 0});
  laptop.connect(editKey);
  const first = await laptop.pull();
  assert.equal(first.searches, null);
  assert.deepEqual(first.follows, ['A1001']);
  const writes = server.writes;
  await laptop.pull(); await laptop.pull();
  assert.equal(server.writes, writes);
});

test('two devices merge saved searches by id, then renames and deletes sync, and older pages cannot erase them', async () => {
  const server = sectionsServer();
  let phoneS = [search('aaaa1111', 'Water')], laptopS = [search('bbbb2222', 'Energy')];
  const phone = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], getSearches: () => phoneS, debounceMs: 0});
  const laptop = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], getSearches: () => laptopS, debounceMs: 0});
  const {editKey, viewKey} = await phone.create([]);
  laptop.connect(editKey);
  laptopS = (await laptop.pull()).searches;
  assert.deepEqual(laptopS.map(s => s.id), ['aaaa1111', 'bbbb2222']);
  phoneS = (await phone.pull()).searches;
  assert.deepEqual(phoneS.map(s => s.id), ['aaaa1111', 'bbbb2222']);
  // Rename on the phone and delete on the stale laptop: both survive the conflict.
  const renamed = {...phoneS[0], name: 'Water bills'};
  phoneS = [renamed, phoneS[1]]; phone.record('save-search', renamed.id, undefined, renamed); await phone.flush();
  laptopS = laptopS.filter(s => s.id !== 'bbbb2222'); laptop.record('delete-search', 'bbbb2222'); await laptop.flush();
  assert.deepEqual(laptop.searches.map(s => s.name), ['Water bills']);
  assert.deepEqual((await phone.pull()).searches.map(s => s.name), ['Water bills']);
  // A page from before saved searches writes bills and follows only.
  const entry = server.lists.get(editKey);
  await server.fetch('/api/sync', {method: 'PUT', headers: {'X-Sync-Key': editKey}, body: JSON.stringify({version: entry.version, data: {watch: ['HB1'], follows: []}})});
  assert.deepEqual((await phone.pull()).searches.map(s => s.name), ['Water bills']);
  const viewer = createSyncClient({fetchImpl: server.fetch, storage: memoryStorage(), getWatch: () => [], debounceMs: 0});
  viewer.connect(viewKey);
  assert.deepEqual(await viewer.pull(), {mode: 'view', watch: ['HB1']});
});

test('after the server learns searches, devices that synced before it still merge rather than replace', async () => {
  const server = sectionsServer(['follows']);
  const phoneStore = memoryStorage(), laptopStore = memoryStorage();
  const open = (storage, list) => createSyncClient({fetchImpl: server.fetch, storage, getWatch: () => [], getSearches: () => list, debounceMs: 0});
  const {editKey} = await open(phoneStore, [search('aaaa1111', 'Water')]).create([]);
  const laptop = open(laptopStore, [search('bbbb2222', 'Energy')]);
  laptop.connect(editKey); await laptop.pull();
  server.known = ['follows', 'searches'];  // The sync service is updated; both devices reload.
  await open(phoneStore, [search('aaaa1111', 'Water')]).pull();
  const laptopAfter = await open(laptopStore, [search('bbbb2222', 'Energy')]).pull();
  assert.deepEqual(laptopAfter.searches.map(s => s.id), ['aaaa1111', 'bbbb2222']);
});

test('saved sync state from before sections keeps its follows merge', async () => {
  const server = sectionsServer();
  const storage = memoryStorage();
  const a = createSyncClient({fetchImpl: server.fetch, storage, getWatch: () => [], getFollows: () => ['A1001'], debounceMs: 0});
  const {editKey} = await a.create([]);
  const saved = JSON.parse(storage.getItem('tx-bill-atlas-sync-v1'));
  delete saved.merged; saved.followsMerged = true;  // As the previous release stored it.
  storage.setItem('tx-bill-atlas-sync-v1', JSON.stringify(saved));
  // The link now has no follows (another device unfollowed everything); this device must adopt that, not re-add.
  const entry = server.lists.get(editKey); entry.data.follows = []; entry.version++;
  const b = createSyncClient({fetchImpl: server.fetch, storage, getWatch: () => [], getFollows: () => ['A1001'], debounceMs: 0});
  assert.deepEqual((await b.pull()).follows, []);
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
