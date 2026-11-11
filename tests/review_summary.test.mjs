import test from 'node:test';
import assert from 'node:assert/strict';
import {reviewProgress, reviewSummary} from '../src/taxonomy.js';

const ids = ['HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6', 'HB7'];

test('bills with queued follow-up questions count as reviewed; missing text is not a failure', () => {
  const status = {running: true, current: 'HB2', upcoming: ['HB3'], reviewed: ['HB1', 'HB2', 'HB4'],
    retry: ['HB4'], failed: {HB5: 'download', HB6: 'processing'}};
  const s = reviewSummary(reviewProgress(ids, status));
  assert.equal(s.current, 'HB2');
  assert.deepEqual(s.reviewed, ['HB1', 'HB4']);
  assert.deepEqual(s.questionsQueued, ['HB4']);
  assert.deepEqual(s.noText, ['HB5']);
  assert.deepEqual(s.failed, [{id: 'HB6', stage: 'processing'}]);
  assert.deepEqual(s.notStarted, ['HB3', 'HB7']);
  const all = [s.current, ...s.reviewed, ...s.noText, ...s.failed.map(f => f.id), ...s.notStarted];
  assert.deepEqual([...all].sort(), [...ids].sort());  // every bill in exactly one group
});
