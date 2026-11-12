// Private sync link client. The key lives in this browser's storage and the X-Sync-Key header only.
import {applyOps, applyFollowOps, cleanFollows} from './prefs.js';

const STORE = 'tx-bill-atlas-sync-v1';
const union = (a, b) => cleanFollows([...(a || []), ...(b || [])]);

// Follows ride along with the watchlist. A reply without `follows` means "unknown" (a server that predates them,
// or a link that never had any), never "none": this device's follows are then kept, not cleared. Until a write
// that carried follows comes back with them stored (followsMerged), this device unions its own follows into the
// link's instead of replacing them, so the first devices to sync follows cannot erase each other's.
export function createSyncClient({fetchImpl = (...a) => fetch(...a), storage, base = './api/sync', getWatch, getFollows = () => [], debounceMs = 800} = {}) {
  let state = read(), available = null, timer = null, flushing = null;
  let unsupported = false;  // This session's server dropped follows we sent; stop re-sending them each pull.
  let follows = null;       // The link's follows after the last exchange (pending ops replayed), or null if unknown.

  function read() {
    try { const v = JSON.parse(storage?.getItem(STORE) || 'null'); return v && typeof v.key === 'string' ? v : null; } catch { return null; }
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

  const hasFollows = data => Array.isArray(data?.follows);
  // What to send: the device's follows, or before the first confirmed merge, those plus the link's.
  const followsToSend = server => {
    const local = cleanFollows(getFollows());
    if (state.followsMerged) return hasFollows(server) ? applyFollowOps(server.follows, state.pending) : local;
    return applyFollowOps(union(hasFollows(server) ? server.follows : [], local), state.pending);
  };
  // After a successful write that carried follows: did the server keep them?
  function noteWrite(data) {
    if (hasFollows(data)) state.followsMerged = true;
    else unsupported = true;
  }
  const settle = data => { follows = hasFollows(data) ? applyFollowOps(data.follows, state.pending) : null; };

  const client = {
    get linked() { return state ? {mode: state.mode, viewKey: state.viewKey || null, editKey: state.mode === 'edit' ? state.key : null, pending: state.pending.length} : null; },
    get follows() { return follows; },

    async isAvailable() {
      if (available === null) {
        try { const r = await call('GET', '/health'); available = r.status === 200 && r.data?.ok === true; } catch { available = false; }
      }
      return available;
    },

    async create(watch, followList = getFollows()) {
      const sent = cleanFollows(followList);
      const r = await call('POST', '', {data: {watch, follows: sent}});
      if (r.status !== 201) throw Error(r.data?.error || `Sync is unavailable (HTTP ${r.status})`);
      state = {key: r.data.edit_key, mode: 'edit', viewKey: r.data.view_key, version: r.data.version, pending: [], followsMerged: false};
      unsupported = false;
      noteWrite(r.data.data);
      settle(r.data.data);
      save();
      return client.linked;
    },

    connect(key) { state = {key, mode: null, viewKey: null, version: 0, pending: [], followsMerged: false}; unsupported = false; follows = null; save(); },

    // Returns {mode, watch} (edit links also {follows}, null when unknown) after pushing this device's pending
    // changes, or null if unlinked.
    async pull() {
      if (!state) return null;
      if (state.pending.length) await client.flush();
      const r = await call('GET');
      if (r.status === 404) { state = null; follows = null; save(); throw Error('This sync link no longer exists'); }
      if (r.status !== 200) throw Error(r.data?.error || `Sync is unavailable (HTTP ${r.status})`);
      Object.assign(state, {mode: r.data.mode, version: r.data.version, viewKey: r.data.view_key || state.viewKey});
      save();
      if (r.data.mode !== 'edit') return {mode: r.data.mode, watch: r.data.data.watch};
      let data = r.data.data;
      if (!state.followsMerged && !unsupported) {
        const missing = cleanFollows(getFollows()).filter(c => !(hasFollows(data) ? data.follows : []).includes(c));
        if (missing.length) {
          // Write once with the union; the reply says whether this server keeps follows at all.
          const merged = await client.flush(true, data, r.data.version);
          if (merged && !Array.isArray(merged)) data = merged;  // An overlapping flush returns a list: retry next pull.
        } else if (hasFollows(data)) {
          state.followsMerged = true; save();
        }
      }
      settle(data);
      return {mode: 'edit', watch: applyOps(data.watch, state.pending), follows};
    },

    record(op, id, onSynced) {
      if (state?.mode !== 'edit') return;
      state.pending.push({op, id}); save();
      clearTimeout(timer);
      timer = setTimeout(() => client.flush().then(w => w && onSynced?.(w, null, follows), error => onSynced?.(null, error)), debounceMs);
    },

    // Pushes the local list and follows. On a conflict, replays pending changes onto the newer server data and
    // retries. `force` writes even with nothing pending (the first follows merge), from `server` at `version`.
    // Returns the watchlist (or, when forced, the stored data).
    async flush(force = false, server = null, version = null) {
      if (flushing) return flushing;
      flushing = (async () => {
        if (state?.mode !== 'edit' || (!state.pending.length && !force)) return null;
        let watch = server ? applyOps(server.watch, state.pending) : getWatch();
        let current = version ?? state.version, base = server;
        for (let attempt = 0; attempt < 3; attempt++) {
          const sent = state.pending.length;
          const r = await call('PUT', '', {version: current, data: {watch, follows: followsToSend(base)}});
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

    forget() { clearTimeout(timer); state = null; follows = null; save(); },

    async remove() {
      if (state?.mode !== 'edit') throw Error('Only the edit link can delete a synced list');
      const r = await call('DELETE');
      if (r.status !== 204 && r.status !== 404) throw Error(r.data?.error || `Delete failed (HTTP ${r.status})`);
      client.forget();
    },
  };
  return client;
}
