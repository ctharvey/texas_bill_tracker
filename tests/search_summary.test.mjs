import test from 'node:test';
import assert from 'node:assert/strict';
import {searchSummary} from '../src/features/searches/view.js';

// N5: a saved search whose query is exactly a section key is that section's bills (filteredBills), filters or not.
test('a section key alone is a follow', () => {
  assert.match(searchSummary({query: 'PE 46.06'}), /^Following .*46\.06: bills that change it$/);
});

test('a section key with filters says it is the section\'s bills, not a text search', () => {
  const s = searchSummary({query: 'PE 46.06', topic: 'Guns'});
  assert.match(s, /^Bills that change .*46\.06 · Topic: Guns$/);
  assert.doesNotMatch(s, /Search “/);
});

test('anything else is still a text search', () => {
  assert.equal(searchSummary({query: 'pe 46.06'}), 'Search “pe 46.06”');
  assert.equal(searchSummary({query: 'PM 2.5', topic: 'Guns'}), 'Search “PM 2.5” · Topic: Guns');
});
