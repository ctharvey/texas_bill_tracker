// The code index (/law) and a code's chapter list (/law/<CODE>): pure functions over the law copy's index
// (live/law/index.json) and the statute index, so the node tests can import this file directly.
// scripts/build_feeds.py (write_law_code_pages) draws the same lists for the static pages.
import {LAW_CODE_NAMES, chapterOf} from '../statutes/model.js';

const CHAPTER = /^\d+[A-Z]?$/;  // "491.v2" (a second version, #21) is left out.
const CHAPTER_PREFIX = /^(?:CHAPTER|ARTICLE|SUBCHAPTER)\s+[0-9A-Za-z.-]+?\.\s+/i;

export const validLawIndex = x => x?.format === 'texas-bill-law-v1' && x.codes && typeof x.codes === 'object' && !Array.isArray(x.codes);

// build_feeds.chapter_title: "CHAPTER 46. WEAPONS" -> "WEAPONS".
export const chapterTitle = heading => String(heading ?? '').trim().replace(CHAPTER_PREFIX, '').trim().replace(/\.+$/, '').trim();

// build_feeds._natural: "12A" after "12", "100" after "99".
function natural(a, b) {
  const [, an, as] = /^(\d+)(.*)$/.exec(a), [, bn, bs] = /^(\d+)(.*)$/.exec(b);
  return Number(an) - Number(bn) || (as < bs ? -1 : as > bs ? 1 : 0);
}

// The tracked codes the law copy lists, by name: [code, name, chapter count].
export function lawCodeList(index) {
  if (!validLawIndex(index)) return [];
  return Object.keys(index.codes).filter(c => LAW_CODE_NAMES[c]).map(c => [c, LAW_CODE_NAMES[c], codeChapters(index, c).length])
    .filter(r => r[2]).sort((a, b) => a[1].localeCompare(b[1]));
}

// One code's chapters in number order: [chapter, title].
export function codeChapters(index, code) {
  const headings = validLawIndex(index) ? index.codes[code]?.headings : null;
  if (!headings || typeof headings !== 'object') return [];
  return Object.entries(headings).filter(([c, h]) => CHAPTER.test(c) && typeof h === 'string')
    .map(([c, h]) => [c, chapterTitle(h)]).sort((a, b) => natural(a[0], b[0]));
}

// "PE 46" -> how many bills change the chapter, whole or in any of its sections (build_feeds._chapter_bills).
export function chapterBillCounts(statutes) {
  const bills = new Map();
  const add = (key, pairs) => {
    if (!key || !Array.isArray(pairs)) return;
    if (!bills.has(key)) bills.set(key, new Set());
    for (const p of pairs) if (Array.isArray(p) && typeof p[0] === 'string') bills.get(key).add(p[0]);
  };
  for (const [key, entry] of Object.entries(statutes?.sections || {})) add(chapterOf(key), entry?.b);
  for (const [key, entry] of Object.entries(statutes?.chapters || {})) add(key, entry?.b);
  return new Map([...bills].filter(([, s]) => s.size).map(([k, s]) => [k, s.size]));
}

export const chapterCount = n => `${n} chapter${n === 1 ? '' : 's'}`;
export const billsChange = n => `${n} bill${n === 1 ? '' : 's'} change${n === 1 ? 's' : ''} it`;
