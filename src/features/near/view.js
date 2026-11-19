// Near you (#local): the visitor's House member and Senator, their bills, and bills naming the county or city. Location
// stays in this browser. Redraws go through core/router.js; app.js passes the follow button.
import {state} from '../../core/state.js';
import {timeoutSignal, httpError} from '../../core/net.js';
import {cleanNear, NEAR_KEY, placeFromPoint, censusPoint, censusUrl, countyDistricts, membersFor, billsByMember, areaFor, gazetteer, areaReasons} from '../../geo.js';
import {writeJson} from '../../core/storage.js';
import {esc, $} from '../../core/dom.js';
import {memberHref, billHref} from '../../core/links.js';
import {memberTitle, tenurePill, memberNameHtml} from '../members/names.js';
import {tenureTag, newestFirst, lastActionInfo, openLinkHtml} from '../../taxonomy.js';
import {safeHref, unique} from '../../core/format.js';
import {topicStyle} from '../home/rows.js';
import {renderContent} from '../../core/router.js';

export const NEAR_FILES={house:'./data/geo/house.json',senate:'./data/geo/senate.json',counties:'./data/geo/counties.json',tables:'./data/geo/districts.json'};
const NEAR_NOTICE='Your location is used once, in this browser, to find your districts. Only the district numbers and county are saved on this device; nothing is sent to this site.';
const ADDRESS_NOTICE='Looking up an address sends the address you type to the US Census Bureau’s geocoder (census.gov) to get its map coordinates. This site never receives or stores it.';
let nearLoading=null;
// The maps can finish loading while someone is typing district numbers or an address; keep what they typed.
const NEAR_INPUTS=['near-house-num','near-senate-num','near-address'];
function keepTyping(render){
  const typed=Object.fromEntries(NEAR_INPUTS.map(id=>[id,document.getElementById(id)?.value||'']));
  const focus=document.activeElement?.id,open=document.querySelector('.near-address')?.open;
  render();
  for(const [id,value] of Object.entries(typed)){const el=document.getElementById(id);if(el&&value)el.value=value}
  if(open){const d=document.querySelector('.near-address');if(d)d.open=true}
  if(NEAR_INPUTS.includes(focus))document.getElementById(focus)?.focus();
}
function loadNearGeo(){
  if(state.nearGeo||nearLoading)return nearLoading;
  nearLoading=Promise.all(Object.entries(NEAR_FILES).map(async([k,url])=>{
    const r=await fetch(url,{signal:timeoutSignal(15000)});if(!r.ok)throw httpError(r);return [k,await r.json()];
  })).then(parts=>{
    const geo=Object.fromEntries(parts);
    if(geo.tables?.format!=='texas-bill-districts-v1'||!Array.isArray(geo.house?.features))throw Error('Unrecognized district files');
    state.nearGeo=geo;state.nearError='';
  }).catch(error=>{state.nearError='District maps could not be loaded; try again later.';console.warn('Near you data unavailable',error.message)})
    .finally(()=>{nearLoading=null;if(state.view==='local')keepTyping(renderContent)});
  return nearLoading;
}
export function saveNear(near){
  state.near=cleanNear(near,state.nearGeo?.tables);state.nearPick=null;state.nearShow={members:5,area:5};
  if(state.near)writeJson(NEAR_KEY,state.near);else{try{localStorage.removeItem(NEAR_KEY)}catch{}}
  renderContent();
}
function setNearFromPoint(lon,lat,accuracy,source){
  const p=placeFromPoint(state.nearGeo,lon,lat,{accuracy});
  if(p.error){state.nearBusy='';state.nearError='That location is outside Texas, so it has no Texas House or Senate district.';renderContent();return}
  state.nearBusy='';state.nearError='';saveNear({...p,source});
}
export function nearLocate(){
  if(!navigator.geolocation){state.nearError='This browser cannot share a location; choose your county instead.';renderContent();return}
  state.nearBusy='Finding your location…';state.nearError='';renderContent();
  navigator.geolocation.getCurrentPosition(pos=>setNearFromPoint(pos.coords.longitude,pos.coords.latitude,pos.coords.accuracy,'location'),
    err=>{state.nearBusy='';state.nearError=err.code===1?'Location permission was declined. Choose your county or enter your districts instead.':'Your location could not be found. Choose your county or enter your districts instead.';renderContent()},
    {enableHighAccuracy:false,timeout:15000,maximumAge:600000});
}
export function nearAddress(address){
  address=String(address||'').trim();
  if(address.length<6){state.nearError='Enter a street address, city and ZIP code.';renderContent();return}
  const name=`nearCensus${Date.now()}`,script=document.createElement('script');
  const done=()=>{delete window[name];script.remove();clearTimeout(timer)};
  const timer=setTimeout(()=>{done();state.nearBusy='';state.nearError='The address lookup did not answer. Try again, or choose your county.';renderContent()},15000);
  window[name]=reply=>{done();const point=censusPoint(reply);
    if(!point){state.nearBusy='';state.nearError='The Census geocoder found no match for that address. Check the spelling, or choose your county.';renderContent();return}
    setNearFromPoint(point.lon,point.lat,0,'address')};
  script.onerror=()=>{done();state.nearBusy='';state.nearError='The address lookup could not be reached. Choose your county instead.';renderContent()};
  state.nearBusy='Looking up the address…';state.nearError='';renderContent();
  script.src=censusUrl(address,name);document.head.appendChild(script);
}
function nearSetupMarkup(){
  const t=state.nearGeo?.tables;
  const pick=state.nearPick,choices=pick?countyDistricts(t,pick):null;
  const opt=(v,label,sel)=>`<option value="${esc(v)}"${sel?' selected':''}>${esc(label)}</option>`;
  const counties=t?Object.keys(t.counties):[];
  const districtSelect=(chamber,list)=>list.length>1?`<label>${chamber==='house'?'Texas House district':'Texas Senate district'}<select id="near-${chamber}-pick">${list.map(d=>opt(d.district,`District ${d.district} · ${Math.round(d.share*100)}% of ${pick} County`)).join('')}</select></label>`:'';
  return `<div class="subpage-card near-setup">
    <h3>Find your legislators</h3><p class="near-notice">${esc(NEAR_NOTICE)}</p>
    ${state.nearBusy?`<p class="near-busy" role="status">${esc(state.nearBusy)}</p>`:''}${state.nearError?`<p class="near-error" role="alert">${esc(state.nearError)}</p>`:''}
    <div class="near-ways">
      <div class="near-way"><h4>Use my location</h4><p>Your browser asks first.</p><button class="primary-button" id="near-locate"${t?'':' disabled'}>Use my location</button></div>
      <div class="near-way"><h4>Choose your county</h4><label>County<select id="near-county"${t?'':' disabled'}>${opt('','Select a county',!pick)}${counties.map(c=>opt(c,c,c===pick)).join('')}</select></label>
        ${choices?`${districtSelect('house',choices.house)}${districtSelect('senate',choices.senate)}<button class="primary-button" id="near-county-use">Use ${esc(pick)} County</button>${choices.house.length>1||choices.senate.length>1?'<p class="near-hint">Your county has more than one district. Pick yours, or use your location or address to be sure.</p>':''}`:''}</div>
      <div class="near-way"><h4>Enter your districts</h4><div class="near-numbers"><label>House<input id="near-house-num" inputmode="numeric" maxlength="3" placeholder="1–150"></label><label>Senate<input id="near-senate-num" inputmode="numeric" maxlength="2" placeholder="1–31"></label></div><button class="outline-button" id="near-numbers-use">Use these districts</button></div>
    </div>
    <details class="near-address"><summary>Look up an address instead (optional)</summary><p class="near-notice">${esc(ADDRESS_NOTICE)}</p><form id="near-address-form" autocomplete="off"><input id="near-address" maxlength="200" placeholder="Street address, city, ZIP" aria-label="Street address, city and ZIP code"><button class="outline-button" type="submit"${t?'':' disabled'}>Look up</button></form></details>
  </div>`;
}
function memberCard(chamber,district,followButton){
  const title=chamber==='house'?'Texas House':'Texas Senate';
  if(!district)return `<div class="near-member"><small>${title}</small><strong>District not set</strong></div>`;
  const people=membersFor(state.roster,chamber,district);
  if(!people.length)return `<div class="near-member"><small>${title} · District ${esc(district)}</small><strong>No member listed yet</strong><p><a class="text-link" href="https://capitol.texas.gov/Members/Members.aspx?Chamber=${chamber==='house'?'H':'S'}" target="_blank" rel="noopener noreferrer">Check Texas Legislature Online ↗</a></p></div>`;
  return people.map(m=>`<div class="near-member"><small>${title} · District ${esc(district)}</small><strong>${m.code?`<a class="text-link" href="${esc(memberHref(m.code))}">${esc(memberTitle(m))}</a>`:esc(memberTitle(m))}</strong><p>${tenurePill(m)} ${esc(m.party||'Party not recorded')}${tenureTag(m)?` · ${esc(tenureTag(m).detail)}`:''}</p>${m.code?`<p>${followButton(m)}</p><a class="text-link" href="${esc(memberHref(m.code))}">All their bills →</a> `:''}${safeHref(m.links?.tlo)?`<a class="text-link" href="${esc(safeHref(m.links.tlo))}" target="_blank" rel="noopener noreferrer">Texas Legislature Online ↗</a>`:''}</div>`).join('');
}
export function nearData(){
  const near=state.near,geo=state.nearGeo;
  const members=[...membersFor(state.roster,'house',near.house),...membersFor(state.roster,'senate',near.senate)];
  const byBill=new Map();
  for(const m of members)for(const {bill,role} of billsByMember(state.bills,m)){
    const entry=byBill.get(bill.id)||{bill,notes:[]};entry.notes.push({member:m,role});byBill.set(bill.id,entry);
  }
  const area=geo?areaFor(near,geo.tables):null,gaz=geo?gazetteer(geo.tables):null;
  const local=area?state.bills.map(bill=>({bill,notes:(areaReasons(bill,area,gaz)||[]).map(r=>r.text)})).filter(x=>x.notes.length):[];
  const order=(a,b)=>newestFirst(a.bill,b.bill);
  return {members:[...byBill.values()].sort(order),local:local.sort(order),area,
    statewide:state.bills.filter(b=>(b.locations||[]).some(l=>l.kind==='statewide')).length};
}
// Ceremonial resolutions (memorials, "Waco Day at the Capitol") fold into one row so the bills that change law stand out.
const CEREMONIAL=/^(in memory of|recognizing|commemorating|congratulating|honoring|memorializing|welcoming|celebrating)\b/i;
const isCeremonial=b=>/^(HR|SR|HCR|SCR)\d/.test(b.id)&&CEREMONIAL.test(String(b.title||''));
// A place note says where a bill names this area; one that only repeats the single county adds nothing.
function placeNote(note,area){
  const city=/^Names (.+?) \((.+) County\)$/.exec(note);
  if(city)return city[1];
  const county=/^Names (.+) County$/.exec(note);
  return county&&area?.counties?.length<=1?'':note.replace(/^Names /,'');
}
export function nearRow({bill:b,notes},opts={}){
  const last=lastActionInfo(b),brief=typeof b.headline==='string'&&b.headline?b.headline:'';
  const who=opts.showWho?notes.filter(n=>typeof n!=='string').map(n=>`${memberNameHtml(n.member,`${n.member.chamber==='house'?'Rep.':'Sen.'} ${n.member.display_name}`)} · ${esc(n.role)}`):
    notes.filter(n=>typeof n!=='string'&&n.role!=='Author').map(n=>esc(n.role));
  const places=unique(notes.filter(n=>typeof n==='string').map(n=>placeNote(n,opts.area)).filter(Boolean));
  const meta=[...who.map(w=>`<span class="near-who">${w}</span>`),...places.map(x=>`<span class="tag near-place">${esc(x)}</span>`),
    ...b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`),last.label!=='Filed'?`<span class="tag">${esc(last.label)}</span>`:''].join('');
  return `<article class="near-row" data-bill-id="${esc(b.id)}"${topicStyle(b.topics)}><p class="near-row-head">${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)} ${brief?`<span class="near-brief">${esc(brief)}</span> <span class="ai-badge" title="Written by Luna, the AI model that reads each bill’s full text; not official.">AI</span>`:openLinkHtml(b.id,billHref(b.id),'bill-title-link',b.title)}</p>${brief?`<p class="near-caption" title="${esc(b.title)}">${esc(b.title)}</p>`:''}${meta?`<div class="near-meta">${meta}</div>`:''}</article>`;
}
function nearList(key,rows,empty,opts={}){
  const main=rows.filter(r=>!isCeremonial(r.bill)),fold=rows.filter(r=>isCeremonial(r.bill));
  const limit=state.nearShow?.[key]||5;
  const list=main.length?`<div class="near-rows">${main.slice(0,limit).map(r=>nearRow(r,opts)).join('')}</div>${main.length>limit?`<button class="text-link near-more" data-near-more="${key}">Show all ${main.length}</button>`:''}`:fold.length?'':`<p class="review-empty">${empty}</p>`;
  const folded=fold.length?`<details class="near-resolutions"><summary>${fold.length} ${fold.length===1?'resolution':'resolutions'} honoring local people and places</summary><div class="near-rows">${fold.map(r=>nearRow(r,opts)).join('')}</div></details>`:'';
  return list+folded;
}
export function nearMarkup({followButton}){
  const head=`<div class="section-head"><div><div class="section-overline">NEAR YOU</div><h2>Your legislators and local bills</h2></div><span class="subtitle">Texas House and Senate districts for the 90th Legislature</span></div>`;
  if(!state.nearGeo&&!state.nearError)loadNearGeo();
  if(!state.near)return head+nearSetupMarkup();
  const n=state.near,d=nearData();
  const how={location:'from your location',address:'from the address you looked up',county:'from your county',district:'from the districts you entered'}[n.source];
  const where=[n.house?`House District ${n.house}`:null,n.senate?`Senate District ${n.senate}`:null,n.county?`${n.county} County`:null].filter(Boolean).join(' · ');
  const areaLabel=d.area?.exact?`${n.county} County`:d.area?.counties.length?`your district's ${d.area.counties.length===1?'county':`counties (${d.area.counties.join(', ')})`}`:'your area';
  // Who filed it only needs saying when both of your legislators have bills here.
  const authors=new Set(d.members.flatMap(x=>x.notes.map(note=>note.member)));
  const count=k=>`<span class="near-count">${k}</span>`;
  return `<div class="info-callout near-summary"><div><strong>${esc(where)}</strong> <span>${esc(how)}</span>${n.near?`<p class="near-hint">${n.source==='county'?`${esc(n.county)} County has more than one district, so these are the ones you picked. Check with your location, address or the official lookup.`:'You are close to a district line, so this may be the neighboring district. Check with your address or the official lookup.'}</p>`:''}</div><div class="tools-row"><button class="outline-button" id="near-change">Change</button><button class="outline-button" id="near-forget">Forget on this device</button></div></div>
    <div class="near-members">${memberCard('house',n.house,followButton)}${memberCard('senate',n.senate,followButton)}</div>
    <section class="near-group"><h3>Filed by your legislators ${count(d.members.length)}</h3>${nearList('members',d.members,'No bills by your legislators in this snapshot yet.',{showWho:authors.size>1})}</section>
    <section class="near-group"><h3>Bills that name ${esc(areaLabel)} ${count(d.local.length)}</h3><details class="near-how"><summary>How matching works</summary><p>A bill is listed when its full-text review names a county or city here, or its caption names the county. Bills written for areas by population size are not matched yet. ${d.statewide.toLocaleString()} reviewed bills apply statewide and are not listed here.</p></details>${nearList('area',d.local,'No bill names this area yet.',{area:d.area})}</section>
    <p class="near-hint">Official check: <a class="text-link" href="https://wrm.capitol.texas.gov/home" target="_blank" rel="noopener noreferrer">Who Represents Me? (Texas Legislative Council) ↗</a></p>`;
}
