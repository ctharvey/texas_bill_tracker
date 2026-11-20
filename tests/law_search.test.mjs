import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {lawSearchTerms, lawTermForms, lawSearchPrefixes, lawSearchMatches, lawNamedMatches, lawTermMatcher, parseStatuteQuery,
  parseChapterQuery, LAW_CODE_NAMES} from '../src/features/statutes/model.js';
import {state} from '../src/core/state.js';
import {CLICK_ORDER} from '../src/core/dispatch.js';
import {lawResults, lawResultsMarkup, statuteHintMarkup} from '../src/features/statutes/view.js';

const tick = () => new Promise(r => setTimeout(r, 0));
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const keys = list => list.map(e => e[0]);

test('a plural also finds the singular, and everyday words find the statutes\' wording', () => {
  assert.deepEqual(lawTermForms('wages'), ['wages', 'wage']);
  assert.deepEqual(lawTermForms('counties'), ['counties', 'county']);
  assert.deepEqual(lawTermForms('taxes'), ['taxes', 'tax']);
  assert.deepEqual(lawTermForms('business'), ['business'], 'a word ending in ss is not a plural');
  assert.deepEqual(lawTermForms('status'), ['status']);
  assert.ok(lawTermForms('marijuana').includes('marihuana'));
  assert.ok(lawTermForms('dwi').includes('intoxicat'));
  assert.deepEqual(lawTermForms('guns'), ['guns', 'gun', 'firearm', 'handgun', 'weapon']);
  const shard = [['LA 62', 'MINIMUM WAGE'], ['LA 62.051', 'MINIMUM WAGE'], ['LA 62.151', 'MINIMUM WAGES FOR CERTAIN WORKERS']];
  assert.deepEqual(keys(lawSearchMatches(shard, ['minimum', 'wages'])), ['LA 62', 'LA 62.051', 'LA 62.151']);
  assert.deepEqual(keys(lawSearchMatches([['HS 481.121', 'OFFENSE: POSSESSION OF MARIHUANA']], ['marijuana'])), ['HS 481.121']);
});

test('"act" and "law" after other words are not required', () => {
  assert.deepEqual(lawSearchTerms('Public Information Act'), ['public', 'information']);
  assert.deepEqual(lawSearchTerms('sunset law'), ['sunset']);
  assert.deepEqual(lawSearchTerms('act'), ['act'], 'alone it is the search');
});

test('a term with aliases loads every prefix file its forms need; a term with none matches nothing', () => {
  const manifest = {prefixes: {gun: 5, fir: 40, han: 20, wea: 30, unl: 10, int: 900}};
  assert.deepEqual(lawSearchPrefixes(manifest, ['guns']), ['gun', 'fir', 'han', 'wea']);
  assert.deepEqual(lawSearchPrefixes(manifest, ['guns', 'unlawful']), ['unl'], 'the cheapest term');
  assert.deepEqual(lawSearchPrefixes(manifest, ['dwi']), ['int'], 'a form no heading starts is skipped');
  assert.equal(lawSearchPrefixes(manifest, ['zebra']), null);
  const shards = [['PE 46.02', 'UNLAWFUL CARRYING WEAPONS'], ['PE 46.02', 'UNLAWFUL CARRYING WEAPONS'], ['GV 2', 'FIREARM SUPPRESSOR REGULATION']];
  assert.deepEqual(keys(lawSearchMatches(shards, ['guns'])), ['GV 2', 'PE 46.02'], 'one entry per law across files');
});

test('the best matches come first: the heading itself, then starting with it, then the words together', () => {
  const shard = [
    ['AG 48', 'PROGRAMS FOR PUBLIC SCHOOL INFORMATION'],
    ['BC 109', 'INFORMATION OF A PUBLIC NATURE'],
    ['ED 1.001', 'PUBLIC INFORMATION ABOUT SCHOOLS'],
    ['GV 552.001', 'PUBLIC INFORMATION'],
    ['GV 552', 'PUBLIC INFORMATION'],
    ['ED 39A.160', 'OPEN MEETINGS AND PUBLIC INFORMATION'],
  ];
  assert.deepEqual(keys(lawSearchMatches(shard, ['public', 'information'])),
    ['GV 552', 'GV 552.001', 'ED 1.001', 'ED 39A.160', 'BC 109', 'AG 48']);
  // Within a tier, laws bills change come before those no bill changes, then chapters, then shorter headings.
  const changed = key => key === 'AG 48';
  assert.deepEqual(keys(lawSearchMatches(shard, ['public', 'information'], changed)).slice(3), ['ED 39A.160', 'AG 48', 'BC 109']);
  assert.deepEqual(keys(lawSearchMatches(shard, ['information', 'public'], changed)).slice(0, 2), ['BC 109', 'AG 48'],
    'order matters for "together": BC 109 reads "information ... public"');
  const highlight = lawTermMatcher(['schools']);
  assert.ok(highlight('School') && highlight('Schools') && !highlight('Preschool') && !highlight('of'));
});

test('laws known by a name their heading lacks', () => {
  assert.deepEqual(lawNamedMatches('Texas Public Information Act'), [['GV 552', 'PUBLIC INFORMATION']]);
  assert.deepEqual(keys(lawNamedMatches('DWI')), ['PE 49']);
  assert.deepEqual(keys(lawNamedMatches('anti-SLAPP')), ['CP 27']);
  assert.deepEqual(lawNamedMatches('dwight'), [], 'whole words only');
  assert.deepEqual(lawNamedMatches('public information'), [], 'the heading words are a plain heading search');
});

test('citations name a code the way lawyers write it', () => {
  const codes = {ED: 'Education Code', PE: 'Penal Code', CR: 'Code of Criminal Procedure', HS: 'Health and Safety Code', GV: 'Government Code',
    LG: 'Local Government Code'};
  assert.deepEqual(parseStatuteQuery('Tex. Penal Code 46.02', codes), {code: 'PE', sec: '46.02'});
  assert.deepEqual(parseStatuteQuery("Tex. Gov't Code \u00a7 552.001", codes), {code: 'GV', sec: '552.001'});
  assert.deepEqual(parseStatuteQuery('Tex. Gov\u2019t Code Ann. \u00a7 552.001', codes), {code: 'GV', sec: '552.001'});
  assert.deepEqual(parseStatuteQuery('Tex. Loc. Gov\'t Code 211.003', codes), {code: 'LG', sec: '211.003'});
  assert.deepEqual(parseStatuteQuery('Tex. Code Crim. Proc. art. 42.01', codes), {code: 'CR', sec: '42.01'});
  assert.deepEqual(parseStatuteQuery('Tex. Health & Safety Code 481.121', codes), {code: 'HS', sec: '481.121'});
  assert.deepEqual(parseStatuteQuery('Texas Education Code 48.160', codes), {code: 'ED', sec: '48.160'});
  assert.equal(parseStatuteQuery('Water Code 11.1', codes), null, 'only codes in the list');

  assert.equal(parseChapterQuery('Penal Code chapter 46', codes), 'PE 46');
  assert.equal(parseChapterQuery("Tex. Gov't Code ch. 552", codes), 'GV 552');
  assert.equal(parseChapterQuery('Education Code, chapter 12a', codes), 'ED 12A');
  assert.equal(parseChapterQuery('Penal Code 46', codes), 'PE 46');
  assert.equal(parseChapterQuery('penal ch 46', codes), 'PE 46');
  for (const q of ['penal 46', 'chapter 46', 'HB 5', 'tax 2025', 'Water Code chapter 11', ''])
    assert.equal(parseChapterQuery(q, codes), null, q);
});

test('Laws results: citations and chapters without the index, a bare number explained, named laws first, matches marked', async () => {
  state.view = 'home';  // No redraws.
  state.statutes = null;
  state.statutesFailed = false;
  const files = {
    'search/index.json': {format: 'texas-bill-law-search-v1', prefixes: {pub: 3, inf: 4, sch: 7}},
    'search/pub.json': [['BC 109', 'INFORMATION OF A PUBLIC NATURE'], ['GV 552', 'PUBLIC INFORMATION'], ['GV 552.001', 'PUBLIC INFORMATION']],
    'search/sch.json': Array.from({length: 7}, (_, i) => [`ED 1.00${i}`, `SCHOOL THING ${i}`]),
  };
  const real = globalThis.fetch;
  globalThis.fetch = async url => {
    const name = Object.keys(files).find(f => String(url).endsWith(`/live/law/${f}`));
    return name ? {ok: true, json: async () => files[name]} : {ok: false, status: 404};
  };
  try {
    assert.deepEqual(lawResults('Tex. Penal Code 46.02').items, [['PE 46.02', '']], 'a code by name needs no index');
    assert.deepEqual(lawResults('Penal Code chapter 46'), {status: 'ok', kind: 'key', items: [['PE 46', '']]});

    for (let i = 0; i < 6; i++) { await tick(); lawResults('public information act'); }
    state.statutes = {format: 'texas-bill-statutes-v1', codes: LAW_CODE_NAMES, bills: {}, chapters: {},
      sections: {'PE 46.02': {h: 'UNLAWFUL CARRYING WEAPONS', b: [['HB1', 'm']]}, 'GV 46.02': {h: 'X', b: [['SB2', 'm']]}}};
    const r = lawResults('public information act');
    assert.equal(r.status, 'ok');
    assert.deepEqual(keys(r.items), ['GV 552', 'GV 552.001', 'BC 109'], 'the named law once, first');
    const html = lawResultsMarkup(r, 50, 'public information act');
    assert.match(html, /<mark class="law-match">Public<\/mark> <mark class="law-match">Information<\/mark>/);

    const bare = lawResults('46.02');
    assert.deepEqual(keys(bare.items).sort(), ['GV 46.02', 'PE 46.02']);
    assert.match(lawResultsMarkup(bare, 50, '46.02'), /Sections numbered 46\.02 that bills change\. For another code's 46\.02, add the code/);
    assert.match(lawResultsMarkup(lawResults('99.99'), 50, '99.99'), /Penal Code 99\.99/);

    for (let i = 0; i < 6; i++) { await tick(); statuteHintMarkup([], 'school'); }
    const hint = statuteHintMarkup([], 'school');
    assert.equal(hint.match(/<li>/g).length, 5, 'five in the hint');
    assert.match(hint, /id="law-see-all">See all 7 laws \u2192<\/button>/);
    assert.doesNotMatch(statuteHintMarkup([], 'public information'), /law-see-all/, 'no button when all are shown');
  } finally {
    globalThis.fetch = real;
  }
});

test('the Changed by bills filter and See all are registered click handlers', () => {
  for (const name of ['law-changed', 'law-see-all']) assert.ok(CLICK_ORDER.includes(name), name);
  const app = read('src/app.js');
  assert.match(app, /clickOn\('law-changed','#law-changed',\(\)=>\{toggleLawChanged\(\);renderResults\(\)/);
  assert.match(app, /clickOn\('law-see-all','#law-see-all',\(\)=>\{state\.scope='laws'/);
});
