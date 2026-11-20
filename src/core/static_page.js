// The static page a server-rendered shell put on screen, and whether the app should keep it until its view is ready.
// Pure functions: no DOM access, so the node tests can import this file directly.
const BILL_ID = /^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9]\d{0,4}$/;

export function parseStaticView(value){
  const text=typeof value==='string'?value:'';
  const at=text.indexOf(':');
  if(at<0)return null;
  const kind=text.slice(0,at),key=text.slice(at+1);
  if(kind==='bill')return BILL_ID.test(key)?{kind,key}:null;
  if(kind==='law'||kind==='chapter')return key?{kind,key}:null;
  return null;
}

export function staticMatches(sv,p){
  if(!sv||!p)return false;
  return sv.kind==='bill'?p.bill===sv.key:p.statute===sv.key;
}

export function takeover(sv,{loaded,matches}){
  if(!sv)return 'none';
  if(!loaded)return 'keep';
  return 'replace';
}
