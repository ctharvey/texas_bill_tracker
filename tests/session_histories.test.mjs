// Real 89R bills, as sync_ftp.py parses them (tests/fixtures/89R-bills.json; test_session_histories.py keeps that
// file in step with the parser), through the site's hearing, last-action and stage logic.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {assessHearing, lastActionInfo, normalizeBill} from '../src/taxonomy.js';

const raw = JSON.parse(readFileSync(new URL('./fixtures/89R-bills.json', import.meta.url), 'utf8'));
const bill = id => normalizeBill(raw[id], []);

test('hearing status reads the full history, not the last 12 actions', () => {
  const heard = bill('HB1232');
  assert.equal(heard.actions.length, 12);
  assert.ok(!heard.actions.some(a => /public hearing|testimony/i.test(a)));
  assert.equal(assessHearing(heard).label, 'Heard');
  for (const id of ['HB2', 'SB3', 'HB2516', 'HJR2']) assert.equal(assessHearing(bill(id)).label, 'Heard', id);
});

test('a referred bill shows its committee, not the prefiling note', () => {
  const h = assessHearing(bill('HB1001'));
  assert.equal(h.label, 'Referred');
  assert.equal(bill('HB1001').committee, 'Elections');
});

test('final actions classify', () => {
  const cases = {HB2: 'law', SB3: 'vetoed', HB2516: 'law', HJR2: 'secretary', HB1232: 'other_chamber', HB1001: 'referred'};
  for (const [id, key] of Object.entries(cases)) assert.equal(lastActionInfo(bill(id)).key, key, id);
  const statuses = Object.fromEntries(Object.keys(cases).map(id => [id, bill(id).status]));
  assert.deepEqual(statuses, {HB2: 'Enacted', SB3: 'Vetoed', HB2516: 'Enacted', HJR2: 'Passed', HB1232: 'Advanced', HB1001: 'Referred'});
});

test('older snapshots without the hearing field still read the actions', () => {
  assert.equal(assessHearing({actions: ['Considered in public hearing']}).label, 'Heard');
  assert.equal(assessHearing({actions: ['Left pending in committee']}).label, 'Heard');
  assert.equal(assessHearing({hearing: 'none', actions: ['Testimony taken in committee']}).label, 'No hearing yet');
  assert.equal(assessHearing({actions: ['Scheduled for public hearing on . . .', 'No action taken in committee']}).label, 'Scheduled');
  assert.equal(assessHearing({hearing: 'bogus', actions: ['Scheduled for public hearing on . . .']}).label, 'Scheduled');
});

test('the last few 89R wordings that used to fall to Other', () => {
  const la = t => lastActionInfo({last_action: t}).key;
  assert.equal(la('06/20/2025 E See remarks for effective date'), 'law');
  assert.equal(la('03/10/2025 H Referred directly to subcommittee by chair'), 'referred');
  assert.equal(la('05/14/2025 E Filed with the Secretary of State'), 'secretary');
});
