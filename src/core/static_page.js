// The static page a server-rendered shell put on screen, and whether the app should keep it until its view is ready.
// Pure functions: no DOM access, so the node tests can import this file directly.
const BILL_ID = /^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9]\d{0,4}$/;
const MEMBER_CODE = /^A\d{3,5}$/;
const ABOUT = new Set(['method', 'saving', 'data']);  // About pages with a static copy (view names).
const AGENCY_ID = /^[a-z0-9][a-z0-9-]{0,40}$/;
const TOPIC_SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

export function parseStaticView(value){
  const text=typeof value==='string'?value:'';
  const at=text.indexOf(':');
  if(at<0)return null;
  const kind=text.slice(0,at),key=text.slice(at+1);
  if(kind==='bill')return BILL_ID.test(key)?{kind,key}:null;
  if(kind==='member')return MEMBER_CODE.test(key)?{kind,key}:null;
  if(kind==='about')return ABOUT.has(key)?{kind,key}:null;
  if(kind==='page')return key==='home'||key==='today'?{kind,key}:null;
  if(kind==='agency')return AGENCY_ID.test(key)?{kind,key}:null;
  if(kind==='topic')return TOPIC_SLUG.test(key)?{kind,key}:null;
  if(kind==='law'||kind==='chapter')return key?{kind,key}:null;
  return null;
}

export function staticMatches(sv,p){
  if(!sv||!p)return false;
  if(sv.kind==='bill')return p.bill===sv.key;
  if(sv.kind==='member')return p.member===sv.key;
  if(sv.kind==='about'||sv.kind==='page')return p.view===sv.key;
  if(sv.kind==='agency')return p.agency===sv.key;
  if(sv.kind==='topic')return p.topic===sv.key;
  return p.statute===sv.key;
}

export function takeover(sv,{loaded,matches}){
  if(!sv)return 'none';
  if(!loaded)return 'keep';
  return 'replace';
}
