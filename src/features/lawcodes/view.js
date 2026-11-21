// The code index (/law) and one code's chapters (/law/<CODE>). The law copy's index is fetched once; the statute
// index (loadStatutes) marks the chapters bills change and redraws the view when it arrives.
import {state} from '../../core/state.js';
import {esc} from '../../core/dom.js';
import {timeoutSignal, httpError} from '../../core/net.js';
import {renderContent} from '../../core/router.js';
import {buildUrl, chapterPath} from '../../prefs.js';
import {titleCase} from '../../core/head.js';
import {LAW_CODE_NAMES, chapterWord} from '../statutes/model.js';
import {loadStatutes} from '../statutes/view.js';
import {validLawIndex, lawCodeList, codeChapters, chapterBillCounts, billsChange, chapterCount, codeTitle} from './model.js';

let lawLoad = null;
export function loadLawCodes() {
  return lawLoad || (lawLoad = (async () => {
    try {
      const r = await fetch('./live/law/index.json', {cache: 'no-cache', signal: timeoutSignal(15000)});
      if (!r.ok) throw httpError(r);
      const index = await r.json();
      if (!validLawIndex(index)) throw Error('Unrecognized law index');
      state.lawCodes = index;
    } catch (error) { state.lawCodes = null; state.lawCodesFailed = true; console.warn('Law index unavailable', error.message); }
    if (state.view === 'laws' || state.view === 'lawcode') renderContent();
  })());
}

let countsFor = null, counts = new Map();
function billCounts() {
  if (!state.statutes) return new Map();
  if (countsFor !== state.statutes) { countsFor = state.statutes; counts = chapterBillCounts(state.statutes); }
  return counts;
}

const head = (kind, title, sub = 'Texas law') => `<div class="section-head"><div><div class="section-overline">${kind}</div><h2>${title}</h2></div><span class="subtitle">${sub}</span></div>`;
// Shared by both views: the law index still loading, or unavailable.
function waiting() {
  if (!state.lawCodes && !state.lawCodesFailed) loadLawCodes();
  if (!state.statutes && !state.statutesFailed) loadStatutes();
  if (state.lawCodesFailed) return '<div class="info-callout callout-warn">The list of Texas codes is not available right now. Try again later.</div>';
  return state.lawCodes ? null : '<p class="near-hint">Loading\u2026</p>';
}

// The name of the code on screen, or null when the address names no tracked code.
export const lawCodeTitle = () => LAW_CODE_NAMES[state.lawCode] ? codeTitle(LAW_CODE_NAMES[state.lawCode]) : null;

export function lawsMarkup() {
  const wait = waiting();
  if (wait) return `${head('TEXAS LAW', 'The codes')}${wait}`;
  const n = billCounts(), list = lawCodeList(state.lawCodes);
  const rows = list.map(([code, name, total]) => {
    const changed = codeChapters(state.lawCodes, code).filter(([c]) => n.get(`${code} ${c}`)).length;
    return `<li><a class="text-link" href="${esc(buildUrl('lawcode', {}, {lawCode: code}))}">${esc(name)}</a>: ${chapterCount(total, code === 'CN' ? 'article' : 'chapter')}${changed ? `, <strong>${changed} changed by bills</strong>` : ''}</li>`;
  }).join('');
  return `${head('TEXAS LAW', 'The codes')}<p class="near-hint">The ${list.length} codes of Texas law this site follows. Open a code to see every chapter and the ones bills in the 90th Legislature would change.</p><ul class="law-code-list" id="law-codes">${rows}</ul>`;
}

export function lawCodeMarkup() {
  const code = state.lawCode, name = LAW_CODE_NAMES[code];
  if (!name) return `${head('TEXAS LAW', 'Code not found')}<div class="info-callout callout-warn">No Texas code this site follows matches ${code ? `<strong>${esc(code)}</strong>` : 'this address'}. See <a class="text-link" href="/law" data-view="laws">all Texas codes</a>.</div>`;
  const title = esc(codeTitle(name)), wait = waiting();
  if (wait) return `${head('TEXAS CODE', title)}${wait}`;
  const chapters = codeChapters(state.lawCodes, code), n = billCounts();
  if (!chapters.length) return `${head('TEXAS CODE', title)}<div class="info-callout callout-warn">This site has no copy of the ${esc(name)} right now. See <a class="text-link" href="/law" data-view="laws">all Texas codes</a>.</div>`;
  const changed = chapters.filter(([c]) => n.get(`${code} ${c}`)).length;
  const word = chapterWord(code), all = chapterCount(chapters.length, word.toLowerCase());
  const lead = !state.statutes ? `${all}.` : changed ? `${all}. Bills in the 90th Legislature would change ${changed} of them.` : `${all}. No bill in the 90th Legislature changes one yet.`;
  const rows = chapters.map(([c, t]) => {
    const count = n.get(`${code} ${c}`) || 0;
    return `<li${count ? ' class="law-code-changed"' : ''}><a class="text-link" href="${esc(chapterPath(`${code} ${c}`))}">${word} ${esc(c)}</a>${t ? `: ${esc(titleCase(t))}` : ''}${count ? ` <strong>(${billsChange(count)})</strong>` : ''}</li>`;
  }).join('');
  return `${head('TEXAS CODE', title)}<p class="near-hint">${lead} <a class="text-link" href="/law" data-view="laws">All Texas codes</a></p><ul class="law-code-list" id="law-chapters">${rows}</ul><p class="near-hint">Bills are matched to chapters automatically from their text and can be missed.</p>`;
}
