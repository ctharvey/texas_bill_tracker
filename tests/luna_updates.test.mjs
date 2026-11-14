// What Luna changed: publishes newest first, the last 24 hours merged per bill, and one line per change.
import test from 'node:test';
import assert from 'node:assert/strict';
import {recentChanges, updateEntries, changeText} from '../src/features/review/updates.js';

const NOW = Date.parse('2026-11-14T20:00:00Z');
const updates = {format: 'texas-bill-luna-updates-v1', updates: [
  {at: '2026-11-14T19:30:00Z', counts: {all_agencies: 2}, bills: {
    HB2: [{kind: 'all_agencies'}], HB9: [{kind: 'all_agencies'}]}},
  {at: '2026-11-14T12:00:00Z', counts: {reviewed: 1, agencies: 1}, bills: {
    HB2: [{kind: 'agencies', added: ['Texas Department of Transportation'], removed: []}],
    HB5: [{kind: 'reviewed'}], HB6: [{kind: 'bogus'}]}},
  {at: '2026-11-12T12:00:00Z', counts: {reviewed: 1}, bills: {HB1: [{kind: 'reviewed'}]}},
  {at: 'not a time', bills: {HB7: [{kind: 'reviewed'}]}},
]};

test('the last 24 hours: each bill once, newest first, with every kind of change it had', () => {
  const {counts, bills} = recentChanges(updates, NOW);
  assert.deepEqual(bills.map(b => [b.id, b.changes.map(c => c.kind)]),
    [['HB2', ['all_agencies', 'agencies']], ['HB9', ['all_agencies']], ['HB5', ['reviewed']]]);
  assert.deepEqual(counts.map(c => [c.kind, c.n]), [['reviewed', 1], ['all_agencies', 2], ['agencies', 1]]);
});

test('every publish in the log, newest first, unknown kinds and bad entries dropped', () => {
  const entries = updateEntries(updates);
  assert.deepEqual(entries.map(e => e.at), ['2026-11-14T19:30:00Z', '2026-11-14T12:00:00Z', '2026-11-12T12:00:00Z']);
  assert.deepEqual(entries[1].bills.map(b => b.id), ['HB2', 'HB5']);
  assert.deepEqual(updateEntries(null), []);
  assert.deepEqual(recentChanges({}, NOW), {counts: [], bills: []});
});

test('one line per change', () => {
  assert.equal(changeText({kind: 'agencies', added: ['A'], removed: ['B']}), 'Agencies: +A, -B');
  assert.equal(changeText({kind: 'topics', added: [], removed: []}), 'topics changed');
  assert.equal(changeText({kind: 'all_agencies'}), 'Now marked all state agencies');
  assert.equal(changeText({kind: 'new_version', to: 'E'}), 'New text version reviewed (E)');
  assert.equal(changeText({kind: 'nope'}), '');
});
