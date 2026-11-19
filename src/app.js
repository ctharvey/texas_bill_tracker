import {SEARCH_FIELDS, searchFields, searchText, matchReasons} from './features/search/model.js';
import {nextVisit, changedSince, newestReviewed} from './features/home/model.js';
import {topicHue, topicStyle, plainTitle, daysUntil} from './features/home/rows.js';
import {reviewParts, reviewLookupHtml, reviewMarkup} from './features/review/view.js';
import {companionCache, companionsOf, relationText, agencyVia, groupWatchButton, companionBlock} from './features/companions/view.js';
import {todayData, todayMarkup} from './features/today/view.js';
import {memberTitle, rosterMember, influencePill, tenurePill, memberNameHtml, authorMember, authorHtml, filerHtml} from './features/members/names.js';
import {NEAR_FILES, saveNear, nearLocate, nearAddress, nearData, nearRow, nearMarkup} from './features/near/view.js';
import {memberData, memberMarkup} from './features/members/view.js';
import {followButton, memberFeedHref} from './features/follows/view.js';
import {followingMarkup} from './features/searches/view.js';
import {sharedBanner, watchTools} from './features/watchlist/view.js';
import {handleSaveClick, importWatchlist} from './features/watchlist/actions.js';
import {MOVE_FROM, renderMoveBanner, startMove, receiveArrivingMove, movePreviousKey} from './features/move/flow.js';
import {cardVersions, fillBillPage} from './features/bill/page.js';
import {confirmJoin} from './features/sync/join.js';
import {listStore, sync, changeFollow, toggleFollow, changeSearch, searchCounts, saveCurrentSearch, refreshWatch, onSynced, changeWatch, setupSync, openSyncLink, pullSync} from './features/sync/lists.js';
import {exportCsv, parseCsv} from './features/explorer/csv.js';
import {importFile} from './features/explorer/import.js';
import {options, AGENCY_SORT_KEY, agencyOptionsMarkup, agencySortButtons} from './features/explorer/controls.js';
import {lawKeysFor, reasonFor, filteredBills} from './features/explorer/model.js';
import {SEARCH_EXAMPLES, clearFilter, explorerMarkup, headlineLine, relatedBlock, drawResults, PREVIEW_WIDE, preview, showPreview, closePreview, stepPreview, sameText} from './features/explorer/view.js';
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
import {state, runtime} from './core/state.js';
import {shortDate, dateText, stampText, unique, safeHref} from './core/format.js';
import {billHref, memberHref, siteBase} from './core/links.js';
import {$, esc, toast} from './core/dom.js';
import {copyText, download} from './core/copy.js';
import {SORTS, agencyName, areaName, realAgencies, todayDay} from './core/labels.js';
import {lastPath, goTo, FILTERED_VIEWS, switchFilters, applyLocation, openBillPage, leaveBillPage, keptPrefs, persistState} from './core/location.js';
import {timeoutSignal, loadShardedMap, httpError} from './core/net.js';
import {registerView, setFallbackView, viewHeading, renderView, setRenderContent, setExplorerHooks, setSyncHooks} from './core/router.js';
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

setRenderContent(renderContent);  // features redraw through core/router.js's renderContent
setExplorerHooks({renderResults,persistState});
setSyncHooks({renderOverview,refreshHome,renderMoveBanner,setView});
loadSaved();
// The dashboard visit before this one: read, and today stamped, the first time the dashboard is drawn in this page
// load, so other pages never add the key. null on a first visit or without storage.
let visit=null;
function previousVisit(){
  if(!visit){visit=nextVisit(readJson(visitKey),chicagoDate(new Date()));if(STORAGE_OK)writeJson(visitKey,visit.store)}
  return visit.prev;
}


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

// ---- The address and remembered filters: src/core/location.js ----
// ---- Moving saved data from the old address: src/features/move/flow.js ----
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
  registerView('all',{heading:['See what’s moving.','Track legislation by policy, affected agency, author influence, and its path through the Capitol.'],render:()=>explorerMarkup({sync,syncAvailable:runtime.syncAvailable,listStore}),after:renderResults});
  registerView('watchlist',{heading:['Your watchlist.','Bills you starred on this device, with a clear view of their movement.'],render:()=>explorerMarkup({sync,syncAvailable:runtime.syncAvailable,listStore}),after:renderResults});
  registerView('following',{heading:['Following.','Legislators you follow on this device, and every bill they file or sign onto.'],render:()=>followingMarkup({searchCounts,agencyName,areaName,SORTS})});
  registerView('today',{heading:['Today at the Lege.','Bills with a recorded action that day, by type of action. Dates follow Texas time.'],render:()=>todayMarkup({dateText,todayRow})});
  registerView('local',{heading:['Near you.','Your Texas House member and Senator, what they filed, and bills that name your county or city.'],render:()=>nearMarkup({followButton})});
  registerView('member',{heading:['One legislator.','A member’s district and the bills they author, coauthor or sponsor in this snapshot.'],render:()=>memberMarkup({followButton,memberFeedHref})});
  registerView('statute',{heading:['One section of law.','The bills that would amend, add or repeal this section of Texas law, with their wording side by side.'],render:()=>statuteMarkup({renderContent,billHref})});
  registerView('bill',{heading:['One bill.','Its summary, text, changes to law, people, agencies and sources.'],render:()=>'<article class="bill-page" id="bill-page" aria-label="Bill details"></article>',after:fillBillPage});
  registerView('agencies',{heading:['Follow the agencies.','Explore where legislation might land across Texas government.'],render:agenciesMarkup});
  registerView('review',{heading:['Full-text review.','Which bills Luna has read in full, which it is working on, and what is still waiting.'],render:()=>reviewMarkup({stampText,dateText,changeCounts,changeRows,todayRow})});
  registerView('method',{heading:['How the atlas works.','Signals and uncertainty are displayed separately from verified legislative actions.'],render:methodMarkup});
  registerView('saving',{heading:['Save your work.','Keep your watchlist and views on one device, carry them in a link or file, or sync them privately.'],render:()=>savingMarkup({linked:sync.linked,syncAvailable:runtime.syncAvailable})});
  registerView('export',{heading:['Export your saved info.','Everything this browser has saved, in one file you can keep or import on another device.'],render:()=>exportMarkup({watch:state.watch,follows:state.follow,searches:state.searches,theme:savedTheme(),memberName:code=>{const m=memberByCode(state.roster,code);return m?memberTitle(m):null},synced:Boolean(sync.linked?.editKey),kept:STORAGE_OK?heldCount(listStore):0,previous:STORAGE_OK?previousLinks(listStore):[]})});
  registerView('data',{heading:['Behind the tracker.','Understand coverage, refreshes, and how to load or export bill data.'],render:()=>dataMarkup({stampText,reviewParts})});
  setFallbackView('data');
}

function renderResults(){keepFocus(drawResults)}
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

// ---- Near you: src/features/near/view.js ----

// ---- Member page: src/features/members/view.js (names: members/names.js) ----

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
  popup.innerHTML=agencyOptionsMarkup(agencyName);
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
    if(el.id==='move-close'){runtime.moveStatus=null;renderMoveBanner()}
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
  clickOn('export-csv','#export-csv',()=>exportCsv(filteredBills));
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

init();
