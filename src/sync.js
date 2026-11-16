// Private sync link client. The key lives in this browser's storage and the X-Sync-Key header only.
import {applyOps, applyFollowOps, cleanFollows, applySearchOps, cleanSearches, MAX_LIST, MAX_FOLLOWS, MAX_SEARCHES} from './prefs.js';

const STORE = 'tx-bill-atlas-sync-v1';

// Sections that ride along with the watchlist. A reply without a section means "unknown" (a server that predates
// it, or a link that never had one), never "none": this device's copy is then kept, not cleared. Until a write that
// carried a section comes back with it stored (merged[name]), this device unions its own entries into the link's
// instead of replacing them, so the first devices to sync a section cannot erase each other's.
// `apply` keeps this device's lists within the limits; `all` (no limit) is what a write would carry before fit().
const SECTIONS = {
  follows: {max: MAX_FOLLOWS, apply: applyFollowOps, ids: list => list,
    all: (list, ops) => applyFollowOps(list, ops, Infinity),
    union: (server, local) => cleanFollows([...server, ...local], Infinity)},
  searches: {max: MAX_SEARCHES, apply: applySearchOps, ids: list => list.map(s => s.id),
    all: (list, ops) => applySearchOps(list, ops, Infinity),
    union: (server, local) => cleanSearches([...server, ...local.filter(s => !server.some(x => x.id === s.id))], Infinity)},
};
const NAMES = Object.keys(SECTIONS);
const has = (data, name) => Array.isArray(data?.[name]);
// The colour theme is one value, not a list: last write wins. A device sends it only with a theme change of its own
// (or when it creates the link), so a device that never changed it cannot overwrite another's choice with a stale copy.
const lastTheme = ops => { for (let i = (ops || []).length - 1; i >= 0; i--) if (ops[i].op === 'theme') return ops[i].id; return null; };
// Pending ops carry a tag so a finished write removes exactly the ops it sent, even when another tab of this site
// queued or sent ops meanwhile. Ops saved by older versions have none and are matched by value.
const opId = op => op.t || JSON.stringify(op);
const newTag = () => Math.random().toString(36).slice(2, 12);
function without(pending, sent) {
  const left = [...sent];
  return pending.filter(op => { const i = left.indexOf(opId(op)); if (i < 0) return true; left.splice(i, 1); return false; });
}
const nothing = d => !d.watch.length && !d.follows.length && !d.searches.length;
// Ops that turn `sent` into `now`: changes saved in this browser while a link was being created.
function diffOps(sent, now) {
  const ops = [], push = (op, id, value) => ops.push(value === undefined ? {op, id, t: newTag()} : {op, id, value, t: newTag()});
  for (const id of now.watch) if (!sent.watch.includes(id)) push('add', id);
  for (const id of sent.watch) if (!now.watch.includes(id)) push('remove', id);
  for (const c of now.follows) if (!sent.follows.includes(c)) push('follow', c);
  for (const c of sent.follows) if (!now.follows.includes(c)) push('unfollow', c);
  for (const s of now.searches) {
    const was = sent.searches.find(x => x.id === s.id);
    if (!was || JSON.stringify(was) !== JSON.stringify(s)) push('save-search', s.id, s);
  }
  for (const s of sent.searches) if (!now.searches.some(x => x.id === s.id)) push('delete-search', s.id);
  return ops;
}

// Invariants (tests/sync_safety.test.mjs):
// - The stored version moves only together with adopt(): this browser's lists are then the link's copy at that
//   version plus pending ops, so a write from them at that version is safe, and any other write 409s and replays.
// - A write never drops an item to fit a limit: what this device contributed and did not fit goes to onDisplaced
//   (which keeps it aside, or throws so nothing is acknowledged) before the write is accepted.
// - A join (connect) adds this browser's bills to the link as ops on its first successful pull.
export function createSyncClient({fetchImpl = (...a) => fetch(...a), storage, base = './api/sync', getWatch, getFollows = () => [], getSearches = () => [], getTheme = () => null,
  adopt = () => {}, onDisplaced = () => { throw Error('Some saved items do not fit the sync link'); }, debounceMs = 800} = {}) {
  let state = read(), available = null, timer = null, flushing = null;
  const getters = {follows: () => cleanFollows(getFollows()), searches: () => cleanSearches(getSearches())};
  let unsupported = {};  // Sections this session's server dropped after we sent them; stop re-sending each pull.
  let values = {};       // Each section after the last exchange (pending ops replayed), or null if unknown.

  function read() {
    try {
      const v = JSON.parse(storage?.getItem(STORE) || 'null');
      if (!v || typeof v.key !== 'string') return null;
      if (!v.merged || typeof v.merged !== 'object') v.merged = {follows: v.followsMerged === true};  // Older saved state.
      return v;
    } catch { return null; }
  }
  // Storage is the truth, shared with this site's other tabs: every call starts from it, and after each request a
  // call writes only if the stored link is still the one it started with.
  function fresh() { state = read(); return state; }
  const same = key => fresh()?.key === key;
  function save() { try { state ? storage?.setItem(STORE, JSON.stringify(state)) : storage?.removeItem(STORE); } catch {} }

  async function call(method, path = '', body) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (state?.key && path === '') headers['X-Sync-Key'] = state.key;
    const response = await fetchImpl(base + path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store'});
    const text = response.status === 204 ? '' : await response.text();
    let data = null; try { data = text ? JSON.parse(text) : null; } catch {}
    return {status: response.status, data};
  }

  // One section as a write would carry it, before fit(): the device's copy, or before the first confirmed merge,
  // the link's plus the device's.
  function sectionToSend(name, server) {
    const {all, union} = SECTIONS[name];
    if (state.merged[name]) return has(server, name) ? all(server[name], state.pending) : getters[name]();
    return all(union(has(server, name) ? server[name] : [], getters[name]()), state.pending);
  }
  // Within the server's limits, the link's items first: what is cut is this device's newest additions.
  function payload(watch, server) {
    const data = {watch: watch.slice(0, MAX_LIST)}, displaced = {watch: watch.slice(MAX_LIST)};
    for (const name of NAMES) {
      const list = sectionToSend(name, server);
      data[name] = list.slice(0, SECTIONS[name].max); displaced[name] = list.slice(SECTIONS[name].max);
    }
    const theme = lastTheme(state.pending);
    if (theme) data.theme = theme;
    return {data, displaced};
  }
  // After a successful write that carried every section: which ones did the server keep?
  function noteWrite(data) {
    for (const name of NAMES) if (has(data, name)) state.merged[name] = true; else unsupported[name] = true;
  }
  function settle(data) {
    values = Object.fromEntries(NAMES.map(n => [n, has(data, n) ? SECTIONS[n].apply(data[n], state.pending) : null]));
    values.theme = lastTheme(state.pending) ?? (typeof data?.theme === 'string' ? data.theme : null);
  }
  // This browser's lists become the link's copy plus pending ops. Called just before the version is stored.
  const adoptData = data => adopt({watch: applyOps(data.watch, state.pending), follows: values.follows ?? null, searches: values.searches ?? null, theme: values.theme ?? null});

  const client = {
    // joinPending: connected but this browser's bills not yet added (an older version stored joins as mode null).
    get linked() { fresh(); return state ? {joinPending: state.joinPending === true || state.mode == null, mode: state.mode, viewKey: state.viewKey || null, editKey: state.mode === 'edit' ? state.key : null, pending: state.pending.length} : null; },
    get follows() { return values.follows ?? null; },
    get searches() { return values.searches ?? null; },
    get theme() { return values.theme ?? null; },

    async isAvailable() {
      if (available === null) {
        try { const r = await call('GET', '/health'); available = r.status === 200 && r.data?.ok === true; } catch { available = false; }
      }
      return available;
    },

    // Sends the given lists (this browser's, read from storage). Changes saved meanwhile are queued, not lost.
    async create(watch, followList = getFollows(), searchList = getSearches()) {
      const theme = getTheme(), list = [...new Set(watch)];
      const sent = {watch: list.slice(0, MAX_LIST), follows: cleanFollows(followList), searches: cleanSearches(searchList)};
      const over = list.slice(MAX_LIST);
      const r = await call('POST', '', {data: {...sent, ...(theme ? {theme} : {})}});
      if (r.status !== 201) throw Error(r.data?.error || `Sync is unavailable (HTTP ${r.status})`);
      if (fresh()) throw Error('This browser joined another sync link meanwhile and keeps that one');
      if (over.length) onDisplaced({watch: over, follows: [], searches: []});
      const now = {watch: getWatch().filter(id => !over.includes(id)), follows: getters.follows(), searches: getters.searches()};
      const stored = r.data.data || {watch: sent.watch};  // An older service replied without the stored data.
      state = {key: r.data.edit_key, mode: 'edit', viewKey: r.data.view_key, version: r.data.version, pending: diffOps(sent, now), merged: {}};
      unsupported = {};
      noteWrite(stored);
      settle(stored);
      adoptData(stored);
      save();
      if (state.pending.length) try { await client.flush(); } catch {}  // Retried by the next write or pull.
      return client.linked;
    },

    // Joining: this browser's bills are added to the link on the first pull that reaches it (joinPending).
    connect(key) { state = {key, mode: null, viewKey: null, version: 0, pending: [], merged: {}, joinPending: true}; unsupported = {}; values = {}; save(); },

    // Returns {mode, watch} (edit links also each section, null when unknown) after pushing this device's pending
    // changes, or null if unlinked, or when another tab or write changed the link meanwhile (pull again later).
    async pull() {
      if (!fresh()) return null;
      const key = state.key;
      if (state.pending.length) await client.flush();
      if (!same(key)) return null;
      const r = await call('GET');
      if (!same(key)) return null;
      if (r.status === 404) { state = null; values = {}; save(); throw Error('This sync link no longer exists'); }
      if (r.status !== 200) throw Error(r.data?.error || `Sync is unavailable (HTTP ${r.status})`);
      const joining = state.joinPending === true || state.mode == null;
      Object.assign(state, {mode: r.data.mode, viewKey: r.data.view_key || state.viewKey});
      if (r.data.mode !== 'edit') { delete state.joinPending; save(); return {mode: r.data.mode, watch: r.data.data.watch}; }
      let data = r.data.data, needsWrite = false;
      if (joining) {
        const theirs = new Set(applyOps(data.watch, state.pending));
        const mine = getWatch().filter(id => !theirs.has(id)), room = Math.max(0, MAX_LIST - theirs.size);
        if (mine.length > room) onDisplaced({watch: mine.slice(room), follows: [], searches: []});
        for (const id of mine.slice(0, room)) state.pending.push({op: 'add', id, t: newTag()});
        delete state.joinPending;
        needsWrite = mine.length > 0;
      }
      for (const name of NAMES) {
        if (state.merged[name] || unsupported[name]) continue;
        const theirs = new Set(SECTIONS[name].ids(has(data, name) ? data[name] : []));
        if (SECTIONS[name].ids(getters[name]()).some(id => !theirs.has(id))) needsWrite = true;
        else if (has(data, name)) state.merged[name] = true;
      }
      save();  // Mode, merge flags and join ops. Not the version: it is stored only with the lists it belongs to.
      if (needsWrite) {
        // One write with the unions and join ops; the reply says which sections this server keeps. On success the
        // write adopted its result and stored its version.
        const merged = await client.flush(true, data, r.data.version);
        if (!same(key)) return null;
        if (!merged || Array.isArray(merged)) return null;  // Another write was already out and adopted its own result.
        return {mode: 'edit', watch: applyOps(merged.watch, state.pending), ...values};
      }
      settle(data);
      adoptData(data);
      state.version = r.data.version;  // The version of the data adopted, even when another tab stored a newer one.
      save();
      return {mode: 'edit', watch: applyOps(data.watch, state.pending), ...values};
    },

    // `value` travels with ops that carry one (a saved search).
    record(op, id, onSynced, value) {
      if (fresh()?.mode !== 'edit') return;
      state.pending.push(value === undefined ? {op, id, t: newTag()} : {op, id, value, t: newTag()}); save();
      clearTimeout(timer);
      timer = setTimeout(() => client.flush().then(w => w && onSynced?.(w, null, {...values}), error => onSynced?.(null, error)), debounceMs);
    },

    // Pushes the local list and sections. On a conflict, replays pending changes onto the newer server data and
    // retries. `force` writes even with nothing pending (the first merge), from `server` at `version`.
    // Returns the watchlist (or, when forced, the stored data).
    async flush(force = false, server = null, version = null) {
      if (flushing) return flushing;
      flushing = (async () => {
        if (fresh()?.mode !== 'edit' || (!state.pending.length && !force)) return null;
        const key = state.key;
        let watch = server ? applyOps(server.watch, state.pending) : getWatch();
        let current = version ?? state.version, base = server;
        for (let attempt = 0; attempt < 3; attempt++) {
          const sent = state.pending.map(opId), {data, displaced} = payload(watch, base);
          const r = await call('PUT', '', {version: current, data});
          if (!same(key)) return null;
          if (r.status === 200) {
            if (!nothing(displaced)) onDisplaced(displaced);  // Throws when it cannot keep them: nothing is acknowledged.
            state.pending = without(state.pending, sent);
            noteWrite(r.data.data);
            settle(r.data.data);
            adoptData(r.data.data);
            state.version = r.data.version;
            save();
            return force ? r.data.data : applyOps(r.data.data.watch, state.pending);  // Keep changes made during the request.
          }
          if (r.status !== 409) throw Error(r.data?.error || `Sync failed (HTTP ${r.status})`);
          base = r.data.data; watch = applyOps(base.watch, state.pending); current = r.data.version;
        }
        throw Error('Sync kept conflicting; try again');
      })();
      try { return await flushing; } finally { flushing = null; }
    },

    forget() { clearTimeout(timer); state = null; values = {}; save(); },

    async remove() {
      if (fresh()?.mode !== 'edit') throw Error('Only the edit link can delete a synced list');
      const key = state.key;
      const r = await call('DELETE');
      if (r.status !== 204 && r.status !== 404) throw Error(r.data?.error || `Delete failed (HTTP ${r.status})`);
      if (same(key)) client.forget();  // Another tab may have joined a different link meanwhile.
    },
  };
  return client;
}
