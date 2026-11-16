// Moving a browser's saved data from the old address to the new one (pure rules; features/move does the hand-off).
// Safety property: no saved item disappears. Each incoming item ends up in its list here, in the held key (over a
// limit, or refused by the cleaners), or stays on the old site, which the move never changes.
import {isBillId, cleanFollows, cleanSearches, cleanFilters, MAX_LIST, MAX_FOLLOWS, MAX_SEARCHES} from '../prefs.js';
import {cleanTheme, cleanMode} from '../features/theme/model.js';
import {cleanNear, NEAR_KEY} from '../geo.js';

// Fixed in code, never read from the address, storage or a message.
export const MOVE_ORIGINS = {'https://bills.ctharvey.me': 'https://billatlas.org'};
// Tests: 127.0.0.1:<port> moves to localhost:<port>, two origins served by one local server. Loopback only.
const LOOPBACK = /^http:\/\/127\.0\.0\.1(:\d{1,5})?$/;
export function moveTarget(origin) {
  if (Object.hasOwn(MOVE_ORIGINS, origin)) return MOVE_ORIGINS[origin];
  const m = LOOPBACK.exec(origin);
  return m ? `http://localhost${m[1] || ''}` : null;
}
export function moveSource(origin) {
  const found = Object.entries(MOVE_ORIGINS).find(([, to]) => to === origin);
  if (found) return found[0];
  const m = /^http:\/\/localhost(:\d{1,5})?$/.exec(origin);
  return m ? `http://127.0.0.1${m[1] || ''}` : null;
}

export const KEYS = {
  watch: 'tx-bill-atlas-watch-90r', follows: 'tx-bill-atlas-follow-90r', searches: 'tx-bill-atlas-searches-90r',
  prefs: 'tx-bill-atlas-prefs-v1', sync: 'tx-bill-atlas-sync-v1', near: NEAR_KEY, agencySort: 'tx-bill-atlas-agency-sort',
};
export const MOVED_KEY = 'tx-bill-atlas-moved-v1';            // Old site: digest of the last verified move.
export const HELD_KEY = 'tx-bill-atlas-move-held-v1';         // New site: items over a limit or refused, raw.
export const PREVIOUS_SYNC_KEY = 'tx-bill-atlas-sync-previous-v1';  // New site: the old browser's other sync link.
const BOOKKEEPING = new Set([MOVED_KEY, HELD_KEY, PREVIOUS_SYNC_KEY]);
const OWN = /^(tx|texas)-bill-atlas-/;
const EDIT_KEY = /^[A-Za-z0-9_-]{22}$/;

const parse = text => { try { return JSON.parse(text); } catch { return undefined; } };
const list = v => (Array.isArray(v) ? v : []);
const normalizeId = s => String(s).trim().toUpperCase().replace(/\s+/g, '');

// Every own key as stored text. Bookkeeping keys stay behind.
export function collect(storage) {
  const items = {};
  for (let i = 0; i < storage.length; i++) {
    const key = storage.key(i);
    if (typeof key === 'string' && OWN.test(key) && !BOOKKEEPING.has(key)) items[key] = storage.getItem(key);
  }
  return {v: 1, items};
}

// The payload through the cleaners the app uses at load. Nothing is capped here: plan() splits at the limits.
// The sync value yields only the edit key, never its version, pending ops or merge state.
export function receive(payload) {
  const items = payload && typeof payload === 'object' && payload.items && typeof payload.items === 'object' ? payload.items : {};
  const raw = key => (typeof items[key] === 'string' ? parse(items[key]) : undefined);
  const refused = {watch: [], follows: [], searches: []};

  const watch = [];
  for (const id of list(raw(KEYS.watch))) {
    const n = typeof id === 'string' ? normalizeId(id) : '';
    if (isBillId(n)) { if (!watch.includes(n)) watch.push(n); } else refused.watch.push(id);
  }
  const follows = [];
  for (const code of list(raw(KEYS.follows))) {
    if (cleanFollows([code]).length) { if (!follows.includes(code)) follows.push(code); } else refused.follows.push(code);
  }
  const searches = [];
  for (const s of list(raw(KEYS.searches))) {
    const [clean] = cleanSearches([s]);
    if (!clean) refused.searches.push(s);
    else if (!searches.some(x => x.id === clean.id)) searches.push(clean);
  }

  const settings = {};
  const prefs = raw(KEYS.prefs);
  if (prefs && typeof prefs === 'object' && !Array.isArray(prefs)) {
    if (typeof prefs.theme === 'string' && cleanTheme(prefs.theme) === prefs.theme) settings.theme = prefs.theme;
    if (typeof prefs.mode === 'string' && cleanMode(prefs.mode) === prefs.mode) settings.mode = prefs.mode;
    const filters = cleanFilters(prefs.filters);
    if (Object.keys(filters).length) settings.filters = filters;
  }
  const near = cleanNear(raw(KEYS.near));
  if (near) settings.near = near;
  const sort = typeof items[KEYS.agencySort] === 'string' ? items[KEYS.agencySort] : null;
  if (sort === 'name' || sort === 'count') settings.agencySort = sort;

  const link = raw(KEYS.sync);
  const editKey = link && typeof link.key === 'string' && EDIT_KEY.test(link.key) && link.mode !== 'view' ? link.key : null;
  return {watch, follows, searches, settings, editKey, refused};
}

// What this site adds, keeps aside and joins. `current` is this site's own state:
// {watch, follows, searches, settings: {theme, mode, filters, near, agencySort}, syncKey}.
export function plan(current, cleaned) {
  const split = (mine, incoming, same, max) => {
    const add = incoming.filter(x => !mine.some(m => same(m, x)));
    const room = Math.max(0, max - mine.length);
    return [add.slice(0, room), add.slice(room)];
  };
  const [watch, watchOver] = split(current.watch, cleaned.watch, (a, b) => a === b, MAX_LIST);
  const [follows, followsOver] = split(current.follows, cleaned.follows, (a, b) => a === b, MAX_FOLLOWS);
  const [searches, searchesOver] = split(current.searches, cleaned.searches, (a, b) => a.id === b.id, MAX_SEARCHES);
  const settings = Object.fromEntries(Object.entries(cleaned.settings).filter(([k]) => current.settings?.[k] == null));
  const held = {
    watch: [...watchOver, ...cleaned.refused.watch],
    follows: [...followsOver, ...cleaned.refused.follows],
    searches: [...searchesOver, ...cleaned.refused.searches],
  };
  let sync = 'none';
  if (cleaned.editKey) sync = !current.syncKey ? 'join' : current.syncKey === cleaned.editKey ? 'same' : 'keep-previous';
  return {watch, follows, searches, settings, held, sync, editKey: cleaned.editKey};
}

const heldIn = (stored, item) => stored.some(x => JSON.stringify(x) === JSON.stringify(item));
// Adds held items to whatever earlier moves held; nothing is ever dropped from it.
export function keepHeld(storage, held) {
  const before = parse(storage.getItem(HELD_KEY) || 'null') || {};
  const out = {};
  for (const name of ['watch', 'follows', 'searches']) {
    out[name] = list(before[name]);
    for (const item of held[name]) if (!heldIn(out[name], item)) out[name].push(item);
  }
  if (!out.watch.length && !out.follows.length && !out.searches.length) return true;
  try { storage.setItem(HELD_KEY, JSON.stringify(out)); return true; } catch { return false; }
}

// Reads back: every incoming item is in its list or held, and the sync outcome stuck. Counts only.
export function verify(storage, cleaned, planned) {
  const read = key => list(parse(storage.getItem(key) || '[]'));
  const held = parse(storage.getItem(HELD_KEY) || 'null') || {};
  const watch = read(KEYS.watch), follows = read(KEYS.follows), searches = read(KEYS.searches).map(s => s?.id);
  const missing = {
    watch: cleaned.watch.filter(id => !watch.includes(id) && !list(held.watch).includes(id)).length,
    follows: cleaned.follows.filter(c => !follows.includes(c) && !list(held.follows).includes(c)).length,
    searches: cleaned.searches.filter(s => !searches.includes(s.id) && !list(held.searches).some(h => h?.id === s.id)).length,
    refused: ['watch', 'follows', 'searches'].reduce((n, k) => n + cleaned.refused[k].filter(x => !heldIn(list(held[k]), x)).length, 0),
  };
  let sync = true;
  if (planned?.sync === 'join' || planned?.sync === 'same') sync = parse(storage.getItem(KEYS.sync) || 'null')?.key === cleaned.editKey;
  if (planned?.sync === 'keep-previous') sync = parse(storage.getItem(PREVIOUS_SYNC_KEY) || 'null')?.key === cleaned.editKey;
  const ok = sync && Object.values(missing).every(n => n === 0);
  return {ok, missing, sync};
}

// Fingerprint of what a move carries (lists, edit key, settings), not of visit stamps, sync versions, pending ops
// or when a search was last opened. The old site offers the move again when this changes.
export function digest(cleaned) {
  const value = JSON.stringify([
    [...cleaned.watch].sort(), [...cleaned.follows].sort(),
    cleaned.searches.map(({id, name, filters}) => [id, name, filters]).sort((a, b) => (a[0] < b[0] ? -1 : 1)),
    cleaned.editKey, Object.keys(cleaned.settings).sort().map(k => [k, cleaned.settings[k]]),
  ]);
  let h = 0x811c9dc5;
  for (let i = 0; i < value.length; i++) { h ^= value.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16).padStart(8, '0');
}

// Anything worth moving: a list item, a sync link or a setting. Not the disclaimer, visit stamp or easter eggs.
export function hasMovable(storage) {
  const c = receive(collect(storage));
  return Boolean(c.watch.length || c.follows.length || c.searches.length || c.editKey || Object.keys(c.settings).length
    || c.refused.watch.length || c.refused.follows.length || c.refused.searches.length);
}

// The old site shows the move banner until a verified move carried exactly what it holds now.
export function moveNeeded(storage) {
  if (!hasMovable(storage)) return false;
  const note = parse(storage.getItem(MOVED_KEY) || 'null');
  return note?.digest !== digest(receive(collect(storage)));
}

