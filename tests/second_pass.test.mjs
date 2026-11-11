import test from 'node:test';
import assert from 'node:assert/strict';
import {applyLunaExtras, relatedFor, auditLine} from '../src/taxonomy.js';

test('applyLunaExtras merges headline and dedupes terms', () => {
  const bill = {id: 'HB1', title: 'T'};
  const out = applyLunaExtras(bill, {headline: ' Plain line ', search_terms: ['voucher', 'ESA', 'voucher'], opposing_terms: ['ESA', 'school choice', '', 5]});
  assert.equal(out.headline, 'Plain line');
  assert.deepEqual(out.search_terms, ['voucher', 'ESA', 'school choice']);
  assert.notEqual(out, bill);
  assert.equal(bill.headline, undefined);
});

test('applyLunaExtras caps lengths and count', () => {
  const many = Array.from({length: 30}, (_, i) => `term${i}`);
  const out = applyLunaExtras({id: 'HB1'}, {search_terms: [...many, 'x'.repeat(100)]});
  assert.equal(out.search_terms.length, 20);
  assert.equal(applyLunaExtras({id: 'HB1'}, {search_terms: ['y'.repeat(100)]}).search_terms[0].length, 60);
});

test('applyLunaExtras ignores malformed input', () => {
  const bill = {id: 'HB1'};
  assert.equal(applyLunaExtras(bill, null), bill);
  assert.equal(applyLunaExtras(bill, 'x'), bill);
  const out = applyLunaExtras(bill, {headline: 7, search_terms: 'nope', opposing_terms: {}});
  assert.equal(out.headline, undefined);
  assert.equal(out.search_terms, undefined);
});

test('relatedFor filters unknown and malformed ids and caps at 5', () => {
  const known = new Set(['SB1', 'SB2', 'SB3', 'SB4', 'SB5', 'SB6', 'HB1']);
  const related = {bills: {HB1: [{id: 'SB1'}, {id: 'ZZ9'}, null, {id: 3}, 'SB2', {id: 'SB3'}, {id: 'SB4'}, {id: 'SB5'}, {id: 'SB6'}]}};
  assert.deepEqual(relatedFor('HB1', related, known), ['SB1', 'SB3', 'SB4', 'SB5', 'SB6']);
  assert.deepEqual(relatedFor('HB2', related, known), []);
  assert.deepEqual(relatedFor('HB1', null, known), []);
  assert.deepEqual(relatedFor('HB1', {bills: {HB1: 'x'}}, known), []);
});

test('auditLine formats plural, singular and omits zero parts', () => {
  assert.equal(auditLine({checked: 12, agree: 9, minor_issues: 2, major_issues: 1}), 'Spot check: 12 reviews re-checked independently · 9 agreed · 2 with minor issues · 1 with major issues');
  assert.equal(auditLine({checked: 1, agree: 1, minor_issues: 0, major_issues: 0}), 'Spot check: 1 review re-checked independently · 1 agreed');
  assert.equal(auditLine({checked: 3, agree: 2, minor_issues: 1, major_issues: 0}), 'Spot check: 3 reviews re-checked independently · 2 agreed · 1 with minor issues');
});

test('auditLine returns null for bad input', () => {
  assert.equal(auditLine(null), null);
  assert.equal(auditLine({}), null);
  assert.equal(auditLine({checked: 0, agree: 0}), null);
  assert.equal(auditLine({checked: 'a', agree: 1}), null);
});
