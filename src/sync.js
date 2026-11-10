// Private sync link client. The key lives in this browser's storage and the X-Sync-Key header only.
import {applyOps} from './prefs.js';

const STORE = 'tx-bill-atlas-sync-v1';

export function createSyncClient({fetchImpl = (...a) => fetch(...a), storage, base = './api/sync', getWatch, debounceMs = 800} = {}) {
  let state = read(), available = null, timer = null, flushing = null;

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

  const client = {
    get linked() { return state ? {mode: state.mode, viewKey: state.viewKey || null, editKey: state.mode === 'edit' ? state.key : null, pending: state.pending.length} : null; },

    async isAvailable() {
      if (available === null) {
        try { const r = await call('GET', '/health'); available = r.status === 200 && r.data?.ok === true; } catch { available = false; }
      }
      return available;
    },

    async create(watch) {
      const r = await call('POST', '', {data: {watch}});
      if (r.status !== 201) throw Error(r.data?.error || `Sync is unavailable (HTTP ${r.status})`);
      state = {key: r.data.edit_key, mode: 'edit', viewKey: r.data.view_key, version: r.data.version, pending: []};
      save();
      return client.linked;
    },

    connect(key) { state = {key, mode: null, viewKey: null, version: 0, pending: []}; save(); },

    // Returns {mode, watch} from the server (after pushing this device's pending changes), or null if unlinked.
    async pull() {
      if (!state) return null;
      if (state.pending.length) await client.flush();
      const r = await call('GET');
      if (r.status === 404) { state = null; save(); throw Error('This sync link no longer exists'); }
      if (r.status !== 200) throw Error(r.data?.error || `Sync is unavailable (HTTP ${r.status})`);
      Object.assign(state, {mode: r.data.mode, version: r.data.version, viewKey: r.data.view_key || state.viewKey});
      save();
      return {mode: r.data.mode, watch: r.data.mode === 'edit' ? applyOps(r.data.data.watch, state.pending) : r.data.data.watch};
    },

    record(op, id, onSynced) {
      if (state?.mode !== 'edit') return;
      state.pending.push({op, id}); save();
      clearTimeout(timer);
      timer = setTimeout(() => client.flush().then(w => w && onSynced?.(w), error => onSynced?.(null, error)), debounceMs);
    },

    // Pushes the local list. On a conflict, replays pending changes onto the newer server list and retries.
    async flush() {
      if (flushing) return flushing;
      flushing = (async () => {
        if (state?.mode !== 'edit' || !state.pending.length) return null;
        let watch = getWatch(), version = state.version;
        for (let attempt = 0; attempt < 3; attempt++) {
          const sent = state.pending.length;
          const r = await call('PUT', '', {version, data: {watch}});
          if (r.status === 200) {
            state.version = r.data.version; state.pending = state.pending.slice(sent); save();
            return applyOps(r.data.data.watch, state.pending);  // Keep changes made during the request.
          }
          if (r.status !== 409) throw Error(r.data?.error || `Sync failed (HTTP ${r.status})`);
          watch = applyOps(r.data.data.watch, state.pending); version = r.data.version;
        }
        throw Error('Sync kept conflicting; try again');
      })();
      try { return await flushing; } finally { flushing = null; }
    },

    forget() { clearTimeout(timer); state = null; save(); },

    async remove() {
      if (state?.mode !== 'edit') throw Error('Only the edit link can delete a synced list');
      const r = await call('DELETE');
      if (r.status !== 204 && r.status !== 404) throw Error(r.data?.error || `Delete failed (HTTP ${r.status})`);
      client.forget();
    },
  };
  return client;
}
