import test from 'node:test';
import assert from 'node:assert/strict';
import {state} from '../src/core/state.js';
import {statuteMarkup} from '../src/features/statutes/view.js';

const bill = (id, caption) => ({id, number: id.replace(/^([A-Z]+)/, '$1 '), caption, title: caption, topics: [], agencies: [],
  authors: [], impacts: [], chamber: 'House', status: 'Filed', actions: ['Filed'], action_dates: ['2026-11-10'], last_action_date: '2026-11-10'});
const index = (sections, bills) => ({format: 'texas-bill-statutes-v1', codes: {TN: 'Transportation Code', LA: 'Labor Code'}, sections, bills});
const tick = () => new Promise(r => setTimeout(r, 0));

// Draws the section page once its section file has "loaded" (fetch stubbed with `doc`).
async function page(key, doc, chapter = null) {
  const real = globalThis.fetch;
  globalThis.fetch = async url => String(url).includes('/live/law/')
    ? (chapter ? {ok: true, text: async () => chapter, headers: {get: () => 'Thu, 19 Nov 2026 18:04:13 GMT'}} : {ok: false, status: 404})
    : {ok: true, json: async () => doc};
  try {
    state.view = 'home';  // No redraw when the file arrives; the test draws again itself.
    state.statuteKey = key;
    statuteMarkup();
    // Drawn again as files arrive: the current-law copy is asked for only once the section file is in.
    for (let i = 0; i < 10; i++) { await tick(); statuteMarkup(); }
    return () => statuteMarkup();
  } finally {
    globalThis.fetch = real;
  }
}
// The bar comes first in the page (focus order), the text after it.
const main = html => html.slice(html.indexOf('<div class="law-main">'));
const bar = html => html.slice(html.indexOf('<aside'), html.indexOf('</aside>'));

test('a proposed new section shows one bill at a time, never a comparison of unrelated texts', async () => {
  const key = 'TN 545.4575';
  state.bills = [bill('HB487', 'Relating to automated motor vehicles.'), bill('HB1250', 'Relating to automated vehicle reports.')];
  state.statutes = index({[key]: {h: 'EMERGENCY RESPONSE PROCEDURES', b: [['HB487', 'n'], ['HB1250', 'n']]}},
    {HB487: {v: 'I', n: 1, u: 0}, HB1250: {v: 'I', n: 1, u: 0}});
  state.statuteCompare = null;
  const draw = await page(key, {format: 'texas-bill-statute-section-v1', key, entries: [
    {bill: 'HB487', kind: 'add', version: 'I', version_name: 'Introduced', paragraphs: ['Sec. 545.4575. EMERGENCY RESPONSE PROCEDURES. (a) Geofence message.']},
    {bill: 'HB1250', kind: 'add', version: 'I', version_name: 'Introduced', paragraphs: ['Sec. 545.4575. COLLISION DATA REPORTING REQUIREMENT. (a) Collision report.']}]});
  let html = draw();
  assert.match(html, /Proposed new section · not in current law yet/);
  // Two proposals: the title is the number, not one bill's heading; it repeats the page's h1, so it is not a second heading.
  assert.match(html, /<div class="law-title-same" aria-hidden="true">Transportation Code § 545\.4575<\/div>/);
  assert.doesNotMatch(html, /<h2>/);
  assert.doesNotMatch(html, /class="law-compare"/);
  assert.doesNotMatch(html, /statutes\.capitol\.texas\.gov/, 'no link to current law that does not exist');
  assert.match(bar(html), /Emergency Response Procedures[\s\S]*Collision Data Reporting Requirement/);
  assert.match(bar(html), /data-law-compare="HB487" aria-pressed="true"/);
  assert.match(main(html), /Geofence message/);
  assert.doesNotMatch(main(html), /Collision report/);
  // Picking the other bill in the bar shows its version instead.
  state.statuteCompare.right = 'HB1250';
  html = draw();
  assert.match(bar(html), /data-law-compare="HB1250" aria-pressed="true"/);
  assert.match(main(html), /Collision report/);
  assert.doesNotMatch(main(html), /Geofence message/);
});

test('an amended section sets current law on the left against the bill picked in the bar', async () => {
  const key = 'LA 62.051';
  state.bills = [bill('HB110', 'Relating to the minimum wage.'), bill('SB253', 'Relating to the minimum wage.'), bill('HB9', 'Relating to repeals.')];
  state.statutes = index({[key]: {h: 'MINIMUM WAGE', b: [['HB110', 'm'], ['SB253', 'm'], ['HB9', 'r']]}},
    {HB110: {v: 'I', n: 1, u: 0}, SB253: {v: 'I', n: 1, u: 0}, HB9: {v: 'I', n: 1, u: 0}});
  state.statuteCompare = null;
  const draw = await page(key, {format: 'texas-bill-statute-section-v1', key, entries: [
    {bill: 'HB110', kind: 'amend', version: 'I', version_name: 'Introduced', partial: false, paragraphs: ['Sec. 62.051. MINIMUM WAGE. (a) Pay \\[<del>the federal</del>\\] <ins>fifteen dollars</ins>.']},
    {bill: 'SB253', kind: 'amend', version: 'I', version_name: 'Introduced', partial: false, paragraphs: ['Sec. 62.051. MINIMUM WAGE. (a) Pay \\[<del>the federal</del>\\] <ins>the state</ins>.']},
    {bill: 'HB9', kind: 'repeal', version: 'I', version_name: 'Introduced', paragraphs: []}]});
  let html = draw();
  assert.match(main(html), /class="law-compare"/);
  assert.match(main(html), /<h3>Current law → HB 110<\/h3>/);
  assert.match(main(html), /<option value="law" selected>/);
  assert.match(main(html), /fifteen<\/mark> <mark class="law-in">dollars/);
  state.statuteCompare.right = 'SB253';
  html = draw();
  assert.match(main(html), /<h3>Current law → SB 253<\/h3>/);
  assert.match(main(html), /class="law-in">state/);
  // A repeal shows the wording it would remove, not a comparison.
  state.statuteCompare.right = 'HB9';
  html = draw();
  assert.doesNotMatch(main(html), /class="law-compare"/);
  assert.match(main(html), /HB 9 would repeal it/);
  assert.match(main(html), /Pay the federal/);
});

test('a repeal or a partial amendment takes current law from the site\'s copy of the statutes', async () => {
  const key = 'CR 37.071';
  state.bills = [bill('HB655', 'Relating to capital cases.'), bill('SB60', 'Relating to capital cases.'), bill('HB77', 'Relating to repeals.')];
  state.statutes = index({[key]: {h: '', b: [['HB655', 'm'], ['SB60', 'm'], ['HB77', 'r']]}},
    {HB655: {v: 'I', n: 1, u: 0}, SB60: {v: 'I', n: 1, u: 0}, HB77: {v: 'I', n: 1, u: 0}});
  state.statutes.codes.CR = 'Code of Criminal Procedure';
  state.statuteCompare = null;
  const quote = ['(d) The court shall \\[<del>tell</del>\\] <ins>charge</ins> the jury.'];
  const chapter = '# Code of Criminal Procedure, CHAPTER 37\n\n## Art. 37.071. PROCEDURE IN CAPITAL CASE\n\n(a) First part.\n\n'
    + '(d) The court shall tell the jury.\n\nAdded by Acts 1973, 63rd Leg.\n\nAmended by:\n\nActs 2005, 79th Leg., Ch. 399.\n\n## Art. 37.0711. OTHER.\n\n(a) Not this one.';
  const draw = await page(key, {format: 'texas-bill-statute-section-v1', key, entries: [
    {bill: 'HB655', kind: 'amend', version: 'I', version_name: 'Introduced', partial: true, subsections: ['d'], paragraphs: quote},
    {bill: 'SB60', kind: 'amend', version: 'I', version_name: 'Introduced', partial: true, subsections: ['d'], paragraphs: quote},
    {bill: 'HB77', kind: 'repeal', version: 'I', version_name: 'Introduced', paragraphs: []}]}, chapter);
  let html = draw();
  assert.match(main(html), /Current law as of Nov 19, 2026, statute files/);
  assert.match(main(html), /First part/, 'the subsection the bills do not quote is on the left');
  assert.match(main(html), /Not changed by HB 655/);
  assert.match(main(html), /1 of 3 parts differ/, 'parts the bills leave alone do not count as different');
  assert.doesNotMatch(main(html), /Acts 2005|Not this one/);
  assert.match(bar(html), /<h3>Bills <span>3 · 2 versions<\/span><\/h3>/);
  state.statuteCompare.right = 'HB77';
  html = draw();
  assert.match(main(html), /HB 77 would repeal it/);
  assert.match(main(html), /First part[\s\S]*The court shall tell the jury/);
  assert.match(main(html), /from the Legislative Council's statute files as of Nov 19, 2026/);
});

test('a section no bill changes says so, and its title is not read twice', () => {
  state.statutes = index({}, {});
  state.statuteKey = 'LA 62.052';
  const html = statuteMarkup();
  assert.match(html, /no bill changes it yet/);
  assert.doesNotMatch(html, /every bill that changes it|<h2>/);
});
