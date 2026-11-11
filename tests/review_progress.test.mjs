import test from 'node:test';
import assert from 'node:assert/strict';
import {reviewProgress, reviewSummary} from '../src/taxonomy.js';

const ids = ['HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6'];

test('splits bills by worker status with current > failed > retry > reviewed precedence', () => {
  const status = {running: true, current: 'HB2', upcoming: ['HB3', 'HB99'], reviewed: ['HB1', 'HB2', 'HB4', 'HB5'],
    retry: ['HB4', 'HB2'], failed: {HB5: 'download', HB6: 'processing'}};
  const p = reviewProgress(ids, status);
  assert.equal(p.current, 'HB2');
  assert.deepEqual(p.upcoming, ['HB3']);
  assert.deepEqual(p.inProgress, ['HB4']);
  assert.deepEqual(p.failed, [{id: 'HB5', stage: 'download'}, {id: 'HB6', stage: 'processing'}]);
  assert.deepEqual(p.reviewed, ['HB1']);
  assert.deepEqual(p.notStarted, ['HB3']);
  const all = [p.current, ...p.inProgress, ...p.failed.map(f => f.id), ...p.reviewed, ...p.notStarted];
  assert.deepEqual([...all].sort(), [...ids].sort());
});

test('an idle worker has no current bill', () => {
  const p = reviewProgress(ids, {running: false, current: 'HB2', reviewed: ['HB2']});
  assert.equal(p.current, null);
  assert.deepEqual(p.reviewed, ['HB2']);
});

test('falls back to published tags when the status file is missing or malformed', () => {
  assert.deepEqual(reviewProgress(ids, null, ['HB3']).reviewed, ['HB3']);
  const p = reviewProgress(ids, {reviewed: 'HB1', retry: null, failed: ['HB2']}, []);
  assert.deepEqual(p.notStarted, ids);
});

test('lists every bill in progress when several workers run, keeping current for older readers', () => {
  const status = {running: true, current: 'HB3', in_progress: ['HB3', 'HB1', 'HB99', 'HB1'], upcoming: ['HB1', 'HB4'],
    reviewed: ['HB1', 'HB2'], retry: [], failed: {HB1: 'processing'}};
  const p = reviewProgress(ids, status);
  assert.deepEqual(p.active, ['HB3', 'HB1']);
  assert.equal(p.current, 'HB3');
  assert.deepEqual(p.upcoming, ['HB4']);
  assert.deepEqual(p.failed, []);  // a bill being re-run is shown in progress, not failed
  assert.deepEqual(p.reviewed, ['HB2']);
  const s = reviewSummary(p);
  assert.deepEqual(s.active, ['HB3', 'HB1']);
});

test('older status files without in_progress fall back to current; an empty list means none', () => {
  assert.deepEqual(reviewProgress(ids, {running: true, current: 'HB2'}).active, ['HB2']);
  assert.deepEqual(reviewProgress(ids, {running: true, current: 'HB2', in_progress: []}).active, []);
  assert.deepEqual(reviewProgress(ids, {running: false, in_progress: ['HB2']}).active, []);
});
