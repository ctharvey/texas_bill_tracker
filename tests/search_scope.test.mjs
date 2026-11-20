import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {buildUrl, buildHash, parseHash, parseLocation, nextScope, cleanScope} from '../src/prefs.js';
import {state} from '../src/core/state.js';
import {CLICK_ORDER} from '../src/core/dispatch.js';
import {lawResults, lawResultsMarkup, statuteHintMarkup} from '../src/features/statutes/view.js';

const index = sections => ({format: 'texas-bill-statutes-v1', codes: {PE: 'Penal Code', GV: 'Government Code'}, sections, chapters: {}, bills: {}});
const tick = () => new Promise(r => setTimeout(r, 0));
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('the explorer address carries a Bills or Laws scope; Both, junk and other views carry none', () => {
  assert.equal(buildUrl('all', {query: 'guns'}, {scope: 'laws'}), '/explorer?query=guns&scope=laws');
  assert.equal(buildUrl('all', {query: 'guns'}, {scope: 'both'}), '/explorer?query=guns', 'Both is the default: left out');
  assert.equal(buildUrl('all', {}, {scope: 'nope'}), '/explorer');
  assert.equal(buildUrl('watchlist', {}, {scope: 'laws'}).includes('scope'), false, 'only the explorer has a scope');
  assert.equal(buildHash('all', {query: 'x'}, {scope: 'bills'}), '#all?query=x&scope=bills');
  assert.equal(parseLocation('/explorer', '', '?query=guns&scope=laws').scope, 'laws');
  assert.equal(parseLocation('/explorer', '', '?query=guns').scope, null);
  assert.equal(parseLocation('/explorer', '', '?scope=junk').scope, null);
  assert.equal(parseHash('#all?scope=bills').scope, 'bills');
  assert.equal(parseHash('#watchlist?scope=laws').scope, null);
  for (const scope of ['bills', 'laws']) {
    const [path, query] = buildUrl('all', {query: 'water'}, {scope}).split('?');
    assert.equal(parseLocation(path, '', `?${query}`).scope, scope, 'round trip');
  }
  assert.equal(cleanScope('laws'), 'laws');
  assert.equal(cleanScope(undefined), 'both');
  assert.equal(cleanScope('__proto__'), 'both');
});

test('each button turns its kind on or off, and the last one on stays on', () => {
  assert.equal(nextScope('both', 'bills'), 'laws');
  assert.equal(nextScope('both', 'laws'), 'bills');
  assert.equal(nextScope('laws', 'bills'), 'both');
  assert.equal(nextScope('bills', 'laws'), 'both');
  assert.equal(nextScope('bills', 'bills'), 'bills', 'the last one on stays on');
  assert.equal(nextScope('laws', 'laws'), 'laws');
  assert.equal(nextScope('both', 'nope'), 'both');
  assert.equal(nextScope('junk', 'laws'), 'bills', 'junk reads as Both');
});

test('the scope buttons and Show more are registered click handlers', () => {
  assert.ok(CLICK_ORDER.includes('search-scope'));
  assert.ok(CLICK_ORDER.includes('law-more'));
  const app = read('src/app.js');
  assert.match(app, /clickOn\('search-scope','\[data-search-scope\]'/);
  assert.match(app, /clickOn\('law-more','#law-more'/);
});

test('a key or section number lists those laws, an exact key even when no bill changes it', () => {
  state.view = 'home';  // No redraws.
  state.statutes = index({
    'PE 46.06': {h: 'UNLAWFUL TRANSFER OF CERTAIN WEAPONS', b: [['HB1', 'm'], ['HB2', 'm'], ['HB1', 'a']]},
    'GV 46.06': {h: 'SOMETHING ELSE', b: [['SB3', 'm']]},
  });
  assert.deepEqual(lawResults(''), {status: 'empty', kind: 'words', items: []});
  assert.deepEqual(lawResults('PE 46.06'), {status: 'ok', kind: 'key', items: [['PE 46.06', 'UNLAWFUL TRANSFER OF CERTAIN WEAPONS']]});
  assert.deepEqual(lawResults('pe 2.01'), {status: 'ok', kind: 'key', items: [['PE 2.01', '']]}, 'untouched, lower case');
  assert.deepEqual(lawResults('Penal Code 1.01').items, [['PE 1.01', '']], 'a code by name');
  assert.deepEqual(lawResults('PE 46').items, [['PE 46', '']], 'a chapter key');
  assert.deepEqual(lawResults('46.06').items.map(i => i[0]).sort(), ['GV 46.06', 'PE 46.06'], 'a bare number: the sections bills change');
  assert.deepEqual(lawResults('99.99'), {status: 'ok', kind: 'key', items: [], bare: '99.99'});

  const html = lawResultsMarkup(lawResults('PE 46.06'), 50);
  assert.match(html, /href="\/law\/PE\/46\.06"/);
  assert.match(html, /<span class="law-heading">Unlawful Transfer of Certain Weapons<\/span>/);
  assert.match(html, /2 bills change it/, 'bills counted once each');
  assert.doesNotMatch(lawResultsMarkup(lawResults('PE 2.01'), 50), /change it/, 'no bill: no count');
  assert.match(lawResultsMarkup(lawResults('99.99'), 50, '99.99'), /No bill changes a section numbered/);
  assert.match(lawResultsMarkup(lawResults(''), 50), /Search Texas law by words/);
});

test('before the statute index arrives a bare number is loading, and unavailable when the index failed', () => {
  state.view = 'home';
  const real = globalThis.fetch;
  globalThis.fetch = async () => ({ok: false, status: 503});
  try {
    state.statutes = null;
    state.statutesFailed = false;
    assert.equal(lawResults('46.06').status, 'loading');
    assert.equal(lawResults('PE 46.06').status, 'ok', 'an exact key needs no index');
    state.statutesFailed = true;
    assert.equal(lawResults('46.06').status, 'error');
    assert.match(lawResultsMarkup(lawResults('46.06'), 50), /not available right now/);
  } finally {
    globalThis.fetch = real;
    state.statutesFailed = false;
  }
});

test('words list every heading match, paged by the caller; Bills mode drops the heading hint', async () => {
  state.view = 'home';
  state.statutes = index({'PE 46.02': {h: 'UNLAWFUL CARRYING WEAPONS', b: [['HB1', 'm']]}});
  const shard = Array.from({length: 60}, (_, i) => [`PE 46.${String(i + 10).padStart(2, '0')}`, `UNLAWFUL THING ${i}`]);
  shard.push(['PE 46.02', 'UNLAWFUL CARRYING WEAPONS']);
  const files = {'search/index.json': {format: 'texas-bill-law-search-v1', prefixes: {unl: 61, car: 900, zeb: 900}}, 'search/unl.json': shard};
  const real = globalThis.fetch;
  globalThis.fetch = async url => {
    const name = Object.keys(files).find(f => String(url).endsWith(`/live/law/${f}`));
    return name ? {ok: true, json: async () => files[name]} : {ok: false, status: 404};
  };
  try {
    assert.equal(lawResults('unlawful').status, 'loading');
    assert.match(lawResultsMarkup(lawResults('unlawful'), 50), /Searching Texas law/);
    for (let i = 0; i < 5; i++) { await tick(); lawResults('unlawful'); }
    const r = lawResults('unlawful');
    assert.equal(r.status, 'ok');
    assert.equal(r.kind, 'words');
    assert.equal(r.items.length, 61, 'every match, not the hint cap');
    const page = lawResultsMarkup(r, 50);
    assert.equal(page.match(/<li /g).length, 50, 'the first 50');
    assert.equal(lawResultsMarkup(r, 100).match(/<li /g).length, 61);
    assert.deepEqual(lawResults('unlawful carrying').items, [['PE 46.02', 'UNLAWFUL CARRYING WEAPONS']]);
    assert.match(lawResultsMarkup(lawResults('unlawful zebra'), 50, 'unlawful zebra'), /No section or chapter heading has all of these words/);

    assert.match(statuteHintMarkup([], 'unlawful carrying'), /law-heading/, 'Both: the heading hint as before');
    assert.equal(statuteHintMarkup([], 'unlawful carrying', false), '', 'Bills: no heading hint');
    assert.match(statuteHintMarkup(['PE 46.02'], '46.02', false), /Bills that change/, 'Bills: the section callout stays');
  } finally {
    globalThis.fetch = real;
  }
});

test('the explorer hides bill-only controls in Laws mode and has no buttons on the watchlist or a shared list', () => {
  const view = read('src/features/explorer/view.js');
  assert.match(view, /if\(state\.view!=='all'\|\|state\.sharedList\)return '';/);
  assert.match(view, /searchScope=\(\)=>state\.view==='all'&&!state\.sharedList\?cleanScope\(state\.scope\):'both'/);
  for (const hidden of ['class="search-help"${hide}', 'class="filter-bar"${hide}', 'aria-label="Quick topic filters"${hide}',
    'aria-label="Active filters"${hide}', 'aria-label="Sort bills"${hide}', 'id="export-csv"${hide}'])
    assert.ok(view.includes(hidden), hidden);
});
