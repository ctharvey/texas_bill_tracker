// Security audit 2026-11-15 (M2): filter values are looked up by name, so "__proto__" and friends must stay plain text.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseHash, cleanFilters, cleanSearches, parseProfileFile} from '../src/prefs.js';

test('a "__proto__" sort is dropped from the address, filters and saved searches', () => {
  assert.equal(parseHash('#all?sort=__proto__').filters.sort, undefined);
  assert.equal(cleanFilters({sort: '__proto__'}).sort, undefined);
  assert.equal(cleanFilters({sort: 'constructor()'}).sort, undefined);
  const [search] = cleanSearches([{id: 'abcdefgh', name: 'x', filters: {sort: '__proto__', chamber: 'House'}}]);
  assert.deepEqual(search.filters, {chamber: 'House'});
});

test('valid sorts are kept unchanged', () => {
  const sorts = readFileSync(new URL('../src/app.js', import.meta.url), 'utf8').match(/const SORTS=\{([^}]*)\}/)[1];
  const names = [...sorts.matchAll(/(\w+):'/g)].map(m => m[1]);
  assert.ok(names.length >= 8);
  for (const name of names) {
    assert.equal(parseHash(`#all?sort=${name}`).filters.sort, name);
    assert.equal(cleanFilters({sort: name}).sort, name);
  }
});

test('a prototype name as a renamed filter value stays a string', () => {
  assert.equal(cleanFilters({outlook: '__proto__'}).outlook, '__proto__');
  assert.equal(cleanFilters({outlook: 'Not rated'}).outlook, 'No hearing yet');  // the real rename still applies
});

test('a saved search with an impossible "seen" day keeps the search and drops the day', () => {
  const [bad] = cleanSearches([{id: 'abcdefgh', name: 'x', filters: {}, seen: '2026-13-45'}]);
  assert.equal(bad.seen, null);
  const [good] = cleanSearches([{id: 'abcdefgh', name: 'x', filters: {}, seen: '2026-11-12'}]);
  assert.equal(good.seen, '2026-11-12');
});

test('a profile file cannot plant a "__proto__" sort', () => {
  const file = JSON.stringify({format: 'texas-bill-atlas-profile-v1', watch: [], follows: [],
    searches: [{id: 'abcdefgh', name: 'x', filters: {sort: '__proto__'}}]});
  let parsed;
  try { parsed = parseProfileFile(file); } catch { return; }  // a rejected file is also safe
  for (const s of parsed.searches || []) assert.notEqual(s.filters.sort, '__proto__');
});
