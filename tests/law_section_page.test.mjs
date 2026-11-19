import test from 'node:test';
import assert from 'node:assert/strict';
import {state} from '../src/core/state.js';
import {statuteMarkup} from '../src/features/statutes/view.js';

const bill = (id, caption) => ({id, number: id.replace(/^([A-Z]+)/, '$1 '), caption, title: caption, topics: [], agencies: [],
  authors: [], impacts: [], chamber: 'House', status: 'Filed', actions: ['Filed'], action_dates: ['2026-11-10'], last_action_date: '2026-11-10'});
const index = (sections, bills) => ({format: 'texas-bill-statutes-v1', codes: {TN: 'Transportation Code', LA: 'Labor Code'}, sections, bills});
const tick = () => new Promise(r => setTimeout(r, 0));

// Draws the section page once its section file has "loaded" (fetch stubbed with `doc`).
async function page(key, doc) {
  const real = globalThis.fetch;
  globalThis.fetch = async () => ({ok: true, json: async () => doc});
  try {
    state.view = 'home';  // No redraw when the file arrives; the test draws again itself.
    state.statuteKey = key;
    statuteMarkup();
    for (let i = 0; i < 5; i++) await tick();
    return () => statuteMarkup();
  } finally {
    globalThis.fetch = real;
  }
}
const main = html => html.slice(html.indexOf('<div class="law-main">'), html.indexOf('<aside'));
const bar = html => html.slice(html.indexOf('<aside'));

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
  assert.match(html, /<h2>Transportation Code § 545\.4575<\/h2>/, 'two proposals: the title is the number, not one bill\'s heading');
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
