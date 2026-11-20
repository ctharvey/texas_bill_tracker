import test from 'node:test';
import assert from 'node:assert/strict';
import {parseLocation, parseHash, buildUrl, buildHash, isAppPath} from '../src/prefs.js';
import {agencyBills, topicName, topicBills} from '../src/features/groups/model.js';
import {SCOPE_AGENCY_ID} from '../src/taxonomy.js';

test('agency and topic addresses round-trip', () => {
  assert.equal(buildUrl('agency', {}, {agency: 'tceq'}), '/agency/tceq');
  assert.equal(buildUrl('topic', {}, {topic: 'energy-and-utilities'}), '/topic/energy-and-utilities');
  assert.equal(buildUrl('agency', {}, {agency: 'tceq', list: ['HB5']}), '/agency/tceq#list=HB5');
  assert.equal(parseLocation('/agency/TCEQ/', '').agency, 'tceq');
  assert.equal(parseLocation('/agency/tceq', '').view, 'agency');
  assert.equal(parseLocation('/topic/Taxes', '').topic, 'taxes');
  assert.equal(parseLocation('/topic/taxes', '').agency, null);
  assert.equal(parseLocation('/agency/tceq', '#list=HB5,SB2').list.join(), 'HB5,SB2');
  assert.equal(parseLocation('/agency/-bad', '').agency, null);
  assert.equal(parseLocation('/topic/a/b', '#today').view, 'today');
  assert.equal(buildUrl('agency', {}, {agency: null}), '/#agency');
  assert.equal(buildUrl('topic', {}, {topic: 'Bad Slug'}), '/#topic');
});

test('agency and topic hashes round-trip', () => {
  assert.equal(buildHash('agency', {}, {agency: 'tceq'}), '#agency?id=tceq');
  assert.equal(buildHash('topic', {}, {topic: 'taxes'}), '#topic?slug=taxes');
  assert.equal(parseHash('#agency?id=TCEQ').agency, 'tceq');
  assert.equal(parseHash('#topic?slug=taxes').topic, 'taxes');
  assert.equal(parseHash('#all?id=tceq').agency, null);
  assert.equal(parseHash('#topic?slug=taxes').agency, null);
  assert.equal(parseHash('#agency?id=Bad%20Id').agency, null);
  assert.equal(parseHash('#all').topic, null);
});

test('agency and topic paths are app paths', () => {
  for (const path of ['/agency/tceq', '/agency/tceq/', '/topic/taxes']) assert.equal(isAppPath(path), true, path);
  for (const path of ['/agency/', '/topic/a/b', '/agency/-x']) assert.equal(isAppPath(path), false, path);
});

const bill = (id, date, extra = {}) => ({id, last_action_date: date, last_action: '', agencies: [], topics: [], ...extra});

test('agencyBills keeps bills naming the agency, newest action first, ties by higher number', () => {
  const bills = [bill('HB1', '2026-02-01', {agencies: [{id: 'tceq'}]}), bill('HB9', '2026-03-01', {agencies: [{id: 'tceq'}]}),
    bill('HB5', '2026-03-01', {agencies: [{id: 'tceq'}]}), bill('SB2', '2026-03-01', {agencies: [{id: 'tdi'}]}),
    bill('HB7', '2026-04-01', {agencies: [{id: SCOPE_AGENCY_ID}]})];
  assert.deepEqual(agencyBills(bills, 'tceq').map(b => b.id), ['HB9', 'HB5', 'HB1']);
  assert.deepEqual(agencyBills(bills, SCOPE_AGENCY_ID), []);
  assert.deepEqual(agencyBills(bills, 'none'), []);
});

test('topicName maps a slug to a policy area, and topicBills selects by name', () => {
  assert.equal(topicName('energy-and-utilities'), 'Energy & utilities');
  assert.equal(topicName('taxes'), 'Taxes');
  assert.equal(topicName('nope'), null);
  assert.equal(topicName(''), null);
  const bills = [bill('HB1', '2026-02-01', {topics: ['Taxes']}), bill('SB3', '2026-02-01', {topics: ['Taxes', 'Education']}), bill('HB2', '2026-05-01', {topics: ['Education']})];
  assert.deepEqual(topicBills(bills, 'Taxes').map(b => b.id), ['HB1', 'SB3']);
  assert.deepEqual(topicBills(bills, 'Education').map(b => b.id), ['HB2', 'SB3']);
});
