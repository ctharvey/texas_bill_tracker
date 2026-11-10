import test from 'node:test';
import assert from 'node:assert/strict';
import {lastActionInfo} from '../src/taxonomy.js';

const la = last_action => lastActionInfo({last_action, last_action_date: '2026-11-09'});

test('parses the TLO date and chamber prefix', () => {
  const info = la('11/09/2026 H Filed');
  assert.deepEqual([info.key, info.label, info.chamber, info.date, info.text], ['filed', 'Filed', 'House', '2026-11-09', 'Filed']);
  assert.equal(la('2/3/2027 S Referred to Business & Commerce').date, '2027-02-03');
  assert.equal(la('06/20/2027 E Signed by the Governor').chamber, 'Governor');
});

test('classifies the common steps along the legislative path', () => {
  const cases = {
    '02/10/2027 H Referred to Public Health': 'referred',
    '03/01/2027 H Scheduled for public hearing on . . .': 'scheduled',
    '03/05/2027 H Considered in public hearing': 'heard',
    '03/05/2027 H Left pending in committee': 'heard',
    '03/20/2027 H Reported favorably w/o amendment(s)': 'reported',
    '03/22/2027 H Placed on General State Calendar': 'calendar',
    '04/02/2027 H Passed to engrossment': 'floor',
    '04/03/2027 H Read 3rd time': 'floor',
    '04/03/2027 H Passed': 'passed',
    '04/04/2027 H Reported engrossed': 'passed',
    '04/07/2027 S Received from the House': 'other_chamber',
    '05/30/2027 E Sent to the Governor': 'governor',
    '06/20/2027 E Signed by the Governor': 'law',
    '09/01/2027 E Effective on 9/1/27': 'law',
    '06/20/2027 E Vetoed by the Governor': 'vetoed',
    '04/09/2027 S Withdrawn from schedule': 'withdrawn',
    '11/09/2026 S Received by the Secretary of the Senate': 'filed',
    '11/09/2026 H Something unusual happened': 'other',
  };
  for (const [text, key] of Object.entries(cases)) assert.equal(la(text).key, key, text);
});

test('falls back to the recorded date and plain text when there is no prefix', () => {
  const info = lastActionInfo({last_action: 'Filed', filed_at: '2026-11-09'});
  assert.equal(info.key, 'filed');
  assert.equal(info.date, '2026-11-09');
  assert.equal(info.chamber, null);
  assert.equal(lastActionInfo({}).key, 'filed');
});

test('rank orders progress so stage sorting puts further bills first', () => {
  const order = ['11/09/2026 H Filed', '02/10/2027 H Referred to Public Health', '03/05/2027 H Considered in public hearing',
    '04/03/2027 H Passed', '06/20/2027 E Signed by the Governor'].map(t => la(t).rank);
  assert.deepEqual([...order].sort((a, b) => a - b), order);
});
