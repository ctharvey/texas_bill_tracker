import test from 'node:test';
import assert from 'node:assert/strict';
import {AREAS, AREA_GROUPS, AREA_BY_ID, subjectMatches, areaMatch, billAreas, inArea, areaCounts, topAgencies} from '../src/features/areas/model.js';
import {POLICY_AREAS} from '../src/taxonomy.js';
import {parseHash, buildHash, cleanFilters, searchName, FILTER_DEFAULTS} from '../src/prefs.js';

const bill = (over = {}) => ({id: 'HB1', title: '', caption: '', subjects: [], agencies: [], actions: [], topics: [], ...over});

test('areas have unique ids, a group, an audience and stateless keyword patterns', () => {
  assert.equal(AREAS.length, 29);
  assert.equal(new Set(AREAS.map(a => a.id)).size, AREAS.length);
  assert.deepEqual(AREA_GROUPS, ['Government technology & operations', 'People & communities', 'Services, professions & money']);
  for (const a of AREAS) {
    assert.match(a.id, /^[a-z]+(-[a-z]+)*$/, a.id);
    assert.ok(a.name && a.group && a.audience && a.subjects.length, a.id);
    assert.ok(a.keywords instanceof RegExp && a.keywords.flags === 'i', a.id);
  }
});

test('areas are separate from the policy areas Luna is asked about', () => {
  const policy = new Set(POLICY_AREAS.map(t => t.name));
  for (const a of AREAS) assert.ok(!policy.has(a.name), a.name);
});

test('a subject rule is one exact subject, or a whole family when it ends in -- or an em dash', () => {
  assert.ok(subjectMatches('INTERNET', 'INTERNET'));
  assert.ok(!subjectMatches('INTERNET', 'INTERNET SERVICE PROVIDERS'));
  assert.ok(subjectMatches('Purchasing--', 'Purchasing--State'));
  assert.ok(!subjectMatches('Purchasing--', 'Purchasing'));
  assert.ok(subjectMatches('Sunset\u2014', 'Sunset\u2014Required Reviews'));
  assert.ok(subjectMatches('Taxation--Property-', 'Taxation--Property-Exemptions'));
});

test('a bill is in an area by its official subject or by a keyword in its title or caption', () => {
  const bySubject = bill({subjects: ['CYBER COMMAND, TEXAS']});
  assert.deepEqual(areaMatch(bySubject, AREA_BY_ID.get('cybersecurity-it')), {subjects: ['CYBER COMMAND, TEXAS'], keyword: false});
  assert.ok(inArea(bySubject, 'cybersecurity-it'));
  const byKeyword = bill({caption: 'relating to state agency procurement of information technology'});
  assert.ok(inArea(byKeyword, 'procurement'));
  assert.ok(inArea(byKeyword, 'cybersecurity-it'));
  assert.deepEqual(billAreas(bill({caption: 'relating to the designation of a state flower'})), []);
});

test('a bill can be in several areas, listed in area order, and the bill object is left as it was', () => {
  const b = bill({subjects: ['BROADBAND NETWORKS', 'GUARDIANS & WARDS']});
  const before = JSON.stringify(b);
  assert.deepEqual(billAreas(b), ['cybersecurity-it', 'disability', 'older-texans', 'rural-texas']);
  assert.equal(JSON.stringify(b), before);
  assert.deepEqual(billAreas(null), []);
});

test('area counts give each area its bills and those with an action in the last 7 days', () => {
  const today = '2026-11-14';
  const bills = [
    bill({id: 'HB1', subjects: ['FOSTER CARE'], last_action: 'Filed', last_action_date: '2026-11-08'}),
    bill({id: 'HB2', subjects: ['FOSTER CARE'], last_action: 'Filed', last_action_date: '2026-11-07'}),
    bill({id: 'HB3', subjects: ['FOSTER CARE'], last_action: 'Filed', last_action_date: '2026-11-15'})];
  const row = areaCounts(bills, today).find(r => r.area.id === 'children-youth');
  assert.equal(row.count, 3);
  assert.equal(row.moved, 1);  // 11-08 is day 7; 11-07 is too old; 11-15 is after today
  assert.equal(areaCounts(bills, today).length, AREAS.length);
  assert.equal(areaCounts(bills, null).find(r => r.area.id === 'children-youth').moved, 0);
});

test('top agencies count each bill once per agency and skip the ones asked', () => {
  const bills = [
    bill({agencies: [{id: 'dir'}, {id: 'dir'}, {id: 'all-state-agencies'}]}),
    bill({agencies: [{id: 'dir'}, {id: 'comptroller'}]})];
  assert.deepEqual(topAgencies(bills, 5, new Set(['all-state-agencies'])), [{id: 'dir', count: 2}, {id: 'comptroller', count: 1}]);
});

test('the area filter round-trips through the address, remembered filters and saved-search names', () => {
  assert.equal(FILTER_DEFAULTS.area, '');
  const hash = buildHash('all', {...FILTER_DEFAULTS, area: 'privacy', chamber: 'Senate'});
  assert.equal(hash, '#all?area=privacy&chamber=Senate');
  assert.equal(parseHash(hash).filters.area, 'privacy');
  assert.equal(buildHash('all', FILTER_DEFAULTS), '#all');
  assert.deepEqual(cleanFilters({area: 'privacy'}), {area: 'privacy'});
  assert.equal(searchName({area: 'privacy', chamber: 'Senate'}, id => id, id => AREA_BY_ID.get(id).name), 'Privacy & personal data \u00b7 Senate');
});
