// Review page: the later pass's bills in flight, one per slot, each with its step.
import test from 'node:test';
import assert from 'node:assert/strict';
import {passJobs} from '../src/features/review/model.js';

const status = {pass_jobs: [{bill: 'HB1', job: 'scope vote 2'}, {bill: 'HB2', job: null}, {job: 'x'}, null]};

test('a later pass lists each bill in flight with its step', () => {
  assert.deepEqual(passJobs(status, {pass: 'topics'}),
    [{id: 'HB1', job: 'scope vote 2'}, {id: 'HB2', job: null}]);
});

test('the first pass and a missing field show nothing', () => {
  assert.deepEqual(passJobs(status, {pass: 'review'}), []);
  assert.deepEqual(passJobs(status, {}), []);
  assert.deepEqual(passJobs({}, {pass: 'audit'}), []);
  assert.deepEqual(passJobs(null, {pass: 'audit'}), []);
});
