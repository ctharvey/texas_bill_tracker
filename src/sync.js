// Private sync link client. The key lives in this browser's storage and the X-Sync-Key header only.
import {applyOps, applyFollowOps, cleanFollows, applySearchOps, cleanSearches} from './prefs.js';

const STORE = 'tx-bill-atlas-sync-v1';

// Sections that ride along with the watchlist. A reply without a section means "unknown" (a server that predates
// it, or a link that never had one), never "none": this device's copy is then kept, not cleared. Until a write that
// carried a section comes back with it stored (merged[name]), this device unions its own entries into the link's
// instead of replacing them, so the first devices to sync a section cannot erase each other's.
const SECTIONS = {
  follows: {apply: applyFollowOps, ids: list => list, union: (server, local) => cleanFollows([...server, ...local])},
  searches: {apply: applySearchOps, ids: list => list.map(s => s.id),
    union: (server, local) => cleanSearches([...server, ...local.filter(s => !server.some(x => x.id === s.id))])},
};
const NAMES = Object.keys(SECTIONS);
const has = (data, name) => Array.isArray(data?.[name]);
// The colour theme is one value, not a list: last write wins. A device sends it only with a theme change of its own
// (or when it creates the link), so a device that never changed it cannot overwrite another's choice with a stale copy.
const lastTheme = ops => { for (let i = (ops || []).length - 1; i >= 0; i--) if (ops[i].op === 'theme') return ops[i].id; return null; };

export function createSyncClient({fetchImpl = (...a) => fetch(...a), storage, base = './api/sync', getWatch, getFollows = () => [], getSearches = () => [], getTheme = () => null, debounceMs = 800} = {}) {
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

  // What to send for one section: the device's copy, or before the first confirmed merge, that plus the link's.
  function sectionToSend(name, server) {
    const {apply, union} = SECTIONS[name];
    if (state.merged[name]) return has(server, name) ? apply(server[name], state.pending) : getters[name]();
    return apply(union(has(server, name) ? server[name] : [], getters[name]()), state.pending);
  }
  const payload = (watch, server) => {
    const out = Object.fromEntries([['watch', watch], ...NAMES.map(n => [n, sectionToSend(n, server)])]);
    const theme = lastTheme(state.pending);
    if (theme) out.theme = theme;
    return out;
  };
  // After a successful write that carried every section: which ones did the server keep?
  function noteWrite(data) {
    for (const name of NAMES) if (has(data, name)) state.merged[name] = true; else unsupported[name] = true;
  }
  function settle(data) {
    values = Object.fromEntries(NAMES.map(n => [n, has(data, n) ? SECTIONS[n].apply(data[n], state.pending) : null]));
    values.theme = lastTheme(state.pending) ?? (typeof data?.theme === 'string' ? data.theme : null);
  }

  const client = {
    get linked() { return state ? {mode: state.mode, viewKey: state.viewKey || null, editKey: state.mode === 'edit' ? state.key : null, pending: state.pending.length} : null; },
    get follows() { return values.follows ?? null; },
    get searches() { return values.searches ?? null; },
    get theme() { return values.theme ?? null; },

    async isAvailable() {
      if (available === null) {
        try { const r = await call('GET', '/health'); available = r.status === 200 && r.data?.ok === true; } catch { available = false; }
      }
      return available;
    },

    async create(watch, followList = getFollows(), searchList = getSearches()) {
      const theme = getTheme();
      const r = await call('POST', '', {data: {watch, follows: cleanFollows(followList), searches: cleanSearches(searchList), ...(theme ? {theme} : {})}});
      if (r.status !== 201) throw Error(r.data?.error || `Sync is unavailable (HTTP ${r.status})`);
      state = {key: r.data.edit_key, mode: 'edit', viewKey: r.data.view_key, version: r.data.version, pending: [], merged: {}};
      unsupported = {};
      noteWrite(r.data.data);
      settle(r.data.data);
      save();
      return client.linked;
    },

    connect(key) { state = {key, mode: null, viewKey: null, version: 0, pending: [], merged: {}}; unsupported = {}; values = {}; save(); },

    // Returns {mode, watch} (edit links also each section, null when unknown) after pushing this device's pending
    // changes, or null if unlinked.
    async pull() {
      if (!state) return null;
      if (state.pending.length) await client.flush();
      const r = await call('GET');
      if (r.status === 404) { state = null; values = {}; save(); throw Error('This sync link no longer exists'); }
      if (r.status !== 200) throw Error(r.data?.error || `Sync is unavailable (HTTP ${r.status})`);
      Object.assign(state, {mode: r.data.mode, version: r.data.version, viewKey: r.data.view_key || state.viewKey});
      save();
      if (r.data.mode !== 'edit') return {mode: r.data.mode, watch: r.data.data.watch};
      let data = r.data.data, needsWrite = false;
      for (const name of NAMES) {
        if (state.merged[name] || unsupported[name]) continue;
        const theirs = new Set(SECTIONS[name].ids(has(data, name) ? data[name] : []));
        if (SECTIONS[name].ids(getters[name]()).some(id => !theirs.has(id))) needsWrite = true;
        else if (has(data, name)) { state.merged[name] = true; save(); }
      }
      if (needsWrite) {
        // Write once with the unions; the reply says which sections this server keeps.
        const merged = await client.flush(true, data, r.data.version);
        if (merged && !Array.isArray(merged)) data = merged;  // An overlapping flush returns a list: retry next pull.
      }
      settle(data);
      return {mode: 'edit', watch: applyOps(data.watch, state.pending), ...values};
    },

    // `value` travels with ops that carry one (a saved search).
    record(op, id, onSynced, value) {
      if (state?.mode !== 'edit') return;
      state.pending.push(value === undefined ? {op, id} : {op, id, value}); save();
      clearTimeout(timer);
      timer = setTimeout(() => client.flush().then(w => w && onSynced?.(w, null, {...values}), error => onSynced?.(null, error)), debounceMs);
    },

    // Pushes the local list and sections. On a conflict, replays pending changes onto the newer server data and
    // retries. `force` writes even with nothing pending (the first merge), from `server` at `version`.
    // Returns the watchlist (or, when forced, the stored data).
    async flush(force = false, server = null, version = null) {
      if (flushing) return flushing;
      flushing = (async () => {
        if (state?.mode !== 'edit' || (!state.pending.length && !force)) return null;
        let watch = server ? applyOps(server.watch, state.pending) : getWatch();
        let current = version ?? state.version, base = server;
        for (let attempt = 0; attempt < 3; attempt++) {
          const sent = state.pending.length;
          const r = await call('PUT', '', {version: current, data: payload(watch, base)});
          if (r.status === 200) {
            state.version = r.data.version; state.pending = state.pending.slice(sent);
            noteWrite(r.data.data);
            save();
            settle(r.data.data);
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
      if (state?.mode !== 'edit') throw Error('Only the edit link can delete a synced list');
      const r = await call('DELETE');
      if (r.status !== 204 && r.status !== 404) throw Error(r.data?.error || `Delete failed (HTTP ${r.status})`);
      client.forget();
    },
  };
  return client;
}
