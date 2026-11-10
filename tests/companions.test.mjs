import test from 'node:test';
import assert from 'node:assert/strict';
import {companionGroups, companionIndex, normalizeCompanions, searchTerms} from '../src/taxonomy.js';

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

test('companionGroups pulls companions in the list together at the first one\'s position', () => {
  const index = new Map([['A', [{id: 'B'}]], ['B', [{id: 'A'}, {id: 'C'}]], ['C', [{id: 'B'}]], ['D', [{id: 'Z'}]]]);
  const ids = groups => groups.map(g => g.map(b => b.id));
  const b = id => ({id});
  // B sits far from A in the sort; it moves up next to A. Chains (A-B-C) form one group.
  assert.deepEqual(ids(companionGroups([b('A'), b('X'), b('Y'), b('B')], index)), [['A', 'B'], ['X'], ['Y']]);
  assert.deepEqual(ids(companionGroups([b('X'), b('C'), b('A'), b('B')], index)), [['X'], ['C', 'A', 'B']]);
  // A companion that is not in the list changes nothing.
  assert.deepEqual(ids(companionGroups([b('D'), b('X')], index)), [['D'], ['X']]);
  assert.deepEqual(ids(companionGroups([], index)), []);
  const list = [b('A'), b('X'), b('B'), b('C'), b('Y')];
  assert.equal(companionGroups(list, index).flat().length, list.length);
});

test('searchTerms reads pasted bill numbers with hidden characters or long forms', () => {
  for (const pasted of ['HB267', '​HB267', 'HB 267﻿', 'H.B. No. 267', 'House Bill 267', ' hb 267 ', 'ＨＢ２６７'])
    assert.equal(searchTerms(pasted).compact, 'hb267', JSON.stringify(pasted));
  assert.equal(searchTerms('Senate Joint Resolution 9').compact, 'sjr9');
  assert.equal(searchTerms('water rights').q, 'water rights');
  assert.equal(searchTerms('water rights').compact, 'waterrights');
});
