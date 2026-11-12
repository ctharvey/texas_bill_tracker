import assert from 'node:assert/strict';
import test from 'node:test';
import {reviewModel,pageSegments} from '../src/review.js';
const bundle = () => ({format:'texas-bill-review-v1',bill_id:'HB1',
    document:{bill_id:'HB1',session:'90R',pages:['😀 Board must act.'],version:'introduced'},
    result:{bill_id:'HB1',summary:{text:'A summary.'}},
    validation:{errors:[],verified_citations:[{claim:'summary',status:'resolved',
        parts:[{page:1,start:2,end:7,quote:'Board'}]}]}});
test('Unicode offsets preserve the full source and exact highlighted excerpt',()=>{
    const model=reviewModel(bundle()), segments=pageSegments(model.pages[0],model.annotations,1);
    assert.equal(segments.map(s=>s.text).join(''),'😀 Board must act.');
    assert.equal(segments.find(s=>s.ids.length).text,'Board');
});
test('Untrusted mismatched citations cannot produce highlights',()=>{
    const bad=bundle();bad.validation.verified_citations[0].parts[0].quote='<script>alert(1)</script>';
    assert.throws(()=>reviewModel(bad),/does not match/);
    bad.validation.verified_citations[0].parts[0].quote='Board';bad.document.bill_id='HB2';
    assert.throws(()=>reviewModel(bad),/not a complete/);
});
test('Overlapping citations keep all reasons without duplicating source text',()=>{
    const b=bundle();b.result.agencies=[{name:'Board',explanation:'Direct duty.',impact:'direct'}];
    b.validation.verified_citations.push({claim:'agencies:0',status:'resolved',parts:[{page:1,start:2,end:12,quote:'Board must'}]});
    const model=reviewModel(b),segments=pageSegments(model.pages[0],model.annotations,1);
    assert.equal(segments.map(s=>s.text).join(''),b.document.pages[0]);
    assert.equal(segments.find(s=>s.text==='Board').ids.length,2);
});
