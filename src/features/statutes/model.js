import {parseParagraph} from '../billtext/model.js';

// ---- Statutes: the sections of Texas law each bill changes (live/statutes, built by scripts/build_feeds.py) ----

export const STATUTE_KEY = /^([A-Z]{2}) (\d+[A-Z]?(?:\.\d+[A-Z]?)+)$/;
export const STATUTE_KINDS = {m: 'amends', n: 'adds a new section', r: 'repeals'};

// Following a law section is a saved search whose only filter is the section key as the query ({query: "PE 46.06"}),
// so it syncs, exports and counts new actions like any saved search. A query that is exactly a key matches only the
// bills the index lists for that section, never free text: "pe" alone is in almost every bill's text.
// The codes the statute parser tracks (scripts/build_feeds.py CODE_ABBR; tests/test_law_pages.py keeps them equal),
// so "PM 2.5" or "CO 2.0" stays a text search.
export const LAW_CODE_NAMES = {AG: 'Agriculture Code', AL: 'Alcoholic Beverage Code', BC: 'Business and Commerce Code',
    BO: 'Business Organizations Code', CP: 'Civil Practice and Remedies Code', CR: 'Code of Criminal Procedure',
    ED: 'Education Code', EL: 'Election Code', ES: 'Estates Code', FA: 'Family Code', FI: 'Finance Code',
    GV: 'Government Code', HR: 'Human Resources Code', HS: 'Health and Safety Code', IN: 'Insurance Code',
    LA: 'Labor Code', LG: 'Local Government Code', NR: 'Natural Resources Code', OC: 'Occupations Code',
    PE: 'Penal Code', PR: 'Property Code', PW: 'Parks and Wildlife Code', SD: 'Special District Local Laws Code',
    TN: 'Transportation Code', TX: 'Tax Code', UT: 'Utilities Code', WA: 'Water Code'};
export const LAW_CODES = new Set(Object.keys(LAW_CODE_NAMES));
export const isLawFollowQuery = query => typeof query === 'string' && STATUTE_KEY.test(query)
    && LAW_CODES.has(query.slice(0, 2)) && query.length <= 20;
// Every saved search that is this section's follow: two devices can each follow it and sync keeps both (ids differ),
// and a search saved from the explorer as exactly the key is the same search. Unfollowing removes them all.
export const lawFollowsOf = (searches, key) => (searches || []).filter(s => s?.filters?.query === key
    && Object.keys(s.filters).length === 1);
export const lawFollowOf = (searches, key) => lawFollowsOf(searches, key)[0] || null;
// The day a bill started changing a section, when that was after the index began recording it (else '').
export const lawFirstSeen = (index, key, id) => {
    const day = index?.sections?.[key]?.f?.[id];
    return typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : '';
};
export const lawFollowSearch = (key, name, id, seen) => ({id, name: String(name).slice(0, 80), filters: {query: key}, seen});
// Bills a section-key query selects: those the index lists for that section (none when no bill changes it yet).
export const lawFollowBills = (index, key) => (index?.sections?.[key]?.b || []).map(p => p[0]);
const isMap = o => o && typeof o === 'object' && !Array.isArray(o);

export const statuteFile = key => STATUTE_KEY.test(key) && key.length <= 20 ? `${key.replace(' ', '-')}.json` : null;
export function statuteLabel(key, codes) {
    const m = STATUTE_KEY.exec(key || '');
    if (!m) return String(key || '');
    return `${codes?.[m[1]] || LAW_CODE_NAMES[m[1]] || m[1]} ${m[1] === 'CR' ? 'Art.' : '§'} ${m[2]}`;
}
// Checked against statutes.capitol.texas.gov for every code the index uses.
export function officialStatuteUrl(key) {
    const m = STATUTE_KEY.exec(key || '');
    if (!m) return '';
    return `https://statutes.capitol.texas.gov/?tab=1&code=${m[1]}&chapter=${m[1]}.${m[2].split('.')[0]}&artSec=${m[2]}`;
}
export const validStatuteIndex = x => x?.format === 'texas-bill-statutes-v1' && isMap(x.sections) && isMap(x.bills) && isMap(x.codes);
export const validStatuteSection = (x, key) => x?.format === 'texas-bill-statute-section-v1' && x.key === key && Array.isArray(x.entries);

// bill id -> [{key, kind, others}] from the index's section -> bills map.
export function statutesByBill(index) {
    const out = new Map();
    for (const [key, s] of Object.entries(index?.sections || {})) {
        if (!STATUTE_KEY.test(key) || !Array.isArray(s?.b)) continue;
        for (const pair of s.b) {
            if (!Array.isArray(pair) || typeof pair[0] !== 'string' || !STATUTE_KINDS[pair[1]]) continue;
            if (!out.has(pair[0])) out.set(pair[0], []);
            out.get(pair[0]).push({key, kind: pair[1], others: s.b.length - 1});
        }
    }
    return out;
}

// "48.160", "§ 48.160", "Penal Code 46.06", "ED 48.160", "CCP art. 46.04" -> {code (or null for any code), sec}.
export function parseStatuteQuery(query, codes) {
    const text = String(query || '').trim().replace(/\s+/g, ' ');
    const m = /^(.*?)[\s,]*(?:§+\s*|sec(?:tion)?\.?\s+|art(?:icle)?\.?\s+)?(\d+[a-z]?(?:\.\d+[a-z]?)+)$/i.exec(text);
    if (!m) return null;
    const sec = m[2].toUpperCase(), name = m[1].trim().replace(/[,§]+$/, '').trim().toLowerCase();
    if (!name) return {code: null, sec};
    for (const [abbr, full] of Object.entries(codes || {})) {
        const f = full.toLowerCase();
        if (name === abbr.toLowerCase() || name === f || name === f.replace(/ code$/, '') || name === f.replace(/^code of /, '')
            || (abbr === 'CR' && /^(ccp|c\.c\.p\.)$/.test(name))) return {code: abbr, sec};
    }
    return null;
}
// Section keys in the index that a parsed query names.
export function statuteKeysFor(index, parsed) {
    if (!parsed || !index?.sections) return [];
    return Object.keys(index.sections).filter(k => {
        const m = STATUTE_KEY.exec(k);
        return m && m[2] === parsed.sec && (!parsed.code || parsed.code === m[1]);
    });
}

// One quoted paragraph as current law (unmarked + struck words) and as proposed (unmarked + added words). The bill
// wraps struck words in brackets outside the del tags ("\[<del>old</del>\]"); those brackets belong to neither.
export function lawParagraph(line) {
    const segments = parseParagraph(line, 1).segments.map(s => ({...s}));
    segments.forEach((s, i) => {
        if (s.mark !== 'del') return;
        const before = segments[i - 1], after = segments[i + 1];
        if (before && !before.mark && before.text.endsWith('[')) before.text = before.text.slice(0, -1);
        if (after && !after.mark && after.text.startsWith(']')) after.text = after.text.slice(1);
    });
    const join = keep => segments.filter(s => !s.mark || s.mark === keep).map(s => s.text).join('').replace(/\s+/g, ' ').trim();
    return {current: join('del'), proposed: join('ins')};
}

const SECTION_HEAD = /^((?:Sec|Art)\. \d+[A-Z]?(?:\.\d+[A-Z]?)+\.\s+[^a-z]*?\.)(?:\s+|$)/;
const SUB_LABEL = /^\(([a-z]{1,3}(?:-\d+[a-z]?)?)\)\s/;

// Paragraphs of one bill's entry -> ordered [{label, text}] for one version. "head" is "Sec. N. HEADING."; "" is
// body text before any lettered subsection; numbered and capital-lettered paragraphs stay with their subsection.
export function lawUnits(paragraphs, which) {
    const units = [];
    let current = null;
    const push = (label, text) => {
        if (!text) return;
        if (current && current.label === label) current.text += `\n${text}`;
        else { current = {label, text}; units.push(current); }
    };
    for (const line of paragraphs || []) {
        let text;
        try { text = lawParagraph(line)[which]; } catch { continue; }
        const head = SECTION_HEAD.exec(text);
        if (head) { push('head', head[1]); text = text.slice(head[0].length); }
        const sub = SUB_LABEL.exec(text);
        push(sub ? sub[1] : current && current.label !== 'head' ? current.label : '', text.trim());
    }
    return units.filter(u => u.text.trim());
}

const labelRank = label => {
    if (label === 'head') return [-2, 0, 0];
    if (label === '') return [-1, 0, 0];
    const m = /^([a-z]+)(?:-(\d+)([a-z]?))?$/.exec(label) || [];
    const letters = m[1] || '';
    return [letters.length * 100 + (letters.charCodeAt(0) - 96), Number(m[2] || 0), (m[3] || '').charCodeAt(0) || 0];
};
const byLabel = (a, b) => {
    const x = labelRank(a), y = labelRank(b);
    return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
};

// Words and punctuation as tokens; `space` records whether whitespace came before, so text rebuilds exactly and
// "Beta." vs "Beta changed." differs only in "changed". A newline (between paragraphs) is kept as its own token.
export function lawTokens(text) {
    const out = [];
    for (const m of String(text).matchAll(/(\s*)([^\s.,;:!?()[\]"]+|[.,;:!?()[\]"])/g)) {
        if (m[1].includes('\n')) out.push({t: '\n', space: false});
        out.push({t: m[2], space: m[1].length > 0 && !m[1].includes('\n')});
    }
    return out;
}

// Token-level differences: [{t, space, changed}] for each side. Long, very different texts are marked changed whole.
export function wordDiff(a, b, limit = 2_500_000) {
    const x = lawTokens(a), y = lawTokens(b);
    const all = list => list.map(w => ({...w, changed: w.t !== '\n'}));
    if (x.length * y.length > limit) return {left: all(x), right: all(y), approximate: true};
    const n = x.length, m = y.length, table = new Uint32Array((n + 1) * (m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
        table[i * (m + 1) + j] = x[i].t === y[j].t ? table[(i + 1) * (m + 1) + j + 1] + 1 : Math.max(table[(i + 1) * (m + 1) + j], table[i * (m + 1) + j + 1]);
    const left = [], right = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
        if (x[i].t === y[j].t) { left.push({...x[i++], changed: false}); right.push({...y[j++], changed: false}); }
        else if (table[(i + 1) * (m + 1) + j] >= table[i * (m + 1) + j + 1]) left.push({...x[i++], changed: true});
        else right.push({...y[j++], changed: true});
    }
    while (i < n) left.push({...x[i++], changed: true});
    while (j < m) right.push({...y[j++], changed: true});
    return {left, right, approximate: false};
}

// A side of a comparison: {units, partial, name}. partial = it quotes only some subsections, so a missing one is
// "not changed by it" rather than "not in it".
export function compareLaw(left, right) {
    const l = new Map(left.units.map(u => [u.label, u.text])), r = new Map(right.units.map(u => [u.label, u.text]));
    const labels = [...new Set([...l.keys(), ...r.keys()])].sort(byLabel);
    const missing = (side, other) => side.partial ? `Not changed by ${side.name}` : `Not in ${side.name}`;
    return labels.map(label => {
        if (l.has(label) && r.has(label)) {
            const d = wordDiff(l.get(label), r.get(label));
            return {label, left: d.left, right: d.right, approximate: d.approximate, same: d.left.every(w => !w.changed) && d.right.every(w => !w.changed)};
        }
        const [has, side] = l.has(label) ? ['left', right] : ['right', left];
        // Missing from a whole-section quote: the words are gone on that side. Missing from a partial quote: unchanged.
        const marked = lawTokens(l.get(label) ?? r.get(label)).map(w => ({...w, changed: !side.partial && w.t !== '\n'}));
        return {label, left: has === 'left' ? marked : null, right: has === 'right' ? marked : null,
            leftNote: has === 'right' ? missing(left) : '', rightNote: has === 'left' ? missing(right) : ''};
    });
}

// Current law as the bills quote it: for each subsection, the first amending entry that quotes it (whole-section
// quotes first). Returns {units, sources: [bill ids], partial}.
export function currentLaw(entries) {
    const amending = (entries || []).filter(e => e.kind === 'amend').sort((a, b) => Number(a.partial) - Number(b.partial));
    const units = new Map(), sources = new Set();
    for (const e of amending) {
        for (const u of lawUnits(e.paragraphs, 'current')) {
            if (!units.has(u.label)) { units.set(u.label, u.text); sources.add(e.bill); }
        }
    }
    const partial = !amending.some(e => !e.partial);
    return {units: [...units].map(([label, text]) => ({label, text})).sort((a, b) => byLabel(a.label, b.label)), sources: [...sources], partial};
}

// Entries with the same kind and the same proposed wording (companions, copies) shown as one version.
export function groupStatuteEntries(entries, broad = () => false) {
    const groups = new Map();
    for (const e of entries || []) {
        const units = lawUnits(e.paragraphs, 'proposed');
        const signature = `${e.kind}|${units.map(u => `${u.label}:${u.text}`).join('\n')}`;
        const key = units.length ? signature : `${e.kind}|${e.bill}`;
        if (!groups.has(key)) groups.set(key, {kind: e.kind, entries: [], units, partial: Boolean(e.partial)});
        groups.get(key).entries.push(e);
    }
    const order = {amend: 0, add: 1, repeal: 2};
    return [...groups.values()].map(g => ({...g, broad: g.entries.every(e => broad(e.bill))}))
        .sort((a, b) => order[a.kind] - order[b.kind] || Number(a.broad) - Number(b.broad) || b.entries.length - a.entries.length);
}
