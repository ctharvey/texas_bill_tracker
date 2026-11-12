// Saving choices without accounts: URL state, remembered filters, profile and watchlist files, and sync merging.
export const FILTER_DEFAULTS = {query: '', topic: '', agency: '', chamber: '', stage: '', action: '', outlook: '', sort: 'newest', onlyWatch: false};
const FILTER_NAMES = Object.keys(FILTER_DEFAULTS);
export const VIEWS = ['all', 'watchlist', 'following', 'today', 'local', 'member', 'agencies', 'review', 'method', 'saving', 'data'];
export const MAX_LIST = 500;
const BILL_ID = /^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9]\d{0,4}$/;
const SYNC_KEY = /^[A-Za-z0-9_-]{22}$/;
const MEMBER_CODE = /^A\d{3,5}$/;  // Texas Legislature Online member code

export const isBillId = id => typeof id === 'string' && BILL_ID.test(id);
export const MAX_FOLLOWS = 200;
// Followed legislators, as stored in this browser: valid member codes only, in order, no repeats.
export const cleanFollows = raw => Array.isArray(raw)
  ? [...new Set(raw.filter(c => typeof c === 'string' && MEMBER_CODE.test(c)))].slice(0, MAX_FOLLOWS) : [];
const normalizeId = s => String(s).trim().toUpperCase().replace(/\s+/g, '');
const uniqueIds = ids => [...new Set(ids.map(normalizeId).filter(isBillId))].slice(0, MAX_LIST);

export function cleanFilters(raw) {
  const out = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const name of FILTER_NAMES) {
    const value = raw[name];
    if (name === 'onlyWatch' ? typeof value === 'boolean' : typeof value === 'string' && value.length <= 200) out[name] = value;
  }
  return out;
}

export const pickFilters = state => Object.fromEntries(FILTER_NAMES.map(name => [name, state[name]]));

export function parseHash(hash) {
  const raw = String(hash || '').replace(/^#/, '');
  const at = raw.indexOf('?');
  const view = at < 0 ? raw : raw.slice(0, at);
  const params = new URLSearchParams(at < 0 ? '' : raw.slice(at + 1));
  const filters = {};
  for (const name of FILTER_NAMES) {
    if (!params.has(name)) continue;
    filters[name] = name === 'onlyWatch' ? params.get(name) === '1' : params.get(name).slice(0, 200);
  }
  const list = params.has('list') ? uniqueIds(params.get('list').split(',')) : null;
  const bill = normalizeId(params.get('bill') || '');
  const sync = params.get('sync') || '';
  const member = String(params.get('code') || '').trim().toUpperCase();
  return {view: VIEWS.includes(view) ? view : 'all', filters, hasFilters: Object.keys(filters).length > 0,
    list: list && list.length ? list : null, bill: isBillId(bill) ? bill : null, sync: SYNC_KEY.test(sync) ? sync : null,
    member: view === 'member' && MEMBER_CODE.test(member) ? member : null};
}

// `sync` is only ever a view-only key; edit keys are never written into the address bar.
export function buildHash(view, filters, {list = null, bill = null, sync = null, member = null} = {}) {
  const parts = [];
  if (view === 'all' || view === 'watchlist') {
    for (const name of FILTER_NAMES) {
      const value = filters?.[name];
      if (value === undefined || value === FILTER_DEFAULTS[name]) continue;
      parts.push(`${name}=${name === 'onlyWatch' ? (value ? '1' : '0') : encodeURIComponent(value)}`);
    }
  }
  if (view === 'member' && MEMBER_CODE.test(member || '')) parts.push(`code=${member}`);
  if (list?.length) parts.push(`list=${list.join(',')}`);
  if (bill) parts.push(`bill=${bill}`);
  if (sync && SYNC_KEY.test(sync)) parts.push(`sync=${sync}`);
  return `#${VIEWS.includes(view) ? view : 'all'}${parts.length ? `?${parts.join('&')}` : ''}`;
}

export function watchlistFile(ids, now = new Date()) {
  return JSON.stringify({format: 'texas-bill-atlas-watchlist-v1', session: '90R', exported_at: now.toISOString(), bills: [...ids]}, null, 2);
}

// Accepts our JSON export, a JSON array, or any text/CSV containing bill numbers ("HB 5, SB12").
export function parseWatchlistFile(text) {
  let ids;
  try {
    const data = JSON.parse(text);
    ids = Array.isArray(data) ? data : Array.isArray(data?.bills) ? data.bills : null;
    if (!ids) throw Error('This file has no list of bills');
  } catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
    ids = String(text).replace(/\b(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\s+(?=\d)/gi, '$1').split(/[^A-Za-z0-9]+/);
  }
  const clean = uniqueIds(ids.filter(x => typeof x === 'string'));
  if (!clean.length) throw Error('No Texas bill numbers found');
  return clean;
}

// Replays this device's unsynced adds/removes on top of the newest server list. Other ops (follows) are skipped.
export function applyOps(watch, ops) {
  const set = new Set(watch);
  for (const {op, id} of ops || []) if (op === 'add') set.add(id); else if (op === 'remove') set.delete(id);
  return [...set];
}

// The same for followed legislators: follow/unfollow ops on top of the server's follows.
export function applyFollowOps(follows, ops) {
  const set = new Set(follows);
  for (const {op, id} of ops || []) if (op === 'follow') set.add(id); else if (op === 'unfollow') set.delete(id);
  return cleanFollows([...set]);
}

// Saved searches: explorer filters under a name. `seen` is the Texas day the search was last opened.
export const MAX_SEARCHES = 20;
// The sync service's per-search limit (SEARCH_FILTER_BYTES), so a saved search always syncs.
export const searchFitsSync = filters => new TextEncoder().encode(JSON.stringify(filters)).length <= 600;
const SEARCH_ID = /^[a-z0-9]{8,16}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
export function cleanSearch(raw) {
  if (!raw || typeof raw !== 'object' || typeof raw.id !== 'string' || !SEARCH_ID.test(raw.id)) return null;
  const name = typeof raw.name === 'string' ? raw.name.trim().slice(0, 80) : '';
  const filters = cleanFilters(raw.filters);
  if (!name || !searchFitsSync(filters)) return null;
  return {id: raw.id, name, filters, seen: typeof raw.seen === 'string' && DAY.test(raw.seen) ? raw.seen : null};
}
export function cleanSearches(raw) {
  const seen = new Set(), out = [];
  for (const item of Array.isArray(raw) ? raw : []) {
    const s = cleanSearch(item);
    if (s && !seen.has(s.id)) { seen.add(s.id); out.push(s); }
  }
  return out.slice(0, MAX_SEARCHES);
}
// save-search replaces (or adds) one search by id; delete-search removes it.
export function applySearchOps(searches, ops) {
  const byId = new Map(cleanSearches(searches).map(s => [s.id, s]));
  for (const {op, id, value} of ops || []) {
    if (op === 'save-search') { const s = cleanSearch(value); if (s && s.id === id) byId.set(id, s); }
    else if (op === 'delete-search') byId.delete(id);
  }
  return cleanSearches([...byId.values()]);
}
export function newSearchId(random = n => crypto.getRandomValues(new Uint8Array(n))) {
  return [...random(10)].map(b => 'abcdefghijklmnopqrstuvwxyz0123456789'[b % 36]).join('');
}
// A readable default name from the filters that are set.
export function searchName(filters, agencyName = id => id) {
  const f = cleanFilters(filters);
  const parts = [f.query && `“${f.query.trim()}”`, f.topic, f.agency && agencyName(f.agency), f.chamber, f.stage, f.outlook,
    f.action, f.onlyWatch && 'Watched only'].filter(Boolean);
  return (parts.join(' · ') || 'All bills').slice(0, 80);
}

// One file for everything saved: the watchlist (as the first of `lists`, ready for named lists), follows and saved
// searches. Device-only things (Near you districts, remembered filters, the sync link) are never in it.
export const PROFILE_FORMAT = 'texas-bill-atlas-profile-v1';
export function profileFile({watch = [], follows = [], searches = []} = {}, now = new Date()) {
  return JSON.stringify({format: PROFILE_FORMAT, session: '90R', exported_at: now.toISOString(),
    lists: [{id: 'main', name: 'Watchlist', bills: [...watch]}], follows: cleanFollows([...follows]),
    searches: cleanSearches(searches)}, null, 2);
}

// A profile file, or anything parseWatchlistFile reads (older watchlist exports, arrays, pasted text).
// Returns {bills, follows, searches}; importing only adds.
export function parseProfileFile(text) {
  let data = null;
  try { data = JSON.parse(text); } catch {}
  if (data?.format !== PROFILE_FORMAT) return {bills: parseWatchlistFile(text), follows: [], searches: []};
  const lists = Array.isArray(data.lists) ? data.lists : [];
  const bills = uniqueIds(lists.flatMap(l => Array.isArray(l?.bills) ? l.bills.filter(x => typeof x === 'string') : []));
  const follows = cleanFollows(data.follows), searches = cleanSearches(data.searches);
  if (!bills.length && !follows.length && !searches.length) throw Error('This file has no bills or legislators (or saved searches)');
  return {bills, follows, searches};
}
