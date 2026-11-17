import test from 'node:test';
import assert from 'node:assert/strict';
import {highestNumberFirst} from '../src/taxonomy.js';

const row = id => ({bill: {id}, actions: ['Filed']});

test("a day's bills list the highest number first, across chambers, House first on a tie", () => {
  const rows = ['HB1192', 'SB404', 'HB1198', 'SB1198', 'HB9', 'HJR12'].map(row);
  assert.deepEqual(highestNumberFirst(rows).map(r => r.bill.id), ['HB1198', 'SB1198', 'HB1192', 'SB404', 'HJR12', 'HB9']);
  assert.deepEqual(rows.map(r => r.bill.id)[0], 'HB1192');  // the input is left as it was
  assert.deepEqual(highestNumberFirst([]), []);
});
