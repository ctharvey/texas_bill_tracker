const isMap = o => o && typeof o === 'object' && !Array.isArray(o);

// ---- Population brackets: "a county with a population of more than four million" and the places that meet it ----
export const validBracketIndex = x => x?.format === 'texas-bill-brackets-v1' && isMap(x.places) && isMap(x.bills);
const BRACKET_STATUS = ['changed', 'new', 'existing', 'removed'];
const countOf = n => Number.isInteger(n) && n >= 0 ? n : null;
// "Houston city" -> "Houston"; a name two places share keeps its county: "Reno (Lamar County)".
export function placeName(row) {
    if (!Array.isArray(row) || typeof row[0] !== 'string') return '';
    const name = row[0].replace(/ (city|town|village)$/, '');
    return row[2] ? `${name} (${row[2]})` : name;
}
// The test as the bill words it: "county with a population of more than four million" -> "more than four million".
export const bracketTest = text => String(text || '').replace(/^.*?\bpopulation (?:of |that is )?/i, '').replace(/[,;:.]+$/, '');
const placeList = (ids, places) => Array.isArray(ids) ? ids.map(id => placeName(places[id])).filter(Boolean) : null;

// Drawer rows for one bill: identical tests merged, changes and new limits first, then the narrowest.
export function bracketRows(entry, places = {}) {
    const rows = new Map();
    for (const c of Array.isArray(entry?.c) ? entry.c : []) {
        if (!c || !BRACKET_STATUS.includes(c.s) || !['county', 'city'].includes(c.k) || typeof c.t !== 'string') continue;
        const rel = BRACKET_RELATIONS[c.rel] ? c.rel : null;
        const key = [c.s, c.k, c.lo, c.hi, !!c.cond, c.census || '', c.was?.t || '', rel || ''].join('|');
        if (rows.has(key)) { rows.get(key).times++; continue; }
        const was = isMap(c.was) ? {test: bracketTest(c.was.t), n: countOf(c.was.n), added: countOf(c.was.added),
            dropped: countOf(c.was.dropped), addedNames: placeList(c.was.added_p, places),
            droppedNames: placeList(c.was.dropped_p, places)} : null;
        const near = (Array.isArray(c.near) ? c.near : []).map(id => ({name: placeName(places[id]), pop: places[id]?.[1]})).filter(p => p.name);
        rows.set(key, {status: c.s, kind: c.k, test: bracketTest(c.t), section: String(c.sec || ''), cond: !!c.cond, rel,
            census: Number.isInteger(c.census) ? c.census : null, n: countOf(c.n), names: placeList(c.p, places),
            near, was, times: 1});
    }
    const narrow = r => r.n ?? Infinity;
    return [...rows.values()].sort((a, b) => BRACKET_STATUS.indexOf(a.status) - BRACKET_STATUS.indexOf(b.status)
        || Number(!!a.rel) - Number(!!b.rel) || narrow(a) - narrow(b));
}

// A test on a related place, not on the place the provision covers.
export const BRACKET_RELATIONS = {
    near: 'a neighboring place, not the place this covers',
    inside: 'a place inside the area this covers',
    seat: 'the county a covered city is the county seat of',
    principal: 'the principal city of what this covers',
};

// "1 county", "40 counties", "1,082 cities".
export function placeCount(n, kind) {
    const word = kind === 'county' ? (n === 1 ? 'county' : 'counties') : (n === 1 ? 'city' : 'cities');
    return `${Number(n).toLocaleString('en-US')} ${word}`;
}
