import {parseParagraph} from '../billtext/model.js';

// ---- Statutes: the sections of Texas law each bill changes (live/statutes, built by scripts/build_feeds.py) ----

// A Constitution section is "CN <article>.<section>" ("CN 8.1-b", "CN 3.49-d-14"): the official case is kept
// ("CN 1.3a"), and the section part may carry hyphenated sub-numbers. Every other code is upper case, dotted numbers.
export const STATUTE_KEY = /^([A-Z]{2}) ((?<=^CN )[1-9]\d?\.\d+[A-Za-z]?(?:-[A-Za-z0-9]+)*|(?<!^CN )\d+[A-Z]?(?:\.\d+[A-Z]?)+)$/;
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
    TN: 'Transportation Code', TX: 'Tax Code', UT: 'Utilities Code', WA: 'Water Code', CN: 'Texas Constitution'};
export const LAW_CODES = new Set(Object.keys(LAW_CODE_NAMES));
// A chapter is "<CODE> <chapter>" ("PE 46", "ED 12A"); a section's chapter is its number before the first dot.
// The Constitution's chapters are its articles ("CN 8", 1 to 17).
export const CHAPTER_KEY = /^([A-Z]{2}) ((?<=^CN )[1-9]\d?|(?<!^CN )\d+[A-Z]?)$/;
// The word for a code's chapters: the Constitution has articles.
export const chapterWord = code => code === 'CN' ? 'Article' : 'Chapter';
export const isChapterKey = key => typeof key === 'string' && CHAPTER_KEY.test(key) && LAW_CODES.has(key.slice(0, 2)) && key.length <= 12;
export const chapterOf = key => {
    const m = STATUTE_KEY.exec(key || '');
    return m ? `${m[1]} ${m[2].split('.')[0]}` : null;
};
// A follow is a section or a whole chapter; a chapter follow counts a change to anything in it.
export const isLawFollowQuery = query => typeof query === 'string' && (STATUTE_KEY.test(query) && LAW_CODES.has(query.slice(0, 2))
    && query.length <= 20 || isChapterKey(query));
// Every saved search that is this section's follow: two devices can each follow it and sync keeps both (ids differ),
// and a search saved from the explorer as exactly the key is the same search. Unfollowing removes them all.
export const lawFollowsOf = (searches, key) => (searches || []).filter(s => s?.filters?.query === key
    && Object.keys(s.filters).length === 1);
export const lawFollowOf = (searches, key) => lawFollowsOf(searches, key)[0] || null;
const isMap = o => o && typeof o === 'object' && !Array.isArray(o);
const DAY = /^\d{4}-\d{2}-\d{2}$/;
// The index entries a key covers: the section itself, or for a chapter its whole-chapter entry (index.chapters,
// bills changing the chapter at once) and every section in it.
export function lawEntries(index, key) {
    if (!isChapterKey(key)) return index?.sections?.[key] ? [index.sections[key]] : [];
    const out = isMap(index?.chapters?.[key]) ? [index.chapters[key]] : [];
    for (const [k, s] of Object.entries(index?.sections || {})) if (chapterOf(k) === key) out.push(s);
    return out;
}
// The day a bill started changing a section, when that was after the index began recording it (else ''). For a
// chapter, the latest such day across the chapter: a bill that starts changing another part of it is news again.
export const lawFirstSeen = (index, key, id) => lawEntries(index, key).map(s => s?.f?.[id])
    .filter(day => typeof day === 'string' && DAY.test(day)).sort().pop() || '';
export const lawFollowSearch = (key, name, id, seen) => ({id, name: String(name).slice(0, 80), filters: {query: key}, seen});
// Bills a law-key query selects: those the index lists for that section, or for anything in that chapter (none when
// no bill changes it yet).
export const lawFollowBills = (index, key) => [...new Set(lawEntries(index, key)
    .flatMap(s => Array.isArray(s?.b) ? s.b.filter(Array.isArray).map(p => p[0]) : []))];

export const statuteFile = key => STATUTE_KEY.test(key) && key.length <= 20 ? `${key.replace(' ', '-')}.json` : null;
export function statuteLabel(key, codes) {
    const c = isChapterKey(key) ? CHAPTER_KEY.exec(key) : null;
    if (c) return c[1] === 'CN' ? `Texas Constitution, Article ${c[2]}` : `${codes?.[c[1]] || LAW_CODE_NAMES[c[1]]} chapter ${c[2]}`;
    const m = STATUTE_KEY.exec(key || '');
    if (!m) return String(key || '');
    if (m[1] === 'CN') { const [article, ...rest] = m[2].split('.'); return `Tex. Const. art. ${article}, § ${rest.join('.')}`; }
    return `${codes?.[m[1]] || LAW_CODE_NAMES[m[1]] || m[1]} ${m[1] === 'CR' ? 'Art.' : '§'} ${m[2]}`;
}
// Checked against statutes.capitol.texas.gov for every code the index uses.
export function officialStatuteUrl(key) {
    const c = isChapterKey(key) ? CHAPTER_KEY.exec(key) : null;
    if (c && c[1] === 'CN') return `https://statutes.capitol.texas.gov/Docs/CN/htm/CN.${c[2]}.htm`;
    if (c) return `https://statutes.capitol.texas.gov/?tab=1&code=${c[1]}&chapter=${c[1]}.${c[2]}`;
    const m = STATUTE_KEY.exec(key || '');
    if (!m) return '';
    if (m[1] === 'CN') return `https://statutes.capitol.texas.gov/Docs/CN/htm/CN.${m[2].split('.')[0]}.htm#${m[2]}`;
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

// Citation-style code names ("Tex. Gov't Code", "Tex. Code Crim. Proc."), after codeName folding below.
const CITATION_NAMES = {AG: ['agric', 'agriculture'], AL: ['alco bev', 'alc bev'], BC: ['bus and com'], BO: ['bus orgs'],
    CP: ['civ prac and rem', 'cprc'], CR: ['code crim proc', 'crim proc', 'ccp'], ED: ['educ'], EL: ['elec'], ES: ['est'],
    FA: ['fam'], FI: ['fin'], GV: ['govt', 'gov'], HR: ['hum res'], HS: ['health and safety'], IN: ['ins'], LA: ['lab'],
    LG: ['loc govt', 'loc gov', 'local govt'], NR: ['nat res'], OC: ['occ', 'occupations'], PE: ['penal'], PR: ['prop'],
    PW: ['parks and wild'], SD: ['spec dist'], TN: ['transp'], TX: ['tax'], UT: ['util'], WA: ['water']};
// Lower case, "&" as "and", no periods or apostrophes, no leading "Tex." / "Texas" / "V.T.C.A.", no trailing "Ann." or "Code".
const codeName = text => String(text).toLowerCase().replace(/&/g, ' and ').replace(/[.'’]/g, '').replace(/[^a-z0-9]+/g, ' ').trim()
    .replace(/^(?:(?:vtca|vernons|tex|texas)\s+)+/, '').replace(/ ann(?:otated)?$/, '').replace(/ code$/, '').replace(/^code of /, '');
// The code a name means, among `codes` (abbr -> full name); null when none.
function codeFor(name, codes) {
    const n = codeName(name);
    if (!n) return null;
    for (const [abbr, full] of Object.entries(codes || {}))
        if (n === abbr.toLowerCase() || n === codeName(full) || (CITATION_NAMES[abbr] || []).includes(n)) return abbr;
    return null;
}
// "48.160", "§ 48.160", "Penal Code 46.06", "ED 48.160", "CCP art. 46.04", "Tex. Gov't Code § 552.001" ->
// {code (or null for any code), sec}.
// The Constitution named by its code or title: "CN 8.1-b", "Texas Constitution 8.1-b", "Tex. Const. art. 8, § 1-b".
// Also "Tex. Const. art. VIII § 1-b", "Texas Constitution article 8 section 1-b", and the bills' own order, "Section
// 1-b, Article VIII, Texas Constitution". Articles are arabic or Roman.
const CN_NAME = '(?:cn|texas constitution|tex\\.? const(?:itution)?\\.?)';
const CN_ART = '(\\d{1,2}|[ivx]{1,6})', CN_SEC = '(\\d+[a-z]?(?:-[a-z0-9]+)*)';
const CN_SECTION = new RegExp(`^${CN_NAME}[\\s,]*(?:art(?:icle)?\\.?\\s*)?${CN_ART}(?:\\s*,?\\s*(?:§+|sec(?:tion)?\\.?)\\s*|\\.|\\s+)${CN_SEC}$`, 'i');
const CN_SECTION_FIRST = new RegExp(`^(?:§+|sec(?:tion)?\\.?)\\s*${CN_SEC}\\s*,?\\s*art(?:icle)?\\.?\\s*${CN_ART}\\s*,?\\s*(?:of\\s+)?(?:the\\s+)?${CN_NAME}$`, 'i');
const CN_ARTICLE = new RegExp(`^${CN_NAME}[\\s,]*(?:art(?:icle)?\\.?\\s*)?${CN_ART}$`, 'i');
// "8" or "VIII" -> "8"; null for a malformed numeral ("IIII", "VX").
function cnArticle(text) {
    if (/^\d+$/.test(text)) return String(Number(text));
    const value = {i: 1, v: 5, x: 10}, s = text.toLowerCase();
    let n = 0;
    for (let i = 0; i < s.length; i++) n += value[s[i]] < (value[s[i + 1]] || 0) ? -value[s[i]] : value[s[i]];
    const roman = k => 'x'.repeat(Math.floor(k / 10)) + ['', 'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix'][k % 10];
    return n > 0 && roman(n) === s ? String(n) : null;
}
// What a typed key is, canonical: other codes in upper case, the Constitution with its code in upper case and the
// section part as typed ("cn 8.1-b" -> "CN 8.1-b"). Not checked: isLawFollowQuery does that.
export function canonicalLawKey(text) {
    const q = String(text || '').trim().replace(/\s+/g, ' ');
    return /^cn /i.test(q) ? `CN ${q.slice(3)}` : q.toUpperCase();
}
export function parseStatuteQuery(query, codes) {
    const text = String(query || '').trim().replace(/\s+/g, ' ');
    const cn = CN_SECTION.exec(text), first = cn ? null : CN_SECTION_FIRST.exec(text);
    const [article, section] = cn ? [cn[1], cn[2]] : first ? [first[2], first[1]] : [];
    if (article) {
        const n = cnArticle(article);
        return n ? {code: 'CN', sec: `${n}.${section}`} : null;
    }
    const m = /^(.*?)[\s,]*(?:§+\s*|sec(?:tion)?\.?\s+|art(?:icle)?\.?\s+)?(\d+[a-z]?(?:\.\d+[a-z]?)+)$/i.exec(text);
    if (!m) return null;
    const sec = m[2].toUpperCase(), name = m[1].trim().replace(/[,§]+$/, '').trim();
    if (!name) return {code: null, sec};
    const code = codeFor(name, codes);
    return code ? {code, sec} : null;
}
// A chapter named with its code: "Penal Code chapter 46", "Tex. Gov't Code ch. 552", "Penal Code 46" -> "PE 46"; else null.
export function parseChapterQuery(query, codes) {
    const cn = CN_ARTICLE.exec(String(query || '').trim().replace(/\s+/g, ' '));
    const n = cn && cnArticle(cn[1]);
    if (cn) return n && isChapterKey(`CN ${n}`) ? `CN ${n}` : null;
    const m = /^(.*?)[\s,]*(ch(?:ap(?:ter)?)?\.?\s*)?(\d+[a-z]?)$/i.exec(String(query || '').trim().replace(/\s+/g, ' '));
    const name = m ? m[1].trim().replace(/,$/, '') : '';
    // Without "chapter" only a full code name counts ("Penal Code 46"), so "tax 2025" stays a word search.
    if (!name || (!m[2] && !/\bcode$/i.test(name))) return null;
    const code = codeFor(name, codes), key = code && `${code} ${m[3].toUpperCase()}`;
    return key && isChapterKey(key) ? key : null;
}
// Section keys in the index that a parsed query names.
export function statuteKeysFor(index, parsed) {
    if (!parsed || !index?.sections) return [];
    return Object.keys(index.sections).filter(k => {
        const m = STATUTE_KEY.exec(k);
        return m && m[2].toUpperCase() === parsed.sec.toUpperCase() && (!parsed.code || parsed.code === m[1]);
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

// CR has "Art. 42.04a."; the Constitution's sections are numbered within an article ("Sec. 1-b.", "Sec. 3a.").
const SECTION_HEAD = /^((?:Sec|Art)\. (?:\d+[A-Za-z]?(?:\.\d+[A-Za-z]?)+|\d+[A-Za-z]?(?:-[A-Za-z0-9]+)*)\.\s+[^a-z]*?\.)(?:\s+|$)/;
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

// The history notes after each section in the Legislative Council's files ("Acts 2005, ...", "Amended by:").
const SOURCE_NOTE = /^(?:Acts \d{4},|Amended by:|(?:Added|Amended|Redesignated|Renumbered|Transferred|Reenacted)(?: and \w+)? (?:by|from) |Subsecs?\. \S+(?: .{0,60})? (?:added|amended) by )/;
// One section of a chapter file in live/law (Markdown, "## Sec. N. HEADING. text" blocks) -> units like lawUnits,
// or null when the file has no such section. The first block wins when the file carries several versions. The number
// is matched without case: keys are upper case, the copy has "Art. 42.04a.". For the Constitution `number` is the
// section within its article ("1-b").
export function lawCopyUnits(markdown, number) {
    return lawCopyVersions(markdown, number)[0] || null;
}

// Every section of a chapter file with this number, as units, in file order: a number can be used twice when two
// laws added a section with it (CN 3.49-d-14). Empty when the file has none.
export function lawCopyVersions(markdown, number) {
    const want = new RegExp(`^(?:Sec|Art)\\. ${number.replace(/\./g, '\\.')}\\.\\s`, 'i');
    return String(markdown).split(/^## /m).slice(1).filter(b => want.test(b)).map(blockUnits).filter(Boolean);
}

// The version of current law a bill's wording is closest to (share of distinct words in common, so a longer version
// does not win by size), for a number used twice. Ties keep the earlier version.
export function closestLawVersion(versions, units) {
    const words = list => new Set(list.flatMap(u => String(u.text).toLowerCase().match(/[a-z0-9]+/g) || []));
    const bill = words(units || []);
    let best = versions[0], score = -1;
    for (const v of versions) {
        const own = words(v);
        let n = 0;
        for (const w of own) if (bill.has(w)) n++;
        const s = n / ((own.size + bill.size - n) || 1);
        if (s > score) { best = v; score = s; }
    }
    return best;
}

function blockUnits(block) {
    const paragraphs = block.split(/\n\s*\n/).map(p => p.replace(/\s+/g, ' ').trim()).filter(p => p && !SOURCE_NOTE.test(p))
        .map(p => p.replace(/[\\<]/g, '\\$&'));  // Plain text: a "<" or "\" is never bill markup.
    // Some files end a heading line without its period ("Art. 37.071. PROCEDURE IN CAPITAL CASE"); bills quote it with one.
    if (paragraphs[0] && /^(?:Sec|Art)\. \S+\.\s+[^a-z]+[^.\s]$/.test(paragraphs[0])) paragraphs[0] += '.';
    const units = lawUnits(paragraphs, 'current');
    return units.length ? units : null;
}

// A chapter file of the law copy -> {heading, sections: [[number, heading]]}: "# Penal Code, CHAPTER 46. WEAPONS" and
// one "## Sec. 46.02. UNLAWFUL CARRYING WEAPONS." block per section.
export function lawChapterOutline(markdown) {
    const text = String(markdown);
    const title = /^# [^\n]*?(?:CHAPTER|ARTICLE) \S+?\.?\s+([^\n]+)$/m.exec(text);
    const sections = [];
    // A heading is upper case and can run into the text on the same line ("DEFINITIONS. In this chapter:").
    const headingOf = line => (/^([^a-z]+)\.(?:\s|$)/.exec(line)?.[1] ?? line).replace(/\.$/, '').trim();
    for (const m of text.matchAll(/^## (?:Sec|Art)\. (\S+?)\.\s+([^\n]*)$/gm)) sections.push([m[1], headingOf(m[2])]);
    return {heading: title ? title[1].replace(/\.$/, '').trim() : '', sections};
}

// ---- Law heading search (live/law/search, written by scripts/sync_law.py): one file per 3-letter word prefix ----
const SEARCH_STOP = new Set('of and the for to in by or a an on with under from as at certain other'.split(' '));
// "Public Information Act": "act" or "law" after other words names the law, and headings rarely say it.
const SEARCH_OPTIONAL = new Set(['act', 'acts', 'law', 'laws']);
// The words a heading search uses: 3 letters or more, not a stop word, at most 6.
export function lawSearchTerms(query) {
    const words = [...new Set(String(query || '').toLowerCase().match(/[a-z0-9]+/g) || [])].filter(w => w.length >= 3 && !SEARCH_STOP.has(w));
    const kept = words.filter(w => !SEARCH_OPTIONAL.has(w));
    return (kept.length ? kept : words).slice(0, 6);
}
// Everyday words for the statutes' wording. Each also matches as typed. Reviewed by hand against the live headings.
const WORD_ALIASES = {marijuana: ['marihuana'], dwi: ['intoxicat'], dui: ['intoxicat'], gun: ['firearm', 'handgun', 'weapon'],
    guns: ['firearm', 'handgun', 'weapon']};
// The same plural rule as bill search (taxonomy.js): "wages" also finds "wage", "counties" "county".
const singularOf = w => w.length > 4 && w.endsWith('ies') ? w.slice(0, -3) + 'y'
    : w.length > 4 && /(s|x|z|ch|sh)es$/.test(w) ? w.slice(0, -2)
    : w.length > 3 && /[^su]s$/.test(w) ? w.slice(0, -1) : '';
// The word starts that count as a term: the term, its singular, its aliases.
export const lawTermForms = term => [...new Set([term, singularOf(term), ...(WORD_ALIASES[term] || [])])].filter(f => f.length >= 3);
// Laws known by a name their heading does not carry: [phrases, key, heading]. Checked against the live law copy.
const NAMED_LAWS = [
    [['public information act', 'open records act', 'open records'], 'GV 552', 'PUBLIC INFORMATION'],
    [['open meetings act'], 'GV 551', 'OPEN MEETINGS'],
    [['whistleblower act', 'whistleblower'], 'GV 554', 'PROTECTION FOR REPORTING VIOLATIONS OF LAW'],
    [['administrative procedure act'], 'GV 2001', 'ADMINISTRATIVE PROCEDURE'],
    [['sunset act'], 'GV 325', 'SUNSET LAW'],
    [['tort claims act'], 'CP 101', 'TORT CLAIMS'],
    [['medical liability act'], 'CP 74', 'MEDICAL LIABILITY'],
    [['citizens participation act', 'tcpa', 'anti slapp'], 'CP 27', 'ACTIONS INVOLVING THE EXERCISE OF CERTAIN CONSTITUTIONAL RIGHTS'],
    [['deceptive trade practices act', 'dtpa'], 'BC 17', 'DECEPTIVE TRADE PRACTICES'],
    [['dwi', 'dui', 'drunk driving'], 'PE 49', 'INTOXICATION AND ALCOHOLIC BEVERAGE OFFENSES'],
    [['marijuana', 'controlled substances act'], 'HS 481', 'TEXAS CONTROLLED SUBSTANCES ACT'],
];
// The named laws a query mentions, as [[key, heading]] (whole words: "dwi" in "dwi penalties", not in "dwight").
export function lawNamedMatches(query) {
    const q = ` ${String(query || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()} `;
    return NAMED_LAWS.filter(([names]) => names.some(n => q.includes(` ${n} `))).map(([, key, heading]) => [key, heading]);
}
// The prefix files to load: those of the term whose forms' prefixes have the fewest headings in all (null when a term
// has none: nothing can match).
export function lawSearchPrefixes(manifest, terms) {
    const plans = terms.map(t => {
        const prefixes = [...new Set(lawTermForms(t).map(f => f.slice(0, 3)))].filter(p => Number(manifest?.prefixes?.[p]) > 0);
        return {prefixes, n: prefixes.reduce((s, p) => s + Number(manifest.prefixes[p]), 0)};
    });
    if (!plans.length || plans.some(p => !p.n)) return null;
    return plans.sort((a, b) => a.n - b.n)[0].prefixes;
}
// Headings in which every term starts a word, best first:
//   1. the heading is the search, then starts with it, then has its words together;
//   2. laws bills are changing (changed(key));
//   3. chapters before sections; 4. shorter headings; 5. code order.
export function lawSearchMatches(entries, terms, changed = () => false) {
    const forms = terms.map(lawTermForms);
    const hits = (word, i) => forms[i].some(f => word.startsWith(f));
    const seen = new Set(), out = [];
    for (const e of Array.isArray(entries) ? entries : []) {
        if (!Array.isArray(e) || typeof e[0] !== 'string' || typeof e[1] !== 'string' || seen.has(e[0])) continue;
        if (!(STATUTE_KEY.test(e[0]) || isChapterKey(e[0])) || !LAW_CODES.has(e[0].slice(0, 2))) continue;
        const words = (e[1].toLowerCase().match(/[a-z0-9]+/g) || []).filter(w => !SEARCH_STOP.has(w));
        if (!forms.every((_, i) => words.some(w => hits(w, i)))) continue;
        seen.add(e[0]);
        const together = at => forms.every((_, i) => words[at + i] !== undefined && hits(words[at + i], i));
        const tier = together(0) ? (words.length === forms.length ? 0 : 1) : words.some((_, at) => together(at)) ? 2 : 3;
        out.push({e, tier, changed: changed(e[0]) ? 0 : 1, chapter: isChapterKey(e[0]) ? 0 : 1});
    }
    return out.sort((a, b) => a.tier - b.tier || a.changed - b.changed || a.chapter - b.chapter || a.e[1].length - b.e[1].length
        || a.e[0].localeCompare(b.e[0], undefined, {numeric: true})).map(x => x.e);
}
// The heading words a search matched, for highlighting: does this heading word start with one of the terms' forms?
export function lawTermMatcher(terms) {
    const forms = terms.flatMap(lawTermForms);
    return word => (String(word).toLowerCase().match(/[a-z0-9]+/g) || []).some(w => !SEARCH_STOP.has(w) && forms.some(f => w.startsWith(f)));
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
