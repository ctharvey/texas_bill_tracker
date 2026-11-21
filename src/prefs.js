// Saving choices without accounts: URL state, remembered filters, profile and watchlist files, and sync merging.
import {routeForPath, routeForView, slugify} from './core/routes.js';
export const FILTER_DEFAULTS = {query: '', topic: '', area: '', agency: '', chamber: '', party: '', stage: '', action: '', outlook: '', sort: 'newest', onlyWatch: false, companion: false};
const FILTER_NAMES = Object.keys(FILTER_DEFAULTS);
// On-or-off filters: true or false when remembered, 1 or 0 in an address.
const ON_OFF = new Set(['onlyWatch', 'companion']);
// What the explorer's search returns (the Bills and Laws buttons). Not a filter: it never reaches saved searches,
// follows or the sync server. It rides in the explorer's address (left out when 'both') and its remembered prefs.
export const SEARCH_SCOPES = ['both', 'bills', 'laws'];
export const cleanScope = value => SEARCH_SCOPES.includes(value) ? value : 'both';
const scopePart = (view, scope) => view === 'all' && scope && scope !== 'both' && SEARCH_SCOPES.includes(scope) ? [`scope=${scope}`] : [];
// The scope after pressing one button: each button turns its kind on or off; the last one on stays on.
export function nextScope(scope, kind) {
  const on = {bills: cleanScope(scope) !== 'laws', laws: cleanScope(scope) !== 'bills'};
  if (!Object.hasOwn(on, kind)) return cleanScope(scope);
  on[kind] = !on[kind];
  return on.bills && on.laws ? 'both' : on.bills ? 'bills' : on.laws ? 'laws' : cleanScope(scope);
}
// Renamed filter values, so old links, saved searches and remembered filters keep working (taxonomy.NO_HEARING).
const RENAMED = {outlook: {'Not rated': 'No hearing yet'}};
// Own keys only, so a value such as "__proto__" passes through as text instead of resolving to Object.prototype.
// Sort names are plain words; anything else ("__proto__") is dropped wherever filters are read.
const SORT_NAME = /^[a-z]{1,20}$/;
const usable = (name, value) => name !== 'sort' || SORT_NAME.test(value);
const current = (name, value) => Object.hasOwn(RENAMED, name) && Object.hasOwn(RENAMED[name], value) ? RENAMED[name][value] : value;
export const VIEWS = ['home', 'all', 'watchlist', 'following', 'today', 'local', 'member', 'agency', 'topic', 'statute', 'laws', 'lawcode', 'bill', 'agencies', 'review', 'method', 'saving', 'export', 'data'];
const LAW_CODE = /^[A-Z]{2}$/;
const LAW_SECTION = /^\d+[A-Z]?(?:\.\d+[A-Z]?)+$/;  // The statute index's section numbers (build_feeds.SECTION_NUM).
const LAW_CHAPTER = /^\d+[A-Z]?$/;  // A chapter: a section number before its first dot ("46", "12A").
// The Constitution (CN): chapters are articles ("8"), sections are "<article>.<section>" ("8.1-b", "1.3a") and keep
// the official case; every other code is upper case.
const CN_CHAPTER = /^[1-9]\d?$/;
const CN_SECTION = /^[1-9]\d?\.\d+[A-Za-z]?(?:-[A-Za-z0-9]+)*$/;
const validSection = (law, sec) => law === 'CN' ? CN_SECTION.test(sec) : LAW_SECTION.test(sec);
const validChapter = (law, ch) => law === 'CN' ? CN_CHAPTER.test(ch) : LAW_CHAPTER.test(ch);
const lawCase = (law, sec) => law === 'CN' ? sec : sec.toUpperCase();
export const MAX_LIST = 500;
const BILL_ID = /^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9]\d{0,4}$/;
const SYNC_KEY = /^[A-Za-z0-9_-]{22}$/;
const MEMBER_CODE = /^A\d{3,5}$/;  // Texas Legislature Online member code
const AGENCY_ID = /^[a-z0-9][a-z0-9-]{0,40}$/;
const TOPIC_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

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
  // Only the explorer has a scope; anything but a known value reads as no scope given.
  const scope = view === 'all' && SEARCH_SCOPES.includes(params.get('scope')) ? params.get('scope') : null;
  const member = String(params.get('code') || '').trim().toUpperCase();
  const agency = String(params.get('id') || '').trim().toLowerCase(), topic = String(params.get('slug') || '').trim().toLowerCase();
  const law = String(params.get('law') || '').toUpperCase(), sec = lawCase(law, String(params.get('sec') || ''));
  const ch = String(params.get('ch') || '').toUpperCase();
  // A whole chapter (`#chapter?law=PE&ch=46`) is the statute view with a chapter key ("PE 46").
  const chapter = view === 'chapter' && LAW_CODE.test(law) && validChapter(law, ch) && ch.length <= 8 ? `${law} ${ch}` : null;
  // A bare address is the dashboard; an unknown view (or `#?query=` and the like) is the explorer.
  return {view: raw === '' ? 'home' : view === 'chapter' ? 'statute' : VIEWS.includes(view) ? view : 'all', filters, hasFilters: Object.keys(filters).length > 0, scope,
    list: list && list.length ? list : null, bill: isBillId(bill) ? bill : null, sync: SYNC_KEY.test(sync) ? sync : null,
    member: view === 'member' && MEMBER_CODE.test(member) ? member : null,
    agency: view === 'agency' && AGENCY_ID.test(agency) ? agency : null, topic: view === 'topic' && TOPIC_SLUG.test(topic) ? topic : null,
    statute: chapter || (view === 'statute' && LAW_CODE.test(law) && validSection(law, sec) && sec.length <= 16 ? `${law} ${sec}` : null),
    lawCode: view === 'lawcode' && LAW_CODE.test(law) ? law : null};
}

// The filters of the views that keep them in the address, defaults left out.
function filterParts(view, filters) {
  const parts = [];
  if (view !== 'all' && view !== 'watchlist') return parts;
  for (const name of FILTER_NAMES) {
    const value = filters?.[name];
    if (value === undefined || value === FILTER_DEFAULTS[name]) continue;
    parts.push(`${name}=${ON_OFF.has(name) ? (value ? '1' : '0') : encodeURIComponent(value)}`);
  }
  return parts;
}

// What rides along with any view: a shared list, a bill open over another view (old links) and a view-only sync key.
// On a path address these stay in the fragment, which never reaches the server, its logs or Cloudflare.
function contextParts(view, {list = null, bill = null, sync = null} = {}) {
  const parts = [];
  if (list?.length) parts.push(`list=${list.join(',')}`);
  if (bill && view !== 'bill') parts.push(`bill=${bill}`);
  if (sync && SYNC_KEY.test(sync)) parts.push(`sync=${sync}`);
  return parts;
}

// `sync` is only ever a view-only key; edit keys are never written into the address bar.
export function buildHash(view, filters, {list = null, bill = null, sync = null, member = null, statute = null, agency = null, topic = null, lawCode = null, scope = null} = {}) {
  const parts = [...filterParts(view, filters), ...scopePart(view, scope)];
  if (view === 'bill' && isBillId(bill)) parts.push(`id=${bill}`);
  if (view === 'member' && MEMBER_CODE.test(member || '')) parts.push(`code=${member}`);
  if (view === 'agency' && AGENCY_ID.test(agency || '')) parts.push(`id=${agency}`);
  if (view === 'topic' && TOPIC_SLUG.test(topic || '')) parts.push(`slug=${topic}`);
  if (view === 'lawcode' && LAW_CODE.test(lawCode || '')) parts.push(`law=${lawCode}`);
  const [law, sec] = String(statute || '').split(' ');
  const chapter = view === 'statute' && LAW_CODE.test(law || '') && validChapter(law, sec || '') && sec.length <= 8;
  if (chapter) parts.push(`law=${law}`, `ch=${sec}`);
  else if (view === 'statute' && LAW_CODE.test(law || '') && validSection(law, sec || '')) parts.push(`law=${law}`, `sec=${sec}`);
  parts.push(...contextParts(view, {list, bill, sync}));
  return `#${chapter ? 'chapter' : VIEWS.includes(view) ? view : 'all'}${parts.length ? `?${parts.join('&')}` : ''}`;
}

// Every view has a path (core/routes.js): /today, /explorer?topic=Water, /bill/HB5, /law/PE/46.06, /law/PE/46,
// /member/A4395/alders. A shared list, an open bill and a view-only sync key ride in the fragment
// (/bill/HB5#list=HB5,SB2&sync=...). Old /#view?... links still parse; the app rewrites them to their path.
const BILL_PATH = /^\/bill\/([A-Za-z]{2,3}\d{1,5})\/?$/;
const LAW_PATH = /^\/law\/([A-Za-z]{2})\/(\d+[A-Za-z]?(?:\.\d+[A-Za-z]?)+)\/?$/;
const CHAPTER_PATH = /^\/law\/([A-Za-z]{2})\/(\d+[A-Za-z]?)\/?$/;
const CN_PATH = /^\/law\/[Cc][Nn]\/(\d{1,2})\/(\d+[A-Za-z]?(?:-[A-Za-z0-9]+)*)\/?$/;  // /law/CN/<article>/<section>: "/law/CN/8/1-b"
const MEMBER_PATH = /^\/member\/([A-Za-z]\d{3,5})(?:\/[^/]*)?\/?$/;  // The slug is for reading only; the code decides.
const AGENCY_PATH = /^\/agency\/([A-Za-z0-9][A-Za-z0-9-]{0,40})\/?$/;
const TOPIC_PATH = /^\/topic\/([A-Za-z0-9][A-Za-z0-9-]{0,79})\/?$/;
const CODE_PATH = /^\/law\/([A-Za-z]{2})\/?$/;  // A code's chapter list (/law/PE); /law itself is a fixed route.
const CONTEXT = new Set(['list', 'bill', 'sync']);

// The fragment's list, bill and sync on a path address; anything else in it is ignored (the path decides the view).
function contextFrom(hash) {
  return [...new URLSearchParams(String(hash || '').replace(/^#\??/, ''))].filter(([name]) => CONTEXT.has(name))
    .map(([name, value]) => `${name}=${encodeURIComponent(value)}`);
}

// Whether a same-site path is one of the app's own views (opened in place), not a file such as /live/feeds/HB1.xml.
export function isAppPath(pathname) {
  const path = String(pathname || '');
  return Boolean(routeForPath(path)) || [BILL_PATH, LAW_PATH, CN_PATH, CHAPTER_PATH, CODE_PATH, MEMBER_PATH, AGENCY_PATH, TOPIC_PATH].some(re => re.test(path));
}

export function parseLocation(pathname, hash, search = '') {
  const path = String(pathname || '');
  const context = contextFrom(hash);
  const at = (view, params = []) => {
    const all = [...params, ...context];
    return parseHash(`#${view}${all.length ? `?${all.join('&')}` : ''}`);
  };
  const keyed = (p, ok) => ok(p) ? p : parseHash('#all');
  let m = LAW_PATH.exec(path);
  if (m) return keyed(at('statute', [`law=${m[1].toUpperCase()}`, `sec=${lawCase(m[1].toUpperCase(), m[2])}`]), p => p.statute);
  if ((m = CN_PATH.exec(path))) return keyed(at('statute', ['law=CN', `sec=${m[1]}.${m[2]}`]), p => p.statute);
  if ((m = CHAPTER_PATH.exec(path))) return keyed(at('chapter', [`law=${m[1].toUpperCase()}`, `ch=${m[2].toUpperCase()}`]), p => p.statute);
  if ((m = BILL_PATH.exec(path))) return keyed(at('bill', [`id=${encodeURIComponent(m[1])}`]), p => p.bill);
  if ((m = MEMBER_PATH.exec(path))) return keyed(at('member', [`code=${m[1].toUpperCase()}`]), p => p.member);
  if ((m = AGENCY_PATH.exec(path))) return keyed(at('agency', [`id=${m[1].toLowerCase()}`]), p => p.agency);
  if ((m = TOPIC_PATH.exec(path))) return keyed(at('topic', [`slug=${m[1].toLowerCase()}`]), p => p.topic);
  if ((m = CODE_PATH.exec(path))) return keyed(at('lawcode', [`law=${m[1].toUpperCase()}`]), p => p.lawCode);
  const route = routeForPath(path);
  const raw = String(hash || '').replace(/^#/, '');
  // A fragment naming a view is an old link (#today, #all?topic=Water, #?query=x), wherever it lands: pasted on /explorer
  // it is a same-page fragment change. At the root anything but plain context (#list=HB5) reads as one, as it always has.
  const named = raw.split('?')[0];
  const oldLink = raw.startsWith('?') || VIEWS.includes(named) || named === 'chapter';
  if (!route || oldLink || route.view === 'home' && raw && !/^[a-z]+=/.test(raw)) return parseHash(hash);
  const query = route.filters ? [...new URLSearchParams(String(search || ''))].filter(([name]) => FILTER_NAMES.includes(name) || name === 'scope')
    .map(([name, value]) => `${name}=${encodeURIComponent(value)}`) : [];
  return at(route.view, query);
}

// The bill link the Share button copies. `version` is the bill's drawn share card (live/og/rendered.json); preview
// caches (Facebook, X, Discord) key on the address, so a redrawn card needs a new one. The app ignores `?c`.
export function shareUrl(origin, id, version) {
  if (!isBillId(id)) return null;
  const v = typeof version === 'string' && /^[0-9a-f]{6,64}$/.test(version) ? version : null;
  return `${origin}/bill/${id}${v ? `?c=${v}` : ''}`;
}

// Links people copy and send. Both are path addresses whose list or key stays in the fragment, so it never reaches the
// server; links copied before paths (/#all?list=..., /#watchlist?sync=...) still open and are rewritten on arrival.
export function shareListUrl(origin, ids) {
  const list = uniqueIds(Array.isArray(ids) ? ids : [...(ids || [])]);
  return `${origin}${buildUrl('all', {}, {list})}`;
}
// A sync link, edit or view-only. buildUrl never writes an edit key into the address bar, so this one is built here.
export function syncLinkUrl(origin, key) {
  return SYNC_KEY.test(key || '') ? `${origin}/watchlist#sync=${key}` : null;
}

// The address of a law section's page, or null for anything that is not a statute key.
export function lawPath(statute) {
  const [law, sec] = String(statute || '').split(' ');
  if (!(LAW_CODE.test(law || '') && validSection(law, sec || '') && sec.length <= 16)) return null;
  return law === 'CN' ? `/law/CN/${sec.replace('.', '/')}` : `/law/${law}/${sec}`;
}

// The address of a whole chapter's view (/law/PE/46), or null.
export function chapterPath(statute) {
  const [law, ch] = String(statute || '').split(' ');
  return LAW_CODE.test(law || '') && validChapter(law, ch || '') && ch.length <= 8 ? `/law/${law}/${ch}` : null;
}

// `slug` (members only) is the member's name, made readable; a member address without one still opens.
export function buildUrl(view, filters, options = {}) {
  view = VIEWS.includes(view) ? view : 'all';
  const context = contextParts(view, options);
  const fragment = context.length ? `#${context.join('&')}` : '';
  const law = view === 'statute' ? lawPath(options.statute) || chapterPath(options.statute) : null;
  if (law) return `${law}${fragment}`;
  if (view === 'bill' && isBillId(options.bill)) return `/bill/${options.bill}${fragment}`;
  if (view === 'member' && MEMBER_CODE.test(options.member || '')) {
    const slug = slugify(options.slug);
    return `/member/${options.member}${slug ? `/${slug}` : ''}${fragment}`;
  }
  if (view === 'agency' && AGENCY_ID.test(options.agency || '')) return `/agency/${options.agency}${fragment}`;
  if (view === 'topic' && TOPIC_SLUG.test(options.topic || '')) return `/topic/${options.topic}${fragment}`;
  if (view === 'lawcode' && LAW_CODE.test(options.lawCode || '')) return `/law/${options.lawCode}${fragment}`;
  const route = routeForView(view);
  // A keyed view without its key keeps the old form, which opens the explorer.
  if (!route?.path) return `/${buildHash(view, filters, options)}`;
  const query = [...filterParts(view, filters), ...scopePart(view, options.scope)];
  return `${route.path}${query.length ? `?${query.join('&')}` : ''}${fragment}`;
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
