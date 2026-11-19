// Companion bills: the source's lists cleaned, links in both directions, groups within a list, labels, and the bills
// an agency reaches only through a companion. No DOM; taxonomy.js re-exports these for its existing importers.

const BILL_KEY = /^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/;
const billNumber = id => id.replace(/^(HJR|SJR|HCR|SCR|HB|SB|HR|SR)/, '$1 ');

// Companions as the source lists them: [{id, author, relation}]. Malformed entries and self-references are dropped.
export function normalizeCompanions(value, selfId = '') {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  return value.flatMap(c => {
    const id = String(c?.id || '').replace(/\s/g, '').toUpperCase();
    if (!BILL_KEY.test(id) || id === selfId || seen.has(id)) return [];
    seen.add(id);
    return [{id, number: billNumber(id), author: typeof c.author === 'string' ? c.author.slice(0, 80) : '',
      relation: typeof c.relation === 'string' ? c.relation.slice(0, 40) : ''}];
  });
}

// Companion links in both directions: a bill lists its companion, and the companion may not list it back yet.
// Returns Map(id -> [{id, number, author, relation}]), sorted by id.
export function companionIndex(bills) {
  const byId = new Map(bills.map(b => [b.id, b]));
  const links = new Map();
  const add = (from, to) => {
    if (!links.has(from)) links.set(from, new Map());
    const known = links.get(from).get(to.id);
    // Prefer what the bill itself lists; fill gaps from the other side.
    links.get(from).set(to.id, known ? {...to, ...Object.fromEntries(Object.entries(known).filter(([, v]) => v))} : to);
  };
  // Own listings first, so a reverse link only fills fields the bill's own listing left empty.
  for (const b of bills) for (const c of b.companions || []) add(b.id, c);
  for (const b of bills) for (const c of b.companions || []) {
    const author = byId.get(b.id)?.authors?.[0] || '';
    add(c.id, {id: b.id, number: billNumber(b.id), author, relation: c.relation});
  }
  return new Map([...links].map(([id, m]) => [id, [...m.values()].sort((a, b) => a.id.localeCompare(b.id, 'en', {numeric: true}))]));
}

// Pull companions that are both in a list together: each bill plus every companion (and their companions) also in
// the list, placed where the first of them sits in the list's order. Returns [[b], [c, d], ...]; every bill once.
export function companionGroups(list, index) {
  const pos = new Map(list.map((b, i) => [b.id, i]));
  const placed = new Set(), groups = [];
  for (const b of list) {
    if (placed.has(b.id)) continue;
    const group = [], queue = [b];
    placed.add(b.id);
    while (queue.length) {
      const x = queue.shift();
      group.push(x);
      for (const c of index.get(x.id) || []) if (pos.has(c.id) && !placed.has(c.id)) { placed.add(c.id); queue.push(list[pos.get(c.id)]); }
    }
    groups.push(group.sort((x, y) => pos.get(x.id) - pos.get(y.id)));
  }
  return groups;
}

// "HB 234 (identical)" for a companion entry from companionIndex.
export const companionLabel = c => `${c.number || String(c.id).replace(/^([A-Z]+)(\d)/, '$1 $2')}${c.relation ? ` (${c.relation.toLowerCase()})` : ''}`;

// Bills that lack `agencyId` themselves but have a companion carrying it: Map(billId -> [companion ids]).
export function agencyViaCompanion(bills, agencyId, index) {
  const tagged = new Set(bills.filter(b => (b.agencies || []).some(a => a.id === agencyId)).map(b => b.id));
  const via = new Map();
  for (const b of bills) {
    if (tagged.has(b.id)) continue;
    const ids = (index.get(b.id) || []).map(c => c.id).filter(id => tagged.has(id));
    if (ids.length) via.set(b.id, ids);
  }
  return via;
}
