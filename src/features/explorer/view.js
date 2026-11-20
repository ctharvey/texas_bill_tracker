// The explorer (#all, #watchlist): filters and their chips, the reader-area header, the results with companion groups,
// the wide-screen preview and each bill card. Matching is in model.js; redraws and the address save go through
// core/router.js.
import {SEARCH_FIELDS} from '../search/model.js';
import {state, runtime} from '../../core/state.js';
import {areaName, agencyName, todayDay, SORTS, realAgencies} from '../../core/labels.js';
import {sameFilters, buildUrl, cleanScope} from '../../prefs.js';
import {esc, $} from '../../core/dom.js';
import {AREA_GROUPS, AREAS, AREA_BY_ID, inArea, areaCounts, topAgencies, subjectLabels} from '../areas/model.js';
import {assessHearing, NO_HEARING, SCOPE_AGENCY_ID, POLICY_AREAS, PARTY_FILTERS, LAST_ACTION_TYPES, lastActionInfo, relatedFor, companionGroups, openLinkHtml, authorInfluence, authorshipParty, companionLabel} from '../../taxonomy.js';
import {unique, dateText, shortDate} from '../../core/format.js';
import {sharedBanner, watchTools} from '../watchlist/view.js';
import {options, agencySortButtons, agencyOptionsMarkup} from './controls.js';
import {filteredBills, reasonFor, lawKeysFor} from './model.js';
import {companionsOf, companionCache, relationText, groupWatchButton, agencyVia} from '../companions/view.js';
import {noticeSearch, TUMBLEWEED} from '../easter/view.js';
import {statuteHintMarkup, lawResults, lawResultsMarkup, lawChanged} from '../statutes/view.js';
import {billHref} from '../../core/links.js';
import {authorHtml, influencePill} from '../members/names.js';
import {renderContent, renderResults, persistState} from '../../core/router.js';

export const SEARCH_EXAMPLES=[...SEARCH_FIELDS.filter(f=>f.example).map(f=>f.example),'"minimum wage"'];
// ---- Filters (D6) ----
const MORE_FILTERS=['agency','party','outlook','action','onlyWatch'];
const moreActive=()=>MORE_FILTERS.filter(k=>Boolean(state[k])).length;
// Open when the reader opened it, or when one of its filters is set (an address can set them).
const moreFiltersOpen=()=>Boolean(state.moreFiltersOpen)||moreActive()>0;
const moreCountText=()=>moreActive()?` · ${moreActive()}`:'';
// Each set filter as [key, label]; a chip's × clears that one key.
function activeFilters(){
  return [['query',state.query&&`Search “${state.query}”`],['area',state.area&&`Area: ${areaName(state.area)}`],['topic',state.topic&&`Policy area: ${state.topic}`],['chamber',state.chamber],
    ['stage',state.stage&&`Stage: ${state.stage}`],['agency',state.agency&&`Agency: ${agencyName(state.agency)}`],['party',state.party&&`Party: ${state.party}`],
    ['outlook',state.outlook&&`Hearing: ${state.outlook}`],['action',state.action&&`Last action: ${state.action}`],['companion',state.companion&&'Has companion'],['onlyWatch',state.onlyWatch&&'Watched only']].filter(([,label])=>label);
}
function activeFiltersMarkup(){
  const set=activeFilters();
  if(!set.length)return '';
  const restored=state.view==='all'&&runtime.restoredFilters&&sameFilters(runtime.restoredFilters,state);
  return `${restored?'<span class="restored-note">Filters from your last visit:</span>':''}${set.map(([key,label])=>`<button type="button" class="filter-chip" data-clear-filter="${key}" aria-label="Remove filter: ${esc(label)}">${esc(label)} <span aria-hidden="true">×</span></button>`).join('')}<button type="button" class="text-button" id="clear-filters">Clear all</button>`;
}
// What to try when nothing matches: drop the filters, or search every bill for the same words.
function emptyNextSteps(){
  const filters=activeFilters().filter(([key])=>key!=='query');
  const steps=[filters.length?'<button type="button" class="outline-button" data-clear-all>Clear all filters</button>':'',
    state.query&&(filters.length||state.view!=='all')?`<a class="outline-button" href="${esc(buildUrl('all',{query:state.query}))}">Search every bill for “${esc(state.query)}”</a>`:'',
    state.view==='watchlist'&&!state.watch.size?'<a class="outline-button" href="/explorer" data-view="all">Browse all bills</a>':''].filter(Boolean);
  return steps.length?`<p class="empty-steps">${steps.join('')}</p>`:'';
}
export function clearFilter(key){
  state[key]=key==='onlyWatch'||key==='companion'?false:'';
  state.visibleCount=30;renderContent();
}

// Reader areas (#13): the Area select, grouped as on the dashboard, and the header shown while one is chosen.
function areaSelect(){
  const opt=a=>`<option value="${esc(a.id)}"${a.id===state.area?' selected':''}>${esc(a.name)}</option>`;
  return `<select aria-label="Reader area" id="filter-area"><option value="">All reader areas</option>${AREA_GROUPS.map(g=>`<optgroup label="${esc(g)}">${AREAS.filter(a=>a.group===g).map(opt).join('')}</optgroup>`).join('')}</select>`;
}
function areaHeaderMarkup(){
  const area=AREA_BY_ID.get(state.area);
  if(!area||state.view!=='all')return '';
  const bills=state.bills.filter(b=>inArea(b,area.id));
  const row=areaCounts(bills,todayDay()).find(r=>r.area.id===area.id);
  const hearing=new Map();for(const b of bills){const l=assessHearing(b).label;hearing.set(l,(hearing.get(l)||0)+1)}
  const status=[NO_HEARING,'Referred','Scheduled','Heard'].filter(l=>hearing.get(l)).map(l=>`<span><strong>${hearing.get(l).toLocaleString()}</strong> ${esc(l.toLowerCase())}</span>`).join('');
  const agencies=topAgencies(bills,3,new Set([SCOPE_AGENCY_ID])).map(a=>`<a class="text-link" href="${esc(buildUrl('all',{area:area.id,agency:a.id}))}">${esc(agencyName(a.id))}</a> (${a.count.toLocaleString()})`).join(', ');
  return `<h2>${esc(area.name)}</h2><p class="area-audience">For ${esc(area.audience.charAt(0).toLowerCase()+area.audience.slice(1))}.</p>`
    +`<p class="home-counts"><span><strong>${bills.length.toLocaleString()}</strong> ${bills.length===1?'bill':'bills'}</span><span><strong>${(row?.moved||0).toLocaleString()}</strong> with an action in the last 7 days</span>${status}</p>`
    +(agencies?`<p class="area-agencies">Agencies named most: ${agencies}.</p>`:'')
    +`<details class="area-rule"><summary>What puts a bill in this area</summary><p>A bill is here when the Legislative Council files it under one of these official subjects, or its title or caption uses one of the area's key terms. Areas are a reading aid built from the subject index, not a legal classification.</p><div class="bill-tags">${subjectLabels(area).map(x=>`<span class="tag subject-tag">${esc(x)}</span>`).join('')}</div></details>`
    +`<p class="tools-note">To follow this area, use <strong>Share / save</strong> then <strong>Save search</strong>.</p>`;
}
// Redrawn only when the area, view or bills change, so an open "What puts a bill" stays open while results update.
let areaHeaderShown={box:null,area:null,view:null,bills:null};
function renderAreaHeader(){
  const box=$('#area-header');if(!box)return;
  const now={box,area:state.area,view:state.view,bills:state.bills};
  if(Object.keys(now).every(k=>now[k]===areaHeaderShown[k]))return;
  areaHeaderShown=now;
  const html=areaHeaderMarkup();box.hidden=!html;box.innerHTML=html;
}
// The watchlist is usually short, so its filters fold under one toggle; any set filter opens it.
function watchFiltersOpen(){
  if(state.view!=='watchlist')return '';
  const n=activeFilters().filter(([key])=>key!=='query').length;
  return `<details class="watch-filters" id="watch-filters"${n||state.watchFiltersOpen?' open':''}><summary class="outline-button">Filters${n?` · ${n}`:''}</summary>`;
}
// ---- Bills / Laws (the buttons above the explorer's search box) ----
// What the explorer searches: 'both', 'bills' or 'laws'. Only the explorer has the buttons; the watchlist and shared
// lists always show bills.
export const searchScope=()=>state.view==='all'&&!state.sharedList?cleanScope(state.scope):'both';
const SVG='viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
const SCOPE_ICONS={
  bills:`<svg ${SVG}><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/></svg>`,
  laws:`<svg ${SVG}><path d="M12 4v16M8 20h8M5 7h14"/><path d="M5 7l-3 6h6zM19 7l-3 6h6z"/></svg>`,
};
function scopeToggle(){
  if(state.view!=='all'||state.sharedList)return '';
  const scope=searchScope(),on={bills:scope!=='laws',laws:scope!=='bills'};
  const button=(kind,label,other)=>{const last=on[kind]&&!on[other==='Laws'?'laws':'bills'];
    return `<button type="button" class="scope-button" data-search-scope="${kind}" aria-pressed="${on[kind]}" title="${last?`One kind stays on: turn on ${other} to switch`:on[kind]?`Hide ${label.toLowerCase()} from the results`:`Show ${label.toLowerCase()} in the results`}">${SCOPE_ICONS[kind]}<span>${label}</span></button>`};
  return `<div class="search-scope" role="group" aria-label="Search in"><span class="scope-label">Search in</span>${button('bills','Bills','Laws')}${button('laws','Laws','Bills')}</div>`;
}
const LAW_PAGE=50;
const lawPage={query:null,n:LAW_PAGE};
export function showMoreLaws(){lawPage.n+=LAW_PAGE}
// "Changed by bills": only laws a bill is changing. For this visit only; not in the address or the prefs.
let lawChangedOnly=false;
export function toggleLawChanged(){lawChangedOnly=!lawChangedOnly;lawPage.n=LAW_PAGE}
// Laws only: the law list replaces the bills, and the bill-only controls are hidden (explorerMarkup).
function drawLawResults(){
  const area=$('#area-header');if(area)area.hidden=true;
  const preview=$('#bill-preview');if(preview)preview.hidden=true;
  const q=state.query.trim();
  if(lawPage.query!==q){lawPage.query=q;lawPage.n=LAW_PAGE}
  const all=lawResults(q),filter=all.status==='ok'&&all.kind==='words'&&all.items.length>0;
  // Until the statute index arrives nothing is known to be changed, so the filter waits rather than emptying the list.
  const on=filter&&lawChangedOnly&&Boolean(state.statutes);
  const r=on?{...all,items:all.items.filter(([k])=>lawChanged(k))}:all,n=r.items.length;
  $('#result-count').textContent=r.status==='ok'?`${n} ${n===1?'law':'laws'}`:'Texas law';
  $('#result-note').textContent=r.status!=='ok'||!n&&!on?'':r.kind==='key'?' · by section number':on?' · changed by bills':' · headings with every word';
  const toggle=filter?`<div class="law-filter"><button type="button" class="check-filter${lawChangedOnly?' selected':''}" id="law-changed" aria-pressed="${lawChangedOnly}" title="Only laws a bill in this session is changing">Changed by bills</button></div>`:'';
  $('#bill-list').innerHTML=toggle+(on&&!n?`<div class="empty-state"><h3>No bill changes these laws</h3><p>None of the ${all.items.length} laws with these words in the heading is changed by a bill. Turn off “Changed by bills” to see them.</p></div>`:lawResultsMarkup(r,lawPage.n,q));
  $('#results-bottom').innerHTML=n>lawPage.n?`<button class="outline-button" id="law-more">Show ${Math.min(LAW_PAGE,n-lawPage.n)} more · showing ${lawPage.n} of ${n}</button>`:'';
  persistState();
}
export function explorerMarkup(){
  const lawsOnly=searchScope()==='laws',hide=lawsOnly?' hidden':'';
  const searchLabel=lawsOnly?'Search Texas law':'Search bills';
  const placeholder=lawsOnly?'Search Texas law: heading words or a section number…':'Search bill number, author, subject, or keyword…';
  const topics=unique([...POLICY_AREAS.map(t=>t.name),...state.bills.flatMap(b=>b.topics)]).sort();
  const popular=['Education','Healthcare','Elections','Taxes','Immigration','Data centers','Local government','Energy & utilities'];
  return `${sharedBanner()}${state.view==='watchlist'?watchTools():''}
    <section class="area-header" id="area-header" aria-label="Reader area" hidden></section><div class="explorer-controls">${scopeToggle()}<div class="search-row"><div class="search-wrap"><input aria-label="${searchLabel}" id="bill-search" maxlength="200" placeholder="${placeholder}" value="${esc(state.query)}" autocomplete="off"></div><details class="share-menu" id="share-menu"><summary class="outline-button">Share / save</summary><div class="share-panel"><button type="button" id="copy-view-link" title="Copy a link to this view, with its filters">Copy link</button>${state.view==='all'&&!state.sharedList&&!lawsOnly?'<button type="button" id="save-search" title="Keep this search and its filters under Following">Save search</button>':''}<button type="button" id="export-csv"${hide}>↓ Export results (CSV)</button></div></details></div><details class="search-help"${hide}><summary>What search looks at</summary><p>Every word you type has to appear somewhere in the bill, in any order. It looks in: ${SEARCH_FIELDS.map(f=>esc(f.label)).join(', ')}. Luna's search terms are words it added to help find a bill; they are not shown on the card, so each result says which field matched.</p><p>Put words in "double quotes" to keep them together. A plural also finds the singular ("wages" finds "wage"). A section number such as <em>Penal Code 46.06</em> finds the bills that change it.</p><p class="search-examples">Try: ${SEARCH_EXAMPLES.map(x=>`<button type="button" class="search-example" data-search-example="${esc(x)}">${esc(x)}</button>`).join('')}</p></details>
    ${watchFiltersOpen()}<div class="filter-bar"${hide}><div class="filter-row">${areaSelect()}<select aria-label="Policy area" id="filter-topic">${options(topics,state.topic,'All policy areas')}</select><select aria-label="Chamber" id="filter-chamber">${options(['House','Senate'],state.chamber,'Both chambers')}</select><select aria-label="Stage" id="filter-stage">${options(['Filed','Referred','Scheduled','Heard','Advanced','Passed','Enacted','Vetoed'],state.stage,'Any stage')}</select><button class="check-filter ${state.companion?'selected':''}" id="companion-filter" aria-pressed="${state.companion}" title="Only bills with an identical or similar bill filed in the other chamber">⇄ Has companion</button></div><details class="more-filters" id="more-filters"${moreFiltersOpen()?' open':''}><summary class="outline-button">More filters<span id="more-count">${moreCountText()}</span></summary><div class="filter-row more-row"><div class="agency-combobox" id="agency-combobox"><input aria-label="Affected agency" aria-controls="agency-options" aria-expanded="false" aria-autocomplete="list" role="combobox" id="filter-agency" placeholder="All affected agencies" value="${esc(state.agency?agencyName(state.agency):'')}" autocomplete="off"><span class="agency-chevron" aria-hidden="true">⌄</span><div class="agency-panel" id="agency-panel" hidden><div class="agency-sort" role="group" aria-label="Sort agencies">${agencySortButtons()}</div><div class="agency-options" id="agency-options" role="listbox" hidden>${agencyOptionsMarkup()}</div></div></div><select aria-label="Author party" id="filter-party" title="Republican or Democratic: the primary author's party, with no author or coauthor from the other party. Bipartisan: authors or coauthors from both parties.">${options(Object.keys(PARTY_FILTERS),state.party,'Any party')}</select><select aria-label="Hearing status" id="filter-outlook">${options([NO_HEARING,'Referred','Scheduled','Heard'],state.outlook,'Hearing status')}</select><select aria-label="Last action" id="filter-action">${options(unique([...LAST_ACTION_TYPES.map(t=>t.label),'Other action']).filter(l=>l===state.action||state.bills.some(b=>lastActionInfo(b).label===l)),state.action,'Any last action')}</select><button class="check-filter ${state.onlyWatch?'selected':''}" id="watch-filter">☆ Watched only</button></div></details></div>${state.view==='watchlist'?'</details>':''}</div>
    ${state.view==='watchlist'?'':`<div class="topic-strip" aria-label="Quick topic filters"${hide}><button class="topic-chip ${state.topic===''?'selected':''}" data-topic="">All topics</button>${popular.map(t=>`<button class="topic-chip ${state.topic===t?'selected':''}" data-topic="${esc(t)}">${esc(t)}</button>`).join('')}</div>`}
    <div class="active-filters" id="active-filters" aria-label="Active filters"${hide}></div><div class="results-header"><div><strong id="result-count">—</strong><span id="result-note"></span></div><select id="sort-order" aria-label="Sort bills"${hide}>${options(Object.values(SORTS),SORTS[state.sort],'Sort by')}</select></div><div class="explorer-results" id="explorer-results"><div class="bill-list" id="bill-list"></div><aside class="bill-preview" id="bill-preview" aria-labelledby="preview-title" hidden></aside></div><div class="explorer-bottom" id="results-bottom"></div>`;
}

export function headlineLine(b,where){
  if(typeof b.headline!=='string'||!b.headline)return '';
  return `<p class="bill-headline ${where}"><span class="headline-label">In brief</span> <span class="ai-badge" title="Written by Luna, the AI model that reads each bill’s full text; not official. How it works explains more.">AI</span> <span class="headline-text"${where==='card'?` title="${esc(b.headline)}"`:''}>${esc(b.headline)}</span></p>`;
}
export function relatedBlock(b){
  const known=new Set(state.bills.map(x=>x.id));
  const ids=relatedFor(b.id,state.related,known);
  if(!ids.length)return '';
  return `<section class="drawer-section related-section"><h3>Related bills</h3><div class="review-chips">${ids.map(id=>`<button class="review-chip" data-open="${esc(id)}">${esc(id)}</button>`).join('')}</div><p><small>Similar captions and Luna summaries; computed automatically.</small></p></section>`;
}

const reasonLine=reasons=>reasons?.length?`<p class="match-reason"><span>Matched:</span> ${reasons.map(r=>`<span${r.label==='Luna search term'?' title="Words Luna added to help search find this bill; they are not shown on the card"':''}>${esc(r.label)}${r.term?` <mark>${esc(r.term)}</mark>`:''}</span>`).join(' · ')}</p>`:'';

export function drawResults(){
  const scope=searchScope();
  if(scope==='laws')return drawLawResults();
  renderAreaHeader();
  const list=filteredBills();
  $('#result-count').textContent=`${list.length} ${list.length===1?'bill':'bills'}`;
  $('#result-note').textContent=' · matching filters';
  // Companions that are both in the results are pulled together and drawn as one joined block.
  // Paging counts whole groups, so a group is never split across "Load more".
  companionsOf('');  // Refreshes the index when the bill list changed.
  // Watchlist: a watched bill's unwatched companions join its block, marked as not watched, so a group always shows
  // whole. They are context only: not counted in the total or the paging.
  const extras=new Map();
  if(state.view==='watchlist'){
    const inList=new Set(list.map(b=>b.id)),byId=new Map(state.bills.map(b=>[b.id,b]));
    for(const b of list)for(const c of companionsOf(b.id))if(!inList.has(c.id)&&byId.has(c.id))extras.set(c.id,byId.get(c.id));
    if(extras.size)$('#result-note').textContent+=` · plus ${extras.size} unwatched ${extras.size===1?'companion':'companions'} shown with ${extras.size===1?'its':'their'} group`;
  }
  const shown=[];let shownCount=0;
  for(const g of companionGroups([...list,...extras.values()],companionCache.index)){if(shownCount>=state.visibleCount)break;shown.push(g);shownCount+=g.filter(b=>!extras.has(b.id)).length}
  const why=reasonFor();
  const card=b=>billCard(b,extras.has(b.id),extras.has(b.id)?null:why(b));
  const groupMarkup=g=>{
    const ids=new Set(g.map(b=>b.id));
    const relations=[...new Set(g.flatMap(b=>companionsOf(b.id).filter(c=>ids.has(c.id)).map(relationText)))];
    const names=g.map(b=>b.number).join(' + ');
    return `<div class="companion-group" role="group" aria-label="${esc(`${names}: companion bills`)}"><div class="companion-group-head"><span><span aria-hidden="true">⇄</span> Companion bills · ${esc(names)}${relations.length?` · ${esc(relations.join(', '))}`:''}</span>${groupWatchButton(g.map(b=>b.id))}</div>${g.map(card).join('')}</div>`};
  noticeSearch(state.query);
  $('#bill-list').innerHTML=statuteHintMarkup(state.sharedList?[]:lawKeysFor(state.query),state.sharedList?'':state.query,scope==='both')+(list.length?shown.map(g=>g.length>1?groupMarkup(g):card(g[0])).join(''):`<div class="empty-state"><h3>Nothing matches yet</h3><p>${state.view==='watchlist'&&!state.watch.size?'Star bills from the explorer to follow them here.':'Try a broader topic, agency, or keyword.'}</p>${emptyNextSteps()}${state.view==='watchlist'?'':TUMBLEWEED}</div>`);
  $('#results-bottom').innerHTML=`${list.length>shownCount?`<button class="outline-button" id="load-more">Load 30 more · showing ${shownCount} of ${list.length}</button><div style="height:12px"></div>`:''}${esc(state.meta?.coverage_note||'Check the official record for authoritative status.')}`;
  persistState();
  syncPreview();
  const chips=$('#active-filters');if(chips)chips.innerHTML=activeFiltersMarkup();
  const more=$('#more-count');if(more)more.textContent=moreCountText();
}

// ---- Preview (D2-B): a short look at one bill beside the results, for triage. Wide screens only; it holds no
// sections and no text, and every link in it still goes to the bill page.
export const PREVIEW_WIDE=typeof matchMedia==='function'?matchMedia('(min-width: 1200px)'):{matches:false,addEventListener(){}};
export const preview={id:null};
const previewing=()=>Boolean(preview.id)&&PREVIEW_WIDE.matches&&Boolean($('#bill-preview'));
function previewMarkup(b){
  const h=assessHearing(b),last=lastActionInfo(b),watched=state.watch.has(b.id),real=realAgencies(b);
  const cards=[...document.querySelectorAll('#bill-list .bill-card')],at=cards.findIndex(c=>c.dataset.billId===b.id);
  // The pager counts every matching bill; Next past the loaded cards loads the next page (stepPreview).
  const total=Math.max(cards.length,filteredBills().length);
  const summary=b.luna?.summary?{label:'Luna summary',text:b.luna.summary}:sameText(b.caption,b.title)?null:{label:'Caption',text:b.caption};
  return `<div class="preview-head">${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span><button type="button" class="preview-close" id="preview-close" aria-label="Close preview">×</button></div>
    <h2 class="preview-title" id="preview-title" tabindex="-1">${esc(b.title)}</h2>
    ${headlineLine(b,'drawer')}
    ${summary?`<section class="preview-summary"><h3>${summary.label}</h3><p>${esc(summary.text)}</p></section>`:''}
    <dl class="preview-facts">
      <div><dt>Last action</dt><dd>${esc(last.label)}${last.chamber?` · ${esc(last.chamber)}`:''}${last.date?` · ${esc(dateText(last.date))}`:''}<small>${esc(last.text)}</small></dd></div>
      <div><dt>Hearing progress</dt><dd>${esc(h.label)}</dd></div>
      <div><dt>Filed by</dt><dd>${authorHtml(b,b.author)}</dd></div>
      ${real.length?`<div><dt>Agencies</dt><dd>${real.slice(0,3).map(a=>esc(agencyName(a.id))).join(' · ')}${real.length>3?` · +${real.length-3} more`:''}</dd></div>`:''}
    </dl>
    ${b.topics.length?`<div class="bill-tags">${b.topics.slice(0,4).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>`:''}
    <div class="preview-actions"><button type="button" class="primary-button" data-open="${esc(b.id)}">Open bill →</button><button type="button" class="outline-button" data-watch="${esc(b.id)}" aria-pressed="${watched}">${watched?'★ Watching':'☆ Watch'}</button></div>
    <div class="preview-step"><button type="button" class="outline-button" data-preview-step="-1"${at<=0?' disabled':''}>← Previous</button><span>${at>=0?`${at+1} of ${total.toLocaleString()}`:'Not in the list now'}</span><button type="button" class="outline-button" data-preview-step="1"${at<0||at>=total-1?' disabled':''}>Next →</button></div>`;
}
// Draws the preview for preview.id, or hides it; marks the previewed card.
function syncPreview(){
  const aside=$('#bill-preview');
  if(!aside)return;
  const b=previewing()?state.bills.find(x=>x.id===preview.id):null;
  document.querySelectorAll('#bill-list .bill-card.previewed').forEach(c=>{c.classList.remove('previewed');c.removeAttribute('aria-current')});
  $('#explorer-results')?.classList.toggle('previewing',Boolean(b));
  if(!b){aside.hidden=true;aside.innerHTML='';return}
  const card=$(`#bill-list .bill-card[data-bill-id="${CSS.escape(b.id)}"]`);if(card){card.classList.add('previewed');card.setAttribute('aria-current','true')}
  aside.innerHTML=previewMarkup(b);aside.hidden=false;
}
export function showPreview(id){preview.id=id;syncPreview();$('#preview-title')?.focus({preventScroll:true})}
export function closePreview(){
  const id=preview.id;preview.id=null;syncPreview();
  if(id)$(`#bill-list .bill-card[data-bill-id="${CSS.escape(id)}"] .bill-title-link`)?.focus({preventScroll:true});
}
export function stepPreview(by){
  let cards=[...document.querySelectorAll('#bill-list .bill-card')];const at=cards.findIndex(c=>c.dataset.billId===preview.id);
  if(at<0)return;
  if(by>0&&!cards[at+by]&&cards.length<filteredBills().length){state.visibleCount+=30;renderResults();cards=[...document.querySelectorAll('#bill-list .bill-card')]}
  const next=cards[at+by];
  if(!next)return;
  next.scrollIntoView({block:'nearest'});showPreview(next.dataset.billId);
}
PREVIEW_WIDE.addEventListener('change',()=>syncPreview());

// D5: a card shows the caption only when it says more than the title, and a count only when it is above zero.
export const sameText=(a,b)=>{const n=x=>String(x||'').toLowerCase().replace(/[.\s]+$/,'').replace(/\s+/g,' ').trim();return n(a)===n(b)};
const countSpan=(n,word)=>n>0?`<span>${n} ${word}${n===1?'':'s'}</span>`:'';
function billCard(b,unwatchedCompanion=false,reasons=null){
  const h=assessHearing(b);const watched=state.watch.has(b.id);const influence=authorInfluence(b);
  const real=realAgencies(b);
  const scopeTag=b.agencies.length>real.length?'<span class="tag" title="Cross-cutting scope marker, not an agency">Statewide scope</span>':'';
  const agencyTags=scopeTag+real.slice(0,2).map(a=>`<span class="tag agency" title="${esc(a.reason||'')}">${esc(agencyName(a.id).replace(/^Texas /,'').replace(/ Department of /,' · '))}</span>`).join('');
  const party=authorshipParty(b),last=lastActionInfo(b);
  const companionTags=companionsOf(b.id).map(c=>`<button class="tag companion-tag" data-open="${esc(c.id)}" title="${esc(`Companion bill (${relationText(c)})${c.author?`, by ${c.author}`:''}. Opens its details.`)}">⇄ Companion ${esc(c.number)}</button>`).join('');
  const via=agencyVia().get(b.id);
  const viaTag=via?`<span class="tag agency via-companion" title="${esc(`Not tagged with ${agencyName(state.agency)} itself; listed because its companion ${via.map(id=>companionLabel({id})).join(', ')} is.`)}">via companion ${esc(via.map(id=>companionLabel({id})).join(', '))}</span>`:'';
  const actionTag=`<span class="tag action-tag action-${esc(last.key)}" title="${esc(`Last action${last.chamber?` (${last.chamber})`:''}: ${last.text}`)}">${esc(last.label)}${last.chamber&&last.key!=='filed'?` · ${esc(last.chamber)}`:''}${last.date?` · ${esc(shortDate(last.date))}`:''}</span>`;
  return `<article class="bill-card party-${party.tint}${unwatchedCompanion?' unwatched-companion':''}" data-bill-id="${esc(b.id)}"><div class="bill-left"><div class="bill-head">${unwatchedCompanion?'<span class="unwatched-pill">Companion · not watched</span>':''}${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span><span class="party-pill party-${party.tint}" title="${esc(party.detail)}">${esc(party.label)}</span>${influence.level>=4?influencePill(influence):''}</div><h3 class="bill-title">${openLinkHtml(b.id,billHref(b.id),'bill-title-link',b.title)}</h3>${headlineLine(b,'card')}${reasonLine(reasons)}${sameText(b.caption,b.title)?'':`<p class="bill-description">${esc(b.caption)}</p>`}<div class="bill-tags">${actionTag}${viaTag}${companionTags}${b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}${agencyTags}${real.length>2?`<span class="tag agency">+${real.length-2} agencies</span>`:''}</div><div class="bill-meta"><span>By <b>${authorHtml(b,b.authors[0]||b.author)}</b></span>${countSpan(b.authors.length>1?b.authors.length:0,'author')}${countSpan(b.coauthors?.length,'coauthor')}${countSpan(b.cosponsors?.length,'cosponsor')}<span class="bill-filed">Filed ${dateText(b.filed_at)}</span>${real.length?`<span class="bill-links">${real.length} agency ${real.length===1?'link':'links'}</span>`:''}</div></div><div class="bill-right"><button class="watch-button" data-watch="${b.id}" aria-label="${watched?`Remove ${esc(b.number)} from`:`Add ${esc(b.number)} to`} watchlist" aria-pressed="${watched}">${watched?'★':'☆'}</button><div>${h.level>0?`<div class="outlook-label">Hearing progress</div><div class="outlook-value">${esc(h.label)}</div>`:''}<button class="bill-open" data-open="${b.id}" aria-label="Bill details for ${esc(b.number)}">Bill details →</button></div></div></article>`;
}
