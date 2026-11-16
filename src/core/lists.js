// Saved lists live in this site's storage, shared by every open tab. A change re-reads the stored list and applies
// only this tab's change, so a tab holding an old copy in memory cannot overwrite what another tab saved.
import {cleanFollows, cleanSearches, applySearchOps} from '../prefs.js';

const parse = (storage, key) => { try { const v = JSON.parse(storage.getItem(key) || '[]'); return Array.isArray(v) ? v : []; } catch { return []; } };
const write = (storage, key, value) => { try { storage.setItem(key, JSON.stringify(value)); } catch {} };

export const readWatch = (storage, key) => [...new Set(parse(storage, key).filter(id => typeof id === 'string'))];
export const readFollows = (storage, key) => cleanFollows(parse(storage, key));
export const readSearches = (storage, key) => cleanSearches(parse(storage, key));

// op 'add' or 'remove'. Returns the stored list after the change and the ids this call actually changed.
export function changeWatchList(storage, key, op, ids) {
  const set = new Set(readWatch(storage, key)), changed = [];
  for (const id of ids) {
    if (op === 'add' ? set.has(id) : !set.has(id)) continue;
    op === 'add' ? set.add(id) : set.delete(id);
    changed.push(id);
  }
  if (changed.length) write(storage, key, [...set]);
  return {list: [...set], changed};
}

// op 'follow' or 'unfollow'; follows stop at `max`.
export function changeFollowList(storage, key, op, codes, max) {
  let list = readFollows(storage, key);
  for (const code of codes) {
    const has = list.includes(code);
    if (op === 'follow' ? has : !has) continue;
    if (op === 'follow' && list.length >= max) break;
    list = op === 'follow' ? [...list, code] : list.filter(c => c !== code);
  }
  const before = readFollows(storage, key);
  list = cleanFollows(list);
  const changed = codes.filter((c, i) => codes.indexOf(c) === i && before.includes(c) !== list.includes(c));
  if (changed.length) write(storage, key, list);
  return {list, changed};
}

// op 'save-search' (item is the search) or 'delete-search' (item is its id).
export function changeSearchList(storage, key, op, item) {
  const id = op === 'save-search' ? item.id : item;
  const list = cleanSearches(applySearchOps(readSearches(storage, key), [{op, id, value: item}]));
  write(storage, key, list);
  return list;
}
