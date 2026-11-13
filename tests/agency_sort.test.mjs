// Agency dropdown order: the all-agencies tag first, then A-Z or most bills first.
import test from 'node:test';
import assert from 'node:assert/strict';
import {sortAgencyIds, SCOPE_AGENCY_ID} from '../src/taxonomy.js';

const NAMES = {b: 'Bravo Board', a: 'Alpha Agency', c: 'Charlie Commission', d: 'Delta Department', [SCOPE_AGENCY_ID]: 'All'};
const nameOf = id => NAMES[id];
const counts = new Map([['c', 9], ['d', 9], ['b', 2], [SCOPE_AGENCY_ID, 1]]);
const ids = ['d', SCOPE_AGENCY_ID, 'b', 'a', 'c'];

test('A-Z keeps the all-agencies tag first', () => {
  assert.deepEqual(sortAgencyIds(ids, nameOf, counts, 'name'), [SCOPE_AGENCY_ID, 'a', 'b', 'c', 'd']);
});

test('A-Z is the default', () => {
  assert.deepEqual(sortAgencyIds(ids, nameOf, counts), [SCOPE_AGENCY_ID, 'a', 'b', 'c', 'd']);
  assert.deepEqual(sortAgencyIds(ids, nameOf, counts, 'anything else'), [SCOPE_AGENCY_ID, 'a', 'b', 'c', 'd']);
});

test('most bills first, ties A-Z, agencies without bills last, the all-agencies tag still first', () => {
  assert.deepEqual(sortAgencyIds(ids, nameOf, counts, 'count'), [SCOPE_AGENCY_ID, 'c', 'd', 'b', 'a']);
});

test('the input list is not changed', () => {
  const copy = [...ids];
  sortAgencyIds(ids, nameOf, counts, 'count');
  assert.deepEqual(ids, copy);
});
