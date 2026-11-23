// Home: the dashboard. Search first, then what changed on your bills, the latest day's actions, hearings and reviews.
// Change and Today rows are shared with the review progress and Today pages; redraws go through core/router.js.
import {nextVisit, changedSince, newestReviewed} from './model.js';
import {readJson, visitKey, STORAGE_OK, writeJson} from '../../core/storage.js';
import {chicagoDate, openLinkHtml, lastActionInfo, groupByActionType, assessHearing} from '../../taxonomy.js';
import {esc, $} from '../../core/dom.js';
import {topicStyle, plainTitle, daysUntil} from './rows.js';
import {billHref} from '../../core/links.js';
import {state, runtime} from '../../core/state.js';
import {todayDay, realAgencies, agencyName} from '../../core/labels.js';
import {shortDate, dateText} from '../../core/format.js';
import {followedBills} from '../../geo.js';
import {searchCounts} from '../sync/lists.js';
import {buildUrl} from '../../prefs.js';
import {todayData} from '../today/view.js';
import {recentChanges, changeText} from '../review/updates.js';
import {areaCounts, AREA_GROUPS} from '../areas/model.js';
import {headlineLine} from '../explorer/view.js';
import {filerHtml} from '../members/names.js';
import {renderContent} from '../../core/router.js';

// The dashboard visit before this one: read, and today stamped, the first time the dashboard is drawn in this page
// load, so other pages never add the key. null on a first visit or without storage.
let visit=null;
function previousVisit(){
  if(!visit){visit=nextVisit(readJson(visitKey),chicagoDate(new Date()));if(STORAGE_OK)writeJson(visitKey,visit.store)}
  return visit.prev;
}

const HOME_ROWS=5,SESSION_START='2027-01-12';
// One line per bill: number, plain-language summary, and a short note (topic, action or review) on the right.
function compactRow(b,note=''){
  return `<article class="compact-row" data-bill-id="${esc(b.id)}"${topicStyle(b.topics)}>${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="compact-text">${openLinkHtml(b.id,billHref(b.id),'bill-title-link',plainTitle(b))}</span>${note?`<span class="compact-note" title="${esc(note)}">${esc(note)}</span>`:''}</article>`;
}
export function homeMarkup(){
  return `<div class="home-top"><form class="home-search" id="home-search-form" role="search"><label for="home-search">Search every bill</label><div class="home-search-row"><input id="home-search" name="query" maxlength="200" placeholder="Bill number, author, subject, agency or keyword…" autocomplete="off"><button class="primary-button" type="submit">Search</button></div><p class="tools-note">Or <a class="text-link" href="/explorer" data-view="all">browse all ${state.bills.length.toLocaleString()} bills</a>.</p></form>
    <div class="calendar-mini home-milestone"><div class="calendar-eyebrow">UPCOMING MILESTONE</div><div class="calendar-date">JAN 12 <span>2027</span></div><div class="calendar-desc">90th regular session convenes${daysUntil(todayDay(),SESSION_START)?` · in ${daysUntil(todayDay(),SESSION_START)} days`:''}</div><div class="calendar-progress"><span></span></div></div></div>
    <div class="home-grid">${homeCards()}</div>`;
}
// Redraws the dashboard's cards only, so a sync or watch change never clears what is typed in its search box.
// A kept static page stays as it is: without bills the cards would all read zero.
export function refreshHome(){if(runtime.keepStatic)return;const grid=$('.home-grid');if(grid)grid.innerHTML=homeCards();else renderContent()}
function homeCards(){
  const today=todayDay(),prev=previousVisit();
  const more=(href,view,label)=>`<a class="text-link home-more" href="${esc(href)}"${view?` data-view="${view}"`:''}>${label} →</a>`;
  const card=(title,count,body,order)=>`<section class="home-card home-o${order}"><h2>${title}${count?` <span>${count.toLocaleString()}</span>`:''}</h2>${body}</section>`;
  const datedRow=({bill,day})=>compactRow(bill,`${lastActionInfo(bill).label} · ${shortDate(day)}`);
  // Your bills: watched, and those of legislators you follow.
  const followed=state.roster&&state.follow.length?followedBills(state.bills,state.roster,state.follow).map(r=>r.bill):[];
  const mine=[...new Map([...state.bills.filter(b=>state.watch.has(b.id)),...followed].map(b=>[b.id,b])).values()];
  const changed=changedSince(mine,prev,today);
  const searches=state.searches.map(s=>({s,...searchCounts(s)})).filter(x=>x.fresh);
  const searchList=searches.length?`<ul class="home-searches">${searches.map(({s,fresh})=>`<li><a class="text-link" href="${esc(buildUrl('all',s.filters))}" data-search-open="${esc(s.id)}">${esc(s.name)}</a> · ${fresh.toLocaleString()} with new actions</li>`).join('')}</ul>`:'';
  const yours=!mine.length&&!state.searches.length
    ?`<p class="tools-note">Star bills, follow legislators or save a search, and what changes for them shows up here.</p>`
    :`${changed.length?changed.slice(0,HOME_ROWS).map(datedRow).join(''):`<p class="tools-note">No new actions on your ${mine.length.toLocaleString()} ${mine.length===1?'bill':'bills'}${prev?` since ${esc(dateText(prev))}`:''}.</p>`}${changed.length>HOME_ROWS?`<p class="tools-note">And ${(changed.length-HOME_ROWS).toLocaleString()} more on your <a class="text-link" href="/watchlist" data-view="watchlist">watchlist</a> and under <a class="text-link" href="/following" data-view="following">Following</a>.</p>`:''}${searchList}`;
  const yoursTitle=prev?`Since your last visit, ${esc(shortDate(prev))}`:'Latest on your bills';
  // The latest day with activity, as on the Today page (unfiltered by its topic chips).
  const {day,rows}=todayData();
  const types=groupByActionType(rows);
  const counts=types.length>1?`<p class="home-counts">${types.map(g=>`<span><strong>${g.rows.length.toLocaleString()}</strong> ${esc(g.label.toLowerCase())}</span>`).join('')}</p>`:'';
  const dayShown=rows.slice(0,HOME_ROWS+1),dayIds=new Set(dayShown.map(r=>r.bill.id));
  const dayBody=rows.length?`${counts}${dayShown.map(r=>compactRow(r.bill,r.bill.topics[0]||'')).join('')}${more('/today','today','The whole day, by topic')}`:'<p class="tools-note">No recorded activity yet.</p>';
  const hearings=state.bills.filter(b=>assessHearing(b).level===3);
  const hearingBody=hearings.length?hearings.slice(0,HOME_ROWS).map(b=>compactRow(b,lastActionInfo(b).label)).join('')+(hearings.length>HOME_ROWS?more(buildUrl('all',{outlook:'Scheduled'}),'','All scheduled hearings'):'')
    :'<p class="tools-note">No hearings are scheduled yet. Committees post them once the session is under way.</p>';
  // Luna's reviews: what changed in the last 24 hours, then the newest reviews; a bill shows once, and not at all
  // when the Today card already lists it.
  const lunaChanged=recentChanges(state.lunaUpdates,Date.now());
  const byId=new Map(state.bills.map(b=>[b.id,b]));
  const luna=new Map(lunaChanged.bills.filter(r=>byId.has(r.id)).map(r=>[r.id,{bill:byId.get(r.id),note:r.changes.length?changeText(r.changes[0]):''}]));
  for(const b of newestReviewed(state.bills).slice(0,20))if(!luna.has(b.id))luna.set(b.id,{bill:b,note:`Reviewed ${shortDate(b.luna.reviewed_at.slice(0,10))}`});
  const lunaRows=[...luna.values()].filter(r=>!dayIds.has(r.bill.id));
  const lunaBody=lunaRows.length?`${lunaChanged.bills.length?changeCounts(lunaChanged.counts):''}${lunaRows.slice(0,HOME_ROWS+1).map(r=>compactRow(r.bill,r.note)).join('')}${more('/review','review','Every review and change')}`
    :`<p class="tools-note">${state.lunaPending?'Loading Luna’s reviews…':'Luna has not reviewed any bills yet.'}</p>`;
  const tile=(n,label,href,view)=>href
    ?`<a class="stat-tile" href="${esc(href)}"${view?` data-view="${view}"`:''}><strong>${n.toLocaleString()}</strong><span>${label}</span></a>`
    :`<div class="stat-tile"><strong>${n.toLocaleString()}</strong><span>${label}</span></div>`;
  const stats=`<div class="home-stats">${tile(rows.length,day===today?'bills with action today':`bills with action ${esc(shortDate(day))}`,'/today','today')}${tile(state.lunaUpdates?lunaChanged.bills.length:'—','bills Luna reviewed or updated, last 24 hours','/review','review')}${tile(hearings.length,hearings.length===1?'hearing scheduled':'hearings scheduled',hearings.length?buildUrl('all',{outlook:'Scheduled'}):'','')}</div>`;
  // Two columns that do not share row heights, split so their lengths come out close on a typical day.
  // On a phone the columns dissolve and .home-oN puts the cards back in this order.
  return stats+`<div class="home-col">${card(yoursTitle,changed.length,yours,1)}${card(day===today?'Today at the Lege':`Most recent activity, ${esc(shortDate(day))}`,rows.length,dayBody,2)}</div>`
    +`<div class="home-col">${card("Luna's reviews",0,lunaBody,3)}${card('Upcoming hearings',hearings.length,hearingBody,4)}</div>${areasCard()}`;
}
// Browse by area: every reader area with its bills and how many moved this week, grouped by audience.
function areasCard(){
  const rows=areaCounts(state.bills,todayDay());
  const largest=Math.max(1,...rows.map(r=>r.count));
  const item=({area,count,moved})=>`<li>
    <a class="area-row" href="${esc(buildUrl('all',{area:area.id}))}">
      <span class="area-row-name">${esc(area.name)}</span>
      <span class="area-count">${count.toLocaleString()} ${count===1?'bill':'bills'}</span>
      <span class="area-track" aria-hidden="true"><i style="width:${100*count/largest}%"></i></span>
      ${moved?`<span class="area-moved">${moved.toLocaleString()} moved</span>`:''}
    </a></li>`;
  return `<section class="home-card home-areas"><h2>Browse by area</h2><p class="tools-note">Areas use the Legislature’s subject index. Bars compare bill counts across all areas. “Moved” means a bill had an action in the last 7 days.</p><div class="area-groups">${AREA_GROUPS.map(g=>`<div><h3>${esc(g)}</h3><ul class="area-list">${rows.filter(r=>r.area.group===g).map(item).join('')}</ul></div>`).join('')}</div></section>`;
}
// Luna change counts as one line, and bills with what changed for each (bills not in the snapshot are skipped).
export function changeCounts(counts){return `<p class="home-counts">${counts.map(c=>`<span><strong>${c.n.toLocaleString()}</strong> ${esc(c.label)}</span>`).join('')}</p>`}
export function changeRows(rows,limit){
  const byId=new Map(state.bills.map(b=>[b.id,b]));
  const shown=rows.filter(r=>byId.has(r.id));
  return `<div class="today-list">${shown.slice(0,limit).map(r=>todayRow({bill:byId.get(r.id),actions:r.changes.map(changeText)})).join('')}</div>${shown.length>limit?`<p class="tools-note">And ${(shown.length-limit).toLocaleString()} more.</p>`:''}`;
}

// `by`: also name who filed the bill (the Today page; member pages and Near you already say whose bills they are).
export function todayRow({bill:b,actions},{by=false}={}){
  const real=realAgencies(b);
  return `<article class="today-row" data-bill-id="${esc(b.id)}"${topicStyle(b.topics)}><div class="today-row-head">${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="chamber-pill">${esc(b.chamber)}</span>${openLinkHtml(b.id,billHref(b.id),'bill-title-link',b.title)}</div>${headlineLine(b,'card')}<div class="today-meta"><p class="today-action">${actions.map(esc).join(' · ')}</p>${by&&b.author?`<span class="today-by">by ${filerHtml(b)}</span>`:''}<div class="bill-tags">${b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}${real.slice(0,2).map(a=>`<span class="tag agency">${esc(agencyName(a.id).replace(/^Texas /,'').replace(/ Department of /,' · '))}</span>`).join('')}</div></div></article>`;
}
