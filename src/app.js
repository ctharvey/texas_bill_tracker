import {SEARCH_FIELDS, searchFields, searchText, matchReasons} from './features/search/model.js';
import {nextVisit, changedSince, newestReviewed} from './features/home/model.js';
import {topicHue, topicStyle, plainTitle, daysUntil} from './features/home/rows.js';
import {reviewParts, reviewLookupHtml, reviewMarkup} from './features/review/view.js';
import {companionCache, companionsOf, relationText, agencyVia, groupWatchButton, companionBlock} from './features/companions/view.js';
import {todayData, todayMarkup} from './features/today/view.js';
import {recentChanges, changeText} from './features/review/updates.js';
import {AREAS, AREA_GROUPS, AREA_BY_ID, billAreas, inArea, areaCounts, topAgencies, subjectLabels} from './features/areas/model.js';
import {statuteLabel, parseStatuteQuery, statuteKeysFor} from './features/statutes/model.js';
import {fillDrawerBrackets} from './features/brackets/view.js';
import {loadStatutes, fillDrawerStatutes, statuteMarkup, statuteHintMarkup} from './features/statutes/view.js';
import {stageFiles, stageSections} from './features/stages/view.js';
import {reviewFileSection} from './features/reviewfile/view.js';
import {exportMarkup} from './features/export/view.js';
import {methodMarkup} from './features/pages/method.js';
import {savingMarkup} from './features/pages/saving.js';
import {dataMarkup} from './features/pages/data.js';
import {setupDisclaimer} from './features/pages/dialogs.js';
import {copyForAi, copyPageForAi} from './features/ai/view.js';
import {billTextSection} from './features/billtext/view.js';
import {aiChatLinks, agentUrl} from './features/ai/model.js';
import {setupThemePicker, setupModePicker, setTheme, savedTheme, applyTheme, applyMode} from './features/theme/view.js';
import {TUMBLEWEED, noticeSearch, setupEasterEggs} from './features/easter/view.js';
import {state} from './core/state.js';
import {$, esc, toast} from './core/dom.js';
import {timeoutSignal, loadShardedMap, httpError} from './core/net.js';
import {registerView, setFallbackView, viewHeading, renderView} from './core/router.js';
import {onClick, clickOn, dispatchClick} from './core/dispatch.js';
import {storageKey, followKey, searchesKey, prefsKey, disclaimerKey, visitKey, STORAGE_OK, readJson, writeJson, memoryStorage, loadSaved} from './core/storage.js';
import {FILTER_DEFAULTS, parseHash, buildHash, pickFilters, sameFilters, cleanFilters, profileFile, parseProfileFile, cleanFollows, MAX_FOLLOWS,
  cleanSearches, newSearchId, searchName, searchFitsSync, MAX_SEARCHES, parseLocation, buildUrl, shareUrl} from './prefs.js';
import {createSyncClient} from './sync.js';
import {readWatch, readFollows, readSearches, changeWatchList, changeFollowList, changeSearchList, adoptLists} from './core/lists.js';
import {moveTarget, moveSource, moveNeeded, collect, receive, digest, keepHeld, heldFile, heldCount, previousLinks, MOVED_KEY} from './core/move.js';
import {sendMove, receiveMove, newNonce} from './features/move/handoff.js';
import {applyMove} from './features/move/apply.js';
import {oldSiteBanner, newSiteResult, savedSummary} from './features/move/view.js';
import {withMode} from './features/theme/model.js';
import {artEntries, artBanner, HERO_MEDIA, heroFits} from './features/art/view.js';
import {NEAR_KEY, placeFromPoint, cleanNear, countyDistricts, countiesOf, membersFor, memberByCode, billsByMember, followedBills, ROLES, gazetteer, areaReasons, areaFor, censusUrl, censusPoint} from './geo.js';
import {AGENCIES, AGENCY_NAME, SCOPE_AGENCY_ID, applyLunaTags, applyLunaExtras, relatedFor, auditLine, attachMembers, authorshipParty, PARTY_FILTERS, partyFilterMatches, NO_HEARING, memberSummary, tenureTag, lastActionInfo, LAST_ACTION_TYPES, reviewProgress, reviewSummary, POLICY_AREAS, assessHearing, authorInfluence, officialUrl, snapshotAgeHours, normalizeBill, companionGroups, sortAgencyIds, groupAgencyIds, searchTerms, textMatches, newestFirst, cardClickOpens, openLinkHtml, chicagoDate, activityOn, highestNumberFirst, latestActivityDay, topicCounts, groupByActionType, companionLabel} from './taxonomy.js';

const SORTS={newest:'Newest filed',latest:'Latest action',oldest:'Oldest last action',actionstage:'Last action stage',number:'Bill number',agencies:'Most agencies',hearing:'Hearing progress',influence:'Author influence'};
const agencyName = id => AGENCY_NAME[id]||state.luna?.agencies?.[id]||id;
const areaName = id => AREA_BY_ID.get(id)?.name||id;
loadSaved();
// The dashboard visit before this one: read, and today stamped, the first time the dashboard is drawn in this page
// load, so other pages never add the key. null on a first visit or without storage.
let visit=null;
function previousVisit(){
  if(!visit){visit=nextVisit(readJson(visitKey),chicagoDate(new Date()));if(STORAGE_OK)writeJson(visitKey,visit.store)}
  return visit.prev;
}

// One formatter each, remembered per day: search formats two dates for every bill on every keystroke, and building a
// formatter per call (toLocaleDateString with options) was most of the typing cost on a slow CPU.
const dayFormat = (options, empty) => {
  const format = new Intl.DateTimeFormat('en-US', {...options, timeZone: 'UTC'}), seen = new Map();
  return iso => {
    if (!iso) return empty;
    const day = String(iso).slice(0,10);
    let text = seen.get(day);
    if (text === undefined) {
      const date = new Date(`${day}T12:00:00Z`);  // a malformed day ("2026-13-45") shows as empty, not a thrown RangeError
      text = Number.isNaN(date.getTime()) ? empty : format.format(date); seen.set(day, text);
    }
    return text;
  };
};
const shortDate = dayFormat({month:'short',day:'numeric'}, '');
const dateText = dayFormat({month:'short',day:'numeric',year:'numeric'}, 'Not available');
const stampText = iso => iso ? new Date(iso).toLocaleString('en-US',{dateStyle:'medium',timeStyle:'short',timeZone:'America/Chicago'})+' CT' : 'Unknown';
const unique = a => [...new Set(a)];

const realAgencies = b => b.agencies.filter(a=>a.id!==SCOPE_AGENCY_ID);
const safeHref = value => {try{const u=new URL(String(value));return u.protocol==='https:'||u.protocol==='http:'?u.href:''}catch{return ''}};
const NAME_TO_AGENCY_ID = new Map(AGENCIES.flatMap(a=>[[a.name.toLowerCase(),a.id],[a.id.toLowerCase(),a.id]]));

const normalized=normalizeBill;

async function init(){
  registerViews();
  registerClicks();
  // A move window answers its opener at once (the opener times out otherwise) and applies once the app is ready.
  const arrivingMove=Boolean(MOVE_FROM)&&location.hash==='#move';
  if(arrivingMove)try{history.replaceState(null,'',location.pathname+location.search)}catch{}
  let booted;const bootReady=new Promise(r=>{booted=r});
  if(arrivingMove)receiveArrivingMove(bootReady);
  const now=new Date();
  $('.day-box').textContent=new Intl.DateTimeFormat('en-US',{day:'2-digit',timeZone:'America/Chicago'}).format(now);
  $('.heading-date strong').textContent=new Intl.DateTimeFormat('en-US',{month:'short',year:'numeric',timeZone:'America/Chicago'}).format(now).toUpperCase();
  let lunaReady=null;
  try {
    // Bills, the roster and the review status load together; Luna's files (about 1 MB) follow the bills and are
    // applied after the first render, so a slow phone sees the bills first instead of waiting for everything.
    const rosterReady=loadRoster(),statusReady=loadReviewStatus();
    // The server's hourly live snapshot is preferred; the bundled copy is the fallback.
    const urls=[['./live/bills.json',15000],['./data/bills.json',7500]];
    let data,loadedFrom,loadedBills;
    for(const [url,ms] of urls){
      try{
        const response=await fetch(url,{cache:'no-cache',signal:timeoutSignal(ms)});
        if(!response.ok)throw httpError(response);
        const candidate=await response.json();
        if(candidate.session!=='90R'||!Array.isArray(candidate.bills)||!candidate.bills.length)throw Error('Invalid bill snapshot');
        if(url==='./live/bills.json'&&(candidate.data_mode!=='official-ftp'||candidate.bills.length<1000))throw Error('Live snapshot failed validation');
        const bills=candidate.bills.map(raw=>normalized(raw,candidate.author_profiles)).filter(Boolean);
        if(!bills.length)throw Error('No valid bills in snapshot');
        data=candidate;loadedFrom=url;loadedBills=bills;break;
      }catch(error){console.warn(`Bill source unavailable: ${url}`,error.message)}
    }
    if(!data)throw Error('Unable to load bill snapshot');
    data.loaded_from=loadedFrom==='./live/bills.json'?'Live server snapshot':'Bundled fallback snapshot';
    lunaReady=fetchLuna().then(luna=>({luna,base:loadedBills}));
    state.roster=await rosterReady;
    await statusReady;
    state.meta=data;
    state.bills=state.roster?loadedBills.map(b=>attachMembers(b,state.roster)):loadedBills;
  }catch(error){
    state.meta={data_mode:'unavailable',coverage_note:'The current dataset could not be loaded. Use Data & imports to load a local CSV or JSON file.'};
  }
  document.addEventListener('click',dispatchClick);
  document.addEventListener('change',handleChange);
  document.addEventListener('input',handleInput);
  document.addEventListener('submit',e=>{if(e.target.id==='near-address-form'){e.preventDefault();nearAddress($('#near-address')?.value)}
    if(e.target.id==='home-search-form'){e.preventDefault();goTo(buildHash('all',{query:$('#home-search').value.trim()}))}
    if(e.target.id==='review-lookup-form'){e.preventDefault();const id=$('#review-lookup-result [data-open]')?.dataset.open;if(id)openBillPage(id,true)}
    const form=e.target.closest?.('[data-search-rename-form]');
    if(form){e.preventDefault();const s=state.searches.find(x=>x.id===form.dataset.searchRenameForm),name=form.elements.name.value.trim().slice(0,80);
      if(s&&name&&name!==s.name)changeSearch('save-search',{...s,name});state.renamingSearch=null;renderContent()}});
  document.addEventListener('focusin',event=>{
    if(event.target.id==='filter-agency')showAgencyChoices('');
  });
  document.addEventListener('toggle',e=>{if(e.target.id==='more-filters')state.moreFiltersOpen=e.target.open;if(e.target.id==='watch-save')state.watchSaveOpen=e.target.open;if(e.target.id==='watch-filters')state.watchFiltersOpen=e.target.open},true);
  document.addEventListener('click',e=>{const m=$('#share-menu');if(m?.open&&(!m.contains(e.target)||e.target.closest('.share-panel button')))setTimeout(()=>{m.open=false})});
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&preview.id&&!$('#bill-preview')?.hidden){closePreview();return}
    if(event.key==='Escape'&&$('.sidebar').classList.contains('nav-open')){setNavOpen(false);$('#nav-more').focus()}
    if(event.target.id==='filter-agency'&&handleAgencyKeydown(event))return;
  });
  // A sync link pasted into an open tab arrives as a hash change, not a page load.
  window.addEventListener('hashchange',()=>{const key=applyLocation(false);if(key)openSyncLink(key)});
  // Back and Forward between /bill/<ID> and /#view change the path, which fires popstate but not hashchange.
  window.addEventListener('popstate',()=>{if(location.pathname===lastPath)return;const key=applyLocation(false);if(key)openSyncLink(key)});
  // With <base href="/">, a fragment-only link on a bill page points at the site root: a view link goes through
  // goTo, and an in-page anchor (the skip link) stays on this page.
  document.addEventListener('click',e=>{
    if(e.defaultPrevented||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||location.pathname==='/')return;
    const a=e.target.closest?.('a[href^="#"]');if(!a)return;
    const href=a.getAttribute('href'),target=href.length>1&&!href.includes('?')?document.getElementById(href.slice(1)):null;
    e.preventDefault();
    if(target){target.tabIndex=target.tabIndex<0?-1:target.tabIndex;target.focus();target.scrollIntoView();return}
    goTo(href);
  });
  state.near=cleanNear(readJson(NEAR_KEY),null);
  const syncKey=applyLocation(true);
  viewReady=true;
  setupDisclaimer();
  setupThemePicker(id=>{if(sync.linked?.mode==='edit')sync.record('theme',id)});
  setupModePicker();
  setupEasterEggs();
  setupSync(syncKey);
  booted();if(!arrivingMove)renderMoveBanner();
  if(state.bills.length)loadStatutes({renderContent,renderResults});
  if(lunaReady){const snapshot=state.bills;lunaReady.then(({luna,base})=>applyLuna(luna,base,snapshot))}
  // Keep the progress view current while it is open; other views never refetch.
  setInterval(async()=>{
    if(state.view!=='review'||document.visibilityState!=='visible')return;
    const before=state.reviewStatus?.updated_at;await loadReviewStatus();
    if(state.view==='review'&&state.reviewStatus?.updated_at!==before){
      const open=[...document.querySelectorAll('.review-group')].map(d=>d.open);
      const box=$('#review-lookup'),typed=box?.value||'',focused=document.activeElement===box,caret=box?.selectionStart??null;
      renderOverview();renderContent();
      document.querySelectorAll('.review-group').forEach((d,i)=>{if(i<open.length)d.open=open[i]});
      const again=$('#review-lookup');
      if(again&&typed){again.value=typed;$('#review-lookup-result').innerHTML=reviewLookupHtml(typed,{dateText})}
      if(again&&focused){again.focus();if(caret!==null)again.setSelectionRange(caret,caret)}
    }
  },60000);
}

// ---- Saving choices without accounts: URL state, remembered filters, files and private sync links ----
// Lists are saved through listStore; each change re-reads it (core/lists.js), so other tabs' saves are kept.
const listStore=STORAGE_OK?localStorage:memoryStorage();
const sync=createSyncClient({storage:STORAGE_OK?localStorage:memoryStorage(),getWatch:()=>readWatch(listStore,storageKey),getFollows:()=>readFollows(listStore,followKey),getSearches:()=>readSearches(listStore,searchesKey),getTheme:savedTheme,
  adopt:adoptSynced,onDisplaced:keepAside});
// The sync client calls this as it stores a new version: the lists become the link's copy plus pending changes.
// Throws if storage refuses, so that version is not stored (core/lists.js adoptLists).
let syncMoved=false;  // Whether the last adoption changed follows or searches (onSynced re-renders only then).
function adoptSynced(d){
  adoptLists(listStore,{watch:storageKey,follows:followKey,searches:searchesKey},d);
  syncMoved=Boolean(d.follows&&d.follows.join()!==state.follow.join()||d.searches&&JSON.stringify(cleanSearches(d.searches))!==JSON.stringify(state.searches));
  state.watch=new Set(d.watch);if(d.follows)state.follow=cleanFollows(d.follows);if(d.searches)state.searches=cleanSearches(d.searches);
  if(d.theme)setTheme(d.theme);
}
// Items this browser added that the sync link has no room for (500 bills, 200 follows, 20 searches): kept aside
// and listed on the Export page, never dropped. Throws when even that fails, so the write is not acknowledged.
function keepAside(held){
  if(!keepHeld(listStore,held))throw Error('This browser is out of storage space; sync paused so nothing is lost');
  const n=held.watch.length+held.follows.length+held.searches.length;
  toast(`${n} saved ${n===1?'item':'items'} did not fit the sync link and ${n===1?'was':'were'} kept aside: see Export`);
}
let syncAvailable=null,lastPull=0;
// The site root, whatever page is open: a bill page's path is /bill/<ID>.
const siteBase=()=>`${location.origin}/`;
// Every view but a bill page lives at /#view. A plain hash change on /bill/<ID> would stay under that path, so it
// moves to / instead and is handled like any other hash change.
let lastPath=location.pathname;
function goTo(hash){
  hash=String(hash||'').startsWith('#')?String(hash):`#${hash||''}`;
  if(location.pathname==='/'){location.hash=hash;return}
  try{history.pushState(null,'',`/${hash}`)}catch{location.href=`/${hash}`;return}
  lastPath=location.pathname;
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

function applyFilters(raw){
  const clean=cleanFilters(raw);
  if(clean.sort&&!Object.hasOwn(SORTS,clean.sort))delete clean.sort;
  Object.assign(state,FILTER_DEFAULTS,clean,{visibleCount:30});
}

// The explorer and the Watchlist each keep their own filters: switching views stashes one set and restores the
// other (the Watchlist starts unfiltered). filtersFor names the view whose filters are in state now.
const FILTERED_VIEWS=new Set(['all','watchlist']);
const viewFilters={};
let filtersFor='all';
function switchFilters(view){
  if(!FILTERED_VIEWS.has(view)||filtersFor===view)return;
  viewFilters[filtersFor]=pickFilters(state);
  applyFilters(viewFilters[view]||{});
  filtersFor=view;
}

// The address without its bill: where an old `#all?…&bill=HB1` link's Back to results goes.
const withoutBill=hash=>String(hash||'').replace(/([?&])bill=[^&]*&?/,'$1').replace(/[?&]$/,'');
// The page a bill was opened from: its address, how many results were showing and the scroll position. Back to
// results (or the browser's Back) to that address restores them; on a cold load there is only an address.
let billReturn=null;

// Returns a sync key from the URL, if any, for setupSync to resolve.
function applyLocation(initial){
  const p=parseLocation(location.pathname,location.hash);
  lastPath=location.pathname;
  // An old link with `bill=` on another view opens the bill page; setView's persistState replaces the address.
  const legacy=Boolean(p.bill)&&p.view!=='bill';
  if(legacy)billReturn={hash:withoutBill(location.hash)};
  const view=p.bill?'bill':p.view==='bill'?'all':p.view;
  // Filters in the address belong to the view it names; otherwise each view gets its own remembered set.
  let urlFilters=true;
  if(!initial&&(p.hasFilters||p.list)&&FILTERED_VIEWS.has(p.view)&&filtersFor!==p.view)viewFilters[filtersFor]=pickFilters(state);
  if(p.hasFilters)applyFilters(p.filters);
  else if(p.list)applyFilters({});  // A share link shows its whole list, even in a tab with filters set.
  else if(initial&&!legacy&&!p.sync){
    restoredFilters=readJson(prefsKey)?.filters||null;
    // Remembered filters are the explorer's; a Watchlist opened directly starts unfiltered.
    if(p.view==='watchlist'){viewFilters.all=readJson(prefsKey)?.filters||{};applyFilters({})}
    else applyFilters(readJson(prefsKey)?.filters);
  }
  else urlFilters=initial;
  if(urlFilters&&FILTERED_VIEWS.has(p.view))filtersFor=p.view;
  if(p.list){state.sharedList=p.list;state.sharedMode='link'}
  else if(!initial&&state.sharedMode==='link'){state.sharedList=null;state.sharedMode=null}
  if(p.member!==state.memberCode)state.memberShow={};
  state.memberCode=p.member;
  state.statuteKey=p.statute;
  state.openBill=view==='bill'?p.bill:null;
  // Arriving back at the page a bill was opened from: show as many results as before, then return to the same place.
  const back=view!=='bill'&&billReturn?.scrollY!==undefined&&location.hash===billReturn.hash?billReturn:null;
  if(back){state.visibleCount=Math.max(state.visibleCount,back.visibleCount);billReturn=null}
  setView(view,false,{focus:!back});
  if(back)window.scrollTo({top:back.scrollY,behavior:'instant'});
  return p.sync;
}

function currentHash(){
  return buildHash(state.view,pickFilters(state),{list:state.sharedMode==='link'?state.sharedList:null,bill:state.openBill,
    sync:state.sharedMode==='sync-view'?state.sharedSyncKey:null,member:state.memberCode,statute:state.statuteKey});
}

function currentUrl(){
  return buildUrl(state.view,pickFilters(state),{list:state.sharedMode==='link'?state.sharedList:null,bill:state.openBill,
    sync:state.sharedMode==='sync-view'?state.sharedSyncKey:null,member:state.memberCode,statute:state.statuteKey});
}

// A bill's page address (/bill/<ID>), so a bill title is a real link (new tab, copy link) as well as a click target.
function billHref(id){
  return buildUrl('bill',{},{list:state.sharedMode==='link'?state.sharedList:null,bill:id,
    sync:state.sharedMode==='sync-view'?state.sharedSyncKey:null});
}

// Opens a bill's page with a history entry, remembering where it was opened from (not when moving bill to bill).
function openBillPage(id,push=false){
  if(state.view!=='bill')billReturn={hash:currentHash(),visibleCount:state.visibleCount,scrollY:window.scrollY};
  state.openBill=id;
  setView('bill',push);
  window.scrollTo({top:0,behavior:'instant'});
}

// Back to results: the page the bill was opened from, or the explorer when the bill page was the first page loaded.
function leaveBillPage(){goTo(billReturn?.hash||'#all')}

// prefs-v1 fields other than the filters (the colour theme) survive a filter save.
const keptPrefs=()=>{const p=readJson(prefsKey);return p&&typeof p==='object'&&!Array.isArray(p)?p:{}};
// push=true adds a history entry (opening a bill), so Back closes it instead of leaving the site.
function persistState(push=false){
  const url=currentUrl();
  let pushed=false;
  if(location.pathname+location.hash!==url)try{if(push){history.pushState(null,'',url);pushed=true}else history.replaceState(null,'',url)}catch{}
  lastPath=location.pathname;
  const canonical=document.querySelector('link[rel="canonical"]');
  if(canonical)canonical.href=state.view==='bill'&&state.openBill?`https://billatlas.org/bill/${state.openBill}`:'https://billatlas.org/';
  if(state.view==='all'&&filtersFor==='all'&&!state.sharedList&&!(readJson(prefsKey)?.filters&&sameFilters(readJson(prefsKey).filters,state)))writeJson(prefsKey,{...keptPrefs(),filters:pickFilters(state)});
  return pushed;
}

function changeFollow(op,codes){
  const {list,changed}=changeFollowList(listStore,followKey,op,codes,MAX_FOLLOWS);
  state.follow=list;for(const code of changed)sync.record(op,code,onSynced);
  if(changed.length)renderMoveBanner();
}
function toggleFollow(code){
  const on=state.follow.includes(code);
  if(!on&&state.follow.length>=MAX_FOLLOWS){toast(`You can follow up to ${MAX_FOLLOWS} legislators`);return}
  changeFollow(on?'unfollow':'follow',[code]);
  const m=memberByCode(state.roster,code);
  toast(`${on?'Unfollowed':'Following'} ${m?memberTitle(m):code}${on||state.view==='following'?'':' · their bills are under Following'}`);
  renderOverview();renderContent();
}
const followButton=m=>{if(!m?.code)return '';const on=state.follow.includes(m.code);
  return `<button class="${on?'outline-button following':'primary-button'} follow-button" data-follow="${esc(m.code)}" aria-pressed="${on}">${on?'✓ Following':'+ Follow'}</button>`};
const memberFeedHref=code=>`./live/feeds/members/${encodeURIComponent(code)}.xml`;
// op: 'save-search' (search object) or 'delete-search' (id).
function changeSearch(op,item){
  const id=op==='save-search'?item.id:item;
  state.searches=changeSearchList(listStore,searchesKey,op,item);
  sync.record(op,id,onSynced,op==='save-search'?item:undefined);
  renderMoveBanner();
}
const todayDay=()=>chicagoDate(new Date());
// Bills matching a saved search now, and those with a dated action after the day it was last opened.
function searchCounts(s){
  const list=filteredBills({...FILTER_DEFAULTS,...s.filters}),today=todayDay();
  const fresh=s.seen?list.filter(b=>(latestActivityDay([b],today)||'')>s.seen).length:0;
  return {total:list.length,fresh};
}
function saveCurrentSearch(){
  if(state.searches.length>=MAX_SEARCHES){toast(`You can save up to ${MAX_SEARCHES} searches`);return}
  const filters=cleanFilters(Object.fromEntries(Object.entries(pickFilters(state)).filter(([k,v])=>v!==FILTER_DEFAULTS[k])));
  if(!searchFitsSync(filters)){toast('This search is too long to save; shorten the search words');return}
  const name=searchName(filters,agencyName,areaName);
  if(state.searches.some(s=>JSON.stringify(s.filters)===JSON.stringify(filters))){toast(`Already saved as “${state.searches.find(s=>JSON.stringify(s.filters)===JSON.stringify(filters)).name}”`);return}
  changeSearch('save-search',{id:newSearchId(),name,filters,seen:todayDay()});
  renderOverview();toast(`Saved “${name}” · find it under Following`);
}
function searchSummary(f){
  const parts=[f.query&&`Search “${f.query}”`,f.area&&`Area: ${areaName(f.area)}`,f.topic&&`Topic: ${f.topic}`,f.agency&&`Agency: ${agencyName(f.agency)}`,f.chamber,f.party&&`Party: ${f.party} authors`,f.stage&&`Stage: ${f.stage}`,
    f.outlook&&`Hearing: ${f.outlook}`,f.action&&`Last action: ${f.action}`,f.companion&&'Has a companion bill',f.onlyWatch&&'Watched bills only',f.sort&&f.sort!=='newest'&&`Sorted by ${SORTS[f.sort]||f.sort}`].filter(Boolean);
  return parts.join(' · ')||'All bills';
}
function savedSearchesMarkup(){
  if(!state.searches.length)return `<section class="followed-section"><h3>Saved searches</h3><p class="tools-note">Set filters or a search in the <a class="text-link" href="#all" data-view="all">Bill explorer</a>, then choose <strong>Save search</strong> to keep it here, with a count of bills that moved since you last opened it.</p></section>`;
  const rows=state.searches.map(s=>{
    const {total,fresh}=searchCounts(s);
    const name=state.renamingSearch===s.id
      ?`<form class="search-rename" data-search-rename-form="${esc(s.id)}"><input name="name" maxlength="80" value="${esc(s.name)}" aria-label="Name for this search" autocomplete="off"><button class="outline-button" type="submit">Save</button></form>`
      :`<a class="text-link saved-search-name" href="${esc(buildHash('all',s.filters))}" data-search-open="${esc(s.id)}">${esc(s.name)}</a>`;
    return `<div class="saved-search">${name}<p>${esc(searchSummary(s.filters))}</p><p class="saved-search-counts"><strong>${total.toLocaleString()}</strong> ${total===1?'bill':'bills'}${fresh?` · <span class="saved-search-new">${fresh.toLocaleString()} with new actions</span>`:''}${s.seen?` · opened ${esc(shortDate(s.seen))}`:''}</p><div class="tools-row">${state.renamingSearch===s.id?'':`<button class="text-button" data-search-rename="${esc(s.id)}">Rename</button>`}<button class="text-button danger" data-search-delete="${esc(s.id)}">Delete</button></div></div>`;
  }).join('');
  return `<section class="followed-section"><h3>Saved searches <span>${state.searches.length}</span></h3><p class="tools-note">“New actions” counts bills with an action dated after the day you last opened the search.</p><div class="saved-searches">${rows}</div></section>`;
}
// Following: saved searches and followed legislators; later also named watchlists.
function followingMarkup(){
  return `<div class="section-head"><div><div class="section-overline">FOLLOWING</div><h2>Your searches and legislators</h2></div><span class="subtitle">Saved in this browser, files and sync links</span></div>${savedSearchesMarkup()}${followedMarkup()}`;
}
function followedMarkup(){
  if(!state.follow.length)return `<section class="followed-section"><h3>Followed legislators</h3><p class="tools-note">Follow a legislator from their member page or from <a class="text-link" href="#local" data-view="local">Near you</a> to see every bill they file or sign onto here.</p></section>`;
  if(!state.roster)return `<section class="followed-section"><h3>Followed legislators</h3><p class="tools-note">The member roster could not be loaded, so followed legislators' bills are not shown right now.</p></section>`;
  const members=state.follow.map(code=>memberByCode(state.roster,code)).filter(Boolean);
  const rows=followedBills(state.bills,state.roster,state.follow,newestFirst),limit=state.followShow||30;
  const chips=members.map(m=>`<span class="followed-member">${memberNameHtml(m,memberTitle(m))} <a class="text-link" href="${esc(memberFeedHref(m.code))}" target="_blank" rel="noopener noreferrer" title="RSS feed of this legislator's bills">RSS</a> <button class="text-button" data-follow="${esc(m.code)}" aria-label="Unfollow ${esc(memberTitle(m))}">Unfollow</button></span>`).join('');
  return `<section class="followed-section"><h3>Followed legislators <span>${members.length}</span></h3><div class="followed-members">${chips}</div><p class="tools-note">Saved in this browser, in exported files and with your sync link; never in share or view-only links. Newest bills first.</p>${rows.length?`${rows.slice(0,limit).map(r=>nearRow(r,{showWho:true})).join('')}${rows.length>limit?`<button class="outline-button" id="follow-more">Show 30 more · showing ${limit} of ${rows.length}</button>`:''}`:'<p class="review-empty">No bills by the legislators you follow in this snapshot yet.</p>'}</section>`;
}
const FOLLOW_VIEWS=new Set(['following','member','local']);
function refreshWatch(){renderOverview();if(state.view==='home')refreshHome();else if(state.view==='all'||state.view==='watchlist'||FOLLOW_VIEWS.has(state.view))renderContent()}
// After a debounced write: the client has already adopted the link's copy (adoptSynced); show it.
const onSynced=(watch,error)=>{if(error){toast(`Sync: ${error.message}`);return}renderOverview();
  if(state.view==='all'||state.view==='watchlist')renderResults();else if(state.view==='home')refreshHome();else if(syncMoved&&FOLLOW_VIEWS.has(state.view))renderContent()};
function changeWatch(op,ids){
  const {list,changed}=changeWatchList(listStore,storageKey,op,ids);
  state.watch=new Set(list);for(const id of changed)sync.record(op,id,onSynced);
  if(changed.length)renderMoveBanner();
}
// Another tab of this site saved: show it. Read-only, so two open tabs never answer each other's saves.
function onOtherTab(e){
  if(e.storageArea&&e.storageArea!==localStorage)return;
  const k=e.key;
  if(k===null||k===storageKey||k===followKey||k===searchesKey){loadSaved();refreshWatch()}
  if(k===null||k===prefsKey){const id=applyTheme(savedTheme()||'');const select=$('#theme-select');if(select)select.value=id}
  renderMoveBanner();  // Includes another tab finishing the move (MOVED_KEY).
  if((k===null||k==='tx-bill-atlas-sync-v1')&&(state.view==='watchlist'||state.view==='saving'||state.view==='export'))renderContent();
}

async function setupSync(key){
  syncAvailable=await sync.isAvailable();
  if(key)await openSyncLink(key);
  else if(sync.linked)await pullSync();
  window.addEventListener('focus',()=>{if(Date.now()-lastPull>30000)pullSync()});
  if(STORAGE_OK)window.addEventListener('storage',onOtherTab);
  persistState();
  if(state.view==='home')refreshHome();else if(state.view==='watchlist'||state.view==='saving'||state.view==='export')renderContent();
}

async function openSyncLink(key){
  if(syncAvailable===null)syncAvailable=await sync.isAvailable();
  if(!syncAvailable){toast('Sync links are not available on this site yet');return}
  try{
    // Probe first: a view-only link is shown as a shared list and never replaces this device's own link.
    const probe=createSyncClient({storage:memoryStorage(),getWatch:()=>[]});probe.connect(key);
    const found=await probe.pull();
    if(found.mode==='view'){Object.assign(state,{sharedList:found.watch,sharedMode:'sync-view',sharedSyncKey:key,visibleCount:30});setView('all');toast('Showing a shared watchlist (view-only)');return}
    const joining=sync.linked?.editKey!==key;
    if(joining&&!await confirmJoin(Boolean(sync.linked))){toast('Sync link not opened');return}
    if(joining)sync.connect(key);  // Its bills are added to the link on the first pull that reaches it.
    if(await pullSync()&&joining)toast('This device is now synced');
  }catch(error){toast(error.message)}
}

// An edit link can come from anyone, and joining adds this device's saved items to that list and keeps syncing them
// there. A device with nothing saved and no link of its own joins straight away; otherwise it asks first.
function confirmJoin(replacing){
  const count=(n,one,many)=>n?`${n} ${n===1?one:many}`:'';
  const items=[count(state.watch.size,'bill','bills'),count(state.follow.length,'legislator','legislators'),count(state.searches.length,'saved search','saved searches')].filter(Boolean);
  if(!replacing&&!items.length)return Promise.resolve(true);
  const dialog=document.createElement('dialog');
  if(typeof dialog.showModal!=='function')return Promise.resolve(false);
  const list=items.length>1?`${items.slice(0,-1).join(', ')} and ${items.at(-1)}`:items[0];
  dialog.className='disclaimer';dialog.id='sync-join';dialog.setAttribute('aria-labelledby','sync-join-title');
  dialog.innerHTML=`<h2 id="sync-join-title">Join this synced list?</h2>
    ${items.length?`<p>This device’s ${esc(list)} will be added to the list, and anyone with its edit link will see them and every later change.</p>`:''}
    ${replacing?'<p>This device will forget its current sync link. Copy its edit link first if you still need it.</p>':''}
    <p>Only join links you got from yourself or someone you trust.</p>
    <form method="dialog" class="sync-join-actions"><button class="outline-button" value="cancel" id="sync-join-cancel" autofocus>Cancel</button><button class="disclaimer-ok" value="join" id="sync-join-ok">Join this list</button></form>`;
  document.body.append(dialog);
  return new Promise(resolve=>{
    dialog.addEventListener('close',()=>{resolve(dialog.returnValue==='join');dialog.remove()},{once:true});
    dialog.showModal();
  });
}

// The client merges a join, adopts the link's copy and stores its version together (sync.js). True when it did.
async function pullSync(){
  if(!syncAvailable||!sync.linked)return false;
  lastPull=Date.now();
  try{
    const pulled=await sync.pull();
    loadSaved();refreshWatch();
    return Boolean(pulled);  // Null: another tab or write changed the link meanwhile; the next pull catches up.
  }catch(error){toast(`Sync: ${error.message}`);loadSaved();refreshWatch();return false}
}

// ---- Moving saved data from the old address (MOVE_FROM) to the new one (MOVE_TO); see core/move.js ----
const MOVE_TO=STORAGE_OK?moveTarget(location.origin):null,MOVE_FROM=STORAGE_OK?moveSource(location.origin):null;
let moveStatus=null;  // Old site: null, 'moving', 'moved' or 'failed:<reason>'. New site: the arrival result.
function renderMoveBanner(){
  const el=$('#move-banner');if(!el)return;
  let html='';
  if(MOVE_TO){
    const status=moveStatus==='moving'||moveStatus?.startsWith?.('failed:')?moveStatus:moveNeeded(localStorage)?'offer':moveStatus==='moved'?'moved':'gone';
    html=oldSiteBanner({status,target:MOVE_TO,goHref:MOVE_TO+location.pathname+location.hash,what:status==='offer'||status.startsWith('failed:')?savedSummary(receive(collect(localStorage))):''});
  }else if(MOVE_FROM&&moveStatus)html=newSiteResult(moveStatus,MOVE_FROM);
  el.innerHTML=html;el.hidden=!html;
}
async function startMove(){
  if(!MOVE_TO||moveStatus==='moving')return;
  // Opened inside the click, so the browser allows it; never noopener: the new page answers its opener.
  const win=window.open(`${MOVE_TO}${location.pathname}#move`,'_blank');
  if(!win){moveStatus='failed:blocked';renderMoveBanner();return}
  moveStatus='moving';renderMoveBanner();
  let payload=null;
  const result=await sendMove({self:window,win,target:MOVE_TO,getPayload:async()=>{try{await sync.flush()}catch{}payload=collect(localStorage);return payload}});
  if(result.ok&&payload){
    try{localStorage.setItem(MOVED_KEY,JSON.stringify({digest:digest(receive(payload)),at:new Date().toISOString()}))}catch{}
    moveStatus='moved';
  }else moveStatus=`failed:${result.counts?.why==='sync'?'sync':result.reason||'failed'}`;
  renderMoveBanner();
}
function moveSettings(settings){
  if(settings.theme){const id=setTheme(settings.theme);if(sync.linked?.mode==='edit')sync.record('theme',id)}
  if(settings.mode){writeJson(prefsKey,withMode(readJson(prefsKey),settings.mode));applyMode(settings.mode)}
  if(settings.filters)writeJson(prefsKey,{...keptPrefs(),filters:settings.filters});
  if(settings.near){writeJson(NEAR_KEY,settings.near);state.near=cleanNear(settings.near,state.nearGeo?.tables)}
  if(settings.agencySort){state.agencySort=settings.agencySort;try{localStorage.setItem(AGENCY_SORT_KEY,settings.agencySort)}catch{}}
}
async function receiveArrivingMove(bootReady){
  if(!window.opener){await bootReady;moveStatus={ok:false,reason:'no-opener'};renderMoveBanner();return}
  const result=await receiveMove({self:window,opener:window.opener,source:MOVE_FROM,nonce:newNonce(),apply:async payload=>{await bootReady;return applyMove(payload,{
    storage:localStorage,
    current:()=>{const prefs=keptPrefs();return {watch:readWatch(localStorage,storageKey),follows:readFollows(localStorage,followKey),searches:readSearches(localStorage,searchesKey),
      settings:{theme:savedTheme(),mode:prefs.mode??null,filters:prefs.filters??null,near:readJson(NEAR_KEY),agencySort:(()=>{try{return localStorage.getItem(AGENCY_SORT_KEY)}catch{return null}})()},
      syncKey:readJson('tx-bill-atlas-sync-v1')?.key||null}},
    addWatch:ids=>changeWatch('add',ids),
    addFollows:codes=>changeFollow('follow',codes),
    addSearch:s=>changeSearch('save-search',s),
    setSettings:moveSettings,
    joinLink:async key=>{sync.connect(key);if(syncAvailable===null)syncAvailable=await sync.isAvailable();await pullSync()},
    flush:async()=>{if(syncAvailable&&sync.linked?.mode==='edit')await sync.flush()},
  })}});
  await bootReady;
  moveStatus=result;
  loadSaved();refreshWatch();renderMoveBanner();
}
const movePreviousKey=()=>moveStatus?.previousKey||null;

// Bill id -> drawn share card version, loaded once when a bill page opens so Share can copy synchronously
// (Safari drops clipboard access after an await). Until it loads, or if it fails, Share copies the plain link.
let cardVersions=null,cardVersionsLoad=null;
function loadCardVersions(){
  if(cardVersionsLoad)return;
  // A 404 body is read too: Chrome counts an unread body as a request still open, so the page never goes idle.
  cardVersionsLoad=fetch('./live/og/rendered.json',{cache:'no-cache'}).then(r=>r.ok?r.json():r.text().then(()=>null))
    .then(d=>{cardVersions=d?.format==='texas-bill-og-rendered-v1'&&d.bills&&typeof d.bills==='object'?d.bills:{}})
    .catch(()=>{cardVersionsLoad=null});
}

// Bill page banner (features/art/view.js): read once per page load, so flipping live/site-flags.json takes effect on
// the next load. Either file missing or unreadable means no banner.
let billArt=null,siteFlags=null,billArtLoad=null;
function loadBillArt(){
  if(billArtLoad)return;
  const get=url=>fetch(url,{cache:'no-cache'}).then(r=>r.ok?r.json():r.text().then(()=>null)).catch(()=>null);
  billArtLoad=Promise.all([get('./live/site-flags.json'),get('./live/og/art.json'),document.fonts?.ready.catch(()=>null)])
    .then(([flags,art])=>{siteFlags=flags;billArt=artEntries(art);placeBillArt()});
}
function placeBillArt(){
  const intro=$('#bill-page .bill-intro');if(!intro)return;
  const old=intro.querySelector(':scope > .bill-art');
  if(old){unheroBillArt(old);old.remove()}
  const b=state.bills.find(b=>b.id===state.openBill);
  const html=b?artBanner(b.id,b.number,siteFlags,billArt):'';
  if(html){intro.insertAdjacentHTML('afterbegin',html);layoutBillArt()}
}
// Moves the pills and title back under the banner; the overlay holds the only copies.
function unheroBillArt(fig){
  const media=fig.querySelector('.bill-art-media');if(!media)return;
  const over=media.querySelector('.bill-art-over');
  if(over)fig.after(...over.children);
  fig.prepend(...media.querySelectorAll(':scope > img'));media.remove();fig.classList.remove('hero');
}
// Re-run on width changes: wrapping, and so whether the title fits, depends on it. Moving a focused title drops focus.
function layoutBillArt(){
  const intro=$('#bill-page .bill-intro'),fig=intro?.querySelector(':scope > .bill-art');if(!fig)return;
  const h1=intro.querySelector('#bill-page-title'),focused=h1&&document.activeElement===h1;
  unheroBillArt(fig);
  const pills=intro.querySelector(':scope > .drawer-pills'),img=fig.querySelector(':scope > img');
  if(HERO_WIDE.matches&&pills&&h1&&h1.parentElement===intro&&img){
    const media=document.createElement('div'),over=document.createElement('div');
    media.className='bill-art-media';over.className='bill-art-over';
    fig.classList.add('hero');fig.prepend(media);media.append(img,over);over.append(pills,h1);
    const num=h1.querySelector('.bill-h1-number');
    if(!heroFits(h1.getBoundingClientRect().height,num?num.getBoundingClientRect().height:0,parseFloat(getComputedStyle(h1).lineHeight)))unheroBillArt(fig);
  }
  if(focused&&document.activeElement!==h1)h1.focus({preventScroll:true});
}
const HERO_WIDE=typeof matchMedia==='function'?matchMedia(HERO_MEDIA):{matches:false,addEventListener(){}};
let billArtFrame=0;
if(typeof addEventListener==='function')addEventListener('resize',()=>{cancelAnimationFrame(billArtFrame);billArtFrame=requestAnimationFrame(layoutBillArt)});

async function copyText(text,label){
  try{await navigator.clipboard.writeText(text);toast(`${label} copied`)}catch{toast(`Copy failed. ${label}: ${text}`)}
}

function download(name,text,type){
  const u=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
}

function sharedBanner(){
  if(!state.sharedList)return '';
  const view=state.sharedMode==='sync-view';
  return `<div class="info-callout shared-banner"><div><strong>${view?'Shared watchlist (view-only)':'Shared list'} · ${state.sharedList.length} ${state.sharedList.length===1?'bill':'bills'}.</strong> ${view?'It stays current as its owner edits it.':'Opened from a link; your own watchlist is unchanged.'}</div><div class="tools-row"><button class="outline-button" id="shared-add">Add all to my watchlist</button><button class="outline-button" id="shared-close">Show all bills</button></div></div>`;
}

// Items a sync limit or a move kept aside are listed on the Export page; say so where saving is managed.
function keptNote(){const n=STORAGE_OK?heldCount(listStore):0;
  return n?`<p class="tools-note">${n} saved ${n===1?'item is':'items are'} kept aside because ${n===1?'it':'they'} did not fit a list limit or ${n===1?'was':'were'} not valid. <a class="text-link" href="#export" data-view="export">See them on the Export page</a>.</p>`:''}
function watchTools(){
  const linked=sync.linked,n=state.watch.size,none=n?'':'disabled';
  const syncPart=syncAvailable===false?'<p class="tools-note">Private sync links aren’t switched on for this site yet. Use a share link or a file to move your list for now.</p>'
    :linked?.editKey?`<p class="tools-note">This device is synced; changes save automatically.</p><div class="tools-row"><button class="outline-button" id="sync-copy-edit">Copy edit link</button><button class="outline-button" id="sync-copy-view">Copy view-only link</button><a class="outline-button" href="./api/sync/feed/${esc(linked.viewKey||'')}.xml" target="_blank" rel="noopener noreferrer">Watchlist RSS</a></div><p class="tools-note">Open the <strong>edit link</strong> on your other devices. Anyone who has it can change this list, so keep it private, like a password. The <strong>view-only link</strong> is safe to share.</p><div class="tools-row"><button class="text-button" id="sync-forget">Stop syncing on this device</button><button class="text-button danger" id="sync-delete">Delete sync link</button></div>`
    :`<p class="tools-note">Get a private link that keeps this watchlist the same on your phone, laptop and work computer. No account, email or name.</p><div class="tools-row"><button class="primary-button" id="sync-create" ${syncAvailable?'':'disabled'}>Create sync link</button></div><p class="tools-note">Already have one? Open it on this device.</p>`;
  const synced=Boolean(linked?.editKey);
  const syncState=synced?'Synced across your devices':'This device only';
  return `<details class="watch-save" id="watch-save"${state.watchSaveOpen?' open':''}><summary><span>Save, share and sync</span><span class="watch-sync-state${synced?' synced':''}">${syncState}</span></summary><div class="watch-tools">${keptNote()}<section><h3>Save and share</h3><p class="tools-note">Your watchlist is kept in this browser. To move it to another device or person:</p><div class="tools-row"><button class="outline-button" id="share-watch" ${none}>Copy share link</button><button class="outline-button" id="export-watch" ${n||state.follow.length||state.searches.length?'':'disabled'} title="Your watchlist, followed legislators and saved searches, in one file">Export file</button><button class="outline-button" id="import-watch">Import file</button><input type="file" id="import-watch-file" accept=".json,.txt,.csv,application/json,text/plain,text/csv" hidden></div><p class="tools-note">Each bill also has an RSS feed in its details, for following it in Outlook or a feed reader. <a href="#saving" data-view="saving">How saving works →</a></p></section><section><h3>Sync across devices</h3>${syncPart}</section></div></details>`;
}

async function handleSaveClick(target){
  const hit=sel=>target.closest(sel);
  if(hit('#copy-view-link')){persistState();return copyText(location.href,'Link to this view')}
  if(hit('#share-watch'))return copyText(siteBase()+buildHash('all',{},{list:[...state.watch]}),'Share link');
  if(hit('#export-watch')){download('texas-bill-atlas-saved.json',profileFile({watch:state.watch,follows:state.follow,searches:state.searches,theme:savedTheme()}),'application/json');return toast('Watchlist, followed legislators and saved searches exported')}
  if(hit('#import-watch')){$('#import-watch-file').click();return}
  if(hit('#shared-add')){const before=state.watch.size;changeWatch('add',state.sharedList);refreshWatch();return toast(`Added ${state.watch.size-before} bills to your watchlist`)}
  if(hit('#shared-close')){Object.assign(state,{sharedList:null,sharedMode:null,sharedSyncKey:null,visibleCount:30});return renderContent()}
  if(hit('#sync-create')){try{await sync.create(readWatch(listStore,storageKey),readFollows(listStore,followKey),readSearches(listStore,searchesKey));loadSaved();renderContent();toast('Sync link created. Copy the edit link to your other devices.')}catch(error){toast(error.message)}return}
  if(hit('#sync-copy-edit'))return copyText(siteBase()+'#watchlist?sync='+sync.linked.editKey,'Edit link');
  if(hit('#sync-copy-view'))return copyText(siteBase()+'#watchlist?sync='+sync.linked.viewKey,'View-only link');
  if(hit('#sync-forget')){sync.forget();renderContent();return toast('This device stopped syncing; your list stays here')}
  const del=hit('#sync-delete');
  if(del){
    if(del.dataset.armed!=='1'){del.dataset.armed='1';del.textContent='Click again to delete for every device';return}
    try{await sync.remove();renderContent();toast('Sync link deleted; your list stays on this device')}catch(error){toast(error.message)}
  }
}

async function importWatchlist(file){
  try{
    if(file.size>1024*1024)throw Error('Select a file smaller than 1 MB');
    const {bills,follows,searches,theme}=parseProfileFile(await file.text()),before=state.watch.size,followed=state.follow.length;
    if(theme){const id=setTheme(theme);if(sync.linked?.mode==='edit')sync.record('theme',id)}  // Like the bills below, a linked device syncs it.
    changeWatch('add',bills);changeFollow('follow',follows);
    const known=new Set(state.searches.map(s=>s.id)),added=searches.filter(s=>!known.has(s.id)).slice(0,Math.max(0,MAX_SEARCHES-state.searches.length));
    for(const s of added)changeSearch('save-search',s);
    refreshWatch();
    toast(`Added ${state.watch.size-before} of ${bills.length} bills${follows.length?`, ${state.follow.length-followed} of ${follows.length} legislators`:''}${searches.length?`, ${added.length} of ${searches.length} saved searches`:''}`);
  }catch(error){toast(`Import failed: ${error.message}`)}
}

async function loadRoster(){
  for(const url of ['./live/members.json','./data/members.json']){
    try{
      const response=await fetch(url,{cache:'no-cache',signal:timeoutSignal(7500)});
      if(!response.ok)throw httpError(response);
      const roster=await response.json();
      if(roster?.format!=='texas-bill-members-v1'||!roster.members||typeof roster.members!=='object'||Array.isArray(roster.members))throw Error('Unrecognized roster format');
      return roster;
    }catch(error){console.warn(`Member roster unavailable: ${url}`,error.message)}
  }
  return null;
}
// Luna's tags, extras, related bills, audit and updates, fetched together. Nothing waits on them, so the limit is
// longer than the bills' 7.5 seconds were: a slow phone gets Luna's data late rather than not at all.
async function fetchLuna(){
  const isMap=o=>o&&typeof o==='object'&&!Array.isArray(o);
  const load=async(name,format,valid)=>{
    try{
      const response=await fetch(`./live/luna/${name}.json`,{cache:'no-cache',signal:timeoutSignal(20000)});
      if(!response.ok)throw httpError(response);
      const body=await response.json();
      if(body?.format!==format||!valid(body))throw Error(`Unrecognized ${name} format`);
      return body;
    }catch(error){console.warn(`Luna ${name} unavailable`,error.message);return null}
  };
  const sharded=(name,format)=>loadShardedMap('./live/luna',name,format).catch(error=>{
    console.warn(`Luna ${name} shards unavailable`,error.message);return load(name,format,x=>isMap(x.bills))});
  const [tags,extras,related,audit,updates]=await Promise.all([
    sharded('tags','texas-bill-luna-tags-v1'),
    sharded('extras','texas-bill-luna-extras-v1'),
    load('related','texas-bill-related-v1',x=>isMap(x.bills)),
    load('audit','texas-bill-luna-audit-v1',x=>true),
    load('updates','texas-bill-luna-updates-v1',x=>Array.isArray(x.updates))]);
  return {tags,extras,related,audit,updates};
}
// Rebuild the bills from the loaded snapshot in the original order (tags, extras, then members) and redraw.
// A local import that replaced the snapshot meanwhile is kept: imported rows never carried Luna's data.
function applyLuna({tags,extras,related,audit,updates},base,snapshot){
  state.luna=tags?{...tags,agencies:isPlainMap(tags.agencies)?tags.agencies:{}}:null;
  state.related=related;state.audit=audit;state.lunaUpdates=updates;
  if(state.bills===snapshot){
    let bills=base;
    if(tags)bills=bills.map(b=>Object.hasOwn(tags.bills,b.id)&&isPlainMap(tags.bills[b.id])?applyLunaTags(b,tags.bills[b.id],state.luna.agencies):b);
    if(extras)bills=bills.map(b=>Object.hasOwn(extras.bills,b.id)?applyLunaExtras(b,extras.bills[b.id]):b);
    if(state.roster)bills=bills.map(b=>attachMembers(b,state.roster));
    state.bills=bills;
  }
  const y=window.scrollY,key=focusKey();
  renderNotice();renderOverview();
  // Someone typing a search keeps the box they are typing in; only the results redraw.
  // Redrawing an open bill page reuses its stage files already in flight instead of asking for them again.
  stageFiles.reuse=true;
  try{if(document.activeElement?.id==='bill-search'&&FILTERED_VIEWS.has(state.view))renderResults();else renderContent()}finally{stageFiles.reuse=false}
  // A redrawn bill page focuses its heading; put focus back where the reader had it.
  if(key&&document.activeElement?.id==='bill-page-title')document.querySelector(key)?.focus({preventScroll:true});
  if(y)window.scrollTo({top:y,behavior:'instant'});
}
const isPlainMap=o=>Boolean(o)&&typeof o==='object'&&!Array.isArray(o);
async function loadReviewStatus(){
  try{
    // The edge cache keeps this file for minutes whatever the origin says; a 15-second bucket in the query keeps the
    // live run view fresh while still letting the edge share one copy per bucket.
    const response=await fetch(`./live/luna/status.json?t=${Math.floor(Date.now()/15000)}`,{cache:'no-cache',signal:timeoutSignal(7500)});
    if(!response.ok)throw httpError(response);
    const status=await response.json();
    if(status?.format!=='texas-bill-luna-status-v1'||!Array.isArray(status.reviewed))throw Error('Unrecognized status format');
    state.reviewStatus=status;
  }catch(error){console.warn('Review status unavailable',error.message)}
}

function setNavOpen(open){
  $('.sidebar').classList.toggle('nav-open',open);
  const more=$('#nav-more');more.setAttribute('aria-expanded',String(open));more.querySelector('.nav-more-label').textContent=open?'Close':'More';
}
// push=true adds a history entry (opening a bill page), so the browser's Back returns to the page before it.
const PAGE_NAMES={home:'Home',all:'Bill explorer',watchlist:'Watchlist',following:'Following',today:'Today',local:'Near you',member:'Legislator',statute:'Section of law',agencies:'Agency index',review:'Review progress',method:'How it works',saving:'Saving your info',export:'Export your saved info',data:'Data & imports'};
// The tab title names the page (and the bill or member), so history, tabs and screen readers can tell views apart.
function namedHeading(view){
  if(view==='member'){const m=memberByCode(state.roster,state.memberCode);return m?esc(memberTitle(m)):null}
  if(view==='statute'&&state.statuteKey&&state.statutes)return esc(statuteLabel(state.statuteKey,state.statutes.codes));
  return null;
}
function refreshNamedHeading(){
  const h=namedHeading(state.view),el=$('#page-title');
  if(!h||!el||el.innerHTML===h)return;
  el.innerHTML=h;document.title=pageTitle(state.view);
}
function pageTitle(view){
  const bill=view==='bill'?state.bills.find(b=>b.id===state.openBill):null;
  const member=view==='member'?memberByCode(state.roster,state.memberCode):null;
  const statute=view==='statute'&&state.statuteKey&&state.statutes?statuteLabel(state.statuteKey,state.statutes.codes):null;
  const name=bill?bill.number:member?memberTitle(member):statute||PAGE_NAMES[view]||'Bill explorer';
  return `${name} · Texas Bill Atlas`;
}
let viewReady=false;  // Set after the first view is drawn; the first load keeps focus where the browser put it.
function setView(view,push=false,{focus=true}={}){
  switchFilters(view);
  state.view=view;
  if(view!=='bill')state.openBill=null;
  setNavOpen(false);
  preview.id=null;
  document.querySelectorAll('[data-view]').forEach(el=>{el.classList.toggle('active',el.dataset.view===view);if(el.classList.contains('nav-item')){if(el.dataset.view===view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current')}});
  document.title=pageTitle(view);
  const [title,subtitle]=viewHeading(view);
  $('#page-title').innerHTML=namedHeading(view)||title;$('#page-subtitle').textContent=subtitle;
  // A bill page has its own header in place of the page heading.
  $('.page-heading').hidden=view==='bill';
  $('#overview').hidden=!['all','watchlist'].includes(view);
  renderNotice();renderOverview();renderContent();persistState(push);
  // A new view starts at its top; arriving back from a bill, applyLocation restores the old place after this.
  window.scrollTo({top:0,behavior:'instant'});
  // A new view is announced by moving focus to its heading; the bill page focuses its own title.
  if(viewReady&&focus&&view!=='bill'){const h=$('#page-title');if(h){h.tabIndex=-1;h.focus({preventScroll:true})}}
}

function renderNotice(){
  const unavailable=state.meta?.data_mode==='unavailable';
  const imported=state.meta?.data_mode==='local import';
  const fallback=state.meta?.loaded_from==='Bundled fallback snapshot';
  const age=unavailable||imported?null:snapshotAgeHours(state.meta?.generated_at);
  const stale=age!==null&&age>8;
  const ageText=age>=48?`${Math.floor(age/24)} days`:`${Math.floor(age)} hours`;
  const staleCopy=stale?` <strong>Stale: this snapshot is ${ageText} old.</strong> The automated refresh may have stopped; check the official record for current status.`:'';
  const fileName=state.meta?.source_file||String(state.meta?.coverage_note||'').replace(/^Local file:\s*/,'').replace(/\.\s*Imported rows.*$/,'');
  const copy=unavailable?'<strong>Dataset unavailable.</strong> '+esc(state.meta.coverage_note):imported?`<strong>Local file, not official data.</strong> Showing rows imported from ${esc(fileName)}; they have not been verified against the legislature’s published files.`:fallback?`<strong>Showing the bundled copy.</strong><span class="notice-more"> The live dataset could not be loaded, so this is the bundled snapshot generated ${esc(stampText(state.meta.generated_at))}; it may be out of date.${staleCopy}</span>`:stale?`<strong>Bulk-data snapshot may be out of date.</strong> Generated ${esc(stampText(state.meta.generated_at))}.${staleCopy}`:'<strong>Bulk-data snapshot.</strong> Derived from the legislature’s published files; changes may lag the official record.';
  const warn=unavailable||imported||fallback||stale;
  // A healthy live snapshot gets one slim line; anything to be careful about keeps the full box.
  const slim=!warn;
  $('#source-notice').className=`source-notice${warn?' warn':''}${slim?' slim':''}`;
  $('#source-notice').innerHTML=`<span class="notice-icon">${warn?'!':'✓'}</span><div>${slim?'<strong>Bulk-data snapshot</strong> from the legislature’s published files; it may lag the official record.':copy} <a href="#data" data-view="data">Coverage & sources →</a></div>`;
  $('#footer-timestamp').textContent=`${imported?'Imported':'Snapshot'}: ${stampText(state.meta?.generated_at)}`;
}

function renderOverview(){
  const bills=state.view==='watchlist'?state.bills.filter(b=>state.watch.has(b.id)):state.bills;
  const scheduled=bills.filter(b=>assessHearing(b).level===3).length;
  const day=new Date().toLocaleDateString('sv-SE',{timeZone:'America/Chicago'});
  const today=bills.filter(b=>b.filed_at===day).length;
  const part=(n,one,many,title)=>`<span title="${title}"><strong>${n.toLocaleString()}</strong> ${n===1?one:many}</span>`;
  $('#overview').innerHTML=[state.view==='watchlist'?part(bills.length,'bill watched','bills watched','Bills on your watchlist'):part(bills.length,'bill in this snapshot','bills in this snapshot','Before any filters'),
    part(today,'filed today','filed today','According to the filing dates in the data'),
    part(scheduled,'hearing scheduled','hearings scheduled','Confirmed by recorded actions')].join('<span aria-hidden="true">·</span>');
  $('#nav-all').textContent=state.bills.length;
  const doneToday=activityOn(state.bills,todayDay()).length,todayCount=$('#nav-today');
  if(todayCount){todayCount.textContent=doneToday;todayCount.hidden=!doneToday}
  $('#nav-watch').textContent=state.watch.size;
  $('#nav-follow').textContent=state.follow.length+state.searches.length;
  const progress=reviewProgress(state.bills.map(b=>b.id),state.reviewStatus,Object.keys(state.luna?.bills||{}));
  $('#nav-review').textContent=progress.reviewed.length+progress.inProgress.length;
}

// A redraw replaces the control that had focus; this finds its replacement so keyboard users keep their place.
const FOCUS_KEYS=['data-watch','data-topic','data-today-topic','data-open','data-clear-filter','data-watch-group','data-bill-jump'];
function focusKey(){
  const el=document.activeElement;
  if(!el||el===document.body||el.id==='page-title')return null;
  if(el.id)return `#${CSS.escape(el.id)}`;
  const a=FOCUS_KEYS.find(k=>el.hasAttribute(k));
  return a?`${el.tagName.toLowerCase()}[${a}="${CSS.escape(el.getAttribute(a))}"]`:null;
}
function keepFocus(draw){
  const key=focusKey();draw();
  const now=document.activeElement;
  if(key&&(!now||now===document.body))document.querySelector(key)?.focus({preventScroll:true});
}
function renderContent(){keepFocus(()=>renderView(state.view,$('#dynamic-content')));refreshNamedHeading()}

// Each view's heading and content. Features take theirs over as they move into src/features/.
function registerViews(){
  registerView('home',{heading:['This session, at a glance.','What changed on your bills, what moved today, upcoming hearings and Luna’s newest reviews.'],render:homeMarkup});
  registerView('all',{heading:['See what’s moving.','Track legislation by policy, affected agency, author influence, and its path through the Capitol.'],render:explorerMarkup,after:renderResults});
  registerView('watchlist',{heading:['Your watchlist.','Bills you starred on this device, with a clear view of their movement.'],render:explorerMarkup,after:renderResults});
  registerView('following',{heading:['Following.','Legislators you follow on this device, and every bill they file or sign onto.'],render:followingMarkup});
  registerView('today',{heading:['Today at the Lege.','Bills with a recorded action that day, by type of action. Dates follow Texas time.'],render:()=>todayMarkup({dateText,todayRow})});
  registerView('local',{heading:['Near you.','Your Texas House member and Senator, what they filed, and bills that name your county or city.'],render:nearMarkup});
  registerView('member',{heading:['One legislator.','A member’s district and the bills they author, coauthor or sponsor in this snapshot.'],render:memberMarkup});
  registerView('statute',{heading:['One section of law.','The bills that would amend, add or repeal this section of Texas law, with their wording side by side.'],render:()=>statuteMarkup({renderContent,billHref})});
  registerView('bill',{heading:['One bill.','Its summary, text, changes to law, people, agencies and sources.'],render:()=>'<article class="bill-page" id="bill-page" aria-label="Bill details"></article>',after:fillBillPage});
  registerView('agencies',{heading:['Follow the agencies.','Explore where legislation might land across Texas government.'],render:agenciesMarkup});
  registerView('review',{heading:['Full-text review.','Which bills Luna has read in full, which it is working on, and what is still waiting.'],render:()=>reviewMarkup({stampText,dateText,changeCounts,changeRows,todayRow})});
  registerView('method',{heading:['How the atlas works.','Signals and uncertainty are displayed separately from verified legislative actions.'],render:methodMarkup});
  registerView('saving',{heading:['Save your work.','Keep your watchlist and views on one device, carry them in a link or file, or sync them privately.'],render:()=>savingMarkup({linked:sync.linked,syncAvailable})});
  registerView('export',{heading:['Export your saved info.','Everything this browser has saved, in one file you can keep or import on another device.'],render:()=>exportMarkup({watch:state.watch,follows:state.follow,searches:state.searches,theme:savedTheme(),memberName:code=>{const m=memberByCode(state.roster,code);return m?memberTitle(m):null},synced:Boolean(sync.linked?.editKey),kept:STORAGE_OK?heldCount(listStore):0,previous:STORAGE_OK?previousLinks(listStore):[]})});
  registerView('data',{heading:['Behind the tracker.','Understand coverage, refreshes, and how to load or export bill data.'],render:()=>dataMarkup({stampText,reviewParts})});
  setFallbackView('data');
}

function options(values,selected,placeholder){return `<option value="">${esc(placeholder)}</option>`+values.map(v=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(v)}</option>`).join('')}

// The agency dropdown's sort, A-Z or most bills first; remembered in this browser only.
const AGENCY_SORT_KEY='tx-bill-atlas-agency-sort';
function agencySortMode(){
  if(!state.agencySort){try{state.agencySort=localStorage.getItem(AGENCY_SORT_KEY)==='count'?'count':'name'}catch{state.agencySort='name'}}
  return state.agencySort;
}
function agencyOptionsMarkup(){
  const agencyCounts=new Map();
  for(const bill of state.bills)for(const agency of bill.agencies)agencyCounts.set(agency.id,(agencyCounts.get(agency.id)||0)+1);
  const {withBills,withoutBills}=groupAgencyIds(unique([...AGENCIES.map(a=>a.id),...Object.keys(state.luna?.agencies||{})]),agencyName,agencyCounts,agencySortMode());
  const option=(id,i)=>`<div id="agency-option-${i+1}" role="option" class="agency-option" data-agency-option="${esc(id)}" data-agency-label="${esc(agencyName(id))}" aria-selected="${state.agency===id}"><span>${esc(agencyName(id))}</span><span class="agency-option-count">${agencyCounts.get(id)||0}</span></div>`;
  const emptyGroup=withoutBills.length?`<div role="group" aria-labelledby="agency-group-empty" data-agency-group><div class="agency-group-label" id="agency-group-empty" role="presentation">No bills in this snapshot</div>${withoutBills.map((id,i)=>option(id,withBills.length+i)).join('')}</div>`:'';
  return `<div id="agency-option-0" role="option" class="agency-option" data-agency-option="" data-agency-label="All affected agencies" aria-selected="${!state.agency}"><span>All affected agencies</span></div>${withBills.map(option).join('')}${emptyGroup}<p class="agency-no-results" id="agency-no-results" hidden>No matching agencies</p>`;
}
function agencySortButtons(){
  const mode=agencySortMode();
  return [['name','A–Z'],['count','Most bills']].map(([value,label])=>`<button type="button" data-agency-sort="${value}" aria-pressed="${mode===value}">${label}</button>`).join('');
}

const SEARCH_EXAMPLES=[...SEARCH_FIELDS.filter(f=>f.example).map(f=>f.example),'"minimum wage"'];
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
// The explorer's filters as restored from the last visit; the chips say so until any of them changes.
let restoredFilters=null;
function activeFiltersMarkup(){
  const set=activeFilters();
  if(!set.length)return '';
  const restored=state.view==='all'&&restoredFilters&&sameFilters(restoredFilters,state);
  return `${restored?'<span class="restored-note">Filters from your last visit:</span>':''}${set.map(([key,label])=>`<button type="button" class="filter-chip" data-clear-filter="${key}" aria-label="Remove filter: ${esc(label)}">${esc(label)} <span aria-hidden="true">×</span></button>`).join('')}<button type="button" class="text-button" id="clear-filters">Clear all</button>`;
}
// What to try when nothing matches: drop the filters, or search every bill for the same words.
function emptyNextSteps(){
  const filters=activeFilters().filter(([key])=>key!=='query');
  const steps=[filters.length?'<button type="button" class="outline-button" data-clear-all>Clear all filters</button>':'',
    state.query&&(filters.length||state.view!=='all')?`<a class="outline-button" href="${esc(buildHash('all',{query:state.query}))}">Search every bill for “${esc(state.query)}”</a>`:'',
    state.view==='watchlist'&&!state.watch.size?'<a class="outline-button" href="#all" data-view="all">Browse all bills</a>':''].filter(Boolean);
  return steps.length?`<p class="empty-steps">${steps.join('')}</p>`:'';
}
function clearFilter(key){
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
  const agencies=topAgencies(bills,3,new Set([SCOPE_AGENCY_ID])).map(a=>`<a class="text-link" href="${esc(buildHash('all',{area:area.id,agency:a.id}))}">${esc(agencyName(a.id))}</a> (${a.count.toLocaleString()})`).join(', ');
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
function explorerMarkup(){
  const topics=unique([...POLICY_AREAS.map(t=>t.name),...state.bills.flatMap(b=>b.topics)]).sort();
  const popular=['Education','Healthcare','Elections','Taxes','Immigration','Data centers','Local government','Energy & utilities'];
  return `${sharedBanner()}${state.view==='watchlist'?watchTools():''}
    <section class="area-header" id="area-header" aria-label="Reader area" hidden></section><div class="explorer-controls"><div class="search-row"><div class="search-wrap"><input aria-label="Search bills" id="bill-search" maxlength="200" placeholder="Search bill number, author, subject, or keyword…" value="${esc(state.query)}" autocomplete="off"></div><details class="share-menu" id="share-menu"><summary class="outline-button">Share / save</summary><div class="share-panel"><button type="button" id="copy-view-link" title="Copy a link to this view, with its filters">Copy link</button>${state.view==='all'&&!state.sharedList?'<button type="button" id="save-search" title="Keep this search and its filters under Following">Save search</button>':''}<button type="button" id="export-csv">↓ Export results (CSV)</button></div></details></div><details class="search-help"><summary>What search looks at</summary><p>Every word you type has to appear somewhere in the bill, in any order. It looks in: ${SEARCH_FIELDS.map(f=>esc(f.label)).join(', ')}. Luna's search terms are words it added to help find a bill; they are not shown on the card, so each result says which field matched.</p><p>Put words in "double quotes" to keep them together. A plural also finds the singular ("wages" finds "wage"). A section number such as <em>Penal Code 46.06</em> finds the bills that change it.</p><p class="search-examples">Try: ${SEARCH_EXAMPLES.map(x=>`<button type="button" class="search-example" data-search-example="${esc(x)}">${esc(x)}</button>`).join('')}</p></details>
    ${watchFiltersOpen()}<div class="filter-bar"><div class="filter-row">${areaSelect()}<select aria-label="Policy area" id="filter-topic">${options(topics,state.topic,'All policy areas')}</select><select aria-label="Chamber" id="filter-chamber">${options(['House','Senate'],state.chamber,'Both chambers')}</select><select aria-label="Stage" id="filter-stage">${options(['Filed','Referred','Scheduled','Heard','Advanced','Passed','Enacted','Vetoed'],state.stage,'Any stage')}</select><button class="check-filter ${state.companion?'selected':''}" id="companion-filter" aria-pressed="${state.companion}" title="Only bills with an identical or similar bill filed in the other chamber">⇄ Has companion</button></div><details class="more-filters" id="more-filters"${moreFiltersOpen()?' open':''}><summary class="outline-button">More filters<span id="more-count">${moreCountText()}</span></summary><div class="filter-row more-row"><div class="agency-combobox" id="agency-combobox"><input aria-label="Affected agency" aria-controls="agency-options" aria-expanded="false" aria-autocomplete="list" role="combobox" id="filter-agency" placeholder="All affected agencies" value="${esc(state.agency?agencyName(state.agency):'')}" autocomplete="off"><span class="agency-chevron" aria-hidden="true">⌄</span><div class="agency-panel" id="agency-panel" hidden><div class="agency-sort" role="group" aria-label="Sort agencies">${agencySortButtons()}</div><div class="agency-options" id="agency-options" role="listbox" hidden>${agencyOptionsMarkup()}</div></div></div><select aria-label="Author party" id="filter-party" title="Republican or Democratic: the primary author's party, with no author or coauthor from the other party. Bipartisan: authors or coauthors from both parties.">${options(Object.keys(PARTY_FILTERS),state.party,'Any party')}</select><select aria-label="Hearing status" id="filter-outlook">${options([NO_HEARING,'Referred','Scheduled','Heard'],state.outlook,'Hearing status')}</select><select aria-label="Last action" id="filter-action">${options(unique([...LAST_ACTION_TYPES.map(t=>t.label),'Other action']).filter(l=>l===state.action||state.bills.some(b=>lastActionInfo(b).label===l)),state.action,'Any last action')}</select><button class="check-filter ${state.onlyWatch?'selected':''}" id="watch-filter">☆ Watched only</button></div></details></div>${state.view==='watchlist'?'</details>':''}</div>
    ${state.view==='watchlist'?'':`<div class="topic-strip" aria-label="Quick topic filters"><button class="topic-chip ${state.topic===''?'selected':''}" data-topic="">All topics</button>${popular.map(t=>`<button class="topic-chip ${state.topic===t?'selected':''}" data-topic="${esc(t)}">${esc(t)}</button>`).join('')}</div>`}
    <div class="active-filters" id="active-filters" aria-label="Active filters"></div><div class="results-header"><div><strong id="result-count">—</strong><span id="result-note"></span></div><select id="sort-order" aria-label="Sort bills">${options(Object.values(SORTS),SORTS[state.sort],'Sort by')}</select></div><div class="explorer-results" id="explorer-results"><div class="bill-list" id="bill-list"></div><aside class="bill-preview" id="bill-preview" aria-labelledby="preview-title" hidden></aside></div><div class="explorer-bottom" id="results-bottom"></div>`;
}

function headlineLine(b,where){
  if(typeof b.headline!=='string'||!b.headline)return '';
  return `<p class="bill-headline ${where}"><span class="headline-label">In brief</span> <span class="ai-badge" title="Written by Luna, the AI model that reads each bill’s full text; not official. How it works explains more.">AI</span> <span class="headline-text"${where==='card'?` title="${esc(b.headline)}"`:''}>${esc(b.headline)}</span></p>`;
}
function relatedBlock(b){
  const known=new Set(state.bills.map(x=>x.id));
  const ids=relatedFor(b.id,state.related,known);
  if(!ids.length)return '';
  return `<section class="drawer-section related-section"><h3>Related bills</h3><div class="review-chips">${ids.map(id=>`<button class="review-chip" data-open="${esc(id)}">${esc(id)}</button>`).join('')}</div><p><small>Similar captions and Luna summaries; computed automatically.</small></p></section>`;
}

const lawKeysFor=query=>state.statutes?statuteKeysFor(state.statutes,parseStatuteQuery(query,state.statutes.codes)):[];

// What a card shows about its authors' parties ("Republican author"), so a search can find it.
const partyWords=b=>{if(!b.people)return[];const p=authorshipParty(b);return[p.label,p.detail]};

const billSearchFields=b=>searchFields(b,{agencyName,partyWords,shortDate});
// Each bill's search text, kept across keystrokes. Bills are replaced, not edited, when their data changes; agency
// names also come from Luna's file, so a new one starts the cache over.
const searchTextCache={luna:undefined,texts:new WeakMap()};
function billSearchText(b){
  if(searchTextCache.luna!==state.luna)Object.assign(searchTextCache,{luna:state.luna,texts:new WeakMap()});
  let text=searchTextCache.texts.get(b);
  if(text===undefined){text=searchText(billSearchFields(b));searchTextCache.texts.set(b,text)}
  return text;
}
// Why a shown result matched the explorer's search words, in the same order of checks as filteredBills.
function reasonFor(){
  const {q,compact}=searchTerms(state.query||'');
  if(!q)return ()=>null;
  const lawBills=new Set(lawKeysFor(state.query).flatMap(k=>state.statutes.sections[k].b.map(p=>p[0])));
  return b=>matchReasons(billSearchFields(b),q,lawBills.has(b.id)?'law':b.id.toLowerCase().includes(compact)?'number':'');
}
const reasonLine=reasons=>reasons?.length?`<p class="match-reason"><span>Matched:</span> ${reasons.map(r=>`<span${r.label==='Luna search term'?' title="Words Luna added to help search find this bill; they are not shown on the card"':''}>${esc(r.label)}${r.term?` <mark>${esc(r.term)}</mark>`:''}</span>`).join(' · ')}</p>`:'';

// The explorer's list for its own filters, or for a saved search's (`f`: the explorer as a plain, unshared view).
function filteredBills(f=state){
  const own=f===state;
  const shared=own&&state.sharedList?new Set(state.sharedList):null;
  const {q,compact}=searchTerms(f.query||'');
  // A section number ("48.160", "Penal Code 46.06") also finds the bills that change that section.
  const lawBills=new Set(lawKeysFor(f.query).flatMap(k=>state.statutes.sections[k].b.map(p=>p[0])));
  let list=state.bills.filter(b=>{
    if(shared&&!shared.has(b.id))return false;
    if(own&&state.view==='watchlist'&&!state.watch.has(b.id))return false;
    if(f.onlyWatch&&!state.watch.has(b.id))return false;
    if(f.companion&&!companionsOf(b.id).length)return false;
    if(f.area&&!inArea(b,f.area))return false;
    if(f.topic&&!b.topics.includes(f.topic))return false;
    if(f.agency&&!b.agencies.some(a=>a.id===f.agency)&&!agencyVia(f.agency).has(b.id))return false;
    if(f.chamber&&b.chamber!==f.chamber)return false;
    if(!partyFilterMatches(b,f.party))return false;
    if(f.outlook&&assessHearing(b).label!==f.outlook)return false;
    if(f.action&&lastActionInfo(b).label!==f.action)return false;
    if(f.stage){const st=(b.status||'').toLowerCase();const outlook=assessHearing(b).label.toLowerCase();if(!st.includes(f.stage.toLowerCase())&&outlook!==f.stage.toLowerCase())return false}
    if(lawBills.has(b.id))return true;
    return !q||b.id.toLowerCase().includes(compact)||textMatches(billSearchText(b),q);
  });
  const byNumber=(a,b)=>a.id.localeCompare(b.id,undefined,{numeric:true});
  const newerNumber=(a,b)=>newestFirst(a.id,b.id);
  const info=new Map(list.map(b=>[b.id,lastActionInfo(b)]));const la=b=>info.get(b.id);
  // Filing dates have no time, so within a day the higher number in each bill type was filed later.
  const sorters={newest:(a,b)=>(b.filed_at||'').localeCompare(a.filed_at||'')||newerNumber(a,b),
    latest:(a,b)=>(la(b).date||'').localeCompare(la(a).date||'')||la(b).rank-la(a).rank||byNumber(a,b),
    oldest:(a,b)=>(la(a).date||'9').localeCompare(la(b).date||'9')||la(a).rank-la(b).rank||byNumber(a,b),
    actionstage:(a,b)=>la(b).rank-la(a).rank||(la(b).date||'').localeCompare(la(a).date||'')||byNumber(a,b),number:byNumber,agencies:(a,b)=>realAgencies(b).length-realAgencies(a).length||byNumber(a,b),hearing:(a,b)=>assessHearing(b).level-assessHearing(a).level||byNumber(a,b),influence:(a,b)=>authorInfluence(b).level-authorInfluence(a).level||byNumber(a,b)};
  return list.sort(Object.hasOwn(sorters,f.sort)?sorters[f.sort]:sorters.newest);  // own keys only: "__proto__" is not a sort
}

function renderResults(){keepFocus(drawResults)}
function drawResults(){
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
  $('#bill-list').innerHTML=statuteHintMarkup(state.sharedList?[]:lawKeysFor(state.query))+(list.length?shown.map(g=>g.length>1?groupMarkup(g):card(g[0])).join(''):`<div class="empty-state"><h3>Nothing matches yet</h3><p>${state.view==='watchlist'&&!state.watch.size?'Star bills from the explorer to follow them here.':'Try a broader topic, agency, or keyword.'}</p>${emptyNextSteps()}${state.view==='watchlist'?'':TUMBLEWEED}</div>`);
  $('#results-bottom').innerHTML=`${list.length>shownCount?`<button class="outline-button" id="load-more">Load 30 more · showing ${shownCount} of ${list.length}</button><div style="height:12px"></div>`:''}${esc(state.meta?.coverage_note||'Check the official record for authoritative status.')}`;
  persistState();
  syncPreview();
  const chips=$('#active-filters');if(chips)chips.innerHTML=activeFiltersMarkup();
  const more=$('#more-count');if(more)more.textContent=moreCountText();
}

// ---- Preview (D2-B): a short look at one bill beside the results, for triage. Wide screens only; it holds no
// sections and no text, and every link in it still goes to the bill page.
const PREVIEW_WIDE=typeof matchMedia==='function'?matchMedia('(min-width: 1200px)'):{matches:false,addEventListener(){}};
const preview={id:null};
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
function showPreview(id){preview.id=id;syncPreview();$('#preview-title')?.focus({preventScroll:true})}
function closePreview(){
  const id=preview.id;preview.id=null;syncPreview();
  if(id)$(`#bill-list .bill-card[data-bill-id="${CSS.escape(id)}"] .bill-title-link`)?.focus({preventScroll:true});
}
function stepPreview(by){
  let cards=[...document.querySelectorAll('#bill-list .bill-card')];const at=cards.findIndex(c=>c.dataset.billId===preview.id);
  if(at<0)return;
  if(by>0&&!cards[at+by]&&cards.length<filteredBills().length){state.visibleCount+=30;renderResults();cards=[...document.querySelectorAll('#bill-list .bill-card')]}
  const next=cards[at+by];
  if(!next)return;
  next.scrollIntoView({block:'nearest'});showPreview(next.dataset.billId);
}
PREVIEW_WIDE.addEventListener('change',()=>syncPreview());

// D5: a card shows the caption only when it says more than the title, and a count only when it is above zero.
const sameText=(a,b)=>{const n=x=>String(x||'').toLowerCase().replace(/[.\s]+$/,'').replace(/\s+/g,' ').trim();return n(a)===n(b)};
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

// ---- Home: the dashboard. Search first, then what changed on your bills, the latest day's actions, hearings and reviews.
const HOME_ROWS=5,SESSION_START='2027-01-12';
// One line per bill: number, plain-language summary, and a short note (topic, action or review) on the right.
function compactRow(b,note=''){
  return `<article class="compact-row" data-bill-id="${esc(b.id)}"${topicStyle(b.topics)}>${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="compact-text">${openLinkHtml(b.id,billHref(b.id),'bill-title-link',plainTitle(b))}</span>${note?`<span class="compact-note" title="${esc(note)}">${esc(note)}</span>`:''}</article>`;
}
function homeMarkup(){
  return `<div class="home-top"><form class="home-search" id="home-search-form" role="search"><label for="home-search">Search every bill</label><div class="home-search-row"><input id="home-search" name="query" maxlength="200" placeholder="Bill number, author, subject, agency or keyword…" autocomplete="off"><button class="primary-button" type="submit">Search</button></div><p class="tools-note">Or <a class="text-link" href="#all" data-view="all">browse all ${state.bills.length.toLocaleString()} bills</a>.</p></form>
    <div class="calendar-mini home-milestone"><div class="calendar-eyebrow">UPCOMING MILESTONE</div><div class="calendar-date">JAN 12 <span>2027</span></div><div class="calendar-desc">90th regular session convenes${daysUntil(todayDay(),SESSION_START)?` · in ${daysUntil(todayDay(),SESSION_START)} days`:''}</div><div class="calendar-progress"><span></span></div></div></div>
    <div class="home-grid">${homeCards()}</div>`;
}
// Redraws the dashboard's cards only, so a sync or watch change never clears what is typed in its search box.
function refreshHome(){const grid=$('.home-grid');if(grid)grid.innerHTML=homeCards();else renderContent()}
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
  const searchList=searches.length?`<ul class="home-searches">${searches.map(({s,fresh})=>`<li><a class="text-link" href="${esc(buildHash('all',s.filters))}" data-search-open="${esc(s.id)}">${esc(s.name)}</a> · ${fresh.toLocaleString()} with new actions</li>`).join('')}</ul>`:'';
  const yours=!mine.length&&!state.searches.length
    ?`<p class="tools-note">Star bills, follow legislators or save a search, and what changes for them shows up here.</p>`
    :`${changed.length?changed.slice(0,HOME_ROWS).map(datedRow).join(''):`<p class="tools-note">No new actions on your ${mine.length.toLocaleString()} ${mine.length===1?'bill':'bills'}${prev?` since ${esc(dateText(prev))}`:''}.</p>`}${changed.length>HOME_ROWS?`<p class="tools-note">And ${(changed.length-HOME_ROWS).toLocaleString()} more on your <a class="text-link" href="#watchlist" data-view="watchlist">watchlist</a> and under <a class="text-link" href="#following" data-view="following">Following</a>.</p>`:''}${searchList}`;
  const yoursTitle=prev?`Since your last visit, ${esc(shortDate(prev))}`:'Latest on your bills';
  // The latest day with activity, as on the Today page (unfiltered by its topic chips).
  const {day,rows}=todayData({dateText});
  const types=groupByActionType(rows);
  const counts=types.length>1?`<p class="home-counts">${types.map(g=>`<span><strong>${g.rows.length.toLocaleString()}</strong> ${esc(g.label.toLowerCase())}</span>`).join('')}</p>`:'';
  const dayShown=rows.slice(0,HOME_ROWS+1),dayIds=new Set(dayShown.map(r=>r.bill.id));
  const dayBody=rows.length?`${counts}${dayShown.map(r=>compactRow(r.bill,r.bill.topics[0]||'')).join('')}${more('#today','today','The whole day, by topic')}`:'<p class="tools-note">No recorded activity yet.</p>';
  const hearings=state.bills.filter(b=>assessHearing(b).level===3);
  const hearingBody=hearings.length?hearings.slice(0,HOME_ROWS).map(b=>compactRow(b,lastActionInfo(b).label)).join('')+(hearings.length>HOME_ROWS?more(buildHash('all',{outlook:'Scheduled'}),'','All scheduled hearings'):'')
    :'<p class="tools-note">No hearings are scheduled yet. Committees post them once the session is under way.</p>';
  // Luna's reviews: what changed in the last 24 hours, then the newest reviews; a bill shows once, and not at all
  // when the Today card already lists it.
  const lunaChanged=recentChanges(state.lunaUpdates,Date.now());
  const byId=new Map(state.bills.map(b=>[b.id,b]));
  const luna=new Map(lunaChanged.bills.filter(r=>byId.has(r.id)).map(r=>[r.id,{bill:byId.get(r.id),note:r.changes.length?changeText(r.changes[0]):''}]));
  for(const b of newestReviewed(state.bills).slice(0,20))if(!luna.has(b.id))luna.set(b.id,{bill:b,note:`Reviewed ${shortDate(b.luna.reviewed_at.slice(0,10))}`});
  const lunaRows=[...luna.values()].filter(r=>!dayIds.has(r.bill.id));
  const lunaBody=lunaRows.length?`${lunaChanged.bills.length?changeCounts(lunaChanged.counts):''}${lunaRows.slice(0,HOME_ROWS+1).map(r=>compactRow(r.bill,r.note)).join('')}${more('#review','review','Every review and change')}`
    :'<p class="tools-note">Luna has not reviewed any bills yet.</p>';
  const tile=(n,label,href,view)=>href
    ?`<a class="stat-tile" href="${esc(href)}"${view?` data-view="${view}"`:''}><strong>${n.toLocaleString()}</strong><span>${label}</span></a>`
    :`<div class="stat-tile"><strong>${n.toLocaleString()}</strong><span>${label}</span></div>`;
  const stats=`<div class="home-stats">${tile(rows.length,day===today?'bills with action today':`bills with action ${esc(shortDate(day))}`,'#today','today')}${tile(lunaChanged.bills.length,'bills Luna reviewed or updated, last 24 hours','#review','review')}${tile(hearings.length,hearings.length===1?'hearing scheduled':'hearings scheduled',hearings.length?buildHash('all',{outlook:'Scheduled'}):'','')}</div>`;
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
    <a class="area-row" href="${esc(buildHash('all',{area:area.id}))}">
      <span class="area-row-name">${esc(area.name)}</span>
      <span class="area-count">${count.toLocaleString()} ${count===1?'bill':'bills'}</span>
      <span class="area-track" aria-hidden="true"><i style="width:${100*count/largest}%"></i></span>
      ${moved?`<span class="area-moved">${moved.toLocaleString()} moved</span>`:''}
    </a></li>`;
  return `<section class="home-card home-areas"><h2>Browse by area</h2><p class="tools-note">Areas use the Legislature’s subject index. Bars compare bill counts across all areas. “Moved” means a bill had an action in the last 7 days.</p><div class="area-groups">${AREA_GROUPS.map(g=>`<div><h3>${esc(g)}</h3><ul class="area-list">${rows.filter(r=>r.area.group===g).map(item).join('')}</ul></div>`).join('')}</div></section>`;
}
// Luna change counts as one line, and bills with what changed for each (bills not in the snapshot are skipped).
function changeCounts(counts){return `<p class="home-counts">${counts.map(c=>`<span><strong>${c.n.toLocaleString()}</strong> ${esc(c.label)}</span>`).join('')}</p>`}
function changeRows(rows,limit){
  const byId=new Map(state.bills.map(b=>[b.id,b]));
  const shown=rows.filter(r=>byId.has(r.id));
  return `<div class="today-list">${shown.slice(0,limit).map(r=>todayRow({bill:byId.get(r.id),actions:r.changes.map(changeText)})).join('')}</div>${shown.length>limit?`<p class="tools-note">And ${(shown.length-limit).toLocaleString()} more.</p>`:''}`;
}

// `by`: also name who filed the bill (the Today page; member pages and Near you already say whose bills they are).
function todayRow({bill:b,actions},{by=false}={}){
  const real=realAgencies(b);
  return `<article class="today-row" data-bill-id="${esc(b.id)}"${topicStyle(b.topics)}><div class="today-row-head">${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="chamber-pill">${esc(b.chamber)}</span>${openLinkHtml(b.id,billHref(b.id),'bill-title-link',b.title)}</div>${headlineLine(b,'card')}<div class="today-meta"><p class="today-action">${actions.map(esc).join(' · ')}</p>${by&&b.author?`<span class="today-by">by ${filerHtml(b)}</span>`:''}<div class="bill-tags">${b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}${real.slice(0,2).map(a=>`<span class="tag agency">${esc(agencyName(a.id).replace(/^Texas /,'').replace(/ Department of /,' · '))}</span>`).join('')}</div></div></article>`;
}

// ---- Near you: the visitor's own legislators and the bills tied to them. Location stays in this browser. ----
const NEAR_FILES={house:'./data/geo/house.json',senate:'./data/geo/senate.json',counties:'./data/geo/counties.json',tables:'./data/geo/districts.json'};
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
function saveNear(near){
  state.near=cleanNear(near,state.nearGeo?.tables);state.nearPick=null;state.nearShow={members:5,area:5};
  if(state.near)writeJson(NEAR_KEY,state.near);else{try{localStorage.removeItem(NEAR_KEY)}catch{}}
  renderContent();
}
function setNearFromPoint(lon,lat,accuracy,source){
  const p=placeFromPoint(state.nearGeo,lon,lat,{accuracy});
  if(p.error){state.nearBusy='';state.nearError='That location is outside Texas, so it has no Texas House or Senate district.';renderContent();return}
  state.nearBusy='';state.nearError='';saveNear({...p,source});
}
function nearLocate(){
  if(!navigator.geolocation){state.nearError='This browser cannot share a location; choose your county instead.';renderContent();return}
  state.nearBusy='Finding your location…';state.nearError='';renderContent();
  navigator.geolocation.getCurrentPosition(pos=>setNearFromPoint(pos.coords.longitude,pos.coords.latitude,pos.coords.accuracy,'location'),
    err=>{state.nearBusy='';state.nearError=err.code===1?'Location permission was declined. Choose your county or enter your districts instead.':'Your location could not be found. Choose your county or enter your districts instead.';renderContent()},
    {enableHighAccuracy:false,timeout:15000,maximumAge:600000});
}
function nearAddress(address){
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
function memberCard(chamber,district){
  const title=chamber==='house'?'Texas House':'Texas Senate';
  if(!district)return `<div class="near-member"><small>${title}</small><strong>District not set</strong></div>`;
  const people=membersFor(state.roster,chamber,district);
  if(!people.length)return `<div class="near-member"><small>${title} · District ${esc(district)}</small><strong>No member listed yet</strong><p><a class="text-link" href="https://capitol.texas.gov/Members/Members.aspx?Chamber=${chamber==='house'?'H':'S'}" target="_blank" rel="noopener noreferrer">Check Texas Legislature Online ↗</a></p></div>`;
  return people.map(m=>`<div class="near-member"><small>${title} · District ${esc(district)}</small><strong>${m.code?`<a class="text-link" href="${esc(memberHref(m.code))}">${esc(memberTitle(m))}</a>`:esc(memberTitle(m))}</strong><p>${tenurePill(m)} ${esc(m.party||'Party not recorded')}${tenureTag(m)?` · ${esc(tenureTag(m).detail)}`:''}</p>${m.code?`<p>${followButton(m)}</p><a class="text-link" href="${esc(memberHref(m.code))}">All their bills →</a> `:''}${safeHref(m.links?.tlo)?`<a class="text-link" href="${esc(safeHref(m.links.tlo))}" target="_blank" rel="noopener noreferrer">Texas Legislature Online ↗</a>`:''}</div>`).join('');
}
function nearData(){
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
function nearRow({bill:b,notes},opts={}){
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
function nearMarkup(){
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
    <div class="near-members">${memberCard('house',n.house)}${memberCard('senate',n.senate)}</div>
    <section class="near-group"><h3>Filed by your legislators ${count(d.members.length)}</h3>${nearList('members',d.members,'No bills by your legislators in this snapshot yet.',{showWho:authors.size>1})}</section>
    <section class="near-group"><h3>Bills that name ${esc(areaLabel)} ${count(d.local.length)}</h3><details class="near-how"><summary>How matching works</summary><p>A bill is listed when its full-text review names a county or city here, or its caption names the county. Bills written for areas by population size are not matched yet. ${d.statewide.toLocaleString()} reviewed bills apply statewide and are not listed here.</p></details>${nearList('area',d.local,'No bill names this area yet.',{area:d.area})}</section>
    <p class="near-hint">Official check: <a class="text-link" href="https://wrm.capitol.texas.gov/home" target="_blank" rel="noopener noreferrer">Who Represents Me? (Texas Legislative Council) ↗</a></p>`;
}

// ---- Member page (#member?code=A1234): one legislator, their district and their bills by role ----
const memberHref=code=>buildHash('member',{},{member:code});
const memberTitle=m=>`${m.chamber==='house'?'Rep.':'Sen.'} ${m.full_name||m.display_name}`;
// A name as the bill lists it, linked to the member page only when the roster places that exact (chamber, name).
const rosterMember=(chamber,name)=>{const m=state.roster?.members?.[`${chamber}|${name}`];return m&&typeof m==='object'?m:null};
// First term / Mid-tenure / Senior, by time in the current chamber; the detail is in the tooltip and on member pages.
// Cards show a verified role, or only the ends of the tenure scale; mid-tenure and unknown authors show nothing.
const influencePill=i=>i.level>=4?`<span class="influence-pill" title="${esc(i.factors.join(' · '))}">◆ ${esc(i.label)}</span>`
  :i.key==='senior'||i.key==='newcomer'?`<span class="tenure-pill tenure-${i.key}" title="${esc(i.factors.join(' · '))}">${esc(i.label)}</span>`:'';
const tenurePill=m=>{const t=tenureTag(m);return t?`<span class="tenure-pill tenure-${t.key}" title="${esc(t.detail)}">${esc(t.label)}</span>`:''};
const memberNameHtml=(member,label)=>member?.code?`<a class="text-link member-name" href="${esc(memberHref(member.code))}">${esc(label)}</a>`:esc(label);
// Authors serve in the bill's own chamber.
const authorMember=(b,name)=>b.people?.authors?.find(p=>p.name===name)?.member||rosterMember(String(b.chamber||'').toLowerCase(),name);
const authorHtml=(b,name)=>memberNameHtml(authorMember(b,name),name);
// The primary author by title and full name ("Rep. Ann Johnson") when the roster knows them; else the bill's own name.
const filerHtml=b=>{const m=authorMember(b,b.author);return memberNameHtml(m,m?.full_name||m?.display_name?memberTitle(m):b.author)};
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
function memberData(m){
  const groups=Object.fromEntries(ROLES.map(([,role])=>[role,[]]));
  for(const {bill,role} of billsByMember(state.bills,m))groups[role].push({bill,notes:[]});
  for(const rows of Object.values(groups))rows.sort((a,b)=>newestFirst(a.bill,b.bill));
  return groups;
}
function memberList(role,rows){
  const limit=state.memberShow?.[role]||30;
  return `${rows.slice(0,limit).map(nearRow).join('')}${rows.length>limit?`<button class="outline-button" data-member-more="${esc(role)}">Show 30 more · showing ${limit} of ${rows.length}</button>`:''}`;
}
function memberMarkup(){
  const head=title=>`<div class="section-head"><div><div class="section-overline">MEMBER</div><h2>${title}</h2></div><span class="subtitle">90th Legislature</span></div>`;
  if(!state.roster)return `${head('Member roster unavailable')}<div class="info-callout callout-warn">The member roster could not be loaded, so member pages are not available right now. Try again later.</div>`;
  const m=memberByCode(state.roster,state.memberCode);
  if(!m)return `${head('Member not found')}<div class="info-callout callout-warn">No member of the 90th Legislature has the code ${state.memberCode?`<strong>${esc(state.memberCode)}</strong>`:'in this address'}. Find members from a bill's authors or from <a class="text-link" href="#local" data-view="local">Near you</a>.</div>`;
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
  return `<div class="info-callout member-profile"><div><small>${where}</small><strong>${esc(memberSummary(m))}</strong>${tenureTag(m)?`<p>${tenurePill(m)} ${esc(tenureTag(m).detail)}</p>`:''}${countyLine}${links?`<p>${links}</p>`:''}</div><div class="tools-row">${followButton(m)}<a class="outline-button" href="${esc(memberFeedHref(m.code))}" target="_blank" rel="noopener noreferrer">RSS feed</a></div></div>
    <p class="near-hint">${total?`${total} ${total===1?'bill':'bills'} in this snapshot. `:''}${roleNote} Sponsors and cosponsors are listed once a bill crosses chambers, so early in the session most bills show authors only.</p>
    ${sections||'<p class="review-empty">No bills by this member in this snapshot yet.</p>'}`;
}

// ---- Population brackets: src/features/brackets/view.js ----

// An agency id is shown as a code only when it is a short form the name does not already spell out (TCEQ, not HOUSE or TX-COURTS).
const agencyCode=a=>/^[a-z]{2,6}$/.test(a.id)&&!a.name.toLowerCase().includes(a.id)?a.id.toUpperCase():'';
function filterAgencyCards(text){
  const words=text.toLowerCase().split(/\s+/).filter(Boolean),list=$('#agency-list');
  if(!list)return;
  // Agencies with no bills stay hidden until "Show all", but a search looks through every agency.
  const rows=[...list.children],all=list.dataset.all==='1';
  let shown=0;for(const li of rows){const hit=words.every(w=>li.firstElementChild.dataset.find.includes(w))&&(words.length>0||all||!li.classList.contains('agency-none'));li.hidden=!hit;if(hit)shown++}
  $('#agency-find-note').textContent=words.length?(shown?`${shown} of ${rows.length} agencies`:'No agency matches. Try part of the name.'):'';
  const more=$('#agency-more');if(more)more.hidden=words.length>0;
}
function agenciesMarkup(){
  const counts=new Map();for(const b of state.bills)for(const id of new Set(realAgencies(b).map(a=>a.id)))counts.set(id,(counts.get(id)||0)+1);
  const agencies=unique([...AGENCIES.map(a=>a.id),...Object.keys(state.luna?.agencies||{})]).filter(id=>id!==SCOPE_AGENCY_ID).map(id=>({id,name:agencyName(id)})).sort((a,b)=>(counts.get(b.id)||0)-(counts.get(a.id)||0)||a.name.localeCompare(b.name));
  const max=Math.max(1,...agencies.map(a=>counts.get(a.id)||0)),none=agencies.filter(a=>!counts.has(a.id)).length;
  const row=a=>{
    const n=counts.get(a.id)||0,code=agencyCode(a);
    return `<li${n?'':' class="agency-none" hidden'}><button class="agency-row" data-agency-pick="${esc(a.id)}" data-find="${esc(`${a.name} ${a.id} ${code}`.toLowerCase())}"><span class="agency-name">${code?`<span class="agency-code">${esc(code)}</span>`:''}<strong>${esc(a.name)}</strong></span><i aria-hidden="true" class="agency-bar"><i style="width:${(100*n/max).toFixed(1)}%"></i></i><span class="hits">${n.toLocaleString()} <small>${n===1?'bill':'bills'}</small></span></button></li>`;
  };
  return `<div class="section-head"><div><div class="section-overline">IMPACT DIRECTORY</div><h2>Texas state agencies</h2></div><span class="subtitle">${agencies.length-none} with possible links in this snapshot</span></div><div class="info-callout"><details class="agency-why"><summary><strong>Why an agency index?</strong> One bill can change the work of several state agencies. <span class="agency-why-more">More</span></summary> “Direct” means the supplied material names an agency; “possible” means an inferred policy connection. An agency absent from a caption is not proof it is unaffected—full bill text review is needed for comprehensive coverage.</details></div><div class="agency-find"><label for="agency-find">Find an agency</label><input id="agency-find" type="search" maxlength="80" placeholder="Name or short form, e.g. TCEQ" autocomplete="off"><span id="agency-find-note" class="tools-note" aria-live="polite"></span></div><ul class="agency-list" id="agency-list">${agencies.map(row).join('')}</ul>${none?`<p class="agency-more" id="agency-more">${none} more ${none===1?'agency has':'agencies have'} no bills in this snapshot. <button type="button" class="text-link" id="agency-show-all" aria-expanded="false">Show all ${agencies.length}</button></p>`:''}`;
}

function lunaBlock(b){
  if(!b.luna)return '';
  const locs=(b.locations||[]).map(l=>`<li><strong>${esc(l.name)}</strong>${l.kind?` (${esc(l.kind)})`:''}${l.explanation?` · ${esc(l.explanation)}`:''}</li>`).join('');
  return `<section class="drawer-section luna-block"><h3>Full-text review by Luna</h3><p><small>Reviewed ${esc(dateText(b.luna.reviewed_at))}${b.luna.text_version?` · ${esc(b.luna.text_version)} text`:''}</small></p>${b.luna.summary?`<p>${esc(b.luna.summary)}</p>`:''}<p><small>Tags from the bill's full text; fields not verified against the text use caption inference. Luna is an AI model and can be wrong; <a class="text-link" href="#method" data-view="method">how it works</a>.</small></p>${locs?`<h4>Locations</h4><ul>${locs}</ul>`:''}</section>`;
}

function memberItem({name,member}){
  const letter=member?.party==='Democratic'?'dem':member?.party==='Republican'?'rep':'unknown';
  const official=safeHref(member?.links?.lrl||member?.links?.tlo);
  const label=member?.full_name||name;
  // The name opens the member's page here; the official record stays one click away.
  const who=member?.code?`<a class="text-link" href="${esc(memberHref(member.code))}">${esc(label)}</a>`:`<strong>${esc(label)}</strong>`;
  return `<li><span class="party-dot party-${letter}" aria-hidden="true"></span>${who} ${tenurePill(member)} <small>${esc(memberSummary(member))}</small>${official?` <a class="text-link member-official" href="${esc(official)}" target="_blank" rel="noopener noreferrer" aria-label="Official record for ${esc(label)}">official ↗</a>`:''}</li>`;
}

// The bill page's section groups, in page order; the header's section menu jumps to each.
const BILL_GROUPS=[['overview','Overview'],['text','Text'],['law','Changes to law'],['people','People'],['impact','Agencies and impact'],['history','History'],['sources','Sources']];
// The bill view's content: every section of one bill, drawn into the page after the router renders its container.
function chamberSummary(b){
  const chamber=(name,role,names)=>`<span class="chamber-summary-side">
    <span class="chamber-building" aria-hidden="true"><i></i></span>
    <span><strong>Texas ${name}</strong><small>${names==null?`${role}s unreported`:names.length===0?`No ${role}s listed`:`${names.length} ${role}${names.length===1?'':'s'}`}</small></span></span>`;
  return `<button type="button" class="chamber-summary" data-bill-jump="people">
    ${chamber(b.chamber,'author',b.authors)}
    ${chamber(b.chamber==='House'?'Senate':'House','sponsor',b.sponsors)}
    <span class="chamber-summary-link">See people ↓</span></button>`;
}

function billChambers(b){
  const role=(label,key)=>{
    const names=b[key];const people=b.people?.[key];return `<h5>${label}${names===null?'':` (${names.length})`}</h5>${names===null?'<p>Not reported in this dataset</p>':!names.length?'<p>None listed in the source snapshot</p>':people?`<ul class="member-list">${people.map(p=>memberItem(p)).join('')}</ul>`:`<p>${names.map(esc).join(' · ')}</p>`}`;
  };
  const other=b.chamber==='House'?'Senate':'House';
  return `<div class="bill-chambers">
    <section><small>Originating chamber</small><h4>Texas ${esc(b.chamber)}</h4>${role('Authors','authors')}${role('Coauthors','coauthors')}</section>
    <section><small>Other chamber</small><h4>Texas ${other}</h4>${role('Sponsors','sponsors')}${role('Cosponsors','cosponsors')}</section>
  </div>`;
}

function fillBillPage(){
  const page=$('#bill-page');if(!page)return;
  const b=state.bills.find(b=>b.id===state.openBill);
  if(!b){page.innerHTML=`<div class="drawer-top"><button type="button" class="outline-button bill-back" id="bill-back">← Back to results</button></div><div class="empty-state"><h3>${esc(state.openBill||'This bill')} is not in this snapshot</h3><p>It may not be filed yet, or the bill list could not be loaded.</p>${state.openBill?`<p class="empty-steps"><a class="outline-button" href="${esc(buildHash('all',{query:state.openBill}))}">Search for ${esc(state.openBill)}</a></p>`:''}</div>`;return}
  const h=assessHearing(b),influence=authorInfluence(b),party=authorshipParty(b),last=lastActionInfo(b);
  const agencyRows=b.agencies.length?b.agencies.map(a=>`<div class="agency-row"><div><strong>${esc(agencyName(a.id))}</strong><p>${esc(a.reason||'Relationship not yet annotated')}</p></div><span class="confidence ${a.relationship==='direct'?'direct':''}">${a.source==='luna'?`Luna · ${a.relationship==='direct'?'direct':'inferred'}`:a.relationship==='direct'?'Direct':'Possible'}</span></div>`).join(''):'<p>No agency has been tagged yet. This does not establish that none are affected.</p>';
  const watched=state.watch.has(b.id);
  page.innerHTML=`<header class="bill-head"><div class="bill-bar"><button type="button" class="outline-button bill-back" id="bill-back">← Back to results</button><span class="drawer-number">90R / ${esc(b.number)}</span><div class="drawer-actions"><a class="primary-button" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Read official bill ↗</a><button class="outline-button" data-watch="${b.id}">${watched?'★ Remove from watchlist':'☆ Add to watchlist'}</button><a class="outline-button" href="./live/feeds/${esc(b.id)}.xml" target="_blank" rel="noopener noreferrer" title="Follow this bill's actions in Outlook or a feed reader">RSS feed</a><button type="button" class="outline-button" data-share-bill="${esc(b.id)}" title="Copy a link to this bill that shows its number and caption when posted on Discord, Facebook, X or Slack">Share</button><details class="ask-ai"><summary class="outline-button" title="Ask an AI assistant about this bill">Ask AI ▾</summary><div class="ask-ai-menu">${aiChatLinks(b,companionsOf(b.id)).map(l=>`<a data-ask-ai="${esc(l.name)}" href="${esc(l.href)}" target="_blank" rel="noopener noreferrer">${esc(l.name)} ↗</a>`).join('')}<small>ChatGPT and Claude open with the prompt filled in. Copy for AI copies it for any other assistant.</small><button type="button" data-copy-ai title="Copy a short prompt with links to this bill, for pasting into any AI assistant">Copy for AI</button></div></details></div></div><nav class="bill-menu" aria-label="Sections of this bill">${BILL_GROUPS.map(([id,label])=>`<button type="button" data-bill-jump="${id}">${label}</button>`).join('')}</nav></header><div class="bill-intro"><div class="drawer-pills"><span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span><span class="party-pill party-${party.tint}" title="${esc(party.detail)}">${esc(party.label)}</span></div><h1 id="bill-page-title" tabindex="-1"><span class="bill-h1-number">${esc(b.number)}</span> ${esc(b.title)}</h1>${sameText(b.caption,b.title)?'':`<p class="drawer-caption">${esc(b.caption)}</p>`}${chamberSummary(b)}</div><div class="bill-layout"><div class="bill-main"><section class="bill-group" id="bill-g-overview" aria-labelledby="bill-h-overview"><h2 class="bill-group-title" tabindex="-1" id="bill-h-overview">Overview</h2>${headlineLine(b,'drawer')}${lunaBlock(b)}<div class="drawer-pills">${b.topics.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>${billAreas(b).length?`<p class="area-badges"><span>Reader areas:</span> ${billAreas(b).map(id=>`<a class="tag area-tag" href="${esc(buildHash('all',{area:id}))}">${esc(areaName(id))}</a>`).join('')}</p>`:''}${b.subjects?.length?`<section class="drawer-section"><h3>Official subjects</h3><p>The Legislative Council's subject index for this bill. Search matches these, so a bill with a vague caption is still found by its subject.</p><div class="bill-tags">${b.subjects.map(s=>`<span class="tag subject-tag">${esc(s)}</span>`).join('')}</div></section>`:''}${companionBlock(b,{memberNameHtml,rosterMember,shortDate})}${relatedBlock(b)}</section><section class="bill-group" id="bill-g-text" aria-labelledby="bill-h-text"><h2 class="bill-group-title" tabindex="-1" id="bill-h-text">Text</h2></section><section class="bill-group" id="bill-g-law" aria-labelledby="bill-h-law"><h2 class="bill-group-title" tabindex="-1" id="bill-h-law">Changes to law</h2><section class="drawer-section law-section" id="drawer-statutes" hidden></section><section class="drawer-section bracket-section" id="drawer-brackets" hidden></section></section><section class="bill-group" id="bill-g-people" aria-labelledby="bill-h-people"><h2 class="bill-group-title" tabindex="-1" id="bill-h-people">People</h2><section class="drawer-section"><h3>Authors & sponsors</h3>${billChambers(b)}<p>Authors include primary and joint authors listed in the Legislative Council snapshot.</p><div class="evidence-card"><strong><span class="party-pill party-${party.tint}">${esc(party.label)}</span></strong><p>${esc(party.detail)}</p><p><small>Party, district and tenure come from the Texas Legislative Reference Library's latest recorded service; for members-elect not yet in its records, party and district come from the Secretary of State's unofficial 2026 general election results. Authorship does not indicate a vote or caucus position.</small></p></div></section><section class="drawer-section"><h3>Author prominence</h3><div class="evidence-card"><strong>${esc(influence.label)}</strong><p>${esc(influence.factors.join(' · '))}</p>${safeHref(b.author_profile?.source)?`<p><a class="text-link" href="${esc(safeHref(b.author_profile.source))}" target="_blank" rel="noopener noreferrer">Verified member biography ↗</a></p>`:''}</div></section></section><section class="bill-group" id="bill-g-impact" aria-labelledby="bill-h-impact"><h2 class="bill-group-title" tabindex="-1" id="bill-h-impact">Agencies and impact</h2><section class="drawer-section"><h3>Potentially affected agencies (${realAgencies(b).length})</h3><p>All known tags are listed. Possible links are model/rule inferences, not confirmed legal obligations.</p>${agencyRows}</section><section class="drawer-section"><h3>Types of impact</h3><div class="drawer-pills">${b.impacts.length?b.impacts.map(t=>`<span class="tag related">${esc(t)}</span>`).join(''):'<span class="tag">Pending analysis</span>'}</div></section>${b.constituencies?.length?`<section class="drawer-section"><h3>People and institutions affected</h3><div class="drawer-pills">${b.constituencies.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></section>`:''}</section><section class="bill-group" id="bill-g-history" aria-labelledby="bill-h-history"><h2 class="bill-group-title" tabindex="-1" id="bill-h-history">History</h2><section class="drawer-section"><h3>Hearing progress & evidence</h3><div class="evidence-card"><strong>${esc(h.label)} · ${h.level===0?'No rating yet':'Verified procedural signal'}</strong><p>${esc(h.detail)}</p><ul>${h.facts.map(f=>`<li>${esc(f)}</li>`).join('')}</ul></div></section></section><section class="bill-group" id="bill-g-sources" aria-labelledby="bill-h-sources"><h2 class="bill-group-title" tabindex="-1" id="bill-h-sources">Sources</h2><section class="drawer-section"><h3>Source & verification</h3><p>Review the bill history and latest text before relying on any classification. <a class="text-link" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Texas Legislature Online ↗</a></p><div class="ai-copy"><a class="text-link" href="${esc(agentUrl(b))}" target="_blank" rel="noopener noreferrer">AI-readable version ↗</a></div></section></section></div><aside class="bill-rail" aria-label="Key facts"><div class="drawer-meta-grid"><div><small>Filed by</small><strong>${authorHtml(b,b.author)}</strong></div><div><small>Filed on</small><strong>${dateText(b.filed_at)}</strong></div><div><small>Most recent action</small><strong>${esc(last.label)}${last.chamber?` · ${esc(last.chamber)}`:''} · ${esc(dateText(last.date))}</strong><small>${esc(last.text)}</small></div><div><small>Hearing status</small><strong>${esc(h.label)}</strong></div></div></aside></div>`;
  loadCardVersions();
  loadBillArt();placeBillArt();

  const review=reviewFileSection(b);
  $('#bill-g-text').append(billTextSection(b),review.section);review.draw();
  $('#bill-g-history').append(stageSections(b));
  $('#bill-page-title').focus({preventScroll:true});
  fillDrawerStatutes(b.id);
  fillDrawerBrackets(b.id);
}


function showAgencyChoices(query=''){
  const input=$('#filter-agency'),popup=$('#agency-options');
  if(!input||!popup)return;
  if(!query)input.value='';
  const needle=query.trim().toLocaleLowerCase();
  let visible=0;
  popup.querySelectorAll('[data-agency-option]').forEach(option=>{
    option.hidden=!!needle&&!option.dataset.agencyLabel.toLocaleLowerCase().includes(needle);
    option.setAttribute('aria-selected',String(option.dataset.agencyOption===state.agency));
    if(!option.hidden)visible++;
    option.classList.remove('active');
  });
  popup.querySelectorAll('[data-agency-group]').forEach(group=>{group.hidden=!group.querySelector('[data-agency-option]:not([hidden])')});
  $('#agency-no-results').hidden=visible!==0;
  popup.hidden=false;
  $('#agency-panel').hidden=false;
  input.setAttribute('aria-expanded','true');
  input.removeAttribute('aria-activedescendant');
  popup.scrollTop=0;
}

function hideAgencyChoices(){
  const input=$('#filter-agency'),popup=$('#agency-options');
  if(!input||!popup)return;
  popup.hidden=true;
  $('#agency-panel').hidden=true;
  input.value=state.agency?agencyName(state.agency):'';
  input.setAttribute('aria-expanded','false');
  input.removeAttribute('aria-activedescendant');
}

// Re-sort the open list in place, keeping what has been typed.
function setAgencySort(mode){
  state.agencySort=mode==='count'?'count':'name';
  try{localStorage.setItem(AGENCY_SORT_KEY,state.agencySort)}catch{}
  const input=$('#filter-agency'),popup=$('#agency-options');
  if(!input||!popup)return;
  popup.innerHTML=agencyOptionsMarkup();
  document.querySelectorAll('[data-agency-sort]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.agencySort===state.agencySort)));
  showAgencyChoices(input.value);
}

function pickAgency(id){
  state.agency=id;
  state.visibleCount=30;
  hideAgencyChoices();
  renderResults();
}

function handleAgencyKeydown(event){
  const popup=$('#agency-options');
  if(event.key==='Escape'){
    hideAgencyChoices();
    return true;
  }
  if(event.key==='Tab'){
    hideAgencyChoices();
    return false;
  }
  if(!['ArrowDown','ArrowUp','Enter'].includes(event.key))return false;
  if(popup.hidden)showAgencyChoices('');
  const options=[...popup.querySelectorAll('[data-agency-option]:not([hidden])')];
  if(!options.length)return true;
  event.preventDefault();
  const current=options.findIndex(option=>option.classList.contains('active'));
  if(event.key==='Enter'){
    pickAgency((options[current]||options[0]).dataset.agencyOption);
    return true;
  }
  const next=options[current===-1?(event.key==='ArrowDown'?0:options.length-1):(current+(event.key==='ArrowDown'?1:-1)+options.length)%options.length];
  options.forEach(option=>option.classList.toggle('active',option===next));
  event.target.setAttribute('aria-activedescendant',next.id);
  next.scrollIntoView({block:'nearest'});
  return true;
}

// handleClick's checks as named handlers; core/dispatch.js runs them in that original order.
function registerClicks(){
  clickOn('agency-sort','[data-agency-sort]',el=>setAgencySort(el.dataset.agencySort));
  clickOn('agency-option','[data-agency-option]',el=>pickAgency(el.dataset.agencyOption));
  clickOn('agency-combobox','#agency-combobox',(el,e)=>{
    const input=$('#filter-agency');
    if(e.target!==input)input.focus();
    if($('#agency-options').hidden)showAgencyChoices('');
  });
  // Every other click closes the agency list, then goes on to the handlers below.
  onClick('agency-dismiss',()=>{hideAgencyChoices();return false});
  clickOn('move','#move-start,#move-close,#move-held,#move-previous,[data-kept-download],[data-previous-link]',el=>{
    if(el.id==='move-start')startMove();
    if(el.id==='move-close'){moveStatus=null;renderMoveBanner()}
    if(el.id==='move-held'||el.hasAttribute('data-kept-download')){const text=heldFile(listStore);if(text)download('texas-bill-atlas-kept-aside.json',text,'application/json')}
    if(el.hasAttribute('data-previous-link'))copyText(siteBase()+'#watchlist?sync='+el.dataset.previousLink,'Edit link');
    if(el.id==='move-previous'&&movePreviousKey())copyText(siteBase()+'#watchlist?sync='+movePreviousKey(),'Edit link');
  });
  clickOn('nav','[data-view]',(nav,e)=>{if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button)return;e.preventDefault();goTo(nav.dataset.view);setView(nav.dataset.view)});  // modified clicks open a new tab
  clickOn('open-bill','[data-open]',(open,e)=>{
    // A modified or non-primary click on a link keeps the browser's own behavior (new tab, new window).
    if(open.tagName!=='A'||cardClickOpens({button:e.button,metaKey:e.metaKey,ctrlKey:e.ctrlKey,shiftKey:e.shiftKey,altKey:e.altKey})){e.preventDefault();openBillPage(open.dataset.open,true)}
  });
  clickOn('copy-ai','[data-copy-ai]',copyAi=>copyForAi(copyAi,{companionsOf}));
  // Ask AI menu: close after a pick, on a click elsewhere, or on Escape.
  document.addEventListener('click',e=>{for(const menu of document.querySelectorAll('details.ask-ai[open]'))if(!menu.contains(e.target)||e.target.closest('[data-ask-ai]'))menu.open=false});
  document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;const menu=document.querySelector('details.ask-ai[open]');if(menu){menu.open=false;menu.querySelector('summary').focus()}});
  // /bill/<ID> is a real page with the bill's own preview tags; the #bill address previews as the home page.
  clickOn('share-bill','[data-share-bill]',el=>copyText(shareUrl(location.origin,el.dataset.shareBill,cardVersions?.[el.dataset.shareBill]),'Share link'));
  clickOn('near-locate','#near-locate',()=>nearLocate());
  clickOn('near-forget','#near-forget',()=>{saveNear(null);toast('Your districts were removed from this device')});
  clickOn('near-change','#near-change',()=>{state.near=null;state.nearError='';renderContent()});
  clickOn('near-county-use','#near-county-use',()=>{const c=countyDistricts(state.nearGeo?.tables,state.nearPick);if(c)saveNear({county:state.nearPick,source:'county',
    house:$('#near-house-pick')?.value||c.house[0]?.district,senate:$('#near-senate-pick')?.value||c.senate[0]?.district,near:c.house.length>1||c.senate.length>1})});
  clickOn('near-numbers-use','#near-numbers-use',()=>{const near=cleanNear({house:$('#near-house-num')?.value,senate:$('#near-senate-num')?.value,source:'district'},state.nearGeo?.tables);
    if(!near){state.nearError='Enter a House district from 1 to 150, a Senate district from 1 to 31, or both.';renderContent();return}saveNear(near)});
  clickOn('near-more','[data-near-more]',nearMore=>{state.nearShow={...state.nearShow,[nearMore.dataset.nearMore]:Infinity};renderContent()});
  clickOn('follow','[data-follow]',follow=>toggleFollow(follow.dataset.follow));
  clickOn('save-search','#save-search',()=>saveCurrentSearch());
  // Opening a saved search marks it seen today; the link itself navigates to the explorer with its filters.
  clickOn('search-open','[data-search-open]',openSearch=>{const s=state.searches.find(x=>x.id===openSearch.dataset.searchOpen);
    if(s&&s.seen!==todayDay())changeSearch('save-search',{...s,seen:todayDay()})});
  clickOn('search-rename','[data-search-rename]',rename=>{state.renamingSearch=rename.dataset.searchRename;renderContent();
    const input=$(`[data-search-rename-form="${state.renamingSearch}"] input`);input?.focus();input?.select()});
  clickOn('search-delete','[data-search-delete]',del=>{
    if(del.dataset.armed!=='1'){del.dataset.armed='1';del.textContent='Click again to delete';return}
    const s=state.searches.find(x=>x.id===del.dataset.searchDelete);changeSearch('delete-search',del.dataset.searchDelete);
    renderOverview();renderContent();toast(s?`Deleted “${s.name}”`:'Deleted')});
  clickOn('follow-more','#follow-more',()=>{state.followShow+=30;renderContent()});
  clickOn('law-compare','[data-law-compare]',lawCompare=>{
    const c=state.statuteCompare;c.right=lawCompare.dataset.lawCompare;if(!c.left||c.left===c.right)c.left='law';
    renderContent();$('.law-compare-wrap')?.scrollIntoView({behavior:'smooth',block:'start'})});
  clickOn('law-show','[data-law-show]',lawShow=>{state.statuteShow=lawShow.dataset.lawShow;renderContent()});
  clickOn('member-more','[data-member-more]',memberMore=>{const role=memberMore.dataset.memberMore;state.memberShow[role]=(state.memberShow[role]||30)+30;renderContent()});
  clickOn('copy-page-ai','#copy-page-ai',copyPage=>copyPageForAi(copyPage,{memberTitle,todayData:()=>todayData({dateText}),agencyName,companionsOf,agencyVia,filteredBills,nearData,memberData}));
  clickOn('today-topic','[data-today-topic]',todayTopic=>{state.todayTopic=todayTopic.dataset.todayTopic;state.todayLimit=100;renderContent()});
  clickOn('today-more','#today-more',()=>{state.todayLimit+=100;renderContent()});
  clickOn('today-topics-toggle','#today-topics-toggle',()=>{state.todayAllTopics=!state.todayAllTopics;renderContent()});
  clickOn('save-tools','#copy-view-link,#share-watch,#export-watch,#import-watch,#shared-add,#shared-close,[id^="sync-"]',(el,e)=>{handleSaveClick(e.target)});
  clickOn('watch-group','[data-watch-group]',group=>{
    const known=new Set(state.bills.map(b=>b.id));const ids=group.dataset.watchGroup.split(',').filter(id=>known.has(id));
    if(!ids.length)return;
    const op=ids.every(id=>state.watch.has(id))?'remove':'add';changeWatch(op,ids);
    renderOverview();if(state.view==='all'||state.view==='watchlist')renderResults();if(state.view==='bill')renderContent();
    const names=ids.map(id=>state.bills.find(b=>b.id===id)?.number||id).join(', ');
    toast(op==='add'?`Watching ${names}`:`Removed ${names} from your watchlist`)});
  clickOn('watch','[data-watch]',star=>{const id=star.dataset.watch;changeWatch(state.watch.has(id)?'remove':'add',[id]);renderOverview();if(state.view==='all'||state.view==='watchlist')renderResults();if(state.view==='bill')renderContent();toast(state.watch.has(id)?`${id} added to your watchlist`:`${id} removed from your watchlist`)});
  clickOn('search-example','[data-search-example]',x=>{state.query=x.dataset.searchExample;state.visibleCount=30;renderContent();$('#bill-search')?.focus()});
  clickOn('topic','[data-topic]',topic=>{state.topic=topic.dataset.topic;state.visibleCount=30;renderContent()});
  clickOn('agency-show-all','#agency-show-all',btn=>{const list=$('#agency-list'),all=list.dataset.all!=='1';list.dataset.all=all?'1':'';btn.setAttribute('aria-expanded',String(all));btn.textContent=all?'Show only agencies with bills':`Show all ${list.children.length}`;filterAgencyCards($('#agency-find').value)});
  clickOn('agency-pick','[data-agency-pick]',pick=>{switchFilters('all');state.agency=pick.dataset.agencyPick;state.visibleCount=30;state.view='all';goTo('all');setView('all')});
  clickOn('clear-filter','[data-clear-filter]',chip=>clearFilter(chip.dataset.clearFilter));
  clickOn('clear-filters','#clear-filters,[data-clear-all]',()=>{Object.assign(state,{query:'',topic:'',area:'',agency:'',chamber:'',party:'',stage:'',action:'',outlook:'',sort:'newest',onlyWatch:false,companion:false,visibleCount:30});renderContent()});
  clickOn('watch-filter','#watch-filter',()=>{state.onlyWatch=!state.onlyWatch;state.visibleCount=30;renderContent()});
  clickOn('companion-filter','#companion-filter',()=>{state.companion=!state.companion;state.visibleCount=30;renderContent()});
  clickOn('load-more','#load-more',()=>{state.visibleCount+=30;renderResults()});
  clickOn('export-csv','#export-csv',()=>exportCsv());
  clickOn('import-trigger','#import-trigger',()=>$('#import-file').click());
  clickOn('nav-more','#nav-more',()=>setNavOpen(!$('.sidebar').classList.contains('nav-open')));
  clickOn('bill-back','#bill-back',()=>leaveBillPage());
  // The skip link moves focus without touching the address, which names the view.
  clickOn('skip-link','#skip-link',(el,e)=>{e.preventDefault();$('#main-content').focus()});
  clickOn('preview-close','#preview-close',()=>closePreview());
  clickOn('preview-step','[data-preview-step]',step=>stepPreview(Number(step.dataset.previewStep)));
  clickOn('bill-jump','[data-bill-jump]',jump=>{const group=$(`#bill-g-${jump.dataset.billJump}`);if(group){group.scrollIntoView({block:'start'});group.querySelector('h2')?.focus?.({preventScroll:true})}});
  // Empty space on a card opens its bill page, unless the click was on a control or the reader is selecting text.
  // In the explorer on a wide screen it opens the preview instead; links and buttons still go to the page.
  onClick('card',e=>{
    const card=e.target.closest('[data-bill-id]');
    if(card&&cardClickOpens({interactive:Boolean(e.target.closest(CARD_CONTROLS)),selection:window.getSelection?.().toString()||'',button:e.button,metaKey:e.metaKey,ctrlKey:e.ctrlKey,shiftKey:e.shiftKey,altKey:e.altKey})){
      if(card.matches('#bill-list .bill-card')&&PREVIEW_WIDE.matches)showPreview(card.dataset.billId);
      else openBillPage(card.dataset.billId,true);
    }
    return true;
  });
}
const CARD_CONTROLS='a,button,input,select,textarea,label,summary,[data-topic],[data-today-topic],[data-open],[data-watch],[data-watch-group]';

function handleInput(e){
  if(e.target.id==='agency-find'){filterAgencyCards(e.target.value);return}
  if(e.target.id==='review-lookup'){$('#review-lookup-result').innerHTML=reviewLookupHtml(e.target.value,{dateText});return}
  if(e.target.id==='bill-search'){state.query=e.target.value.slice(0,200);state.visibleCount=30;renderResults()}
  if(e.target.id==='filter-agency'){
    if(state.agency){state.agency='';state.visibleCount=30;renderResults()}
    showAgencyChoices(e.target.value);
  }
}
function handleChange(e){
  const side=e.target.dataset?.lawSide;
  if(side&&state.statuteCompare){state.statuteCompare[side]=e.target.value;renderContent();return}
  if(e.target.id==='near-county'){state.nearPick=e.target.value||null;state.nearError='';renderContent();$('#near-county')?.focus();return}
  const m={'filter-area':'area','filter-topic':'topic','filter-chamber':'chamber','filter-party':'party','filter-stage':'stage','filter-outlook':'outlook','filter-action':'action'};
  if(m[e.target.id]){state[m[e.target.id]]=e.target.value;state.visibleCount=30;renderResults();return}
  if(e.target.id==='sort-order'){state.sort=Object.keys(SORTS).find(k=>SORTS[k]===e.target.value)||'newest';state.visibleCount=30;renderResults();return}
  if(e.target.id==='import-file'&&e.target.files?.length)importFile(e.target.files[0]);
  if(e.target.id==='import-watch-file'&&e.target.files?.length){importWatchlist(e.target.files[0]);e.target.value=''}
}

function csvCell(value){let s=String(value??'');if(/^[=+\-@]/.test(s))s=`'${s}`;return /[",\n\r]/.test(s)?`"${s.replaceAll('"','""')}"`:s}
function exportCsv(){
  const rows=[['id','title','author','chamber','status','filed_at','hearing_progress','policy_areas','agencies','agency_relationships','official_url','authors','author_count','coauthors','coauthor_count','sponsors','sponsor_count','cosponsors','cosponsor_count'],...filteredBills().map(b=>[b.id,b.title,b.author,b.chamber,b.status,b.filed_at,assessHearing(b).label,b.topics.join('|'),b.agencies.map(a=>AGENCY_NAME[a.id]||a.id).join('|'),b.agencies.map(a=>a.relationship||'related').join('|'),officialUrl(b),b.authors.join('|'),b.authors.length,b.coauthors?.join('|')??'',b.coauthors?.length??'',b.sponsors?.join('|')??'',b.sponsors?.length??'',b.cosponsors?.join('|')??'',b.cosponsors?.length??''])];
  const blob=new Blob(['﻿'+rows.map(row=>row.map(csvCell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});const u=URL.createObjectURL(blob);const a=document.createElement('a');a.href=u;a.download='texas-90R-bills.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
}

function parseCsv(text){
  const rows=[];let row=[],field='',quoted=false;
  for(let i=0;i<text.length;i++){const c=text[i];if(quoted){if(c==='"'&&text[i+1]==='"'){field+='"';i++}else if(c==='"')quoted=false;else field+=c}else if(c==='"')quoted=true;else if(c===','){row.push(field);field=''}else if(c==='\n'){row.push(field.replace(/\r$/,''));rows.push(row);row=[];field=''}else field+=c}
  if(field||row.length){row.push(field);rows.push(row)}
  const headers=rows.shift()?.map(s=>s.trim().replace(/^\uFEFF/,'').toLowerCase())||[];
  return rows.filter(row=>row.some(Boolean)).map(row=>Object.fromEntries(headers.map((key,i)=>[key,(row[i]||'').replace(/^'(?=[=+\-@])/,'')]))).map(o=>{
    const list=v=>v?v.split('|').map(s=>s.trim()).filter(Boolean):[];
    const topics=list(o.policy_areas||o.topics);
    const agencies=list(o.agencies).map(v=>NAME_TO_AGENCY_ID.get(v.toLowerCase())||v);
    const optional={};for(const k of ['coauthors','sponsors','cosponsors'])optional[k]=o[k]?o[k]:null;
    return {...o,...optional,topics,agencies,impacts:list(o.impacts)};
  });
}

async function importFile(file){
  try{
    if(file.size>15*1024*1024)throw Error('Select a file smaller than 15 MB');
    const contents=await file.text();const data=file.name.toLowerCase().endsWith('.csv')?parseCsv(contents):JSON.parse(contents);
    const rows=Array.isArray(data)?data:data.bills;
    if(!Array.isArray(rows))throw Error('Expected an array of bills or an object with a bills array');
    const profiles=!Array.isArray(data)&&data.author_profiles&&typeof data.author_profiles==='object'?data.author_profiles:null;
    const valid=rows.filter(r=>r&&typeof r==='object').map(raw=>normalized(raw,profiles)).filter(Boolean).map(b=>attachMembers(b,state.roster));
    if(!valid.length)throw Error('No valid Texas bill numbers found');
    const previous={bills:state.bills,meta:state.meta,topic:state.topic,area:state.area,agency:state.agency,chamber:state.chamber,party:state.party,stage:state.stage,action:state.action,outlook:state.outlook,query:state.query,visibleCount:state.visibleCount,view:state.view};
    try{
      state.bills=valid;state.meta={session:'90R',data_mode:'local import',source_file:file.name,generated_at:new Date().toISOString(),coverage_note:`Local file: ${file.name}. Imported rows are visible only during this session.`};
      switchFilters('all');Object.assign(state,{topic:'',area:'',agency:'',chamber:'',party:'',stage:'',action:'',outlook:'',query:'',visibleCount:30});setView('all');
    }catch(renderError){Object.assign(state,previous);setView(previous.view);throw renderError}
    goTo('all');toast(`Imported ${valid.length} bills`);
  }catch(err){toast(`Import failed: ${err.message}`)}
}

init();
