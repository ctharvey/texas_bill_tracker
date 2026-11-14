// Agency dropdown groups: agencies with bills on top, those with none in a second group, A-Z.
import test from 'node:test';
import assert from 'node:assert/strict';
import {groupAgencyIds, SCOPE_AGENCY_ID} from '../src/taxonomy.js';

const NAMES = {b: 'Bravo Board', a: 'Alpha Agency', c: 'Charlie Commission', d: 'Delta Department', e: 'Echo Office',
  [SCOPE_AGENCY_ID]: 'All'};
const nameOf = id => NAMES[id];
const counts = new Map([['c', 9], ['d', 3], ['b', 2]]);
const ids = ['e', 'd', SCOPE_AGENCY_ID, 'b', 'a', 'c'];

test('A-Z: agencies with bills first, then the ones with none, each A-Z', () => {
  assert.deepEqual(groupAgencyIds(ids, nameOf, counts),
    {withBills: [SCOPE_AGENCY_ID, 'b', 'c', 'd'], withoutBills: ['a', 'e']});
});

test('most bills: the top group by count, the empty group still A-Z', () => {
  assert.deepEqual(groupAgencyIds(ids, nameOf, counts, 'count'),
    {withBills: [SCOPE_AGENCY_ID, 'c', 'd', 'b'], withoutBills: ['a', 'e']});
});

test('the all-agencies marker stays on top even with no bills', () => {
  assert.equal(groupAgencyIds(ids, nameOf, new Map()).withBills[0], SCOPE_AGENCY_ID);
});

test('every agency appears exactly once and the input is not changed', () => {
  const copy = [...ids];
  const {withBills, withoutBills} = groupAgencyIds(ids, nameOf, counts);
  assert.deepEqual([...withBills, ...withoutBills].sort(), [...ids].sort());
  assert.deepEqual(ids, copy);
});
