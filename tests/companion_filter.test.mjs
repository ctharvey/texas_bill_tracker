import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseHash, buildHash, cleanFilters, searchName, sameFilters, FILTER_DEFAULTS} from '../src/prefs.js';

test('the companion filter is off by default and kept out of plain addresses', () => {
  assert.equal(FILTER_DEFAULTS.companion, false);
  assert.equal(buildHash('all', FILTER_DEFAULTS), '#all');
});

test('the companion filter round-trips through an address as 1', () => {
  const hash = buildHash('all', {...FILTER_DEFAULTS, companion: true, topic: 'Education'});
  assert.equal(hash, '#all?topic=Education&companion=1');
  assert.deepEqual(parseHash(hash).filters, {topic: 'Education', companion: true});
  assert.deepEqual(parseHash('#all?companion=0').filters, {companion: false});
  assert.deepEqual(parseHash('#all?companion=yes').filters, {companion: false});
});

test('remembered filters keep the companion filter only as true or false', () => {
  assert.deepEqual(cleanFilters({companion: true}), {companion: true});
  assert.deepEqual(cleanFilters({companion: 'true'}), {});
  // A save from before the filter existed still matches a page with it off, so loading never rewrites it.
  assert.equal(sameFilters({topic: 'Taxes'}, {...FILTER_DEFAULTS, topic: 'Taxes'}), true);
  assert.equal(sameFilters({topic: 'Taxes'}, {...FILTER_DEFAULTS, topic: 'Taxes', companion: true}), false);
});

test('a saved search with the companion filter is named for it', () => {
  assert.equal(searchName({companion: true}), 'Has companion');
  assert.equal(searchName({topic: 'Education', companion: true}), 'Education · Has companion');
});

test('the explorer keeps only bills with a companion, and Clear all and the chip reset it', () => {
  const app = readFileSync(new URL('../src/app.js', import.meta.url), 'utf8');
  assert.match(app, /if\(f\.companion&&!companionsOf\(b\.id\)\.length\)return false;/);
  assert.match(app, /id="companion-filter"/);
  assert.match(app, /onlyWatch:false,companion:false,visibleCount:30\}\);renderContent\(\)/);
  assert.match(app, /\['companion',state\.companion&&'Has companion'\]/);
});
