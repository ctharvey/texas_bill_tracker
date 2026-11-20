// Member page (#member?code=A1234): one legislator, their district and their bills by role. Reuses Near you's district
// tables and rows.
import {state} from '../../core/state.js';
import {NEAR_FILES, nearRow} from '../near/view.js';
import {timeoutSignal, httpError} from '../../core/net.js';
import {ROLES, billsByMember, memberByCode, countiesOf} from '../../geo.js';
import {newestFirst, memberSummary, tenureTag} from '../../taxonomy.js';
import {esc} from '../../core/dom.js';
import {safeHref} from '../../core/format.js';
import {tenurePill} from './names.js';
import {renderContent} from '../../core/router.js';
import {followButton, memberFeedHref} from '../follows/view.js';

// Only the district tables (about 240 KB), not the maps; reused when Near you already loaded everything.
let tablesLoading=null;
function districtTables(){
  if(state.nearGeo?.tables)return state.nearGeo.tables;
  if(state.geoTables)return state.geoTables;
  if(!tablesLoading)tablesLoading=fetch(NEAR_FILES.tables,{signal:timeoutSignal(15000)})
    .then(r=>{if(!r.ok)throw httpError(r);return r.json()})
    .then(t=>{if(t?.format!=='texas-bill-districts-v1')throw Error('Unrecognized district tables');state.geoTables=t})
    .catch(error=>console.warn('District tables unavailable',error.message))
    .finally(()=>{if(state.view==='member')renderContent()});
  return null;
}
export function memberData(m){
  const groups=Object.fromEntries(ROLES.map(([,role])=>[role,[]]));
  for(const {bill,role} of billsByMember(state.bills,m))groups[role].push({bill,notes:[]});
  for(const rows of Object.values(groups))rows.sort((a,b)=>newestFirst(a.bill,b.bill));
  return groups;
}
function memberList(role,rows){
  const limit=state.memberShow?.[role]||30;
  return `${rows.slice(0,limit).map(nearRow).join('')}${rows.length>limit?`<button class="outline-button" data-member-more="${esc(role)}">Show 30 more · showing ${limit} of ${rows.length}</button>`:''}`;
}
export function memberMarkup(){
  const head=title=>`<div class="section-head"><div><div class="section-overline">MEMBER</div><h2>${title}</h2></div><span class="subtitle">90th Legislature</span></div>`;
  if(!state.roster)return `${head('Member roster unavailable')}<div class="info-callout callout-warn">The member roster could not be loaded, so member pages are not available right now. Try again later.</div>`;
  const m=memberByCode(state.roster,state.memberCode);
  if(!m)return `${head('Member not found')}<div class="info-callout callout-warn">No member of the 90th Legislature has the code ${state.memberCode?`<strong>${esc(state.memberCode)}</strong>`:'in this address'}. Find members from a bill's authors or from <a class="text-link" href="/near-you" data-view="local">Near you</a>.</div>`;
  const tables=districtTables();
  const counties=m.district&&tables?countiesOf(tables,m.chamber,m.district):[];
  const split=c=>Object.keys(tables?.counties?.[c]?.[m.chamber]||{}).length>1;
  const chamber=m.chamber==='house'?'Texas House':'Texas Senate';
  const groups=memberData(m),total=Object.values(groups).reduce((n,rows)=>n+rows.length,0);
  const links=[[m.links?.tlo,'Texas Legislature Online'],[m.links?.lrl,'Legislative Reference Library']].filter(([u])=>safeHref(u))
    .map(([u,label])=>`<a class="text-link" href="${esc(safeHref(u))}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`).join(' · ');
  const where=m.district?`${chamber} · District ${esc(m.district)}`:`${chamber} · district not recorded yet`;
  const countyLine=!m.district?'':tables?(counties.length?`<p>${counties.map(c=>`${esc(c)} County${split(c)?' (part)':''}`).join(', ')}</p>`:''):'<p class="near-hint">Loading the district’s counties…</p>';
  const sections=ROLES.map(([,role])=>[role,groups[role]]).filter(([,rows])=>rows.length)
    .map(([role,rows])=>`<section class="today-group"><h3>${role} <span>${rows.length}</span></h3>${memberList(role,rows)}</section>`).join('');
  const roleNote=m.chamber==='house'?'Representatives author and coauthor House bills and sponsor Senate bills that reach the House.':'Senators author and coauthor Senate bills and sponsor House bills that reach the Senate.';
  return `<div class="info-callout member-profile"><div><small>${where}</small><strong>${esc(memberSummary(m))}</strong>${tenureTag(m)?`<p>${tenurePill(m)} ${esc(tenureTag(m).detail)}</p>`:''}${countyLine}${links?`<p>${links}</p>`:''}</div><div class="tools-row">${followButton(m)}<a class="outline-button" data-feed href="${esc(memberFeedHref(m.code))}" target="_blank" rel="noopener noreferrer">RSS feed</a></div></div>
    <p class="near-hint">${total?`${total} ${total===1?'bill':'bills'} in this snapshot. `:''}${roleNote} Sponsors and cosponsors are listed once a bill crosses chambers, so early in the session most bills show authors only.</p>
    ${sections||'<p class="review-empty">No bills by this member in this snapshot yet.</p>'}`;
}
