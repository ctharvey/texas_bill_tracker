import test from 'node:test';
import assert from 'node:assert/strict';
import {autoTagBill,assessHearing,authorInfluence,officialUrl,AGENCY_NAME} from '../src/taxonomy.js';

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
