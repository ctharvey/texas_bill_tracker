import test from 'node:test';
import assert from 'node:assert/strict';
import {nextRunAt, runState, passRows, billKey, lookup} from '../src/features/review/model.js';
import {reviewProgress, reviewSummary} from '../src/taxonomy.js';

const at = s => Date.parse(s);
const NOW = at('2026-11-13T15:40:00Z');

test('the next run is the next :35 past the hour', () => {
  assert.equal(nextRunAt(at('2026-11-13T15:20:00Z')), at('2026-11-13T15:35:00Z'));
  assert.equal(nextRunAt(at('2026-11-13T15:35:00Z')), at('2026-11-13T16:35:00Z'));
  assert.equal(nextRunAt(at('2026-11-13T23:50:00Z')), at('2026-11-14T00:35:00Z'));
});

test('run state: running with its pass and minutes used; waiting; stale; quiet; idle; unavailable', () => {
  const base = {running: true, updated_at: '2026-11-13T15:39:00Z', run_started_at: '2026-11-13T15:22:00Z', pass: 'entities'};
  assert.deepEqual(
    (({kind, pass, minutesUsed}) => ({kind, pass, minutesUsed}))(runState(base, NOW)),
    {kind: 'running', pass: 'entities', minutesUsed: 18});
  const waiting = runState({...base, waiting_until: '2026-11-13T15:45:00Z'}, NOW);
  assert.equal(waiting.kind, 'waiting');
  assert.equal(waiting.waitingUntil, at('2026-11-13T15:45:00Z'));
  assert.equal(runState({...base, updated_at: '2026-11-13T13:00:00Z'}, NOW).kind, 'stale');
  const stale = runState({...base, updated_at: '2026-11-13T13:00:00Z'}, NOW);
  assert.equal(stale.pass, null);  // a stopped worker is not "in" a pass
  assert.equal(runState({running: false, updated_at: '2026-11-13T14:00:00Z'}, NOW).kind, 'quiet');
  assert.equal(runState({running: false, updated_at: '2026-11-13T15:30:00Z'}, NOW).kind, 'idle');
  assert.equal(runState(null, NOW).kind, 'unavailable');
  // A status file from before passes were published: running, but no pass and no start time.
  const old = runState({running: true, updated_at: '2026-11-13T15:39:00Z'}, NOW);
  assert.deepEqual([old.kind, old.pass, old.minutesUsed], ['running', null, null]);
});

const ids = ['HB1', 'HB2', 'HB3', 'HB4', 'HB5', 'HB6'];
const status = {running: true, updated_at: '2026-11-13T15:39:00Z', in_progress: ['HB2'], reviewed: ['HB1', 'HB3'],
  retry: ['HB3'], failed: {HB4: 'download', HB5: 'extract'},
  passes: {entities: {due: 40, checked: 3}, topics: {due: 506, checked: 0}}, pass: 'entities'};
const summary = reviewSummary(reviewProgress(ids, status, []));

test('pass rows: full review counts bills not started; later passes use the status counts; unknown stays null', () => {
  const rows = passRows(status, summary, runState(status, NOW));
  assert.deepEqual(rows.map(r => [r.key, r.due, r.checked, r.now, r.known]), [
    ['review', 1, null, false, true],
    ['entities', 40, 3, true, true],
    ['topics', 506, 0, false, true],
    ['audit', null, null, false, false],
  ]);
});

test('bill numbers as typed', () => {
  for (const text of ['HB474', 'hb 474', 'H.B. 474', ' hb0474 ']) assert.equal(billKey(text), 'HB474', text);
  assert.equal(billKey('SJR 9'), 'SJR9');
  assert.equal(billKey('water'), null);
  assert.equal(billKey(''), null);
});

test('lookup gives each bill exactly one state', () => {
  const state = text => lookup(text, summary, ids)?.state;
  assert.equal(state('HB1'), 'reviewed');
  assert.equal(state('HB2'), 'active');
  assert.equal(state('HB3'), 'questions');
  assert.equal(state('HB4'), 'notext');
  assert.equal(state('HB5'), 'failed');
  assert.match(lookup('HB5', summary, ids).label, /extract/);
  assert.equal(state('HB6'), 'notstarted');
  assert.equal(state('HB999'), 'unknown');
  assert.equal(lookup('water', summary, ids), null);
});
