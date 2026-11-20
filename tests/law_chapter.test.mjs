import test from 'node:test';
import assert from 'node:assert/strict';
import {cleanSearches, parseHash, buildHash, buildUrl} from '../src/prefs.js';
import {isLawFollowQuery, isChapterKey, chapterOf, lawFollowBills, lawFirstSeen, lawFollowSearch, statuteLabel, lawChapterOutline,
  lawSearchTerms, lawSearchPrefix, lawSearchMatches} from '../src/features/statutes/model.js';
import {state} from '../src/core/state.js';
import {searchCounts} from '../src/features/sync/lists.js';
import {statuteMarkup, statuteHintMarkup} from '../src/features/statutes/view.js';

const bill = (id, day) => ({id, number: id.replace(/^([A-Z]+)/, '$1 '), caption: 'Relating to weapons.', title: 'Relating to weapons.',
  topics: [], agencies: [], authors: [], impacts: [], chamber: 'House', status: 'Filed', actions: ['Filed'], action_dates: [day], last_action_date: day});
const index = (sections, chapters = {}) => ({format: 'texas-bill-statutes-v1', codes: {PE: 'Penal Code', GV: 'Government Code'}, sections, chapters, bills: {}});
const tick = () => new Promise(r => setTimeout(r, 0));

test('a chapter key is a follow query of a known code, and a section names its chapter', () => {
  for (const q of ['PE 46', 'ED 12A', 'GV 2271']) assert.ok(isChapterKey(q) && isLawFollowQuery(q), q);
  for (const q of ['PM 2', 'PE 46 guns', 'pe 46', 'PE', '46']) assert.ok(!isLawFollowQuery(q), q);
  assert.equal(chapterOf('PE 46.06'), 'PE 46');
  assert.equal(chapterOf('ED 12A.001'), 'ED 12A');
  assert.equal(chapterOf('PE 46'), null);
  assert.equal(statuteLabel('PE 46', {PE: 'Penal Code'}), 'Penal Code chapter 46');
  const s = lawFollowSearch('PE 46', 'Penal Code chapter 46', 'abcdefgh12', '2026-11-19');
  assert.deepEqual(cleanSearches([s]), [s], 'a chapter follow is a saved search every cleaner keeps');
});

test('a chapter address opens the statute view with the chapter key and is written back the same way', () => {
  const p = parseHash('#chapter?law=PE&ch=46');
  assert.equal(p.view, 'statute');
  assert.equal(p.statute, 'PE 46');
  assert.equal(parseHash('#chapter?law=PE&ch=12a').statute, 'PE 12A');
  assert.equal(parseHash('#chapter?law=PE&ch=../x').statute, null);
  assert.equal(buildHash('statute', {}, {statute: 'PE 46'}), '#chapter?law=PE&ch=46');
  assert.equal(buildUrl('statute', {}, {statute: 'PE 46'}), '/law/PE/46');  // Served once chunk 3's gateway route is live.
  assert.equal(buildUrl('statute', {}, {statute: 'PE 46.06'}), '/law/PE/46.06');
});

test('a chapter follow covers every section in it and whole-chapter changes; a change anywhere in it is new', () => {
  const idx = index({
    'PE 46.02': {h: 'UNLAWFUL CARRYING WEAPONS', b: [['HB1', 'm']], f: {HB1: '2026-11-10'}},
    'PE 46.06': {h: 'UNLAWFUL TRANSFER', b: [['HB1', 'm'], ['HB2', 'm']], f: {HB1: '2026-11-18'}},
    'PE 47.01': {h: 'DEFINITIONS', b: [['HB3', 'm']]},
  }, {'PE 46': {h: 'WEAPONS', b: [['HB4', 'r']], f: {HB4: '2026-11-17'}}});
  assert.deepEqual(lawFollowBills(idx, 'PE 46').sort(), ['HB1', 'HB2', 'HB4']);
  assert.equal(lawFirstSeen(idx, 'PE 46', 'HB1'), '2026-11-18', 'the latest day a part of the chapter gained the bill');
  assert.equal(lawFirstSeen(idx, 'PE 46.02', 'HB1'), '2026-11-10', 'a section follow is unchanged');
  assert.equal(lawFirstSeen(idx, 'PE 46', 'HB3'), '');

  // Done when: following a chapter, then a bill changing a section in it (or the whole chapter) shows as new.
  state.bills = [bill('HB1', '2026-11-01'), bill('HB2', '2026-11-01'), bill('HB3', '2026-11-01'), bill('HB4', '2026-11-01')];
  state.statutes = idx;
  const follow = lawFollowSearch('PE 46', 'Penal Code chapter 46', 'abcdefgh12', '2026-11-15');
  assert.deepEqual(searchCounts(follow), {total: 3, fresh: 2}, 'HB1 (now amends 46.06) and HB4 (repeals the chapter) are new; HB3 is another chapter');
});

test('the chapter page lists whole-chapter bills, the sections bills change, and every section from the law copy', async () => {
  state.bills = [bill('HB1', '2026-11-01'), bill('HB4', '2026-11-01')];
  state.statutes = index({'PE 46.02': {h: 'UNLAWFUL CARRYING WEAPONS', b: [['HB1', 'm']]}}, {'PE 46': {h: 'WEAPONS', b: [['HB4', 'r']]}});
  state.searches = [];
  const chapter = '# Penal Code, CHAPTER 46. WEAPONS\n\n## Sec. 46.01. DEFINITIONS.\n\n(a) Text.\n\n## Sec. 46.02. UNLAWFUL CARRYING WEAPONS.\n\n(a) Text.';
  const real = globalThis.fetch;
  globalThis.fetch = async url => String(url).endsWith('/live/law/PE/46.md') ? {ok: true, text: async () => chapter} : {ok: false, status: 404};
  try {
    state.view = 'home';
    state.statuteKey = 'PE 46';
    statuteMarkup();
    for (let i = 0; i < 5; i++) await tick();
    const html = statuteMarkup();
    assert.match(html, /<h2>Weapons<\/h2>/);
    assert.match(html, /\+ Follow this chapter/);
    assert.match(html, /2 bills change something in it/);
    assert.match(html, /Bills that change the whole chapter[\s\S]*HB 4[\s\S]*repeals the whole chapter/);
    assert.match(html, /Sections bills change[\s\S]*Penal Code § 46\.02[\s\S]*HB 1/);
    assert.match(html, /All 2 sections in this chapter[\s\S]*§ 46\.01<\/a> <span class="law-heading">Definitions/);
    assert.match(html, /RSS feed/);
  } finally {
    globalThis.fetch = real;
  }
  assert.deepEqual(lawChapterOutline(chapter), {heading: 'WEAPONS', sections: [['46.01', 'DEFINITIONS'], ['46.02', 'UNLAWFUL CARRYING WEAPONS']]});
  // In the law copy a heading can run into the section's text on the same line.
  assert.deepEqual(lawChapterOutline('## Sec. 46.01. DEFINITIONS. In this chapter:\n\n## Sec. 46.04. UNLAWFUL POSSESSION OF FIREARM. (a) A person who\n\n## Sec. 1.05. SALE OF U.S. FLAGS.').sections,
    [['46.01', 'DEFINITIONS'], ['46.04', 'UNLAWFUL POSSESSION OF FIREARM'], ['1.05', 'SALE OF U.S. FLAGS']]);
});

test('a section no bill changes shows its current text and links its chapter', async () => {
  state.statutes = index({});
  state.searches = [];
  const chapter = '# Penal Code, CHAPTER 46. WEAPONS\n\n## Sec. 46.05. PROHIBITED WEAPONS.\n\n(a) A person commits an offense.\n\nAdded by Acts 1973.';
  const real = globalThis.fetch;
  globalThis.fetch = async url => String(url).endsWith('/live/law/PE/46.md')
    ? {ok: true, text: async () => chapter, headers: {get: () => 'Thu, 19 Nov 2026 18:04:13 GMT'}} : {ok: false, status: 404};
  try {
    state.view = 'home';
    state.statuteKey = 'PE 46.05';
    statuteMarkup();
    for (let i = 0; i < 5; i++) await tick();
    const html = statuteMarkup();
    assert.match(html, /no bill changes it yet/);
    assert.match(html, /<h2>Prohibited Weapons<\/h2>/);
    assert.match(html, /Current law as of Nov 19, 2026/);
    assert.match(html, /A person commits an offense/);
    assert.doesNotMatch(html, /Added by Acts/);
    assert.match(html, /href="#chapter\?law=PE&amp;ch=46">Chapter 46<\/a>/);
  } finally {
    globalThis.fetch = real;
  }
});

test('heading search loads the smallest matching prefix file and lists headings with every word', async () => {
  assert.deepEqual(lawSearchTerms('Unlawful carrying of a weapon'), ['unlawful', 'carrying', 'weapon']);
  const manifest = {format: 'texas-bill-law-search-v1', prefixes: {unl: 40, car: 900, wea: 300}};
  assert.equal(lawSearchPrefix(manifest, ['unlawful', 'carrying']), 'unl');
  assert.equal(lawSearchPrefix(manifest, ['unlawful', 'zebra']), null, 'a word no heading has: nothing can match');
  const shard = [['PE 46.02', 'UNLAWFUL CARRYING WEAPONS'], ['PE 46', 'WEAPONS'], ['PE 46.06', 'UNLAWFUL TRANSFER OF CERTAIN WEAPONS'],
    ['CN 1.1', 'UNLAWFUL CARRYING'], ['PE 30.05', 'CRIMINAL TRESPASS'], ['GV 411.1', 'BUNLAWFUL CARRYING']];
  assert.deepEqual(lawSearchMatches(shard, ['unlawful', 'carrying']), [['PE 46.02', 'UNLAWFUL CARRYING WEAPONS']],
    'every word must start a heading word; untracked codes are left out');
  assert.deepEqual(lawSearchMatches(shard, ['weapons']).map(e => e[0]), ['PE 46', 'PE 46.02', 'PE 46.06'], 'chapters first');

  const files = {'search/index.json': manifest, 'search/unl.json': shard};
  const real = globalThis.fetch, asked = [];
  globalThis.fetch = async url => {
    const name = Object.keys(files).find(f => String(url).endsWith(`/live/law/${f}`));
    asked.push(String(url));
    return name ? {ok: true, json: async () => files[name]} : {ok: false, status: 404};
  };
  try {
    state.statutes = index({'PE 46.02': {h: 'UNLAWFUL CARRYING WEAPONS', b: [['HB1', 'm']]}});
    state.view = 'home';
    statuteHintMarkup([], 'unlawful carrying');
    for (let i = 0; i < 5; i++) { await tick(); statuteHintMarkup([], 'unlawful carrying'); }
    const html = statuteHintMarkup([], 'unlawful carrying');
    assert.match(html, /“unlawful carrying” in its heading/);
    assert.match(html, /Penal Code § 46\.02<\/a> <span class="law-heading">Unlawful Carrying Weapons<\/span> <small>· bills change it/);
    assert.ok(!asked.some(u => /car\.json|wea\.json/.test(u)), 'only the smallest prefix file is loaded');
    assert.equal(statuteHintMarkup([], 'zz'), '', 'no usable words: no hint');
  } finally {
    globalThis.fetch = real;
  }
});

test('an exact chapter query in the explorer shows only the bills that change something in it', () => {
  state.statutes = index({'PE 46.02': {h: 'X', b: [['HB1', 'm']]}});
  assert.match(statuteHintMarkup([], 'PE 46'), /Showing only bills that change something in <a[^>]*>Penal Code chapter 46<\/a>\. Open it/);
  assert.match(statuteHintMarkup([], 'PE 47'), /: none yet\./);
});
