import test from 'node:test';
import assert from 'node:assert/strict';
import {POLICY_AREAS} from '../src/taxonomy.js';
import {TOPIC_HUES, topicHue, topicStyle, plainTitle, daysUntil} from '../src/features/home/rows.js';

test('every policy area has its own colour, and nothing else does', () => {
  const names = POLICY_AREAS.map(p => p.name);
  assert.deepEqual(Object.keys(TOPIC_HUES).sort(), [...names].sort());
  assert.equal(new Set(Object.values(TOPIC_HUES)).size, names.length);
  for (const name of names) assert.ok(Number.isInteger(topicHue(name)) && topicHue(name) >= 0 && topicHue(name) < 360, name);
  for (const bad of ['Nope', '', null, undefined, 'toString', 'constructor']) assert.equal(topicHue(bad), null);
});

test('a row takes its main topic colour, or none', () => {
  assert.equal(topicStyle(['Education', 'Taxes']), ` style="--topic-h:${TOPIC_HUES.Education}"`);
  assert.equal(topicStyle(['Not a topic']), '');
  assert.equal(topicStyle([]), '');
  assert.equal(topicStyle(undefined), '');
});

test('the row text is the plain summary, else the caption without "Relating to"', () => {
  assert.equal(plainTitle({headline: ' Lets cities lower speed limits. ', title: 'Relating to speed.'}), 'Lets cities lower speed limits.');
  assert.equal(plainTitle({headline: '', title: 'Relating to the authority of a municipality.'}), 'Authority of a municipality.');
  assert.equal(plainTitle({title: 'relating to fees.'}), 'Fees.');
  assert.equal(plainTitle({title: 'An act about water.'}), 'An act about water.');
  assert.equal(plainTitle({}), '');
});

test('days until the session counts whole days and stops at zero', () => {
  assert.equal(daysUntil('2026-11-17', '2027-01-12'), 56);
  assert.equal(daysUntil('2027-01-12', '2027-01-12'), 0);
  assert.equal(daysUntil('2027-02-01', '2027-01-12'), 0);
  assert.equal(daysUntil('bad', '2027-01-12'), 0);
});
