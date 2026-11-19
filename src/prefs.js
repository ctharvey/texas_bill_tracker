// Saving choices without accounts: URL state, remembered filters, profile and watchlist files, and sync merging.
export const FILTER_DEFAULTS = {query: '', topic: '', area: '', agency: '', chamber: '', party: '', stage: '', action: '', outlook: '', sort: 'newest', onlyWatch: false, companion: false};
const FILTER_NAMES = Object.keys(FILTER_DEFAULTS);
// On-or-off filters: true or false when remembered, 1 or 0 in an address.
const ON_OFF = new Set(['onlyWatch', 'companion']);
// Renamed filter values, so old links, saved searches and remembered filters keep working (taxonomy.NO_HEARING).
const RENAMED = {outlook: {'Not rated': 'No hearing yet'}};
// Own keys only, so a value such as "__proto__" passes through as text instead of resolving to Object.prototype.
// Sort names are plain words; anything else ("__proto__") is dropped wherever filters are read.
const SORT_NAME = /^[a-z]{1,20}$/;
const usable = (name, value) => name !== 'sort' || SORT_NAME.test(value);
const current = (name, value) => Object.hasOwn(RENAMED, name) && Object.hasOwn(RENAMED[name], value) ? RENAMED[name][value] : value;
export const VIEWS = ['home', 'all', 'watchlist', 'following', 'today', 'local', 'member', 'statute', 'bill', 'agencies', 'review', 'method', 'saving', 'export', 'data'];
const LAW_CODE = /^[A-Z]{2}$/;
const LAW_SECTION = /^\d+[A-Z]?(?:\.\d+[A-Z]?)+$/;  // The statute index's section numbers (build_feeds.SECTION_NUM).
export const MAX_LIST = 500;
const BILL_ID = /^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9]\d{0,4}$/;
const SYNC_KEY = /^[A-Za-z0-9_-]{22}$/;
const MEMBER_CODE = /^A\d{3,5}$/;  // Texas Legislature Online member code

export const isBillId = id => typeof id === 'string' && BILL_ID.test(id);
export const MAX_FOLLOWS = 200;
// Followed legislators, as stored in this browser: valid member codes only, in order, no repeats.
// `max` Infinity keeps every item: sync uses that to see what a limit would cut, then keeps the cut items aside.
export const cleanFollows = (raw, max = MAX_FOLLOWS) => Array.isArray(raw)
  ? [...new Set(raw.filter(c => typeof c === 'string' && MEMBER_CODE.test(c)))].slice(0, max) : [];
const normalizeId = s => String(s).trim().toUpperCase().replace(/\s+/g, '');
const uniqueIds = ids => [...new Set(ids.map(normalizeId).filter(isBillId))].slice(0, MAX_LIST);

export function cleanFilters(raw) {
  const out = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const name of FILTER_NAMES) {
    const value = raw[name];
    if (ON_OFF.has(name) ? typeof value === 'boolean' : typeof value === 'string' && value.length <= 200 && usable(name, value)) out[name] = current(name, value);
  }
  return out;
}

export const pickFilters = state => Object.fromEntries(FILTER_NAMES.map(name => [name, state[name]]));
// Whether remembered filters already say the same as `filters`. The page rewrites them only when this is false, so a
// filter added in a later version (held at its default) never rewrites an older save just by loading it.
export const sameFilters = (saved, filters) =>
  JSON.stringify(pickFilters({...FILTER_DEFAULTS, ...cleanFilters(saved)})) === JSON.stringify(pickFilters(filters));

export function parseHash(hash) {
  const raw = String(hash || '').replace(/^#/, '');
  const at = raw.indexOf('?');
  const view = at < 0 ? raw : raw.slice(0, at);
  const params = new URLSearchParams(at < 0 ? '' : raw.slice(at + 1));
  const filters = {};
  for (const name of FILTER_NAMES) {
    if (!params.has(name) || !usable(name, params.get(name))) continue;
    filters[name] = ON_OFF.has(name) ? params.get(name) === '1' : current(name, params.get(name).slice(0, 200));
  }
  const list = params.has('list') ? uniqueIds(params.get('list').split(',')) : null;
  // A bill page is `#bill?id=HB1`; `bill=` on any view is the older address (RSS items, agent docs, saved links).
  const bill = normalizeId((view === 'bill' ? params.get('id') : null) || params.get('bill') || '');
  const sync = params.get('sync') || '';
  const member = String(params.get('code') || '').trim().toUpperCase();
  const law = String(params.get('law') || '').toUpperCase(), sec = String(params.get('sec') || '').toUpperCase();
  // A bare address is the dashboard; an unknown view (or `#?query=` and the like) is the explorer.
  return {view: raw === '' ? 'home' : VIEWS.includes(view) ? view : 'all', filters, hasFilters: Object.keys(filters).length > 0,
    list: list && list.length ? list : null, bill: isBillId(bill) ? bill : null, sync: SYNC_KEY.test(sync) ? sync : null,
    member: view === 'member' && MEMBER_CODE.test(member) ? member : null,
    statute: view === 'statute' && LAW_CODE.test(law) && LAW_SECTION.test(sec) && sec.length <= 16 ? `${law} ${sec}` : null};
}

// `sync` is only ever a view-only key; edit keys are never written into the address bar.
export function buildHash(view, filters, {list = null, bill = null, sync = null, member = null, statute = null} = {}) {
  const parts = [];
  if (view === 'all' || view === 'watchlist') {
    for (const name of FILTER_NAMES) {
      const value = filters?.[name];
      if (value === undefined || value === FILTER_DEFAULTS[name]) continue;
      parts.push(`${name}=${ON_OFF.has(name) ? (value ? '1' : '0') : encodeURIComponent(value)}`);
    }
  }
  if (view === 'bill' && isBillId(bill)) parts.push(`id=${bill}`);
  if (view === 'member' && MEMBER_CODE.test(member || '')) parts.push(`code=${member}`);
  const [law, sec] = String(statute || '').split(' ');
  if (view === 'statute' && LAW_CODE.test(law || '') && LAW_SECTION.test(sec || '')) parts.push(`law=${law}`, `sec=${sec}`);
  if (list?.length) parts.push(`list=${list.join(',')}`);
  if (bill && view !== 'bill') parts.push(`bill=${bill}`);
  if (sync && SYNC_KEY.test(sync)) parts.push(`sync=${sync}`);
  return `#${VIEWS.includes(view) ? view : 'all'}${parts.length ? `?${parts.join('&')}` : ''}`;
}

// A bill page's address is the path /bill/<ID>; a shared list or view-only sync key it was opened from rides in the
// fragment (/bill/HB5#list=HB5,SB2&sync=...). Every other view is /#view?... as before.
const BILL_PATH = /^\/bill\/([A-Za-z]{2,3}\d{1,5})\/?$/;
// A law section's address is /law/<CODE>/<section> (/law/PE/46.06); old /#statute?law=PE&sec=46.06 links still work.
const LAW_PATH = /^\/law\/([A-Za-z]{2})\/(\d+[A-Za-z]?(?:\.\d+[A-Za-z]?)+)\/?$/;

export function parseLocation(pathname, hash) {
  const path = String(pathname || '');
  const extra = String(hash || '').replace(/^#\??/, '');
  const law = LAW_PATH.exec(path);
  if (law) {
    // The path wins over any law/sec in the fragment, as a bill path's id does.
    const kept = extra.split('&').filter(part => part && !/^(?:law|sec)=/.test(part)).join('&');
    const p = parseHash(`#statute?law=${law[1].toUpperCase()}&sec=${law[2].toUpperCase()}${kept ? `&${kept}` : ''}`);
    return p.statute ? p : parseHash('#all');
  }
  const match = BILL_PATH.exec(path);
  if (!match) return parseHash(hash);
  const p = parseHash(`#bill?id=${encodeURIComponent(match[1])}${extra ? `&${extra}` : ''}`);
  return p.bill ? p : parseHash('#all');
}

// The bill link the Share button copies. `version` is the bill's drawn share card (live/og/rendered.json); preview
// caches (Facebook, X, Discord) key on the address, so a redrawn card needs a new one. The app ignores `?c`.
export function shareUrl(origin, id, version) {
  if (!isBillId(id)) return null;
  const v = typeof version === 'string' && /^[0-9a-f]{6,64}$/.test(version) ? version : null;
  return `${origin}/bill/${id}${v ? `?c=${v}` : ''}`;
}

// The address of a law section's page, or null for anything that is not a statute key.
export function lawPath(statute) {
  const [law, sec] = String(statute || '').split(' ');
  return LAW_CODE.test(law || '') && LAW_SECTION.test(sec || '') && sec.length <= 16 ? `/law/${law}/${sec}` : null;
}

export function buildUrl(view, filters, options = {}) {
  const law = view === 'statute' ? lawPath(options.statute) : null;
  if (law) {
    const extra = buildHash('statute', filters, {...options, statute: null}).replace(/^#statute\??/, '');
    return `${law}${extra ? `#${extra}` : ''}`;
  }
  if (view !== 'bill' || !isBillId(options.bill)) return `/${buildHash(view, filters, options)}`;
  const extra = buildHash('bill', {}, {...options, bill: null}).replace(/^#bill\??/, '');
  return `/bill/${options.bill}${extra ? `#${extra}` : ''}`;
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
export function applyFollowOps(follows, ops, max = MAX_FOLLOWS) {
  const set = new Set(follows);
  for (const {op, id} of ops || []) if (op === 'follow') set.add(id); else if (op === 'unfollow') set.delete(id);
  return cleanFollows([...set], max);
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
  return {id: raw.id, name, filters, seen: typeof raw.seen === 'string' && DAY.test(raw.seen) && !Number.isNaN(Date.parse(`${raw.seen}T00:00:00Z`)) ? raw.seen : null};
}
export function cleanSearches(raw, max = MAX_SEARCHES) {
  const seen = new Set(), out = [];
  for (const item of Array.isArray(raw) ? raw : []) {
    const s = cleanSearch(item);
    if (s && !seen.has(s.id)) { seen.add(s.id); out.push(s); }
  }
  return out.slice(0, max);
}
// save-search replaces (or adds) one search by id; delete-search removes it.
export function applySearchOps(searches, ops, max = MAX_SEARCHES) {
  const byId = new Map(cleanSearches(searches, Infinity).map(s => [s.id, s]));
  for (const {op, id, value} of ops || []) {
    if (op === 'save-search') { const s = cleanSearch(value); if (s && s.id === id) byId.set(id, s); }
    else if (op === 'delete-search') byId.delete(id);
  }
  return cleanSearches([...byId.values()], max);
}
export function newSearchId(random = n => crypto.getRandomValues(new Uint8Array(n))) {
  return [...random(10)].map(b => 'abcdefghijklmnopqrstuvwxyz0123456789'[b % 36]).join('');
}
// A readable default name from the filters that are set.
export function searchName(filters, agencyName = id => id, areaName = id => id) {
  const f = cleanFilters(filters);
  const parts = [f.query && `“${f.query.trim()}”`, f.area && areaName(f.area), f.topic, f.agency && agencyName(f.agency), f.chamber, f.party && `${f.party} authors`, f.stage, f.outlook,
    f.action, f.companion && 'Has companion', f.onlyWatch && 'Watched only'].filter(Boolean);
  return (parts.join(' · ') || 'All bills').slice(0, 80);
}

// One file for everything saved: the watchlist (as the first of `lists`, ready for named lists), follows, saved
// searches and the colour theme. Device-only things (Near you districts, remembered filters, the sync link) are never in it.
const THEME_ID = /^[a-z][a-z-]{0,23}$/;
export const PROFILE_FORMAT = 'texas-bill-atlas-profile-v1';
export function profileFile({watch = [], follows = [], searches = [], theme = null} = {}, now = new Date()) {
  return JSON.stringify({format: PROFILE_FORMAT, session: '90R', exported_at: now.toISOString(),
    lists: [{id: 'main', name: 'Watchlist', bills: [...watch]}], follows: cleanFollows([...follows]),
    searches: cleanSearches(searches), ...(typeof theme === 'string' && THEME_ID.test(theme) ? {theme} : {})}, null, 2);
}

// A profile file, or anything parseWatchlistFile reads (older watchlist exports, arrays, pasted text).
// Returns {bills, follows, searches} plus theme when the file has valid colours; importing only adds.
export function parseProfileFile(text) {
  let data = null;
  try { data = JSON.parse(text); } catch {}
  if (data?.format !== PROFILE_FORMAT) return {bills: parseWatchlistFile(text), follows: [], searches: []};
  const lists = Array.isArray(data.lists) ? data.lists : [];
  const bills = uniqueIds(lists.flatMap(l => Array.isArray(l?.bills) ? l.bills.filter(x => typeof x === 'string') : []));
  const follows = cleanFollows(data.follows), searches = cleanSearches(data.searches);
  if (!bills.length && !follows.length && !searches.length) throw Error('This file has no bills or legislators (or saved searches)');
  return {bills, follows, searches, ...(typeof data.theme === 'string' && THEME_ID.test(data.theme) ? {theme: data.theme} : {})};
}
