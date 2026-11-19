// Companion bills in the app: the cached index, the agency-through-a-companion lists, the group watch button and the
// bill page's companion section.
import {state} from '../../core/state.js';
import {esc} from '../../core/dom.js';
import {lastActionInfo} from '../../taxonomy.js';
import {companionIndex, agencyViaCompanion} from './model.js';
import {memberNameHtml, rosterMember} from '../members/names.js';
import {shortDate} from '../../core/format.js';

export const companionCache={bills:null,index:new Map()};
export function companionsOf(id){
  if(companionCache.bills!==state.bills){companionCache.bills=state.bills;companionCache.index=companionIndex(state.bills)}
  return companionCache.index.get(id)||[];
}
export const relationText=c=>c.relation?c.relation.toLowerCase():'companion';
// With an agency filter, bills whose companion carries the agency are listed too (marked on the card).
const viaCache={bills:null,maps:new Map()};  // agency id -> bills tagged only through a companion
export function agencyVia(agency=state.agency){
  if(!agency)return new Map();
  if(viaCache.bills!==state.bills){companionsOf('');Object.assign(viaCache,{bills:state.bills,maps:new Map()})}
  if(!viaCache.maps.has(agency))viaCache.maps.set(agency,agencyViaCompanion(state.bills,agency,companionCache.index));
  return viaCache.maps.get(agency);
}
// One control for a bill and its companions: watches every one, or unwatches all when all are already watched.
// The watchlist stays a plain list of ids, so sync, share links and export are unchanged.
export function groupWatchButton(ids){
  const n=ids.filter(id=>state.watch.has(id)).length,all=n===ids.length;
  const label=all?`★ Watching all ${ids.length}`:n?`☆ Watch all ${ids.length} (${n} watched)`:`☆ Watch all ${ids.length}`;
  return `<button class="companion-watch${all?' on':''}" data-watch-group="${esc(ids.join(','))}" aria-pressed="${all}" title="${all?'Remove these companion bills from your watchlist':'Add every bill in this companion group to your watchlist'}">${label}</button>`;
}

export function companionBlock(b){
  const list=companionsOf(b.id);
  if(!list.length)return '';
  const byId=new Map(state.bills.map(x=>[x.id,x]));
  const rows=list.map(c=>{const other=byId.get(c.id);const last=other?lastActionInfo(other):null;
    return `<div class="companion-row"><div><strong>${other?`<button class="text-link companion-open" data-open="${esc(c.id)}">${esc(c.number)}</button>`:esc(c.number)}</strong> <span class="chamber-pill">${esc(c.id.startsWith('H')?'House':'Senate')}</span> <small>${esc(relationText(c))}${c.author?` · by ${memberNameHtml(rosterMember(c.id.startsWith('H')?'house':'senate',c.author),c.author)}`:''}</small><p>${other?esc(other.title):'Not in this snapshot yet; it appears here within about an hour of the Legislative Council publishing it.'}</p></div>${last?`<span class="tag action-tag action-${esc(last.key)}">${esc(last.label)}${last.date?` · ${esc(shortDate(last.date))}`:''}</span>`:''}</div>`}).join('');
  const groupIds=[b.id,...list.filter(c=>byId.has(c.id)).map(c=>c.id)];
  return `<section class="drawer-section companion-section"><div class="companion-section-head"><h3>Companion ${list.length===1?'bill':'bills'} (${list.length})</h3>${groupIds.length>1?groupWatchButton(groupIds):''}</div><p>A companion is a matching bill, usually filed in the other chamber so the same proposal can move in both at once. “Identical”, “similar” and “duplicate” are the Legislative Council's description.</p>${rows}</section>`;
}
