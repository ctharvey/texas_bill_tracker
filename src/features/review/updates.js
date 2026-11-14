// What Luna's publishes changed (live/luna/updates.json): the overall counts and each bill's changes. No DOM.

export const KINDS = [
  {kind: 'reviewed', label: 'newly reviewed'},
  {kind: 'new_version', label: 'new text version reviewed'},
  {kind: 'all_agencies', label: 'now marked all state agencies'},
  {kind: 'not_all_agencies', label: 'no longer marked all state agencies'},
  {kind: 'agencies', label: 'agencies changed'},
  {kind: 'topics', label: 'topics changed'},
  {kind: 'summary', label: 'summary rewritten'},
  {kind: 'withdrawn', label: 'review withdrawn while its text changes'},
];
const ORDER = Object.fromEntries(KINDS.map((k, i) => [k.kind, i]));
const LABEL = Object.fromEntries(KINDS.map(k => [k.kind, k.label]));

const list = (names, sign) => (Array.isArray(names) ? names : []).map(n => sign + n);

// One change as a short line: "Agencies: +Texas Department of Transportation, -Comptroller".
export function changeText(change) {
  if (!change || !LABEL[change.kind]) return '';
  if (change.kind === 'agencies' || change.kind === 'topics') {
    const parts = [...list(change.added, '+'), ...list(change.removed, '-')];
    const head = change.kind === 'agencies' ? 'Agencies' : 'Topics';
    return parts.length ? `${head}: ${parts.join(', ')}` : LABEL[change.kind];
  }
  if (change.kind === 'new_version' && change.to) return `New text version reviewed (${change.to})`;
  const text = LABEL[change.kind];
  return text[0].toUpperCase() + text.slice(1);
}

const valid = u => u && typeof u.at === 'string' && Number.isFinite(Date.parse(u.at)) && u.bills && typeof u.bills === 'object';

// The publishes in the log, newest first, each {at, counts: [{kind, label, n}], bills: [{id, changes}]}.
export function updateEntries(updates) {
  const entries = Array.isArray(updates?.updates) ? updates.updates.filter(valid) : [];
  return entries.sort((a, b) => Date.parse(b.at) - Date.parse(a.at)).map(u => ({
    at: u.at,
    counts: KINDS.map(k => ({...k, n: Number(u.counts?.[k.kind]) || 0})).filter(c => c.n > 0),
    bills: Object.entries(u.bills).filter(([, cs]) => Array.isArray(cs) && cs.length)
      .map(([id, changes]) => ({id, changes: [...changes].filter(c => LABEL[c?.kind])
        .sort((a, b) => ORDER[a.kind] - ORDER[b.kind])}))
      .filter(b => b.changes.length),
  }));
}

// Everything that changed in the last `hours` before `now` (ms), merged: each bill once with its newest change of
// each kind, newest bills first; counts are bills per kind over the window.
export function recentChanges(updates, now, hours = 24) {
  const since = now - hours * 3600000;
  const bills = new Map();
  for (const entry of updateEntries(updates)) {
    if (Date.parse(entry.at) < since) continue;
    for (const {id, changes} of entry.bills) {
      const seen = bills.get(id) || {id, at: entry.at, changes: []};
      for (const change of changes) {
        if (!seen.changes.some(c => c.kind === change.kind)) seen.changes.push(change);  // entries are newest first
      }
      bills.set(id, seen);
    }
  }
  const rows = [...bills.values()].map(b => ({...b, changes: b.changes.sort((x, y) => ORDER[x.kind] - ORDER[y.kind])}))
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at) || ORDER[a.changes[0].kind] - ORDER[b.changes[0].kind]
      || a.id.localeCompare(b.id));
  const counts = KINDS.map(k => ({...k, n: rows.filter(r => r.changes.some(c => c.kind === k.kind)).length}))
    .filter(c => c.n > 0);
  return {counts, bills: rows};
}
