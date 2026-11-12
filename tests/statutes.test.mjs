import assert from 'node:assert/strict';
import test from 'node:test';
import {STATUTE_KEY, statuteFile, statuteLabel, officialStatuteUrl, validStatuteIndex, statutesByBill, parseStatuteQuery,
  statuteKeysFor, lawParagraph, lawUnits, wordDiff, compareLaw, currentLaw, groupStatuteEntries} from '../src/review.js';
import {parseHash, buildHash} from '../src/prefs.js';

const CODES = {ED: 'Education Code', PE: 'Penal Code', CR: 'Code of Criminal Procedure', HS: 'Health and Safety Code'};

test('keys, file names, labels and official links', () => {
  assert.ok(STATUTE_KEY.test('ED 48.160') && STATUTE_KEY.test('CR 42A.054'));
  assert.equal(statuteFile('ED 48.160'), 'ED-48.160.json');
  for (const bad of ['ED 48', 'ED 48.160/../x', 'ed 48.160', '../ED 1.1', 'ED  1.1']) assert.equal(statuteFile(bad), null, bad);
  assert.equal(statuteLabel('PE 46.06', CODES), 'Penal Code § 46.06');
  assert.equal(statuteLabel('CR 46.04', CODES), 'Code of Criminal Procedure Art. 46.04');
  assert.equal(officialStatuteUrl('HR 101A.251'), 'https://statutes.capitol.texas.gov/?tab=1&code=HR&chapter=HR.101A&artSec=101A.251');
  assert.equal(officialStatuteUrl('nope'), '');
});

test('index validation and the per-bill view', () => {
  const index = {format: 'texas-bill-statutes-v1', codes: CODES, bills: {},
    sections: {'ED 48.160': {h: 'X', b: [['HB1', 'm'], ['SB2', 'n']]}, 'bad key': {b: [['HB9', 'm']]}, 'PE 46.06': {b: [['HB1', 'z'], ['HB1', 'r']]}}};
  assert.ok(validStatuteIndex(index));
  assert.ok(!validStatuteIndex({...index, format: 'x'}) && !validStatuteIndex({...index, sections: []}));
  const by = statutesByBill(index);
  assert.deepEqual(by.get('HB1'), [{key: 'ED 48.160', kind: 'm', others: 1}, {key: 'PE 46.06', kind: 'r', others: 1}]);
  assert.ok(!by.has('HB9'));
});

test('section searches', () => {
  assert.deepEqual(parseStatuteQuery('48.160', CODES), {code: null, sec: '48.160'});
  assert.deepEqual(parseStatuteQuery('§ 48.160', CODES), {code: null, sec: '48.160'});
  assert.deepEqual(parseStatuteQuery('Penal Code 46.06', CODES), {code: 'PE', sec: '46.06'});
  assert.deepEqual(parseStatuteQuery('penal code, § 46.06', CODES), {code: 'PE', sec: '46.06'});
  assert.deepEqual(parseStatuteQuery('ED 48.160', CODES), {code: 'ED', sec: '48.160'});
  assert.deepEqual(parseStatuteQuery('education sec. 48.160', CODES), {code: 'ED', sec: '48.160'});
  assert.deepEqual(parseStatuteQuery('CCP art. 46.04', CODES), {code: 'CR', sec: '46.04'});
  assert.deepEqual(parseStatuteQuery('criminal procedure 42a.054', CODES), {code: 'CR', sec: '42A.054'});
  for (const q of ['HB 5', 'water', '', 'Water Code 11.1', 'school 48.160']) assert.equal(parseStatuteQuery(q, CODES), null, q);
  const index = {sections: {'ED 48.160': {}, 'PE 48.160': {}, 'ED 48.1601': {}}};
  assert.deepEqual(statuteKeysFor(index, {code: null, sec: '48.160'}), ['ED 48.160', 'PE 48.160']);
  assert.deepEqual(statuteKeysFor(index, {code: 'PE', sec: '48.160'}), ['PE 48.160']);
  assert.deepEqual(statuteKeysFor(index, null), []);
});

test('statute pages round-trip through the address', () => {
  const hash = buildHash('statute', {}, {statute: 'ED 48.160', bill: 'HB5'});
  assert.equal(hash, '#statute?law=ED&sec=48.160&bill=HB5');
  const p = parseHash(hash);
  assert.equal(p.view, 'statute'); assert.equal(p.statute, 'ED 48.160'); assert.equal(p.bill, 'HB5');
  assert.equal(parseHash('#statute?law=ED&sec=../x').statute, null);
  assert.equal(parseHash('#all?law=ED&sec=48.160').statute, null);
  assert.equal(buildHash('all', {}, {statute: 'ED 48.160'}), '#all');
});

test('current law and the proposal from one quoted paragraph', () => {
  const line = 'Sec. 526.0056. PILOT PROGRAM TO PREVENT SPREAD OF INFECTIOUS <ins>AND</ins> \\[<del>OR</del>\\] COMMUNICABLE DISEASES. The commission may provide guidance to the <ins>counties</ins> \\[<del>local health authority</del>\\] in a pilot program.';
  const v = lawParagraph(line);
  assert.equal(v.current, 'Sec. 526.0056. PILOT PROGRAM TO PREVENT SPREAD OF INFECTIOUS OR COMMUNICABLE DISEASES. The commission may provide guidance to the local health authority in a pilot program.');
  assert.equal(v.proposed, 'Sec. 526.0056. PILOT PROGRAM TO PREVENT SPREAD OF INFECTIOUS AND COMMUNICABLE DISEASES. The commission may provide guidance to the counties in a pilot program.');
  assert.ok(!v.current.includes('[') && !v.proposed.includes(']'));
});

test('paragraphs become subsection units; numbered items stay with their subsection', () => {
  const paragraphs = ['Sec. 9.01. A HEADING. (a) First <ins>new</ins>.', '(1) item one;', '(a-1) <ins>Added subsection.</ins>', '(b) Second.', '(A) still b.'];
  assert.deepEqual(lawUnits(paragraphs, 'proposed').map(u => u.label), ['head', 'a', 'a-1', 'b']);
  assert.equal(lawUnits(paragraphs, 'proposed')[1].text, '(a) First new.\n(1) item one;');
  // The added subsection has no current-law text at all.
  assert.deepEqual(lawUnits(paragraphs, 'current').map(u => u.label), ['head', 'a', 'b']);
  assert.deepEqual(lawUnits(['Sec. 1.01. SHORT. Body without subsections.'], 'current').map(u => u.label), ['head', '']);
  assert.deepEqual(lawUnits(['<ins>broken'], 'current'), []);  // Unbalanced markup is skipped, not thrown.
});

test('word differences', () => {
  const d = wordDiff('the board shall act', 'the commission shall act now');
  assert.deepEqual(d.left.filter(w => w.changed).map(w => w.t), ['board']);
  assert.deepEqual(d.right.filter(w => w.changed).map(w => w.t), ['commission', 'now']);
  assert.ok(wordDiff('a b', 'c d', 1).approximate);
  const rebuilt = list => list.map(w => w.t === '\n' ? '\n' : (w.space ? ' ' : '') + w.t).join('');
  const p = wordDiff('(a) First, the rule.\n(1) item;', '(a) First, a rule.\n(1) item;');
  assert.equal(rebuilt(p.left), '(a) First, the rule.\n(1) item;');
  assert.deepEqual(p.right.filter(w => w.changed).map(w => w.t), ['a']);
});

test('a partial quote does not look like a deletion', () => {
  const whole = {name: 'HB 1', partial: false, units: [{label: 'a', text: '(a) Alpha.'}, {label: 'b', text: '(b) Beta.'}]};
  const onlyB = {name: 'HB 2', partial: true, units: [{label: 'b', text: '(b) Beta changed.'}]};
  const rows = compareLaw(whole, onlyB);
  assert.equal(rows[0].label, 'a');
  assert.equal(rows[0].rightNote, 'Not changed by HB 2');
  assert.ok(rows[0].left.every(w => !w.changed));
  assert.deepEqual(rows[1].right.filter(w => w.changed).map(w => w.t), ['changed']);
  // A whole-section quote that leaves a subsection out removes it.
  const rows2 = compareLaw(onlyB, {...whole, units: whole.units.slice(1)});
  assert.equal(rows2.length, 1);
  const rows3 = compareLaw({...whole, name: 'Current law'}, {name: 'HB 3', partial: false, units: [{label: 'b', text: '(b) Beta.'}]});
  assert.equal(rows3[0].rightNote, 'Not in HB 3');
  assert.ok(rows3[0].left.every(w => w.changed));
  assert.ok(rows3[1].same);
});

test('current law prefers whole-section quotes and records its sources', () => {
  const entries = [
    {bill: 'HB2', kind: 'amend', partial: true, paragraphs: ['(b) Old \\[<del>beta</del>\\] <ins>gamma</ins>.']},
    {bill: 'HB1', kind: 'amend', partial: false, paragraphs: ['Sec. 1.01. T. (a) Alpha.', '(b) Old beta.']},
    {bill: 'SB3', kind: 'add', partial: false, paragraphs: ['Sec. 1.01. NEW. Text.']},
  ];
  const law = currentLaw(entries);
  assert.deepEqual(law.units.map(u => u.label), ['head', 'a', 'b']);
  assert.deepEqual(law.sources, ['HB1']);
  assert.equal(law.partial, false);
  assert.deepEqual(currentLaw([entries[2]]).units, []);
});

test('identical proposals are grouped; broad bills sort last', () => {
  const same = ['Sec. 1.01. T. (a) Same <ins>text</ins>.'];
  const groups = groupStatuteEntries([
    {bill: 'HB376', kind: 'amend', paragraphs: ['Sec. 1.01. T. (a) Broad <ins>bill</ins>.']},
    {bill: 'HB110', kind: 'amend', paragraphs: same},
    {bill: 'SB253', kind: 'amend', paragraphs: same},
    {bill: 'HB9', kind: 'repeal', paragraphs: []},
    {bill: 'HB8', kind: 'repeal', paragraphs: []},
    {bill: 'HB7', kind: 'add', paragraphs: ['Sec. 1.01. NEW. Text.']},
  ], id => id === 'HB376');
  assert.deepEqual(groups.map(g => [g.kind, g.entries.map(e => e.bill), g.broad]),
    [['amend', ['HB110', 'SB253'], false], ['amend', ['HB376'], true], ['add', ['HB7'], false], ['repeal', ['HB9'], false], ['repeal', ['HB8'], false]]);
});
