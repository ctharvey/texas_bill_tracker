import test from 'node:test';
import assert from 'node:assert/strict';
import {companionIndex, companionRuns, normalizeCompanions, searchTerms} from '../src/taxonomy.js';

test('normalizeCompanions keeps valid ids and drops malformed, self and duplicate entries', () => {
  const out = normalizeCompanions([{id: 'SB 132', author: 'Menéndez', relation: 'Identical'}, {id: 'sb132'}, {id: 'HB267'},
    {id: 'nonsense'}, null, {id: 'HJR5', author: 7}], 'HB267');
  assert.deepEqual(out, [{id: 'SB132', number: 'SB 132', author: 'Menéndez', relation: 'Identical'},
    {id: 'HJR5', number: 'HJR 5', author: '', relation: ''}]);
  assert.deepEqual(normalizeCompanions(undefined), []);
});

test('companionIndex links both directions and prefers the bill\'s own listing', () => {
  const bills = [
    {id: 'HB267', authors: ['Cole'], companions: [{id: 'SB132', number: 'SB 132', author: 'Menéndez', relation: 'Identical'}]},
    {id: 'SB132', authors: ['Menéndez'], companions: []},
    {id: 'SB9', authors: ['Hall'], companions: [{id: 'HB10', number: 'HB 10', author: 'Own author', relation: ''}]},
    {id: 'HB10', authors: ['X'], companions: [{id: 'SB9', number: 'SB 9', author: 'Hall', relation: 'Similar'}]},
  ];
  const index = companionIndex(bills);
  assert.deepEqual(index.get('SB132'), [{id: 'HB267', number: 'HB 267', author: 'Cole', relation: 'Identical'}]);
  // HB10 listed by SB9 with an empty relation: own author wins, the reverse link fills the relation.
  assert.deepEqual(index.get('SB9'), [{id: 'HB10', number: 'HB 10', author: 'Own author', relation: 'Similar'}]);
  // Order of bills must not change the result.
  assert.deepEqual(companionIndex([...bills].reverse()).get('SB9'), index.get('SB9'));
});

test('companionRuns ties adjacent companions into pairs only', () => {
  const index = new Map([['A', [{id: 'B'}]], ['B', [{id: 'A'}, {id: 'C'}]], ['C', [{id: 'B'}]]]);
  const ids = runs => runs.map(r => r.map(b => b.id));
  assert.deepEqual(ids(companionRuns([{id: 'A'}, {id: 'B'}, {id: 'C'}], index)), [['A', 'B'], ['C']]);
  assert.deepEqual(ids(companionRuns([{id: 'A'}, {id: 'X'}, {id: 'B'}], index)), [['A'], ['X'], ['B']]);
  assert.deepEqual(ids(companionRuns([], index)), []);
});

test('searchTerms reads pasted bill numbers with hidden characters or long forms', () => {
  for (const pasted of ['HB267', '​HB267', 'HB 267﻿', 'H.B. No. 267', 'House Bill 267', ' hb 267 ', 'ＨＢ２６７'])
    assert.equal(searchTerms(pasted).compact, 'hb267', JSON.stringify(pasted));
  assert.equal(searchTerms('Senate Joint Resolution 9').compact, 'sjr9');
  assert.equal(searchTerms('water rights').q, 'water rights');
  assert.equal(searchTerms('water rights').compact, 'waterrights');
});
