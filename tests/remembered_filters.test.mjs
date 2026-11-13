import test from 'node:test';
import assert from 'node:assert/strict';
import {sameFilters, FILTER_DEFAULTS} from '../src/prefs.js';

// A save made before the party filter existed (as in tests/e2e/fixtures/stored/local_storage.json).
const before = {query: 'school', topic: '', agency: '', chamber: 'Senate', stage: '', action: '', outlook: '', sort: 'newest',
  onlyWatch: false};
const loaded = {...FILTER_DEFAULTS, ...before};

test('an older save still means the same filters once a newer filter is added at its default', () => {
  assert.equal(sameFilters(before, loaded), true);
});

test('a real change or a non-default new filter differs; a legacy value the load maps does not', () => {
  assert.equal(sameFilters(before, {...loaded, chamber: 'House'}), false);
  assert.equal(sameFilters(before, {...loaded, party: 'Republican'}), false);
  assert.equal(sameFilters({...before, outlook: 'Not rated'}, {...loaded, outlook: 'No hearing yet'}), true);
});
