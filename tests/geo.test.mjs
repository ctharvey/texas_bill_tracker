import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {areaFor, areaReasons, billsByMember, followedBills, censusPoint, censusUrl, cleanNear, countyDistricts, gazetteer, locate,
  membersFor, placeFromPoint, resolvePlace} from '../src/geo.js';
import {attachMembers} from '../src/taxonomy.js';

const read = name => JSON.parse(readFileSync(new URL(`../data/${name}`, import.meta.url), 'utf8'));
const geo = {house: read('geo/house.json'), senate: read('geo/senate.json'), counties: read('geo/counties.json'),
  tables: read('geo/districts.json')};
const roster = read('members.json');

test('the Capitol is in House 49, Senate 14, Travis County', () => {
  // Expected values from the Legislative Council's plan reports (Capitol grounds: HD 49, SD 14).
  const p = placeFromPoint(geo, -97.7404, 30.2747);
  assert.deepEqual([p.house, p.senate, p.county], ['49', '14', 'Travis']);
});

test('other known points', () => {
  // City halls; districts checked against TLC report 125 (each city's districts) and report 150 (county).
  const cases = [
    [-106.4870, 31.7587, 'El Paso'],   // El Paso City Hall
    [-95.3698, 29.7604, 'Harris'],     // downtown Houston
    [-101.8552, 33.5779, 'Lubbock'],   // Lubbock
    [-97.3964, 27.8006, 'Nueces'],     // Corpus Christi
  ];
  for (const [lon, lat, county] of cases) {
    const p = placeFromPoint(geo, lon, lat);
    assert.equal(p.county, county, `${lon},${lat}`);
    assert.ok(Object.keys(geo.tables.counties[county].house).includes(p.house), `${county}: house ${p.house}`);
    assert.ok(Object.keys(geo.tables.counties[county].senate).includes(p.senate), `${county}: senate ${p.senate}`);
  }
});

test('a point outside Texas is refused, never matched to the nearest district', () => {
  assert.deepEqual(placeFromPoint(geo, -90.07, 29.95), {error: 'outside'});  // New Orleans
  assert.deepEqual(placeFromPoint(geo, -104.6, 33.0), {error: 'outside'});  // New Mexico, inside the box check
});

test('a point on a district line is flagged near', () => {
  // Midpoint of a shared House edge: take two adjacent coordinates of a district's outline.
  const ring = geo.house.features.find(f => String(f.properties.district) === '49').geometry;
  const coords = (ring.type === 'Polygon' ? ring.coordinates : ring.coordinates[0])[0];
  const [a, b] = [coords[10], coords[11]];
  const hit = locate(geo.house, 'district', (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 200);
  assert.ok(hit && hit.near);
});

test('county table: Travis spans seven House districts; an unsplit county has one at 100%', () => {
  const travis = countyDistricts(geo.tables, 'Travis');
  assert.deepEqual(travis.house.map(d => d.district).sort((a, b) => a - b), ['19', '46', '47', '48', '49', '50', '51']);
  assert.deepEqual(countyDistricts(geo.tables, 'Lee').house, [{district: '17', share: 1}]);
  assert.equal(countyDistricts(geo.tables, 'Nowhere'), null);
});

test('saved location keeps district numbers and a known county only', () => {
  assert.deepEqual(cleanNear({house: '49', senate: 14, county: 'Travis', source: 'location', lat: 30.2, lon: -97.7,
    address: '1100 Congress'}, geo.tables), {house: '49', senate: '14', county: 'Travis', source: 'location', near: false});
  assert.equal(cleanNear({house: '151', senate: '0'}, geo.tables), null);
  assert.equal(cleanNear({house: '5', county: 'Atlantis'}, geo.tables).county, null);
});

test('members for a district; a Senate district with no listed member gives none, not a guess', () => {
  const house = membersFor(roster, 'house', '49');
  assert.equal(house.length, 1);
  const known = new Set(Object.values(roster.members).filter(m => m.chamber === 'senate').map(m => m.district));
  const empty = Array.from({length: 31}, (_, i) => String(i + 1)).find(d => !known.has(d));
  if (empty) assert.deepEqual(membersFor(roster, 'senate', empty), []);
  assert.deepEqual(membersFor(roster, 'senate', '32'), []);
  assert.deepEqual(membersFor(roster, 'senate', null), []);
});

test('bills by member match the roster entry, by chamber', () => {
  const [member] = membersFor(roster, 'house', '49');
  const name = member.display_name;
  const bills = [
    {id: 'HB1', chamber: 'House', authors: [name], coauthors: [], sponsors: [], cosponsors: []},
    {id: 'SB1', chamber: 'Senate', authors: ['Someone'], coauthors: [], sponsors: [name], cosponsors: []},
    {id: 'SB2', chamber: 'Senate', authors: [name], coauthors: [], sponsors: [], cosponsors: []},  // a senator, not them
    {id: 'HB2', chamber: 'House', authors: ['Other'], coauthors: [name], sponsors: [], cosponsors: []},
  ].map(b => attachMembers(b, roster));
  assert.deepEqual(billsByMember(bills, member).map(x => [x.bill.id, x.role]), [['HB1', 'Author'], ['SB1', 'Sponsor'], ['HB2', 'Coauthor']]);
});

test('followed bills merge members per bill, skip unknown codes, and follow the given order', () => {
  const [rep] = membersFor(roster, 'house', '49');
  const sen = Object.values(roster.members).find(m => m.chamber === 'senate' && m.code && m.display_name !== rep.display_name);
  const bills = [
    {id: 'HB1', chamber: 'House', filed: 1, authors: [rep.display_name], coauthors: [], sponsors: [sen.display_name], cosponsors: []},
    {id: 'SB1', chamber: 'Senate', filed: 3, authors: [sen.display_name], coauthors: [], sponsors: [], cosponsors: []},
    {id: 'HB2', chamber: 'House', filed: 2, authors: ['Nobody'], coauthors: [], sponsors: [], cosponsors: []},
  ].map(b => attachMembers(b, roster));
  const rows = followedBills(bills, roster, [rep.code, sen.code, 'A99999'], (a, b) => b.filed - a.filed);
  assert.deepEqual(rows.map(r => [r.bill.id, r.notes.map(n => `${n.member.code}:${n.role}`)]),
    [['SB1', [`${sen.code}:Author`]], ['HB1', [`${rep.code}:Author`, `${sen.code}:Sponsor`]]]);
  assert.deepEqual(followedBills(bills, roster, []), []);
  assert.deepEqual(followedBills(bills, null, [rep.code]), []);
});

test('place names resolve exactly: "Austin" is the city, "Austin County" the county', () => {
  const gaz = gazetteer(geo.tables);
  assert.deepEqual(resolvePlace('Austin', gaz).counties.includes('Travis'), true);
  assert.deepEqual(resolvePlace('Austin County', gaz), {county: 'Austin'});
  assert.deepEqual(resolvePlace('Travis County', gaz), {county: 'Travis'});
  assert.deepEqual(resolvePlace('City of San Antonio', gaz).place, 'San Antonio');
  assert.equal(resolvePlace('Texas-Mexico border', gaz), null);
  assert.equal(resolvePlace('Austn', gaz), null);
});

test('bills naming the area, with reasons; statewide bills never match', () => {
  const gaz = gazetteer(geo.tables);
  const travis = {counties: ['Travis'], exact: true};
  const reasons = b => areaReasons(b, travis, gaz)?.map(r => r.text) ?? null;
  assert.deepEqual(reasons({locations: [{kind: 'named_place', name: 'Austin'}]}), ['Names Austin (Travis County)']);
  assert.deepEqual(reasons({locations: [{kind: 'named_place', name: 'Travis County'}], caption: 'Relating to Travis County.'}),
    ['Names Travis County']);
  assert.equal(reasons({locations: [{kind: 'statewide', name: 'Texas'}]}), null);
  assert.equal(reasons({locations: [{kind: 'defined_area', name: 'Travis County'}]}), null);  // defined areas deferred
  assert.equal(reasons({locations: [{kind: 'named_place', name: 'Austin County'}]}), null);
  assert.deepEqual(areaReasons({caption: 'Relating to a hospital district in El Paso County.'},
    {counties: ['El Paso'], exact: true}, gaz).map(r => r.text), ['Names El Paso County']);
});

test('without a known county, the area is every county of the House district', () => {
  assert.deepEqual(areaFor({house: '17', senate: null, county: null}, geo.tables).counties,
    Object.keys(geo.tables.districts.house['17'].counties).sort());
  assert.deepEqual(areaFor({house: '17', county: 'Lee'}, geo.tables), {counties: ['Lee'], exact: true});
});

test('census lookup URL and reply parsing', () => {
  const url = new URL(censusUrl('1100 Congress Ave, Austin TX', 'cb1'));
  assert.equal(url.origin + url.pathname, 'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress');
  assert.equal(url.searchParams.get('format'), 'jsonp');
  assert.deepEqual(censusPoint({result: {addressMatches: [{coordinates: {x: -97.74, y: 30.27}, matchedAddress: 'A'}]}}),
    {lon: -97.74, lat: 30.27, matched: 'A'});
  assert.equal(censusPoint({result: {addressMatches: []}}), null);
});

test('a member by roster code, across both chambers; unknown codes give null', async () => {
  const {memberByCode} = await import('../src/geo.js');
  const [rep] = membersFor(roster, 'house', '49');
  assert.equal(memberByCode(roster, rep.code).display_name, rep.display_name);
  const senator = Object.values(roster.members).find(m => m.chamber === 'senate');
  assert.equal(memberByCode(roster, senator.code).chamber, 'senate');
  assert.equal(memberByCode(roster, 'A0000'), null);
  assert.equal(memberByCode(roster, null), null);
});
