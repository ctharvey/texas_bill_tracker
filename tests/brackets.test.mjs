import test from 'node:test';
import assert from 'node:assert/strict';
import {validBracketIndex, placeName, bracketTest, bracketRows, placeCount, BRACKET_RELATIONS} from '../src/review.js';

const places = {'48201': ['Harris County', 4731145], '48113': ['Dallas County', 2613539],
  '4861592': ['Reno city', 3454, 'Lamar County'], '4835000': ['Houston city', 2304580, '']};

test('index format is checked', () => {
  assert.ok(validBracketIndex({format: 'texas-bill-brackets-v1', places: {}, bills: {}}));
  assert.ok(!validBracketIndex({format: 'texas-bill-brackets-v1', places: [], bills: {}}));
  assert.ok(!validBracketIndex({format: 'texas-bill-statutes-v1', places: {}, bills: {}}));
  assert.ok(!validBracketIndex(null));
});

test('place names drop the census suffix and keep the county only for shared names', () => {
  assert.equal(placeName(places['4835000']), 'Houston');
  assert.equal(placeName(places['4861592']), 'Reno (Lamar County)');
  assert.equal(placeName(places['48201']), 'Harris County');
  assert.equal(placeName(undefined), '');
});

test('the test is quoted from the bill', () => {
  assert.equal(bracketTest('county with a population of more than four million'), 'more than four million');
  assert.equal(bracketTest('(1) has a population of less than 100,000;'), 'less than 100,000');
  assert.equal(bracketTest('municipality having a population in excess of 1.1 million'), 'in excess of 1.1 million');
});

test('rows merge repeats, put changes first and narrow sets before broad ones, and skip bad rows', () => {
  const entry = {c: [
    {s: 'existing', k: 'county', t: 'county with a population of 2.5 million or more', lo: 2500000, hi: null, n: 2, p: ['48201', '48113']},
    {s: 'new', k: 'city', t: 'municipality with a population of less than 20,000', lo: null, hi: 19999, n: 1082, p: null},
    {s: 'new', k: 'county', t: 'county with a population of more than four million', lo: 4000001, hi: null, n: 1, p: ['48201'], sec: 'SECTION 2'},
    {s: 'new', k: 'county', t: 'county that has a population of more than four million', lo: 4000001, hi: null, n: 1, p: ['48201']},
    {s: 'changed', k: 'county', t: 'county with a population of 2.5 million or more', lo: 2500000, hi: null, n: 2, p: ['48201', '48113'],
      was: {t: 'county with a population of four million or more', n: 1, added: 1, dropped: 0, added_p: ['48113'], dropped_p: []}},
    {s: 'bogus', k: 'county', t: 'x'}, {s: 'new', k: 'district', t: 'x'}, null,
  ]};
  const rows = bracketRows(entry, places);
  assert.deepEqual(rows.map(r => [r.status, r.n]), [['changed', 2], ['new', 1], ['new', 1082], ['existing', 2]]);
  assert.equal(rows[1].times, 2);
  assert.deepEqual(rows[1].names, ['Harris County']);
  assert.equal(rows[2].names, null);  // too many to list: counted only
  assert.deepEqual(rows[0].was.addedNames, ['Dallas County']);
  assert.equal(rows[0].was.test, 'four million or more');
});

test('older-census rows keep the year and no count', () => {
  const [row] = bracketRows({c: [{s: 'new', k: 'county', t: 'county with a population of more than 600,000', lo: 600001, hi: null, census: 2010}]});
  assert.equal(row.census, 2010);
  assert.equal(row.n, null);
});

test('counts read naturally', () => {
  assert.equal(placeCount(1, 'county'), '1 county');
  assert.equal(placeCount(1082, 'city'), '1,082 cities');
});

test('tests on related places are labeled, sort after tests on the covered place, and unknown relations are dropped', () => {
  const rows = bracketRows({c: [
    {s: 'new', k: 'county', t: 'county with a population of 4 million or more', lo: 4000000, hi: null, n: 1, p: ['48201'], rel: 'near'},
    {s: 'new', k: 'county', t: 'county with a population of 800,000 or more', lo: 800000, hi: null, n: 10, p: null},
    {s: 'new', k: 'city', t: 'municipality with a population of 500,000 or more', lo: 500000, hi: null, n: 6, p: null, rel: 'bogus'},
  ]}, places);
  assert.deepEqual(rows.map(r => [r.n, r.rel]), [[6, null], [10, null], [1, 'near']]);
  assert.ok(BRACKET_RELATIONS.near && BRACKET_RELATIONS.inside && BRACKET_RELATIONS.seat && BRACKET_RELATIONS.principal);
});

test('places close to the line keep their own population even when a name is missing', () => {
  const [row] = bracketRows({c: [{s: 'new', k: 'county', t: 'county with a population of 2.5 million or more', lo: 2500000,
    hi: null, n: 2, p: ['48201', '48113'], near: ['99999', '48113']}]}, places);
  assert.deepEqual(row.near, [{name: 'Dallas County', pop: 2613539}]);
});
