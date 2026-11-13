import test from 'node:test';
import assert from 'node:assert/strict';
import {attachMembers, authorshipParty, memberSummary, authorInfluence, PARTY_FILTERS, partyFilterMatches} from '../src/taxonomy.js';

const member = (chamber, name, party, extra = {}) => ({chamber, display_name: name, full_name: name, party,
  district: '1', service: party ? [{chamber, district: '1', years: '2015 - 2027', party: party[0]}] : [],
  years_served: party ? 12 : null, first_year: party ? 2015 : null, new_to_chamber: !party, links: {tlo: 'https://capitol.texas.gov/x'}, ...extra});
const roster = {format: 'texas-bill-members-v1', members: {
  'house|Bucy': member('house', 'Bucy', 'Democratic'),
  'house|Landgraf': member('house', 'Landgraf', 'Republican'),
  'house|Moody': member('house', 'Moody', 'Democratic'),
  'house|Bailey': member('house', 'Bailey', null),
  'senate|Zaffirini': member('senate', 'Zaffirini', 'Democratic'),
  'senate|Bucy': member('senate', 'Bucy', 'Republican'),
}};
const bill = (id, authors, coauthors = []) => attachMembers({id, authors, coauthors, sponsors: [], cosponsors: null}, roster);

test('primary Democratic author tints blue and Republican tints red', () => {
  assert.equal(authorshipParty(bill('HB1', ['Bucy', 'Moody'])).tint, 'dem');
  assert.equal(authorshipParty(bill('HB2', ['Landgraf'])).label, 'Republican author');
});

test('authors spanning both parties tint purple, including via a coauthor', () => {
  assert.equal(authorshipParty(bill('HB3', ['Bucy', 'Landgraf'])).tint, 'bipartisan');
  const p = authorshipParty(bill('HB4', ['Landgraf'], ['Moody', 'Bailey']));
  assert.equal(p.tint, 'bipartisan');
  assert.equal(p.label, 'Bipartisan authors · party data incomplete');
  assert.match(p.detail, /Coauthors: 1 Democratic, 1 unknown/);
});

test('members resolve by exact chamber and display name, never by surname alone', () => {
  // Senate bill: a House "Bucy" must not lend his party to an unknown Senate author.
  assert.equal(authorshipParty(bill('SB1', ['Bucy'])).tint, 'rep');
  assert.equal(authorshipParty(bill('SB2', ['Landgraf'])).tint, 'unknown');
  assert.equal(authorshipParty(bill('HB5', ['Bucy, John'])).label, 'Author party unknown');
});

test('unknown primary author stays neutral even with known coauthors of one party', () => {
  assert.equal(authorshipParty(bill('HB6', ['Bailey'], ['Moody'])).tint, 'unknown');
  assert.equal(authorshipParty({id: 'HB7', authors: ['Bucy']}).tint, 'unknown');  // No roster loaded.
});

test('sponsors use the other chamber and do not affect the authorship tint', () => {
  const b = attachMembers({id: 'SB9', authors: ['Zaffirini'], coauthors: [], sponsors: ['Landgraf'], cosponsors: []}, roster);
  assert.equal(b.people.sponsors[0].member.party, 'Republican');
  assert.equal(authorshipParty(b).tint, 'dem');
});

test('roster tenure feeds author influence only when no curated profile exists', () => {
  assert.equal(authorInfluence(bill('HB8', ['Bucy'])).label, 'Senior author');
  const curated = attachMembers({id: 'HB9', authors: ['Bucy'], author_profile: {seniority_years: 3}}, roster);
  assert.equal(curated.author_profile.seniority_years, 3);
  assert.equal(authorInfluence(bill('HB10', ['Bailey'])).key, 'newcomer');  // member-elect with no record: a first term
});

test('author influence and the member tenure tag use one measure: time in the current chamber', () => {
  // 14 House years, now a first-term senator: all-service counting called this an established member.
  const moved = {senate: member('senate', 'Hall', 'Republican', {service: [{chamber: 'house', years: '2013 - 2027'}], years_served: 14})};
  const b = attachMembers({id: 'SB20', authors: ['Hall'], coauthors: [], sponsors: [], cosponsors: null},
    {format: 'texas-bill-members-v1', members: {'senate|Hall': moved.senate}});
  const i = authorInfluence(b);
  assert.deepEqual([i.key, i.label], ['newcomer', 'First-term author']);
  assert.match(i.factors.join(' | '), /New to the Senate · 14 years in the House/);
  assert.ok(!i.factors.some(f => /Approximately/.test(f)));  // the all-service figure is not shown beside it
  const order = ['leadership', 'chair', 'senior', 'average', 'newcomer', 'unknown'];
  const levels = order.map(k => authorInfluence({author_profile: {leadership_position: k === 'leadership' ? 'Speaker' : '',
    committee_chair: k === 'chair', seniority_years: {senior: 20}[k] || 0}}).level);
  assert.deepEqual([levels[0], levels[1], levels[2]], [5, 4, 3]);
});

test('election-based party is labelled as the unofficial 2026 ballot', () => {
  const elect = member('house', 'Bord', null, {party: 'Democratic', party_basis: 'election', district: '126'});
  assert.equal(memberSummary(elect), 'Democratic (2026 ballot, unofficial) · HD 126 · member-elect; no prior service on record');
});

test('member summary is explicit about missing records', () => {
  assert.equal(memberSummary(null), 'Not matched to the 90th Legislature roster');
  assert.match(memberSummary(roster.members['house|Bailey']), /member-elect; no prior service on record/);
  assert.equal(memberSummary(roster.members['house|Bucy']), 'Democratic · HD 1 · 12 years served · since 2015');
});

test('tenure tags count time in the current chamber: first term, 12+ years, other chamber reported only', async () => {
  const {tenureTag} = await import('../src/taxonomy.js');
  const m = (chamber, ...spans) => ({chamber, service: spans.map(([c, years]) => ({chamber: c, years}))});
  assert.equal(tenureTag(m('house')).key, 'newcomer');                                   // member-elect, no record
  assert.deepEqual([m('house'), m('house', ['house', '2025 - 2027']), m('house', ['house', '2015 - 2027'])]
    .map(x => tenureTag(x).label), ['First term', 'Mid-tenure', 'Senior']);
  assert.equal(tenureTag(m('house', ['house', '2025 - 2027'])).key, 'average');            // second term starts
  assert.equal(tenureTag(m('senate', ['senate', '2025 - 2029'])).key, 'newcomer');         // still in a first 4-year term
  assert.equal(tenureTag(m('senate', ['senate', '2023 - 2027'])).key, 'average');
  assert.equal(tenureTag(m('house', ['house', '2015 - 2027'])).key, 'senior');             // 12 years
  assert.equal(tenureTag(m('house', ['house', '2016 - 2027'])).key, 'average');            // 11 years
  const moved = tenureTag(m('senate', ['house', '2013 - 2027']));                          // representative now senator
  assert.deepEqual([moved.key, moved.years, moved.otherYears, moved.detail], ['newcomer', 0, 14, 'New to the Senate · 14 years in the House']);
  assert.equal(tenureTag(m('house', ['house', '2019 - 2029'])).years, 8);                  // counted only to the 2027 start
  assert.equal(tenureTag(m('house', ['house', 'unknown'])), null);                        // unreadable years: no tag
  assert.equal(tenureTag(null), null);
});

test('the party filter keeps bills by their authorship tint', () => {
  const bills = [bill('HB1', ['Bucy', 'Moody']), bill('HB2', ['Landgraf']), bill('HB3', ['Bucy', 'Landgraf']),
    bill('HB4', ['Landgraf'], ['Moody']), bill('HB6', ['Bailey'], ['Moody']), {id: 'HB7', authors: ['Bucy']}];
  const keep = value => bills.filter(b => partyFilterMatches(b, value)).map(b => b.id);
  assert.deepEqual(Object.keys(PARTY_FILTERS), ['Republican', 'Democratic', 'Bipartisan']);
  assert.deepEqual(keep('Republican'), ['HB2']);
  assert.deepEqual(keep('Democratic'), ['HB1']);
  assert.deepEqual(keep('Bipartisan'), ['HB3', 'HB4']);  // a Democratic coauthor makes HB4 bipartisan, not Republican
  assert.equal(keep('').length, bills.length);            // no filter keeps unknown-party bills too
  assert.deepEqual(keep('Whig'), []);                     // an unknown value from a link matches nothing
});
