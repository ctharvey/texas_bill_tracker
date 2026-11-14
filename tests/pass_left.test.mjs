// Review page: "bills left" for a later pass comes down as bills are done; the pass's own count is kept as reported.
import test from 'node:test';
import assert from 'node:assert/strict';
import {passRows} from '../src/features/review/model.js';

const summary = {notStarted: []};
const status = {passes: {review: {due: 24, checked: 5}, topics: {due: 1080, checked: 409}, audit: {due: 31, checked: 0}}};
const row = (rows, key) => rows.find(r => r.key === key);

test('the running later pass shows its count minus the bills done so far', () => {
  const rows = passRows(status, summary, {pass: 'topics'});
  assert.deepEqual([row(rows, 'topics').due, row(rows, 'topics').left], [1080, 671]);
  assert.equal(row(rows, 'audit').left, 31);
});

test('a pass that is not running, and the full review, show the count as reported', () => {
  const idle = passRows(status, summary, {pass: 'audit'});
  assert.equal(row(idle, 'topics').left, 1080);
  const review = passRows(status, summary, {pass: 'review'});
  assert.equal(row(review, 'review').left, 24);
});

test('done never takes the count below zero; an unknown pass stays null', () => {
  const over = passRows({passes: {topics: {due: 3, checked: 9}}}, summary, {pass: 'topics'});
  assert.equal(row(over, 'topics').left, 0);
  assert.equal(row(over, 'entities').left, null);
});
