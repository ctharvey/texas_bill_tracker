import test from 'node:test';
import assert from 'node:assert/strict';
import {autoTagBill,assessHearing,authorInfluence,officialUrl,AGENCY_NAME,memberNames,snapshotAgeHours,matchAuthorProfile,SCOPE_AGENCY_ID} from '../src/taxonomy.js';

test('tags all relevant detected agencies instead of picking one',()=>{
  const b=autoTagBill({title:'Medicaid, voter registration and public school changes',caption:'Changes to Medicaid eligibility, voter registration and school districts'});
  const ids=b.agencies.map(a=>a.id);
  assert.ok(ids.includes('hhsc'));
  assert.ok(ids.includes('sos'));
  assert.ok(ids.includes('tea'));
  assert.equal(b.agencies.find(a=>a.id==='hhsc').relationship,'related');
});

test('names explicitly cited agencies direct, does not invent a numeric probability',()=>{
  const b=autoTagBill({title:'Texas Education Agency rulemaking',caption:'The Texas Education Agency may adopt rules'});
  assert.equal(b.agencies.find(a=>a.id==='tea').relationship,'direct');
  assert.equal(assessHearing({status:'Filed'}).label,'Not rated');
  assert.equal(assessHearing({status:'Filed'}).level,0);
});

test('committee referral and scheduled hearing are distinguished',()=>{
  assert.equal(assessHearing({committee:'Elections'}).label,'Referred');
  assert.equal(assessHearing({committee:'Elections',hearing_date:'2027-03-02'}).label,'Scheduled');
  assert.equal(assessHearing({actions:['Public hearing held on March 2']}).label,'Heard');
});

test('author prominence is unassessed without verified role evidence',()=>{
  assert.equal(authorInfluence({author:'Unknown'}).label,'Unassessed');
  assert.equal(authorInfluence({author_profile:{committee_chair:true}}).label,'High institutional access');
});

test('official link points to regular 90th session',()=>{
  assert.equal(officialUrl({number:'HB 164'}),'https://capitol.texas.gov/BillLookup/History.aspx?LegSess=90R&Bill=HB164');
  assert.ok(AGENCY_NAME.hhsc);
});

test('Texas State Board of Public Accountancy is indexed and matched to CPA regulation',()=>{
  assert.equal(AGENCY_NAME.tsbpa,'Texas State Board of Public Accountancy');
  const inferred=autoTagBill({title:'CPA licensing and examination requirements'});
  assert.equal(inferred.agencies.find(a=>a.id==='tsbpa').relationship,'related');
  const named=autoTagBill({title:'Duties of the Texas State Board of Public Accountancy'});
  assert.equal(named.agencies.find(a=>a.id==='tsbpa').relationship,'direct');
});

test('all-state-agencies scope is explicit for statewide duties, not individual agency rules',()=>{
  const broad=autoTagBill({title:'Cybersecurity standards',caption:'Each state agency must comply with statewide security requirements'});
  assert.equal(broad.agencies.find(a=>a.id==='all-state-agencies').relationship,'direct');
  assert.ok(broad.impacts.includes('Cross-agency scope'));
  const narrow=autoTagBill({title:'Texas Education Agency shall adopt rules for public schools'});
  assert.equal(narrow.agencies.some(a=>a.id==='all-state-agencies'),false);
  const limited=autoTagBill({title:'Audit requirements for certain state agencies'});
  assert.equal(limited.agencies.some(a=>a.id==='all-state-agencies'),false);
});

test('possible cross-agency compliance is flagged without false certainty',()=>{
  const result=autoTagBill({title:'Records retention standards for state agencies'});
  assert.equal(result.agencies.find(a=>a.id==='all-state-agencies').relationship,'related');
});


test('member lists preserve names, remove duplicates and support CSV pipes',()=>{
  assert.deepEqual(memberNames(' One | Two | One | '),['One','Two']);
  assert.deepEqual(memberNames(['One',' Two ',null,'One']),['One','Two']);
  assert.deepEqual(memberNames(undefined),[]);
  assert.deepEqual(memberNames(''),[]);
  assert.deepEqual(memberNames('Surname, Jr. | Other'),['Surname, Jr.','Other']);
});

test('snapshotAgeHours measures age and rejects bad timestamps',()=>{
  const now=Date.parse('2026-11-09T12:00:00Z');
  assert.equal(snapshotAgeHours('2026-11-09T06:00:00Z',now),6);
  assert.equal(snapshotAgeHours('2026-11-08T12:00:00Z',new Date(now)),24);
  assert.equal(snapshotAgeHours('2026-11-10T12:00:00Z',now),0);
  assert.equal(snapshotAgeHours('',now),null);
  assert.equal(snapshotAgeHours('not a date',now),null);
  assert.equal(snapshotAgeHours(undefined,now),null);
});

test('author profiles match by surname, first author, skipping ambiguous surnames',()=>{
  const profiles={'Judith Zaffirini':{id:1},'John Bucy III':{id:2},'Trey Martinez Fischer':{id:3},'Ann Smith':{id:4},'Bob Smith':{id:5}};
  assert.equal(matchAuthorProfile('Zaffirini',profiles).id,1);
  assert.equal(matchAuthorProfile('Bucy',profiles).id,2);
  assert.equal(matchAuthorProfile('Martinez Fischer',profiles).id,3);
  assert.equal(matchAuthorProfile('Fischer',profiles).id,3);
  assert.equal(matchAuthorProfile('Bucy | Zaffirini',profiles).id,2);
  assert.equal(matchAuthorProfile('Smith',profiles),undefined);
  assert.equal(matchAuthorProfile('Nobody',profiles),undefined);
  assert.equal(matchAuthorProfile('Zaffirini',null),undefined);
});

test('topic patterns use word boundaries',()=>{
  const topics=title=>autoTagBill({title}).topics;
  assert.ok(!topics('Relating to the legislative branch').includes('Agriculture'));
  assert.ok(!topics('Relating to syntax of rules').includes('Taxes'));
  assert.ok(!topics('Relating to taxi service').includes('Taxes'));
  assert.ok(topics('Relating to ranch land').includes('Agriculture'));
  assert.ok(topics('Relating to ranching').includes('Agriculture'));
  for(const t of ['tax','taxes','taxation'])assert.ok(topics(`Relating to ${t} rates`).includes('Taxes'));
  assert.ok(!autoTagBill({title:'Taxi permits'}).impacts.includes('Taxes & incentives'));
  assert.ok(autoTagBill({title:'Franchise tax'}).impacts.includes('Taxes & incentives'));
});

test('import coercion tolerates string tags and null actions',()=>{
  const b=autoTagBill({title:'x',topics:'Education; Taxes',agencies:'tea,hhsc',constituencies:'Teachers, Students'});
  assert.ok(b.topics.includes('Education')&&b.topics.includes('Taxes'));
  assert.ok(!b.topics.includes('E'));
  assert.deepEqual(b.agencies.filter(a=>a.id==='tea'||a.id==='hhsc').map(a=>a.id).sort(),['hhsc','tea']);
  assert.deepEqual(b.constituencies,['Teachers','Students']);
  assert.equal(assessHearing({actions:[null,'Public hearing held']}).label,'Heard');
  assert.equal(SCOPE_AGENCY_ID,'all-state-agencies');
});
