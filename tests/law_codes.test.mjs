// Code pages (#24): /law and /law/<CODE> in the app, the same lists build_feeds.write_law_code_pages draws statically.
import test from 'node:test';
import assert from 'node:assert/strict';
import {lawCodeList, codeChapters, chapterBillCounts, chapterTitle, billsChange, chapterCount, validLawIndex} from '../src/features/lawcodes/model.js';
import {parseLocation, buildUrl, isAppPath} from '../src/prefs.js';
import {parseStaticView, staticMatches} from '../src/core/static_page.js';
import {lawsHead, lawCodeHead} from '../src/core/head.js';
import {pageMeta} from '../src/core/routes.js';

const LAW = {format: 'texas-bill-law-v1', codes: {
  PE: {headings: {'46': 'CHAPTER 46. WEAPONS', '12': 'CHAPTER 12. PUNISHMENTS', '12A': 'CHAPTER 12A. STATE JAIL',
    '100': 'CHAPTER 100. LAST', '491.v2': 'CHAPTER 491. A SECOND VERSION'}},
  HS: {headings: {'481': 'CHAPTER 481. TEXAS CONTROLLED SUBSTANCES ACT'}},
  ZZ: {headings: {'1': 'CHAPTER 1. X'}},
  AG: {headings: {}},
}};
const INDEX = {sections: {'PE 46.02': {b: [['HB1', 'm'], ['SB2', 'm']]}, 'PE 46.06': {b: [['HB1', 'r']]}},
  chapters: {'HS 481': {b: [['HB9', 'm']]}}};

test('a code lists every chapter in number order, without second versions', () => {
  assert.deepEqual(codeChapters(LAW, 'PE'), [['12', 'PUNISHMENTS'], ['12A', 'STATE JAIL'], ['46', 'WEAPONS'], ['100', 'LAST']]);
  assert.deepEqual(codeChapters(LAW, 'XX'), []);
  assert.deepEqual(codeChapters({format: 'other', codes: LAW.codes}, 'PE'), []);
});

test('the code list has the tracked codes with chapters, by name', () => {
  assert.deepEqual(lawCodeList(LAW), [['HS', 'Health and Safety Code', 1], ['PE', 'Penal Code', 4]]);
  assert.deepEqual(lawCodeList(null), []);
  assert.equal(validLawIndex({format: 'texas-bill-law-v1', codes: []}), false);
});

test('a chapter counts each bill once, whether it changes a section or the whole chapter', () => {
  assert.deepEqual([...chapterBillCounts(INDEX)], [['PE 46', 2], ['HS 481', 1]]);
  assert.deepEqual([...chapterBillCounts(null)], []);
  assert.equal(billsChange(1), '1 bill changes it');
  assert.equal(billsChange(3), '3 bills change it');
  assert.deepEqual([chapterCount(1), chapterCount(2)], ['1 chapter', '2 chapters']);
  assert.equal(chapterTitle('ARTICLE 42A. COMMUNITY SUPERVISION.'), 'COMMUNITY SUPERVISION');
});

test('/law and /law/<CODE> are app paths that round-trip', () => {
  assert.equal(parseLocation('/law', '').view, 'laws');
  assert.equal(parseLocation('/law/', '').view, 'laws');
  const p = parseLocation('/law/pe', '');
  assert.deepEqual([p.view, p.lawCode], ['lawcode', 'PE']);
  assert.equal(buildUrl('lawcode', {}, {lawCode: 'PE'}), '/law/PE');
  assert.equal(buildUrl('laws', {}, {}), '/law');
  assert.equal(parseLocation('/law/PE/46', '').statute, 'PE 46');  // A chapter is still a chapter.
  assert.notEqual(parseLocation('/law/PEN', '').view, 'lawcode');
  for (const path of ['/law', '/law/PE', '/law/PE/46']) assert.ok(isAppPath(path), path);
  assert.ok(!isAppPath('/law/PEN'));
  assert.equal(parseLocation('/', '#lawcode?law=HS').lawCode, 'HS');
});

test('both are indexed, with their own canonical', () => {
  assert.deepEqual([pageMeta('laws', '/law').canonical, pageMeta('laws', '/law').robots], ['https://billatlas.org/law', null]);
  assert.equal(pageMeta('lawcode', '/law/PE').canonical, 'https://billatlas.org/law/PE');
});

test('the app keeps the static code pages until it has drawn the same view', () => {
  assert.deepEqual(parseStaticView('page:laws'), {kind: 'page', key: 'laws'});
  assert.deepEqual(parseStaticView('code:PE'), {kind: 'code', key: 'PE'});
  assert.equal(parseStaticView('code:pe'), null);
  assert.ok(staticMatches(parseStaticView('page:laws'), parseLocation('/law', '')));
  assert.ok(staticMatches(parseStaticView('code:PE'), parseLocation('/law/PE', '')));
  assert.ok(!staticMatches(parseStaticView('code:PE'), parseLocation('/law/HS', '')));
  assert.ok(!staticMatches(parseStaticView('code:PE'), parseLocation('/law', '')));
});

test('the heads match the static pages', () => {
  assert.equal(lawsHead().title, 'Texas law: the codes');
  assert.equal(lawCodeHead('Penal Code').title, 'Texas Penal Code: every chapter');
});
