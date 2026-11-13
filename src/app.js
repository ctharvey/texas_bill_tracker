import {nextVisit, changedSince, newestReviewed} from './features/home/model.js';
import {reviewModel, renderReview, parseBillMarkdown, validHighlights, sha256Hex, renderBillText, validChanges, renderChanges, renderHearing, validFiscal, renderFiscal,
  STATUTE_KINDS, statuteFile, statuteLabel, officialStatuteUrl, validStatuteIndex, validStatuteSection, statutesByBill, parseStatuteQuery, statuteKeysFor,
  compareLaw, currentLaw, groupStatuteEntries} from './review.js';
import {fillDrawerBrackets} from './features/brackets/view.js';
import {setupThemePicker} from './features/theme/view.js';
import {state} from './core/state.js';
import {$, esc, toast} from './core/dom.js';
import {timeoutSignal} from './core/net.js';
import {registerHooks} from './core/hooks.js';
import {registerView, setFallbackView, viewHeading, renderView} from './core/router.js';
import {onClick, clickOn, dispatchClick} from './core/dispatch.js';
import {storageKey, followKey, searchesKey, prefsKey, disclaimerKey, visitKey, STORAGE_OK, readJson, writeJson, memoryStorage, loadSaved} from './core/storage.js';
import {FILTER_DEFAULTS, parseHash, buildHash, pickFilters, sameFilters, cleanFilters, profileFile, parseProfileFile, cleanFollows, MAX_FOLLOWS,
  cleanSearches, applySearchOps, newSearchId, searchName, searchFitsSync, MAX_SEARCHES} from './prefs.js';
import {createSyncClient} from './sync.js';
import {NEAR_KEY, placeFromPoint, cleanNear, countyDistricts, countiesOf, membersFor, memberByCode, billsByMember, followedBills, ROLES, gazetteer, areaReasons, areaFor, censusUrl, censusPoint} from './geo.js';
import {AGENCIES, AGENCY_NAME, SCOPE_AGENCY_ID, autoTagBill, applyLunaTags, applyLunaExtras, relatedFor, auditLine, attachMembers, authorshipParty, PARTY_FILTERS, partyFilterMatches, NO_HEARING, memberSummary, tenureTag, lastActionInfo, LAST_ACTION_TYPES, reviewProgress, reviewSummary, POLICY_AREAS, assessHearing, authorInfluence, officialUrl, memberNames, matchAuthorProfile, snapshotAgeHours, normalizeBill, companionIndex, companionGroups, sortAgencyIds, searchTerms, textMatches, newestFirst, aiPrompt, agentUrl, cardClickOpens, openLinkHtml, chicagoDate, activityOn, latestActivityDay, topicCounts, groupByActionType, pageAiText, companionLabel, agencyViaCompanion} from './taxonomy.js';

const SORTS={newest:'Newest filed',latest:'Latest action',oldest:'Oldest last action',actionstage:'Last action stage',number:'Bill number',agencies:'Most agencies',hearing:'Hearing progress',influence:'Author influence'};
const agencyName = id => AGENCY_NAME[id]||state.luna?.agencies?.[id]||id;
const reviews = new Map();
loadSaved();
// The visit before this one, read once per page load (null on a first visit or without storage).
const visit=nextVisit(readJson(visitKey),chicagoDate(new Date()));
if(STORAGE_OK)writeJson(visitKey,visit.store);

const shortDate = iso => iso ? new Date(`${String(iso).slice(0,10)}T12:00:00Z`).toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'}) : '';
const dateText = iso => iso ? new Date(`${String(iso).slice(0,10)}T12:00:00Z`).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}) : 'Not available';
const stampText = iso => iso ? new Date(iso).toLocaleString('en-US',{dateStyle:'medium',timeStyle:'short',timeZone:'America/Chicago'})+' CT' : 'Unknown';
const unique = a => [...new Set(a)];

const realAgencies = b => b.agencies.filter(a=>a.id!==SCOPE_AGENCY_ID);
const safeHref = value => {try{const u=new URL(String(value));return u.protocol==='https:'||u.protocol==='http:'?u.href:''}catch{return ''}};
const NAME_TO_AGENCY_ID = new Map(AGENCIES.flatMap(a=>[[a.name.toLowerCase(),a.id],[a.id.toLowerCase(),a.id]]));

const normalized=normalizeBill;

async function init(){
  registerHooks({renderContent, renderOverview, openBillPage, toast});
  registerViews();
  registerClicks();
  const now=new Date();
  $('.day-box').textContent=new Intl.DateTimeFormat('en-US',{day:'2-digit',timeZone:'America/Chicago'}).format(now);
  $('.heading-date strong').textContent=new Intl.DateTimeFormat('en-US',{month:'short',year:'numeric',timeZone:'America/Chicago'}).format(now).toUpperCase();
  try {
    // The server's hourly live snapshot is preferred; the bundled copy is the fallback.
    const urls=['./live/bills.json','./data/bills.json'];
    let data,loadedFrom,loadedBills;
    for(const url of urls){
      try{
        const response=await fetch(url,{cache:'no-cache',signal:timeoutSignal(7500)});
        if(!response.ok)throw Error(`HTTP ${response.status}`);
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
    try{
      const response=await fetch('./live/luna/tags.json',{cache:'no-cache',signal:timeoutSignal(7500)});
      if(!response.ok)throw Error(`HTTP ${response.status}`);
      const tags=await response.json();
      if(tags?.format!=='texas-bill-luna-tags-v1'||!tags.bills||typeof tags.bills!=='object'||Array.isArray(tags.bills))throw Error('Unrecognized tags format');
      state.luna={...tags,agencies:tags.agencies&&typeof tags.agencies==='object'?tags.agencies:{}};
      loadedBills=loadedBills.map(b=>Object.hasOwn(tags.bills,b.id)&&tags.bills[b.id]&&typeof tags.bills[b.id]==='object'?applyLunaTags(b,tags.bills[b.id],state.luna.agencies):b);
    }catch(error){state.luna=null;console.warn('Luna tags unavailable',error.message)}
    const loadOptional=async(name,format,valid)=>{
      try{
        const response=await fetch(`./live/luna/${name}.json`,{cache:'no-cache',signal:timeoutSignal(7500)});
        if(!response.ok)throw Error(`HTTP ${response.status}`);
        const body=await response.json();
        if(body?.format!==format||!valid(body))throw Error(`Unrecognized ${name} format`);
        return body;
      }catch(error){console.warn(`Luna ${name} unavailable`,error.message);return null}
    };
    const isMap=o=>o&&typeof o==='object'&&!Array.isArray(o);
    const [extras,related,audit]=await Promise.all([
      loadOptional('extras','texas-bill-luna-extras-v1',x=>isMap(x.bills)),
      loadOptional('related','texas-bill-related-v1',x=>isMap(x.bills)),
      loadOptional('audit','texas-bill-luna-audit-v1',x=>true)]);
    if(extras)loadedBills=loadedBills.map(b=>Object.hasOwn(extras.bills,b.id)?applyLunaExtras(b,extras.bills[b.id]):b);
    state.related=related;state.audit=audit;
    await loadReviewStatus();
    for(const url of ['./live/members.json','./data/members.json']){
      try{
        const response=await fetch(url,{cache:'no-cache',signal:timeoutSignal(7500)});
        if(!response.ok)throw Error(`HTTP ${response.status}`);
        const roster=await response.json();
        if(roster?.format!=='texas-bill-members-v1'||!roster.members||typeof roster.members!=='object'||Array.isArray(roster.members))throw Error('Unrecognized roster format');
        state.roster=roster;break;
      }catch(error){console.warn(`Member roster unavailable: ${url}`,error.message)}
    }
    if(state.roster)loadedBills=loadedBills.map(b=>attachMembers(b,state.roster));
    state.meta=data;
    state.bills=loadedBills;
  }catch(error){
    state.meta={data_mode:'unavailable',coverage_note:'The current dataset could not be loaded. Use Data & imports to load a local CSV or JSON file.'};
  }
  document.addEventListener('click',dispatchClick);
  document.addEventListener('change',handleChange);
  document.addEventListener('input',handleInput);
  document.addEventListener('submit',e=>{if(e.target.id==='near-address-form'){e.preventDefault();nearAddress($('#near-address')?.value)}
    if(e.target.id==='home-search-form'){e.preventDefault();location.hash=buildHash('all',{query:$('#home-search').value.trim()})}
    const form=e.target.closest?.('[data-search-rename-form]');
    if(form){e.preventDefault();const s=state.searches.find(x=>x.id===form.dataset.searchRenameForm),name=form.elements.name.value.trim().slice(0,80);
      if(s&&name&&name!==s.name)changeSearch('save-search',{...s,name});state.renamingSearch=null;renderContent()}});
  document.addEventListener('focusin',event=>{
    if(event.target.id==='filter-agency')showAgencyChoices('');
  });
  document.addEventListener('keydown',event=>{
    if(event.target.id==='filter-agency'&&handleAgencyKeydown(event))return;
  });
  // A sync link pasted into an open tab arrives as a hash change, not a page load.
  window.addEventListener('hashchange',()=>{const key=applyLocation(false);if(key)openSyncLink(key)});
  state.near=cleanNear(readJson(NEAR_KEY),null);
  const syncKey=applyLocation(true);
  setupDisclaimer();
  setupThemePicker();
  setupSync(syncKey);
  if(state.bills.length)loadStatutes();
  // Keep the progress view current while it is open; other views never refetch.
  setInterval(async()=>{
    if(state.view!=='review'||document.visibilityState!=='visible')return;
    const before=state.reviewStatus?.updated_at;await loadReviewStatus();
    if(state.view==='review'&&state.reviewStatus?.updated_at!==before){
      const open=[...document.querySelectorAll('.review-group')].map(d=>d.open);
      renderOverview();renderContent();
      document.querySelectorAll('.review-group').forEach((d,i)=>{if(i<open.length)d.open=open[i]});
    }
  },60000);
}

function setupDisclaimer(){
  const dialog=$('#disclaimer');
  if(!dialog||typeof dialog.showModal!=='function')return;
  // Closing by button or Escape both count as seen; without storage it simply shows on each visit.
  dialog.addEventListener('close',()=>{try{localStorage.setItem(disclaimerKey,new Date().toISOString())}catch{}});
  $('#disclaimer-open')?.addEventListener('click',()=>{if(!dialog.open)dialog.showModal()});
  let seen=false;try{seen=Boolean(localStorage.getItem(disclaimerKey))}catch{}
  if(!seen)dialog.showModal();
  const privacy=$('#privacy');
  $('#privacy-open')?.addEventListener('click',()=>{if(privacy&&!privacy.open)privacy.showModal()});
}

// ---- Saving choices without accounts: URL state, remembered filters, files and private sync links ----
const sync=createSyncClient({storage:STORAGE_OK?localStorage:memoryStorage(),getWatch:()=>[...state.watch],getFollows:()=>[...state.follow],getSearches:()=>state.searches});
let syncAvailable=null,lastPull=0;
const siteBase=()=>location.href.split('#')[0];

function applyFilters(raw){
  const clean=cleanFilters(raw);
  if(clean.sort&&!SORTS[clean.sort])delete clean.sort;
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
  const p=parseHash(location.hash);
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
  setView(view);
  if(back)window.scrollTo({top:back.scrollY,behavior:'instant'});
  return p.sync;
}

function currentHash(){
  return buildHash(state.view,pickFilters(state),{list:state.sharedMode==='link'?state.sharedList:null,bill:state.openBill,
    sync:state.sharedMode==='sync-view'?state.sharedSyncKey:null,member:state.memberCode,statute:state.statuteKey});
}

// A bill's page address, so a bill title is a real link (new tab, copy link) as well as a click target.
function billHref(id){
  return buildHash('bill',{},{list:state.sharedMode==='link'?state.sharedList:null,bill:id,
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
function leaveBillPage(){location.hash=billReturn?.hash||'#all'}

// prefs-v1 fields other than the filters (the colour theme) survive a filter save.
const keptPrefs=()=>{const p=readJson(prefsKey);return p&&typeof p==='object'&&!Array.isArray(p)?p:{}};
// push=true adds a history entry (opening a bill), so Back closes it instead of leaving the site.
function persistState(push=false){
  const hash=currentHash();
  let pushed=false;
  if(location.hash!==hash)try{if(push){history.pushState(null,'',hash);pushed=true}else history.replaceState(null,'',hash)}catch{}
  if(state.view==='all'&&filtersFor==='all'&&!state.sharedList&&!(readJson(prefsKey)?.filters&&sameFilters(readJson(prefsKey).filters,state)))writeJson(prefsKey,{...keptPrefs(),filters:pickFilters(state)});
  return pushed;
}

function saveWatchLocal(){if(STORAGE_OK)writeJson(storageKey,[...state.watch])}
function setFollows(list){state.follow=cleanFollows(list);if(STORAGE_OK)writeJson(followKey,state.follow)}
// `follows` from sync is the link's list, or null when the server did not say (then this device's list stands).
function adoptFollows(follows){
  if(!follows||follows.join()===state.follow.join())return false;
  setFollows(follows);return true;
}
function changeFollow(op,codes){
  for(const code of codes){const has=state.follow.includes(code);if(op==='follow'?has:!has)continue;
    if(op==='follow'&&state.follow.length>=MAX_FOLLOWS)break;
    setFollows(op==='follow'?[...state.follow,code]:state.follow.filter(c=>c!==code));sync.record(op,code,onSynced)}
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
function setSearches(list){state.searches=cleanSearches(list);if(STORAGE_OK)writeJson(searchesKey,state.searches)}
function adoptSearches(searches){
  if(!searches||JSON.stringify(searches)===JSON.stringify(state.searches))return false;
  setSearches(searches);return true;
}
// op: 'save-search' (search object) or 'delete-search' (id).
function changeSearch(op,item){
  const id=op==='save-search'?item.id:item;
  setSearches(applySearchOps(state.searches,[{op,id,value:item}]));
  sync.record(op,id,onSynced,op==='save-search'?item:undefined);
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
  const name=searchName(filters,agencyName);
  if(state.searches.some(s=>JSON.stringify(s.filters)===JSON.stringify(filters))){toast(`Already saved as “${state.searches.find(s=>JSON.stringify(s.filters)===JSON.stringify(filters)).name}”`);return}
  changeSearch('save-search',{id:newSearchId(),name,filters,seen:todayDay()});
  renderOverview();toast(`Saved “${name}” · find it under Following`);
}
function searchSummary(f){
  const parts=[f.query&&`Search “${f.query}”`,f.topic&&`Topic: ${f.topic}`,f.agency&&`Agency: ${agencyName(f.agency)}`,f.chamber,f.party&&`Party: ${f.party} authors`,f.stage&&`Stage: ${f.stage}`,
    f.outlook&&`Hearing: ${f.outlook}`,f.action&&`Last action: ${f.action}`,f.onlyWatch&&'Watched bills only',f.sort&&f.sort!=='newest'&&`Sorted by ${SORTS[f.sort]||f.sort}`].filter(Boolean);
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
  return `<section class="followed-section"><h3>Followed legislators <span>${members.length}</span></h3><div class="followed-members">${chips}</div><p class="tools-note">Saved in this browser, in exported files and with your sync link; never in share or view-only links. Newest bills first.</p>${rows.length?`${rows.slice(0,limit).map(nearRow).join('')}${rows.length>limit?`<button class="outline-button" id="follow-more">Show 30 more · showing ${limit} of ${rows.length}</button>`:''}`:'<p class="review-empty">No bills by the legislators you follow in this snapshot yet.</p>'}</section>`;
}
function setWatch(ids){state.watch=new Set(ids);saveWatchLocal()}
const FOLLOW_VIEWS=new Set(['following','member','local']);
function refreshWatch(){renderOverview();if(state.view==='all'||state.view==='watchlist'||state.view==='home'||FOLLOW_VIEWS.has(state.view))renderContent()}
// `sections` from sync: {follows, searches}, each the link's copy or null when the server did not say.
const onSynced=(watch,error,sections)=>{if(error){toast(`Sync: ${error.message}`);return}setWatch(watch);const moved=adoptFollows(sections?.follows)|adoptSearches(sections?.searches);renderOverview();
  if(state.view==='all'||state.view==='watchlist')renderResults();else if(state.view==='home'||moved&&FOLLOW_VIEWS.has(state.view))renderContent()};
function changeWatch(op,ids){
  for(const id of ids){if(op==='add'?state.watch.has(id):!state.watch.has(id))continue;op==='add'?state.watch.add(id):state.watch.delete(id);sync.record(op,id,onSynced)}
  saveWatchLocal();
}

async function setupSync(key){
  syncAvailable=await sync.isAvailable();
  if(key)await openSyncLink(key);
  else if(sync.linked)await pullSync(false);
  window.addEventListener('focus',()=>{if(Date.now()-lastPull>30000)pullSync(false)});
  persistState();
  if(state.view==='watchlist'||state.view==='saving'||state.view==='home')renderContent();
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
    if(joining)sync.connect(key);
    await pullSync(joining);
    if(joining)toast('This device is now synced');
  }catch(error){toast(error.message)}
}

async function pullSync(mergeLocal){
  if(!syncAvailable||!sync.linked)return;
  lastPull=Date.now();
  try{
    const {watch,follows,searches}=await sync.pull();  // The client already merged this device's follows and searches.
    const local=[...state.watch];
    setWatch(watch);adoptFollows(follows);adoptSearches(searches);
    if(mergeLocal)changeWatch('add',local.filter(id=>!watch.includes(id)));  // Joining keeps this device's bills.
    refreshWatch();
  }catch(error){toast(`Sync: ${error.message}`);refreshWatch()}
}

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

function watchTools(){
  const linked=sync.linked,n=state.watch.size,none=n?'':'disabled';
  const syncPart=syncAvailable===false?'<p class="tools-note">Private sync links aren’t switched on for this site yet. Use a share link or a file to move your list for now.</p>'
    :linked?.editKey?`<p class="tools-note">This device is synced; changes save automatically.</p><div class="tools-row"><button class="outline-button" id="sync-copy-edit">Copy edit link</button><button class="outline-button" id="sync-copy-view">Copy view-only link</button><a class="outline-button" href="./api/sync/feed/${esc(linked.viewKey||'')}.xml" target="_blank" rel="noopener noreferrer">Watchlist RSS</a></div><p class="tools-note">Open the <strong>edit link</strong> on your other devices. Anyone who has it can change this list, so keep it private, like a password. The <strong>view-only link</strong> is safe to share.</p><div class="tools-row"><button class="text-button" id="sync-forget">Stop syncing on this device</button><button class="text-button danger" id="sync-delete">Delete sync link</button></div>`
    :`<p class="tools-note">Get a private link that keeps this watchlist the same on your phone, laptop and work computer. No account, email or name.</p><div class="tools-row"><button class="primary-button" id="sync-create" ${syncAvailable?'':'disabled'}>Create sync link</button></div><p class="tools-note">Already have one? Open it on this device.</p>`;
  return `<div class="watch-tools"><section><h3>Save and share</h3><p class="tools-note">Your watchlist is kept in this browser. To move it to another device or person:</p><div class="tools-row"><button class="outline-button" id="share-watch" ${none}>Copy share link</button><button class="outline-button" id="export-watch" ${n||state.follow.length||state.searches.length?'':'disabled'} title="Your watchlist, followed legislators and saved searches, in one file">Export file</button><button class="outline-button" id="import-watch">Import file</button><input type="file" id="import-watch-file" accept=".json,.txt,.csv,application/json,text/plain,text/csv" hidden></div><p class="tools-note">Each bill also has an RSS feed in its details, for following it in Outlook or a feed reader. <a href="#saving" data-view="saving">How saving works →</a></p></section><section><h3>Sync across devices</h3>${syncPart}</section></div>`;
}

async function handleSaveClick(target){
  const hit=sel=>target.closest(sel);
  if(hit('#copy-view-link')){persistState();return copyText(location.href,'Link to this view')}
  if(hit('#share-watch'))return copyText(siteBase()+buildHash('all',{},{list:[...state.watch]}),'Share link');
  if(hit('#export-watch')){download('texas-bill-atlas-saved.json',profileFile({watch:state.watch,follows:state.follow,searches:state.searches}),'application/json');return toast('Watchlist, followed legislators and saved searches exported')}
  if(hit('#import-watch')){$('#import-watch-file').click();return}
  if(hit('#shared-add')){const before=state.watch.size;changeWatch('add',state.sharedList);refreshWatch();return toast(`Added ${state.watch.size-before} bills to your watchlist`)}
  if(hit('#shared-close')){Object.assign(state,{sharedList:null,sharedMode:null,sharedSyncKey:null,visibleCount:30});return renderContent()}
  if(hit('#sync-create')){try{await sync.create([...state.watch],[...state.follow],state.searches);adoptFollows(sync.follows);adoptSearches(sync.searches);renderContent();toast('Sync link created. Copy the edit link to your other devices.')}catch(error){toast(error.message)}return}
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
    const {bills,follows,searches}=parseProfileFile(await file.text()),before=state.watch.size,followed=state.follow.length;
    changeWatch('add',bills);changeFollow('follow',follows);
    const known=new Set(state.searches.map(s=>s.id)),added=searches.filter(s=>!known.has(s.id)).slice(0,Math.max(0,MAX_SEARCHES-state.searches.length));
    for(const s of added)changeSearch('save-search',s);
    refreshWatch();
    toast(`Added ${state.watch.size-before} of ${bills.length} bills${follows.length?`, ${state.follow.length-followed} of ${follows.length} legislators`:''}${searches.length?`, ${added.length} of ${searches.length} saved searches`:''}`);
  }catch(error){toast(`Import failed: ${error.message}`)}
}

async function loadReviewStatus(){
  try{
    const response=await fetch('./live/luna/status.json',{cache:'no-cache',signal:timeoutSignal(7500)});
    if(!response.ok)throw Error(`HTTP ${response.status}`);
    const status=await response.json();
    if(status?.format!=='texas-bill-luna-status-v1'||!Array.isArray(status.reviewed))throw Error('Unrecognized status format');
    state.reviewStatus=status;
  }catch(error){console.warn('Review status unavailable',error.message)}
}

// push=true adds a history entry (opening a bill page), so the browser's Back returns to the page before it.
function setView(view,push=false){
  switchFilters(view);
  state.view=view;
  if(view!=='bill')state.openBill=null;
  document.querySelectorAll('[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===view));
  const [title,subtitle]=viewHeading(view);
  $('#page-title').innerHTML=title;$('#page-subtitle').textContent=subtitle;
  // A bill page has its own header in place of the page heading.
  $('.page-heading').hidden=view==='bill';
  $('#overview').hidden=!['all','watchlist'].includes(view);
  renderNotice();renderOverview();renderContent();persistState(push);
}

function renderNotice(){
  const curated=state.meta?.data_mode==='curated';
  const unavailable=state.meta?.data_mode==='unavailable';
  const imported=state.meta?.data_mode==='local import';
  const fallback=state.meta?.loaded_from==='Bundled fallback snapshot';
  const age=curated||unavailable||imported?null:snapshotAgeHours(state.meta?.generated_at);
  const stale=age!==null&&age>8;
  const ageText=age>=48?`${Math.floor(age/24)} days`:`${Math.floor(age)} hours`;
  const staleCopy=stale?` <strong>Stale: this snapshot is ${ageText} old.</strong> The automated refresh may have stopped; check the official record for current status.`:'';
  const fileName=state.meta?.source_file||String(state.meta?.coverage_note||'').replace(/^Local file:\s*/,'').replace(/\.\s*Imported rows.*$/,'');
  const copy=unavailable?'<strong>Dataset unavailable.</strong> '+esc(state.meta.coverage_note):curated?'<strong>Curated opening-day snapshot.</strong> This is a selection of confirmed filings, not the full 90R docket. Automated official bulk-feed sync is prepared but not yet verified.':imported?`<strong>Local file, not official data.</strong> Showing rows imported from ${esc(fileName)}; they have not been verified against the legislature’s published files.`:fallback?`<strong>Showing the bundled copy.</strong> The live dataset could not be loaded, so this is the bundled snapshot generated ${esc(stampText(state.meta.generated_at))}; it may be out of date.${staleCopy}`:stale?`<strong>Bulk-data snapshot may be out of date.</strong> Generated ${esc(stampText(state.meta.generated_at))}.${staleCopy}`:'<strong>Bulk-data snapshot.</strong> Derived from the legislature’s published files; changes may lag the official record.';
  const warn=unavailable||imported||fallback||stale;
  // A healthy live snapshot gets one slim line; anything to be careful about keeps the full box.
  const slim=!warn&&!curated;
  $('#source-notice').className=`source-notice${warn?' warn':''}${slim?' slim':''}`;
  $('#source-notice').innerHTML=`<span class="notice-icon">${curated?'◷':warn?'!':'✓'}</span><div>${slim?'<strong>Bulk-data snapshot</strong> from the legislature’s published files; it may lag the official record.':copy} <a href="#data" data-view="data">Coverage & sources →</a></div>`;
  $('#footer-timestamp').textContent=`${imported?'Imported':'Snapshot'}: ${stampText(state.meta?.generated_at)}`;
}

function renderOverview(){
  const bills=state.view==='watchlist'?state.bills.filter(b=>state.watch.has(b.id)):state.bills;
  const scheduled=bills.filter(b=>assessHearing(b).level===3).length;
  const today=bills.filter(b=>b.filed_at===new Date().toLocaleDateString('sv-SE',{timeZone:'America/Chicago'})).length;
  const part=(n,one,many,title)=>`<span title="${title}"><strong>${n.toLocaleString()}</strong> ${n===1?one:many}</span>`;
  $('#overview').innerHTML=[part(bills.length,'bill in view','bills in view',state.meta?.data_mode==='curated'?'Curated sample, not the session total':'Bills in this snapshot'),
    part(today,'filed today','filed today','According to the filing dates in the data'),
    part(scheduled,'hearing scheduled','hearings scheduled','Confirmed by recorded actions')].join('<span aria-hidden="true">·</span>');
  $('#nav-all').textContent=state.bills.length;
  $('#nav-watch').textContent=state.watch.size;
  $('#nav-follow').textContent=state.follow.length+state.searches.length;
  const progress=reviewProgress(state.bills.map(b=>b.id),state.reviewStatus,Object.keys(state.luna?.bills||{}));
  $('#nav-review').textContent=progress.reviewed.length+progress.inProgress.length;
}

function renderContent(){renderView(state.view,$('#dynamic-content'))}

// Each view's heading and content. Features take theirs over as they move into src/features/.
function registerViews(){
  registerView('home',{heading:['This session, at a glance.','What changed on your bills, what moved today, upcoming hearings and Luna’s newest reviews.'],render:homeMarkup});
  registerView('all',{heading:['See what’s moving.','Track legislation by policy, affected agency, author influence, and its path through the Capitol.'],render:explorerMarkup,after:renderResults});
  registerView('watchlist',{heading:['Your watchlist.','Bills you starred on this device, with a clear view of their movement.'],render:explorerMarkup,after:renderResults});
  registerView('following',{heading:['Following.','Legislators you follow on this device, and every bill they file or sign onto.'],render:followingMarkup});
  registerView('today',{heading:['Today at the Lege.','Bills with a recorded action today, grouped by type of action. Dates follow Texas time.'],render:todayMarkup});
  registerView('local',{heading:['Near you.','Your Texas House member and Senator, what they filed, and bills that name your county or city.'],render:nearMarkup});
  registerView('member',{heading:['One legislator.','A member’s district and the bills they author, coauthor or sponsor in this snapshot.'],render:memberMarkup});
  registerView('statute',{heading:['One section of law.','The bills that would amend, add or repeal this section of Texas law, with their wording side by side.'],render:statuteMarkup});
  registerView('bill',{heading:['One bill.','Its summary, text, changes to law, people, agencies and sources.'],render:()=>'<article class="bill-page" id="bill-page" aria-label="Bill details"></article>',after:fillBillPage});
  registerView('agencies',{heading:['Follow the agencies.','Explore where legislation might land across Texas government.'],render:agenciesMarkup});
  registerView('review',{heading:['Full-text review.','Which bills Luna has read in full, which it is working on, and what is still waiting.'],render:reviewMarkup});
  registerView('method',{heading:['The scoring method.','Signals and uncertainty are displayed separately from verified legislative actions.'],render:methodMarkup});
  registerView('saving',{heading:['Save your work.','Keep your watchlist and views on one device, carry them in a link or file, or sync them privately.'],render:savingMarkup});
  registerView('data',{heading:['Behind the tracker.','Understand coverage, refreshes, and how to load or export bill data.'],render:dataMarkup});
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
  const agencies=sortAgencyIds(unique([...AGENCIES.map(a=>a.id),...Object.keys(state.luna?.agencies||{})]),agencyName,agencyCounts,agencySortMode());
  const agencyOpts=agencies.map((id,i)=>`<div id="agency-option-${i+1}" role="option" class="agency-option" data-agency-option="${esc(id)}" data-agency-label="${esc(agencyName(id))}" aria-selected="${state.agency===id}"><span>${esc(agencyName(id))}</span><span class="agency-option-count">${agencyCounts.get(id)||0}</span></div>`).join('');
  return `<div id="agency-option-0" role="option" class="agency-option" data-agency-option="" data-agency-label="All affected agencies" aria-selected="${!state.agency}"><span>All affected agencies</span></div>${agencyOpts}<p class="agency-no-results" id="agency-no-results" hidden>No matching agencies</p>`;
}
function agencySortButtons(){
  const mode=agencySortMode();
  return [['name','A–Z'],['count','Most bills']].map(([value,label])=>`<button type="button" data-agency-sort="${value}" aria-pressed="${mode===value}">${label}</button>`).join('');
}

function explorerMarkup(){
  const topics=unique([...POLICY_AREAS.map(t=>t.name),...state.bills.flatMap(b=>b.topics)]).sort();
  const popular=['Education','Healthcare','Elections','Taxes','Immigration','Data centers','Local government','Energy & utilities'];
  return `${sharedBanner()}${state.view==='watchlist'?watchTools():''}
    <div class="explorer-controls"><div class="search-row"><div class="search-wrap"><input aria-label="Search bills" id="bill-search" maxlength="200" placeholder="Search bill number, author, subject, or keyword…" value="${esc(state.query)}" autocomplete="off"></div><button class="outline-button" id="clear-filters">Clear filters</button><button class="outline-button" id="copy-view-link" title="Copy a link to this view, with its filters">Copy link</button>${state.view==='all'&&!state.sharedList?'<button class="outline-button" id="save-search" title="Keep this search and its filters under Following">Save search</button>':''}<button class="primary-button" id="export-csv">↓ Export results</button></div>
    <div class="filter-row"><select aria-label="Policy area" id="filter-topic">${options(topics,state.topic,'All policy areas')}</select><div class="agency-combobox" id="agency-combobox"><input aria-label="Affected agency" aria-controls="agency-options" aria-expanded="false" aria-autocomplete="list" role="combobox" id="filter-agency" placeholder="All affected agencies" value="${esc(state.agency?agencyName(state.agency):'')}" autocomplete="off"><span class="agency-chevron" aria-hidden="true">⌄</span><div class="agency-panel" id="agency-panel" hidden><div class="agency-sort" role="group" aria-label="Sort agencies">${agencySortButtons()}</div><div class="agency-options" id="agency-options" role="listbox" hidden>${agencyOptionsMarkup()}</div></div></div><select aria-label="Chamber" id="filter-chamber">${options(['House','Senate'],state.chamber,'Both chambers')}</select><select aria-label="Author party" id="filter-party" title="Republican or Democratic: the primary author's party, with no author or coauthor from the other party. Bipartisan: authors or coauthors from both parties.">${options(Object.keys(PARTY_FILTERS),state.party,'Any party')}</select><select aria-label="Stage" id="filter-stage">${options(['Filed','Referred','Scheduled','Heard','Advanced','Passed','Enacted'],state.stage,'Any stage')}</select><select aria-label="Hearing status" id="filter-outlook">${options([NO_HEARING,'Referred','Scheduled','Heard'],state.outlook,'Hearing status')}</select><select aria-label="Last action" id="filter-action">${options(unique([...LAST_ACTION_TYPES.map(t=>t.label),'Other action']).filter(l=>l===state.action||state.bills.some(b=>lastActionInfo(b).label===l)),state.action,'Any last action')}</select><button class="check-filter ${state.onlyWatch?'selected':''}" id="watch-filter">☆ Watched only</button></div></div>
    <div class="topic-strip" aria-label="Quick topic filters"><button class="topic-chip ${state.topic===''?'selected':''}" data-topic="">All topics</button>${popular.map(t=>`<button class="topic-chip ${state.topic===t?'selected':''}" data-topic="${esc(t)}">${esc(t)}</button>`).join('')}</div>
    <div class="results-header"><div><strong id="result-count">—</strong><span id="result-note"></span></div><select id="sort-order" aria-label="Sort bills">${options(Object.values(SORTS),SORTS[state.sort],'Sort by')}</select></div><div class="bill-list" id="bill-list"></div><div class="explorer-bottom" id="results-bottom"></div>`;
}

const companionCache={bills:null,index:new Map()};
function companionsOf(id){
  if(companionCache.bills!==state.bills){companionCache.bills=state.bills;companionCache.index=companionIndex(state.bills)}
  return companionCache.index.get(id)||[];
}
const relationText=c=>c.relation?c.relation.toLowerCase():'companion';
// With an agency filter, bills whose companion carries the agency are listed too (marked on the card).
const viaCache={bills:null,maps:new Map()};  // agency id -> bills tagged only through a companion
function agencyVia(agency=state.agency){
  if(!agency)return new Map();
  if(viaCache.bills!==state.bills){companionsOf('');Object.assign(viaCache,{bills:state.bills,maps:new Map()})}
  if(!viaCache.maps.has(agency))viaCache.maps.set(agency,agencyViaCompanion(state.bills,agency,companionCache.index));
  return viaCache.maps.get(agency);
}
// One control for a bill and its companions: watches every one, or unwatches all when all are already watched.
// The watchlist stays a plain list of ids, so sync, share links and export are unchanged.
function groupWatchButton(ids){
  const n=ids.filter(id=>state.watch.has(id)).length,all=n===ids.length;
  const label=all?`★ Watching all ${ids.length}`:n?`☆ Watch all ${ids.length} (${n} watched)`:`☆ Watch all ${ids.length}`;
  return `<button class="companion-watch${all?' on':''}" data-watch-group="${esc(ids.join(','))}" aria-pressed="${all}" title="${all?'Remove these companion bills from your watchlist':'Add every bill in this companion group to your watchlist'}">${label}</button>`;
}

function companionBlock(b){
  const list=companionsOf(b.id);
  if(!list.length)return '';
  const byId=new Map(state.bills.map(x=>[x.id,x]));
  const rows=list.map(c=>{const other=byId.get(c.id);const last=other?lastActionInfo(other):null;
    return `<div class="companion-row"><div><strong>${other?`<button class="text-link companion-open" data-open="${esc(c.id)}">${esc(c.number)}</button>`:esc(c.number)}</strong> <span class="chamber-pill">${esc(c.id.startsWith('H')?'House':'Senate')}</span> <small>${esc(relationText(c))}${c.author?` · by ${memberNameHtml(rosterMember(c.id.startsWith('H')?'house':'senate',c.author),c.author)}`:''}</small><p>${other?esc(other.title):'Not in this snapshot yet; it appears here within about an hour of the Legislative Council publishing it.'}</p></div>${last?`<span class="tag action-tag action-${esc(last.key)}">${esc(last.label)}${last.date?` · ${esc(shortDate(last.date))}`:''}</span>`:''}</div>`}).join('');
  const groupIds=[b.id,...list.filter(c=>byId.has(c.id)).map(c=>c.id)];
  return `<section class="drawer-section companion-section"><div class="companion-section-head"><h3>Companion ${list.length===1?'bill':'bills'} (${list.length})</h3>${groupIds.length>1?groupWatchButton(groupIds):''}</div><p>A companion is a matching bill, usually filed in the other chamber so the same proposal can move in both at once. “Identical”, “similar” and “duplicate” are the Legislative Council's description.</p>${rows}</section>`;
}

function headlineLine(b,where){
  if(typeof b.headline!=='string'||!b.headline)return '';
  return `<p class="bill-headline ${where}"><span class="headline-label">In brief</span> <span class="ai-badge" title="Plain-language line written by Luna from its review; not official">AI</span> <span class="headline-text">${esc(b.headline)}</span></p>`;
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
    if(f.topic&&!b.topics.includes(f.topic))return false;
    if(f.agency&&!b.agencies.some(a=>a.id===f.agency)&&!agencyVia(f.agency).has(b.id))return false;
    if(f.chamber&&b.chamber!==f.chamber)return false;
    if(!partyFilterMatches(b,f.party))return false;
    if(f.outlook&&assessHearing(b).label!==f.outlook)return false;
    if(f.action&&lastActionInfo(b).label!==f.action)return false;
    if(f.stage){const st=(b.status||'').toLowerCase();const outlook=assessHearing(b).label.toLowerCase();if(!st.includes(f.stage.toLowerCase())&&outlook!==f.stage.toLowerCase())return false}
    if(lawBills.has(b.id))return true;
    return !q||b.id.toLowerCase().includes(compact)||textMatches([b.id,b.number,b.title,b.caption,b.author,...b.authors,...(b.coauthors||[]),...(b.sponsors||[]),...(b.cosponsors||[]),b.last_action,...b.topics,...(b.subjects||[]),...(b.search_terms||[]),...b.impacts,...(b.constituencies||[]),...b.agencies.map(a=>agencyName(a.id)),...partyWords(b),shortDate(b.filed_at),shortDate(b.last_action_date)].join(' '),q);
  });
  const byNumber=(a,b)=>a.id.localeCompare(b.id,undefined,{numeric:true});
  const newerNumber=(a,b)=>newestFirst(a.id,b.id);
  const info=new Map(list.map(b=>[b.id,lastActionInfo(b)]));const la=b=>info.get(b.id);
  // Filing dates have no time, so within a day the higher number in each bill type was filed later.
  const sorters={newest:(a,b)=>(b.filed_at||'').localeCompare(a.filed_at||'')||newerNumber(a,b),
    latest:(a,b)=>(la(b).date||'').localeCompare(la(a).date||'')||la(b).rank-la(a).rank||byNumber(a,b),
    oldest:(a,b)=>(la(a).date||'9').localeCompare(la(b).date||'9')||la(a).rank-la(b).rank||byNumber(a,b),
    actionstage:(a,b)=>la(b).rank-la(a).rank||(la(b).date||'').localeCompare(la(a).date||'')||byNumber(a,b),number:byNumber,agencies:(a,b)=>realAgencies(b).length-realAgencies(a).length||byNumber(a,b),hearing:(a,b)=>assessHearing(b).level-assessHearing(a).level||byNumber(a,b),influence:(a,b)=>authorInfluence(b).level-authorInfluence(a).level||byNumber(a,b)};
  return list.sort(sorters[f.sort]||sorters.newest);
}

function renderResults(){
  const list=filteredBills();
  $('#result-count').textContent=`${list.length} ${list.length===1?'bill':'bills'}`;
  $('#result-note').textContent=state.meta?.data_mode==='curated'?' · within curated sample':' · matching filters';
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
  const card=b=>billCard(b,extras.has(b.id));
  const groupMarkup=g=>{
    const ids=new Set(g.map(b=>b.id));
    const relations=[...new Set(g.flatMap(b=>companionsOf(b.id).filter(c=>ids.has(c.id)).map(relationText)))];
    const names=g.map(b=>b.number).join(' + ');
    return `<div class="companion-group" role="group" aria-label="${esc(`${names}: companion bills`)}"><div class="companion-group-head"><span><span aria-hidden="true">⇄</span> Companion bills · ${esc(names)}${relations.length?` · ${esc(relations.join(', '))}`:''}</span>${groupWatchButton(g.map(b=>b.id))}</div>${g.map(card).join('')}</div>`};
  $('#bill-list').innerHTML=statuteHintMarkup(state.sharedList?[]:lawKeysFor(state.query))+(list.length?shown.map(g=>g.length>1?groupMarkup(g):card(g[0])).join(''):`<div class="empty-state"><h3>Nothing matches yet</h3><p>${state.view==='watchlist'?'Star bills from the explorer to follow them here.':'Try a broader topic, agency, or keyword.'}</p></div>`);
  $('#results-bottom').innerHTML=`${list.length>shownCount?`<button class="outline-button" id="load-more">Load 30 more · showing ${shownCount} of ${list.length}</button><div style="height:12px"></div>`:''}${esc(state.meta?.coverage_note||'Check the official record for authoritative status.')}`;
  persistState();
}

function billCard(b,unwatchedCompanion=false){
  const h=assessHearing(b);const watched=state.watch.has(b.id);const influence=authorInfluence(b);
  const real=realAgencies(b);
  const scopeTag=b.agencies.length>real.length?'<span class="tag" title="Cross-cutting scope marker, not an agency">Statewide scope</span>':'';
  const agencyTags=scopeTag+real.slice(0,2).map(a=>`<span class="tag agency" title="${esc(a.reason||'')}">${esc(agencyName(a.id).replace(/^Texas /,'').replace(/ Department of /,' · '))}</span>`).join('');
  const party=authorshipParty(b),last=lastActionInfo(b);
  const companionTags=companionsOf(b.id).map(c=>`<button class="tag companion-tag" data-open="${esc(c.id)}" title="${esc(`Companion bill (${relationText(c)})${c.author?`, by ${c.author}`:''}. Opens its details.`)}">⇄ Companion ${esc(c.number)}</button>`).join('');
  const via=agencyVia().get(b.id);
  const viaTag=via?`<span class="tag agency via-companion" title="${esc(`Not tagged with ${agencyName(state.agency)} itself; listed because its companion ${via.map(id=>companionLabel({id})).join(', ')} is.`)}">via companion ${esc(via.map(id=>companionLabel({id})).join(', '))}</span>`:'';
  const actionTag=`<span class="tag action-tag action-${esc(last.key)}" title="${esc(`Last action${last.chamber?` (${last.chamber})`:''}: ${last.text}`)}">${esc(last.label)}${last.chamber&&last.key!=='filed'?` · ${esc(last.chamber)}`:''}${last.date?` · ${esc(shortDate(last.date))}`:''}</span>`;
  return `<article class="bill-card party-${party.tint}${unwatchedCompanion?' unwatched-companion':''}" data-bill-id="${esc(b.id)}"><div class="bill-left"><div class="bill-head">${unwatchedCompanion?'<span class="unwatched-pill">Companion · not watched</span>':''}${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span><span class="party-pill party-${party.tint}" title="${esc(party.detail)}">${esc(party.label)}</span>${influencePill(influence)}${b.luna?`<span class="luna-pill" title="Tags from the bill's full text, reviewed ${esc(dateText(b.luna.reviewed_at))}">Luna · full text</span>`:''}</div><h3 class="bill-title">${openLinkHtml(b.id,billHref(b.id),'bill-title-link',b.title)}</h3><p class="bill-description">${esc(b.caption)}</p>${headlineLine(b,'card')}<div class="bill-tags">${actionTag}${viaTag}${companionTags}${b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}${agencyTags}${real.length>2?`<span class="tag agency">+${real.length-2} agencies</span>`:''}</div><div class="bill-meta"><span>By <b>${authorHtml(b,b.authors[0]||b.author)}</b></span><span>${b.authors.length?`${b.authors.length} ${b.authors.length===1?'author':'authors'}`:'Authors not reported'}</span><span>${b.coauthors===null?'Coauthors not reported':`${b.coauthors.length} ${b.coauthors.length===1?'coauthor':'coauthors'}`}</span><span>${b.cosponsors===null?'Cosponsors not reported':`${b.cosponsors.length} ${b.cosponsors.length===1?'cosponsor':'cosponsors'}`}</span><span>Filed ${dateText(b.filed_at)}</span><span>${real.length} agency ${real.length===1?'link':'links'}</span></div></div><div class="bill-right"><button class="watch-button" data-watch="${b.id}" aria-label="${watched?'Remove from':'Add to'} watchlist" aria-pressed="${watched}">${watched?'★':'☆'}</button><div><div class="outlook-label">Hearing progress</div><div class="outlook-value">${esc(h.label)}</div><button class="bill-open" data-open="${b.id}">Bill details →</button></div></div></article>`;
}

// ---- Home: the dashboard. Search first, then what changed on your bills, the latest day's actions, hearings and reviews.
const HOME_ROWS=5;
function homeMarkup(){
  const today=todayDay(),prev=visit.prev;
  const more=(href,view,label)=>`<a class="text-link home-more" href="${esc(href)}"${view?` data-view="${view}"`:''}>${label} →</a>`;
  const card=(title,count,body)=>`<section class="home-card"><h2>${title}${count?` <span>${count.toLocaleString()}</span>`:''}</h2>${body}</section>`;
  const datedRow=({bill,day})=>todayRow({bill,actions:(activityOn([bill],day)[0]?.actions||[lastActionInfo(bill).text]).map(t=>`${shortDate(day)} · ${t}`)});
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
  const {day,rows}=todayData();
  const counts=groupByActionType(rows).map(g=>`<span><strong>${g.rows.length.toLocaleString()}</strong> ${esc(g.label.toLowerCase())}</span>`).join('');
  const dayBody=rows.length?`<p class="home-counts">${counts}</p>${rows.slice(0,HOME_ROWS).map(todayRow).join('')}${more('#today','today','The whole day, by topic')}`:'<p class="tools-note">No recorded activity yet.</p>';
  const hearings=state.bills.filter(b=>assessHearing(b).level===3);
  const hearingBody=hearings.length?hearings.slice(0,HOME_ROWS).map(b=>todayRow({bill:b,actions:[lastActionInfo(b).text]})).join('')+(hearings.length>HOME_ROWS?more(buildHash('all',{outlook:'Scheduled'}),'','All scheduled hearings'):'')
    :'<p class="tools-note">No hearings are scheduled yet. Committees post them once the session is under way.</p>';
  const reviewed=newestReviewed(state.bills);
  const reviewBody=reviewed.length?reviewed.slice(0,HOME_ROWS).map(b=>todayRow({bill:b,actions:[`Reviewed ${dateText(b.luna.reviewed_at)}`]})).join('')+more('#review','review','Review progress')
    :'<p class="tools-note">Luna has not reviewed any bills yet.</p>';
  return `<form class="home-search" id="home-search-form" role="search"><label for="home-search">Search every bill</label><div class="home-search-row"><input id="home-search" name="query" maxlength="200" placeholder="Bill number, author, subject, agency or keyword…" autocomplete="off"><button class="primary-button" type="submit">Search</button></div><p class="tools-note">Or <a class="text-link" href="#all" data-view="all">browse all ${state.bills.length.toLocaleString()} bills</a>.</p></form>
    <div class="home-grid">${card(yoursTitle,changed.length,yours)}${card(day===today?'Today at the Lege':`Most recent activity, ${esc(shortDate(day))}`,rows.length,dayBody)}${card('Upcoming hearings',hearings.length,hearingBody)}${card('Newly reviewed by Luna',0,reviewBody)}</div>`;
}

// Remove this line once the Legislature is in session and the view has real floor and hearing content.
const TODAY_INTERIM_NOTE='The 90th Legislature convenes in January 2027; floor calendars and hearings will appear here then.';

// The Today view's day and rows, shared by its markup and "Copy page for AI".
function todayData(){
  const today=chicagoDate(new Date());
  let day=today,rows=activityOn(state.bills,day),note='';
  if(!rows.length){
    const last=latestActivityDay(state.bills,today);
    if(last){day=last;rows=activityOn(state.bills,day)}
    note=`No recorded activity today${last?`; showing ${esc(dateText(last))}`:''}.`;
  }
  const counts=topicCounts(rows.map(r=>r.bill));
  if(state.todayTopic&&!counts.some(c=>c.topic===state.todayTopic))state.todayTopic='';
  const shown=state.todayTopic?rows.filter(r=>r.bill.topics.includes(state.todayTopic)):rows;
  return {today,day,rows,note,counts,shown};
}

function todayMarkup(){
  const {today,day,rows,note,counts,shown}=todayData();
  // Every topic is reachable: the 12 largest show first, the rest behind "+N more"; a selected topic always shows.
  const TOP=12,listed=state.todayAllTopics?counts:counts.filter((c,i)=>i<TOP||c.topic===state.todayTopic);
  const chip=(topic,label)=>`<button class="topic-chip ${state.todayTopic===topic?'selected':''}" data-today-topic="${esc(topic)}" aria-pressed="${state.todayTopic===topic}">${label}</button>`;
  const chips=`<div class="today-topics" role="group" aria-label="Filter this day's bills by topic">${chip('',`All · ${rows.length}`)}${listed.map(c=>chip(c.topic,`${esc(c.topic)} · ${c.count}`)).join('')}${counts.length>TOP?`<button class="text-button" id="today-topics-toggle">${state.todayAllTopics?'Show fewer':`+${counts.length-listed.length} more topics`}</button>`:''}</div>`;
  let budget=state.todayLimit;
  const sections=groupByActionType(shown).map(g=>{
    const part=g.rows.slice(0,Math.max(0,budget));budget-=part.length;
    return part.length?`<section class="today-group"><h3>${esc(g.label)} <span>${g.rows.length}</span></h3>${part.map(todayRow).join('')}</section>`:'';
  }).join('');
  return `<div class="section-head"><div><div class="section-overline">${day===today?'TODAY':'MOST RECENT ACTIVITY'}</div><h2>${esc(dateText(day))}</h2></div><span class="subtitle">${shown.length} ${shown.length===1?'bill':'bills'} with recorded action</span></div>
    <div class="info-callout today-note">${note?`<p>${note}</p>`:''}<p>${esc(TODAY_INTERIM_NOTE)}</p></div>
    ${rows.length?chips:''}${sections||'<div class="empty-state"><h3>No activity to show</h3><p>Nothing is recorded for this day yet.</p></div>'}
    ${shown.length>state.todayLimit?`<button class="outline-button" id="today-more">Show 100 more · showing ${state.todayLimit} of ${shown.length}</button>`:''}`;
}

function todayRow({bill:b,actions}){
  const real=realAgencies(b);
  return `<article class="today-row" data-bill-id="${esc(b.id)}"><div class="today-row-head">${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="chamber-pill">${esc(b.chamber)}</span>${openLinkHtml(b.id,billHref(b.id),'bill-title-link',b.title)}</div>${headlineLine(b,'card')}<p class="today-action">${actions.map(esc).join(' · ')}</p><div class="bill-tags">${b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}${real.slice(0,2).map(a=>`<span class="tag agency">${esc(agencyName(a.id).replace(/^Texas /,'').replace(/ Department of /,' · '))}</span>`).join('')}</div></article>`;
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
    const r=await fetch(url,{signal:timeoutSignal(15000)});if(!r.ok)throw Error(`HTTP ${r.status}`);return [k,await r.json()];
  })).then(parts=>{
    const geo=Object.fromEntries(parts);
    if(geo.tables?.format!=='texas-bill-districts-v1'||!Array.isArray(geo.house?.features))throw Error('Unrecognized district files');
    state.nearGeo=geo;state.nearError='';
  }).catch(error=>{state.nearError='District maps could not be loaded; try again later.';console.warn('Near you data unavailable',error.message)})
    .finally(()=>{nearLoading=null;if(state.view==='local')keepTyping(renderContent)});
  return nearLoading;
}
function saveNear(near){
  state.near=cleanNear(near,state.nearGeo?.tables);state.nearPick=null;state.nearShow={members:30,area:30};
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
  if(!people.length)return `<div class="near-member"><small>${title} · District ${esc(district)}</small><strong>No member listed yet</strong><p>The roster has no member with a known district here yet (a new member's district may not be recorded, or results are not posted). Check <a class="text-link" href="https://capitol.texas.gov/Members/Members.aspx?Chamber=${chamber==='house'?'H':'S'}" target="_blank" rel="noopener noreferrer">Texas Legislature Online ↗</a>.</p></div>`;
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
function nearRow({bill:b,notes}){
  return `<article class="today-row" data-bill-id="${esc(b.id)}"><div class="today-row-head">${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="chamber-pill">${esc(b.chamber)}</span>${openLinkHtml(b.id,billHref(b.id),'bill-title-link',b.title)}</div>${headlineLine(b,'card')}${notes.length?`<p class="today-action">${notes.map(n=>typeof n==='string'?esc(n):`${memberNameHtml(n.member,`${n.member.chamber==='house'?'Rep.':'Sen.'} ${n.member.display_name}`)} · ${esc(n.role)}`).join(' · ')}</p>`:''}<div class="bill-tags">${b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}<span class="tag">${esc(lastActionInfo(b).label)}</span></div></article>`;
}
function nearList(key,rows,empty){
  const limit=state.nearShow?.[key]||30;
  return rows.length?`${rows.slice(0,limit).map(nearRow).join('')}${rows.length>limit?`<button class="outline-button" data-near-more="${key}">Show 30 more · showing ${limit} of ${rows.length}</button>`:''}`:`<p class="review-empty">${empty}</p>`;
}
function nearMarkup(){
  const head=`<div class="section-head"><div><div class="section-overline">NEAR YOU</div><h2>Your legislators and local bills</h2></div><span class="subtitle">Texas House and Senate districts for the 90th Legislature</span></div>`;
  if(!state.nearGeo&&!state.nearError)loadNearGeo();
  if(!state.near)return head+nearSetupMarkup();
  const n=state.near,d=nearData();
  const how={location:'from your location',address:'from the address you looked up',county:'from your county',district:'from the districts you entered'}[n.source];
  const where=[n.house?`House District ${n.house}`:null,n.senate?`Senate District ${n.senate}`:null,n.county?`${n.county} County`:null].filter(Boolean).join(' · ');
  const areaLabel=d.area?.exact?`${n.county} County`:d.area?.counties.length?`your district's ${d.area.counties.length===1?'county':`counties (${d.area.counties.join(', ')})`}`:'your area';
  return `${head}<div class="info-callout near-summary"><div><strong>${esc(where)}</strong> <span>${esc(how)}</span>${n.near?`<p class="near-hint">${n.source==='county'?`${esc(n.county)} County has more than one district, so these are the ones you picked. Check with your location, address or the official lookup.`:'You are close to a district line, so this may be the neighboring district. Check with your address or the official lookup.'}</p>`:''}</div><div class="tools-row"><button class="outline-button" id="near-change">Change</button><button class="outline-button" id="near-forget">Forget on this device</button></div></div>
    <div class="near-members">${memberCard('house',n.house)}${memberCard('senate',n.senate)}</div>
    <section class="today-group"><h3>Filed or signed by your legislators <span>${d.members.length}</span></h3>${nearList('members',d.members,'No bills by your legislators in this snapshot yet.')}</section>
    <section class="today-group"><h3>Bills that name ${esc(areaLabel)} <span>${d.local.length}</span></h3><p class="near-hint">A bill is listed when its full-text review names a county or city here, or its caption names the county. Bills written for areas by population size are not matched yet. ${d.statewide.toLocaleString()} reviewed bills apply statewide and are not listed here.</p>${nearList('area',d.local,'No bill names this area yet.')}</section>
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
const authorHtml=(b,name)=>memberNameHtml(b.people?.authors?.find(p=>p.name===name)?.member||rosterMember(String(b.chamber||'').toLowerCase(),name),name);
// Only the district tables (about 240 KB), not the maps; reused when Near you already loaded everything.
let tablesLoading=null;
function districtTables(){
  if(state.nearGeo?.tables)return state.nearGeo.tables;
  if(state.geoTables)return state.geoTables;
  if(!tablesLoading)tablesLoading=fetch(NEAR_FILES.tables,{signal:timeoutSignal(15000)})
    .then(r=>{if(!r.ok)throw Error(`HTTP ${r.status}`);return r.json()})
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
  if(!state.roster)return `${head('Member roster unavailable')}<div class="info-callout">The member roster could not be loaded, so member pages are not available right now. Try again later.</div>`;
  const m=memberByCode(state.roster,state.memberCode);
  if(!m)return `${head('Member not found')}<div class="info-callout">No member of the 90th Legislature has the code ${state.memberCode?`<strong>${esc(state.memberCode)}</strong>`:'in this address'}. Find members from a bill's authors or from <a class="text-link" href="#local" data-view="local">Near you</a>.</div>`;
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
  return `${head(esc(memberTitle(m)))}<div class="info-callout member-profile"><div><small>${where}</small><strong>${esc(memberSummary(m))}</strong>${tenureTag(m)?`<p>${tenurePill(m)} ${esc(tenureTag(m).detail)}</p>`:''}${countyLine}${links?`<p>${links}</p>`:''}</div><div class="tools-row">${followButton(m)}<a class="outline-button" href="${esc(memberFeedHref(m.code))}" target="_blank" rel="noopener noreferrer">RSS feed</a></div></div>
    <p class="near-hint">${total?`${total} ${total===1?'bill':'bills'} in this snapshot. `:''}${roleNote} Sponsors and cosponsors are listed once a bill crosses chambers, so early in the session most bills show authors only.</p>
    ${sections||'<p class="review-empty">No bills by this member in this snapshot yet.</p>'}`;
}

// ---- Statutes: which sections of Texas law each bill changes, and the versions side by side ----
// The index (live/statutes/index.json) is optional; without it the drawer list, statute pages and section search hide.
const BROAD_BILL=25;  // A bill changing more sections than this is "broad"; its versions sort after focused bills.
let statutesLoad=null,statuteBills=new Map();
const statuteDocs=new Map();  // key -> section document, 'loading' or 'error'
function loadStatutes(){
  return statutesLoad||(statutesLoad=(async()=>{
    try{
      const r=await fetch('./live/statutes/index.json',{cache:'no-cache',signal:timeoutSignal(15000)});
      if(!r.ok)throw Error(`HTTP ${r.status}`);
      const index=await r.json();
      if(!validStatuteIndex(index))throw Error('Unrecognized statute index');
      state.statutes=index;statuteBills=statutesByBill(index);
    }catch(error){state.statutes=null;state.statutesFailed=true;console.warn('Statute index unavailable',error.message)}
    // Views drawn before it arrived: section search results, saved-search counts, the statute page, the open drawer.
    if(state.view==='all'||state.view==='watchlist')renderResults();
    else if(state.view==='following'||state.view==='statute')renderContent();
    if(state.openBill)fillDrawerStatutes(state.openBill);
  })());
}
function statuteDoc(key){
  const have=statuteDocs.get(key);
  if(have)return have;
  const file=statuteFile(key);
  if(!file)return 'error';
  statuteDocs.set(key,'loading');
  (async()=>{
    try{
      const r=await fetch(`./live/statutes/sections/${file}`,{cache:'no-cache',signal:timeoutSignal(15000)});
      if(!r.ok)throw Error(`HTTP ${r.status}`);
      const doc=await r.json();
      if(!validStatuteSection(doc,key))throw Error('Unrecognized statute section');
      statuteDocs.set(key,doc);
    }catch(error){statuteDocs.set(key,'error');console.warn('Statute section unavailable',key,error.message)}
    if(state.view==='statute'&&state.statuteKey===key)renderContent();
  })();
  return 'loading';
}
const statuteHref=key=>buildHash('statute',{},{statute:key});
const billNumber=id=>state.bills.find(b=>b.id===id)?.number||id;
const SMALL_WORDS=new Set(['a','an','and','as','at','by','for','in','of','on','or','the','to','with','from','under']);
// "FUNDING FOR CERTAIN SCHOOLS" -> "Funding for Certain Schools"
const titleCase=text=>String(text||'').toLowerCase().split(' ').map((w,i)=>i&&SMALL_WORDS.has(w)?w:w.charAt(0).toUpperCase()+w.slice(1)).join(' ');
const statuteLink=key=>`<a class="text-link" href="${esc(statuteHref(key))}">${esc(statuteLabel(key,state.statutes?.codes))}</a>`;

function fillDrawerStatutes(id){
  const el=$('#drawer-statutes');
  if(!el||state.openBill!==id)return;
  const rows=(statuteBills.get(id)||[]).slice().sort((a,b)=>b.others-a.others||a.key.localeCompare(b.key,undefined,{numeric:true}));
  const meta=state.statutes?.bills?.[id];
  if(!state.statutes||(!rows.length&&!meta?.u)){el.hidden=true;el.innerHTML='';return}
  const item=r=>{const h=state.statutes.sections[r.key]?.h;
    return `<li>${statuteLink(r.key)}${h?` <span class="law-heading">${esc(titleCase(h))}</span>`:''} <small>· ${esc(STATUTE_KINDS[r.kind])}${r.others?` · <strong>${r.others} other ${r.others===1?'bill':'bills'}</strong>`:''}</small></li>`};
  const shown=rows.slice(0,8),rest=rows.slice(8);
  const contested=rows.filter(r=>r.others&&r.kind==='m').length;
  el.innerHTML=`<h3>Laws this bill changes${rows.length?` (${rows.length})`:''}</h3>
    <p>Sections of Texas law named in this bill's latest text${contested?`. ${contested} ${contested===1?'is':'are'} also amended by other bills: open one to compare the versions side by side`:''}.</p>
    ${rows.length?`<ul class="law-list">${shown.map(item).join('')}</ul>`:''}${rest.length?`<details class="law-more"><summary>Show all ${rows.length}</summary><ul class="law-list">${rest.map(item).join('')}</ul></details>`:''}
    ${meta?.u?`<p><small>${meta.u} ${meta.u===1?'change':'changes'} in this bill could not be matched to a section; see the bill text.</small></p>`:''}`;
  el.hidden=false;
}

// ---- Population brackets: src/features/brackets/view.js ----

// One side of the comparison: Current law, or one version (a group of bills with the same wording).
function lawOptions(doc,groups){
  const law=currentLaw(doc.entries),options=[];
  const names=g=>g.entries.map(e=>billNumber(e.bill)).join(' = ');
  if(law.units.length)options.push({id:'law',name:'current law',label:`Current law, as quoted in ${law.sources.map(billNumber).join(', ')}`,units:law.units,partial:law.partial});
  for(const g of groups){
    if(g.kind==='repeal'||!g.units.length)continue;
    const e=g.entries[0];
    options.push({id:e.bill,name:names(g),label:`${names(g)} · ${g.kind==='add'?'new section':'amended'} · ${e.version_name||e.version}${g.broad?' · broad bill':''}`,units:g.units,partial:g.partial});
  }
  return options;
}
function lawWords(words,cls){
  return words.map(w=>w.t==='\n'?'<br>':`${w.space?' ':''}${w.changed?`<mark class="${cls}">${esc(w.t)}</mark>`:esc(w.t)}`).join('');
}
function lawCompareMarkup(options){
  if(options.length<2){
    const only=options[0];
    return only?`<section class="law-compare-wrap"><h3>${esc(only.label)}</h3><div class="law-single">${only.units.map(u=>`<p>${esc(u.text).replaceAll('\n','<br>')}</p>`).join('')}</div></section>`:'';
  }
  const c=state.statuteCompare;
  const pick=(id,fallback)=>options.find(o=>o.id===id)||fallback;
  const left=pick(c.left,options[0]),right=pick(c.right,options.find(o=>o!==left));
  const select=(side,current)=>`<label class="law-pick"><span>${side==='left'?'Left':'Right'}</span><select data-law-side="${side}">${options.map(o=>`<option value="${esc(o.id)}" ${o===current?'selected':''}>${esc(o.label)}</option>`).join('')}</select></label>`;
  const rows=left===right?[]:compareLaw({name:left.name,units:left.units,partial:left.partial},{name:right.name,units:right.units,partial:right.partial});
  const label=l=>l==='head'?'Heading':l===''?'Text':`(${l})`;
  const changed=rows.filter(r=>!r.same).length;
  // data-name labels each cell when the columns stack on a phone.
  const cell=(words,note,cls,name)=>words?`<div class="law-cell" data-name="${esc(name)}">${lawWords(words,cls)}</div>`:`<div class="law-cell law-missing" data-name="${esc(name)}">${esc(note)}</div>`;
  const body=rows.map(r=>`<div class="law-row${r.same?' law-same':''}"><div class="law-label">${esc(label(r.label))}${r.same?' · same':''}</div>${cell(r.left,r.leftNote,'law-out',left.name)}${cell(r.right,r.rightNote,'law-in',right.name)}</div>`).join('');
  const show=state.statuteShow||'both';
  return `<section class="law-compare-wrap"><h3>Side by side</h3>
    <div class="law-picks">${select('left',left)}${select('right',right)}</div>
    <p class="law-legend"><mark class="law-out">Highlighted on the left</mark> is wording only the left has; <mark class="law-in">highlighted on the right</mark> is wording only the right has. ${left===right?'Pick two different versions.':`${changed} of ${rows.length} ${rows.length===1?'part differs':'parts differ'}.`}${rows.some(r=>r.approximate)?' Some parts are too long to compare word by word and are marked whole.':''}</p>
    <div class="law-toggle" role="group" aria-label="Columns to show">${[['both','Both'],['left','Left'],['right','Right']].map(([v,t])=>`<button type="button" class="outline-button${show===v?' active':''}" data-law-show="${v}" aria-pressed="${show===v}">${t}</button>`).join('')}</div>
    <div class="law-compare" data-show="${show}"><div class="law-row law-head"><div class="law-label"></div><div class="law-cell">${esc(left.label)}</div><div class="law-cell">${esc(right.label)}</div></div>${body}</div></section>`;
}

function statuteMarkup(){
  const key=state.statuteKey;
  const head=(title,sub='90th Legislature · every bill that changes it')=>`<div class="section-head"><div><div class="section-overline">TEXAS LAW</div><h2>${title}</h2></div><span class="subtitle">${sub}</span></div>`;
  if(!key)return `${head('Section not found')}<div class="info-callout">This address does not name a section of Texas law. Open one from a bill's "Laws this bill changes" list, or search the explorer for a section number such as 48.160.</div>`;
  if(!state.statutes)return state.statutesFailed?`${head(esc(key))}<div class="info-callout">The list of laws each bill changes is not available right now. Try again later.</div>`:`${head(esc(key))}<p class="near-hint">Loading…</p>`;
  const label=statuteLabel(key,state.statutes.codes),info=state.statutes.sections[key];
  const official=`<a class="text-link" href="${esc(officialStatuteUrl(key))}" target="_blank" rel="noopener noreferrer">Current law on statutes.capitol.texas.gov ↗</a>`;
  if(!info)return `${head(esc(label))}<div class="info-callout">No bill in this snapshot changes ${esc(label)}. ${official}</div>`;
  const doc=statuteDoc(key);
  const title=head(esc(label),info.h?esc(titleCase(info.h)):undefined);
  if(doc==='loading')return `${title}<p class="near-hint">Loading the bills' versions…</p>`;
  if(doc==='error')return `${title}<div class="info-callout">The versions of this section could not be loaded. ${official}</div>`;
  if(state.statuteCompare?.key!==key)state.statuteCompare={key,left:null,right:null};
  const groups=groupStatuteEntries(doc.entries,id=>(state.statutes.bills[id]?.n||0)>BROAD_BILL);
  const options=lawOptions(doc,groups);
  const row=g=>{
    const e=g.entries[0];
    const bills=g.entries.map(x=>{const b=state.bills.find(y=>y.id===x.bill);return b?`${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)} <span class="law-status">${esc(lastActionInfo(b).label)}</span>`:esc(x.bill)}).join('<span class="law-same-text"> = </span>');
    const parts=g.kind==='amend'&&g.partial&&e.subsections?.length?`subsections ${e.subsections.map(s=>`(${s})`).join(', ')}`:g.kind==='amend'?'whole section':'';
    const notes=[e.version_name||e.version,parts,g.entries.length>1?'same wording':'',g.broad?`broad bill · changes ${state.statutes.bills[e.bill]?.n} sections`:''].filter(Boolean);
    const compare=g.kind!=='repeal'&&g.units.length&&options.length>1?`<button type="button" class="outline-button" data-law-compare="${esc(e.bill)}">Compare</button>`:'';
    return `<li class="law-version${g.broad?' law-broad':''}"><div>${bills}</div><small>${esc(notes.join(' · '))}</small>${compare}</li>`;
  };
  const block=(kind,heading,intro)=>{const list=groups.filter(g=>g.kind===kind);return list.length?`<section class="today-group"><h3>${heading} <span>${list.reduce((n,g)=>n+g.entries.length,0)}</span></h3>${intro?`<p class="near-hint">${intro}</p>`:''}<ul class="law-versions">${list.map(row).join('')}</ul></section>`:''};
  return `${title}<div class="info-callout law-intro"><p>Each bill quotes the wording it would change, so current law below is as those bills quote it. It can trail the official text if a later law changed it. ${official}</p></div>
    ${lawCompareMarkup(options)}
    ${block('amend','Bills that amend this section','')}
    ${block('add','Bills that add a new section with this number','Each of these adds a section numbered '+esc(key.split(' ')[1])+'. Bills drafted separately can pick the same next number for unrelated subjects, so check the wording.')}
    ${block('repeal','Bills that repeal it','')}`;
}

// Explorer: a search for a section number lists the bills that change it; this links to their comparison.
function statuteHintMarkup(keys){
  if(!keys.length)return '';
  return `<div class="info-callout statute-hint">Bills that change ${keys.map(statuteLink).join(', ')} are included. Open ${keys.length===1?'it':'one'} to compare their versions side by side.</div>`;
}

function agenciesMarkup(){
  const counts=new Map();for(const b of state.bills)for(const a of realAgencies(b))counts.set(a.id,(counts.get(a.id)||0)+1);
  const agencies=unique([...AGENCIES.map(a=>a.id),...Object.keys(state.luna?.agencies||{})]).filter(id=>id!==SCOPE_AGENCY_ID).map(id=>({id,name:agencyName(id)})).sort((a,b)=>(counts.get(b.id)||0)-(counts.get(a.id)||0)||a.name.localeCompare(b.name));
  return `<div class="section-head"><div><div class="section-overline">IMPACT DIRECTORY</div><h2>Texas state agencies</h2></div><span class="subtitle">${counts.size} with possible links in this snapshot</span></div><div class="info-callout"><strong>Why an agency index?</strong> One bill can change the work of several state agencies. “Direct” means the supplied material names an agency; “possible” means an inferred policy connection. An agency absent from a caption is not proof it is unaffected—full bill text review is needed for comprehensive coverage.</div><div class="agency-grid" style="margin-top:18px">${agencies.map(a=>`<button class="agency-card" data-agency-pick="${esc(a.id)}"><span class="agency-code">${esc(a.id.toUpperCase())}</span><strong>${esc(a.name)}</strong><span class="hits">${counts.get(a.id)||0} ${counts.get(a.id)===1?'bill':'bills'} in snapshot →</span></button>`).join('')}</div>`;
}

function reviewMarkup(){
  const ids=state.bills.map(b=>b.id),status=state.reviewStatus,tagged=state.luna?.bills||{};
  const s=reviewSummary(reviewProgress(ids,status,Object.keys(tagged)));
  const total=ids.length||1,pct=n=>Math.round(n/total*1000)/10;
  const minutes=status?.updated_at?(Date.now()-Date.parse(status.updated_at))/60000:null;
  const stale=Boolean(status?.running)&&minutes>90;
  const quiet=Boolean(status)&&!status.running&&minutes>75;  // runs are hourly; each one rewrites the status
  const waiting=Boolean(status?.running)&&!stale&&Date.parse(status.waiting_until)>Date.now();
  const line=!status?'Live worker status is unavailable, so bills with published Luna tags are counted as reviewed.'
    :stale?`The worker last reported ${esc(stampText(status.updated_at))} and may have stopped.`
    :quiet?`No hourly run has reported since ${esc(stampText(status.updated_at))}; the worker may be stopped.`
    :waiting?`Waiting for Luna capacity · ${status.current?`retrying ${esc(status.current)}`:'resuming'} at ${esc(stampText(status.waiting_until))}`
    :status.running?`Reviewing now · updated ${esc(stampText(status.updated_at))}`
    :`Idle until the next hourly run · last update ${esc(stampText(status.updated_at))}`;
  const chip=(id,note='')=>`<button class="review-chip${tagged[id]?' tagged':''}" data-open="${esc(id)}" title="${tagged[id]?'Luna tags published':'Reviewed; no verified tags published'}${note?' · '+esc(note):''}">${esc(id)}</button>`;
  const group=(title,list,empty,open=true)=>`<details class="review-group"${open?' open':''}><summary><strong>${title}</strong> <span>${list.length.toLocaleString()}</span></summary>${list.length?`<div class="review-chips">${list.join('')}</div>`:`<p class="review-empty">${empty}</p>`}</details>`;
  const counts=[['Reviewed',s.reviewed.length,'done'],...(s.active.length?[['Reviewing now',s.active.length,'progress']]:[]),
    ['Waiting for bill text',s.noText.length,'notext'],...(s.failed.length?[['Failed',s.failed.length,'failed']]:[]),
    ['Not started',s.notStarted.length,'waiting']];
  const now=s.active.length&&!stale?`<div class="review-now"><span class="review-pulse" aria-hidden="true"></span><div><small>${waiting?'Waiting to retry':'Reviewing now'}</small>${s.active.map(id=>chip(id)).join('')}</div>${s.upcoming.length?`<div><small>Up next</small>${s.upcoming.map(id=>chip(id)).join('')}</div>`:''}</div>`:'';
  const auditText=auditLine(state.audit);
  const headline=`<p class="review-headline"><strong>${s.reviewed.length.toLocaleString()} of ${ids.length.toLocaleString()} bills reviewed</strong> (${pct(s.reviewed.length)}%)${s.questionsQueued.length?` · ${s.questionsQueued.length.toLocaleString()} of them have follow-up questions queued`:''}</p>`;
  return `<div class="section-head"><div><div class="section-overline">LUNA FULL-TEXT REVIEW</div><h2>Review progress</h2></div><span class="subtitle">${line}</span></div>
  ${headline}
  <div class="review-bar" role="img" aria-label="${counts.map(([label,n])=>`${n} ${label.toLowerCase()}`).join(', ')} of ${ids.length}">${counts.map(([,n,cls])=>`<span class="seg ${cls}" style="width:${pct(n)}%"></span>`).join('')}</div>
  <div class="review-counts">${counts.map(([label,n,cls])=>`<div class="review-count ${cls}"><span class="dot"></span><strong>${n.toLocaleString()}</strong><span>${label} · ${pct(n)}%</span></div>`).join('')}</div>
  ${now}
  ${group('Reviewed',s.reviewed.map(id=>chip(id,s.questionsQueued.includes(id)?'follow-up questions queued':'')),'No bills reviewed yet.')}
  ${group('Follow-up questions queued',s.questionsQueued.map(id=>chip(id,'first-pass review published; follow-up questions run on a later visit')),'No follow-up questions waiting.',false)}
  ${group('Waiting for bill text',s.noText.map(id=>chip(id,'the legislature has not posted text yet')),'Every bill has text.',false)}
  ${s.failed.length?group('Failed',s.failed.map(f=>chip(f.id,f.stage?`${f.stage} failed`:'failed')),'No failures.'):''}
  ${group('Not started',s.notStarted.map(id=>chip(id)),'Every bill has been picked up.',false)}
  ${auditText?`<p class="review-audit">${esc(auditText)}</p>`:''}
  <p class="review-legend"><span class="review-chip tagged">HB1</span> verified Luna tags published · <span class="review-chip">HB1</span> reviewed, no claims verified against the text yet. Bills waiting for text are retried automatically once the legislature posts it. Follow-up questions refine a review that is already published.</p>`;
}

function methodMarkup(){
  const parts=[
    ['01','What is affected','Bills can carry many policy tags, legal effects, affected populations, local-government layers, and agencies. A tag can be explicitly supported or an inference, and we show that distinction.'],
    ['02','Who filed it','Author influence is based on independently verified roles: chamber leadership, committee chairmanship, relevant committee seats, and legislative tenure. We do not assign prominence just for party or media attention.'],
    ['03','Chance of a hearing','Instead of invented percentages, the tracker initially shows whether referral, scheduling, or an actual hearing is confirmed. Once there is historical and committee data, a calibrated probability model can be added.'],
    ['04','Likelihood of passage','Passage requires a separate model: committee action, chamber calendars and votes, companion progress, cross-chamber support, deadlines, and executive position. No passage probabilities are currently claimed.'],
    ['05','What changes over time','Each action, bill version, fiscal note, referral, hearing notice, companion filing, and author role can add or change signals. The dataset preserves source timestamps and links to the state record.'],
    ['06','Known limitations','Automated agency extraction from captions is incomplete. Predictions in early prefiling are particularly unstable, and committee assignments after the election must be verified before influence scoring.']
  ];
  return `<div class="section-head"><div><div class="section-overline">EXPLAINABLE SIGNALS</div><h2>Verified facts first. Forecasts second.</h2></div></div><div class="info-callout"><strong>A filed bill is not a viable bill by default.</strong> Hearing progress, author prominence, policy impact, and predicted enactment are separate dimensions. No numeric forecast appears without a measured historical basis and a stated confidence level.</div><div class="method-grid">${parts.map(([n,title,body])=>`<article class="method-card"><span class="n">${n}</span><h3>${title}</h3><p>${body}</p></article>`).join('')}</div>`;
}

function savingMarkup(){
  const linked=sync.linked;
  const syncState=syncAvailable===false?'Not switched on for this site':syncAvailable?'Available':'Checking…';
  const deviceState=linked?.editKey?'Synced (edit link)':'Not synced';
  const parts=[
    ['01','Your watchlist','Star any bill to follow it. The list is kept in this browser on this device, with nothing sent anywhere. Clearing site data, or using a private window, removes it, so use one of the options below if you want a copy.'],
    ['02','Remembered filters','Your last filters and sort order are remembered on this device and come back the next time you visit.'],
    ['03','Links to any view','The address bar always describes what you are looking at: the page, filters, sort and any open bill. Use <strong>Copy link</strong> above the results, or bookmark the page, to return to it or send it to someone.'],
    ['04','Share links','On the Watchlist, <strong>Copy share link</strong> makes a link to your bills. Whoever opens it sees a read-only list and can add those bills to their own watchlist. It is a snapshot: later changes to your list are not included.'],
    ['05','Export and import a file','<strong>Export file</strong> saves your watchlist, followed legislators and saved searches as one small file you can keep or email. <strong>Import file</strong> adds them from that file (or an older watchlist export), or from any text or spreadsheet export that mentions bill numbers such as “HB 5” or “SJR 9”. Importing only adds; it never removes bills.'],
    ['06','Private sync links','<strong>Create sync link</strong> on the Watchlist keeps your watchlist, followed legislators and saved searches the same on your phone, laptop and work computer, with no account. Open the <strong>edit link</strong> on each device; treat it like a password, because anyone with it can change the list. The <strong>view-only link</strong> is safe to share: it shows your watchlist’s bills only, never who you follow or what you saved, and stays current as you edit. You can stop syncing one device, or delete the link for every device.'],
    ['07','RSS feeds','Each bill’s details include an <strong>RSS feed</strong> of its recorded actions, for Outlook or any feed reader. A synced watchlist also has one feed for all of its bills, linked from the Watchlist. Each legislator has a feed too, linked from their member page.'],
    ['08','Followed legislators','<strong>Follow</strong> a legislator on their member page or in Near you, and their bills appear under <strong>Following</strong>. Follows are kept in this browser like the watchlist, and go into exported files and sync links. Share links and view-only links never include them.'],
    ['09','Saved searches','On the Bill explorer, <strong>Save search</strong> keeps the current search words and filters under <strong>Following</strong>, with how many bills have new actions since you last opened it. Saved searches go into exported files and sync links like follows; share and view-only links never include them.']
  ];
  return `<div class="section-head"><div><div class="section-overline">NO ACCOUNT NEEDED</div><h2>Saving and sharing your info</h2></div><button class="outline-button" data-view="watchlist">Open your watchlist →</button></div><div class="info-callout"><strong>There are no logins on this site.</strong> Everything below works without an account, email address or name. Pick whichever fits: keep things on one device, carry them in a link or file, or sync a private link across devices.</div><div class="method-grid">${parts.map(([n,title,body])=>`<article class="method-card"><span class="n">${n}</span><h3>${title}</h3><p>${body}</p></article>`).join('')}</div><div class="section-head"><div><div class="section-overline">PRIVACY</div><h2>What is stored, and where</h2></div></div><div class="subpage-card"><div class="data-field long"><span class="data-label">On this device</span><span class="data-value">Watchlist, followed legislators, saved searches, last filters, that you saw the disclaimer, and your sync link if you made one</span></div><div class="data-field long"><span class="data-label">On the server (sync links only)</span><span class="data-value">The watched bill numbers, the member codes of legislators you follow, your saved searches (their names, search words and filters), a version number and dates. Links are stored only as one-way fingerprints, so the database cannot be used to open a list.</span></div><div class="data-field long"><span class="data-label">Never collected</span><span class="data-value">Names, email addresses, accounts, tracking cookies or analytics</span></div><div class="data-field long"><span class="data-label">Abuse limits</span><span class="data-value">The sync service counts requests per address in memory for up to an hour, and never writes addresses down</span></div><div class="data-field long"><span class="data-label">Retention</span><span class="data-value">A sync link unused for a year is deleted. Deleting it yourself removes it at once; each device keeps its own copy of the list.</span></div><div class="data-field"><span class="data-label">Sync on this site</span><span class="data-value">${esc(syncState)}</span></div><div class="data-field"><span class="data-label">This device</span><span class="data-value">${esc(deviceState)} · ${state.watch.size} ${state.watch.size===1?'bill':'bills'} watched</span></div><p style="font-size:11px;color:color-mix(in srgb,var(--ink) 45%,var(--surface));margin:14px 0 0">Limits: up to 500 bills per synced list. Lost your edit link? Your list is still on each device that had it; create a new sync link from any of them.</p></div>`;
}

function dataMarkup(){
  return `<div class="section-head"><div><div class="section-overline">DATA PROVENANCE</div><h2>Source, coverage & export</h2></div></div><div class="subpage-card"><div class="data-field"><span class="data-label">Legislative session</span><span class="data-value">90R · 2027</span></div><div class="data-field"><span class="data-label">Loaded records</span><span class="data-value">${state.bills.length}</span></div><div class="data-field"><span class="data-label">Snapshot mode</span><span class="data-value">${esc(state.meta?.data_mode||'Unknown')}</span></div><div class="data-field"><span class="data-label">Read from</span><span class="data-value">${esc(state.meta?.loaded_from||'User import')}</span></div><div class="data-field"><span class="data-label">Last generated</span><span class="data-value">${stampText(state.meta?.generated_at)}</span></div><div class="data-field"><span class="data-label">Luna reviews</span><span class="data-value">${state.luna?`${Object.keys(state.luna.bills).length} bills · updated ${esc(stampText(state.luna.generated_at))}`:'not available'}</span></div><div class="data-field"><span class="data-label">Member roster</span><span class="data-value">${state.roster?`${state.roster.counts?.house??'?'} House · ${state.roster.counts?.senate??'?'} Senate · updated ${esc(stampText(state.roster.generated_at))}`:'not available'}</span></div><p style="font-size:12px;color:color-mix(in srgb,var(--ink) 57%,var(--surface));line-height:1.65;margin:18px 0">${esc(state.meta?.coverage_note||'Coverage is not guaranteed complete.')}</p><div class="info-callout"><strong>Official source policy:</strong> The Texas Legislative Council publishes bulk material through anonymous FTP and discourages data mining the public Legislature Online pages. The project includes an updater for the official bulk files, with snapshot validation so a failed import cannot silently replace data with an empty result. <a class="text-link" href="https://capitol.texas.gov/billlookup/filedownloads.aspx" target="_blank" rel="noopener noreferrer">Read the source policy ↗</a></div><div class="data-actions"><button class="primary-button" id="import-trigger">↑ Import CSV or JSON</button><button class="outline-button" id="export-csv">↓ Export current results</button><a class="outline-button" href="https://github.com/ctharvey/texas_bill_tracker" target="_blank" rel="noopener noreferrer">Source code ↗</a><input type="file" id="import-file" accept=".csv,.json,text/csv,application/json" hidden></div><p style="font-size:11px;color:color-mix(in srgb,var(--ink) 45%,var(--surface));margin:14px 0 0">Imports are temporary to this browser session; they do not alter the public dataset. Watchlist stars are stored on this device.</p></div>`;
}

function lunaBlock(b){
  if(!b.luna)return '';
  const locs=(b.locations||[]).map(l=>`<li><strong>${esc(l.name)}</strong>${l.kind?` (${esc(l.kind)})`:''}${l.explanation?` · ${esc(l.explanation)}`:''}</li>`).join('');
  return `<section class="drawer-section luna-block"><h3>Full-text review by Luna</h3><p><small>Reviewed ${esc(dateText(b.luna.reviewed_at))}${b.luna.text_version?` · ${esc(b.luna.text_version)} text`:''}</small></p>${b.luna.summary?`<p>${esc(b.luna.summary)}</p>`:''}<p><small>Tags from the bill's full text; fields not verified against the text use caption inference.</small></p>${locs?`<h4>Locations</h4><ul>${locs}</ul>`:''}</section>`;
}

function memberItem({name,member}){
  const letter=member?.party==='Democratic'?'dem':member?.party==='Republican'?'rep':'unknown';
  const official=safeHref(member?.links?.lrl||member?.links?.tlo);
  const label=member?.full_name||name;
  // The name opens the member's page here; the official record stays one click away.
  const who=member?.code?`<a class="text-link" href="${esc(memberHref(member.code))}">${esc(label)}</a>`:`<strong>${esc(label)}</strong>`;
  return `<li><span class="party-dot party-${letter}" aria-hidden="true"></span>${who} ${tenurePill(member)} <small>${esc(memberSummary(member))}</small>${official?` <a class="text-link member-official" href="${esc(official)}" target="_blank" rel="noopener noreferrer" aria-label="Official record for ${esc(label)}">official ↗</a>`:''}</li>`;
}

function billTextSection(b){
  const section=document.createElement('section');section.className='drawer-section bill-text-section';
  const heading=document.createElement('h3');heading.textContent='Bill text';
  const intro=document.createElement('p');intro.textContent='Read the filed text with additions underlined and deletions struck through. Luna highlights show where its tags come from.';
  const button=document.createElement('button');button.className='outline-button';button.type='button';button.textContent='Show bill text';
  const picker=document.createElement('div');picker.className='bt-versions';
  const area=document.createElement('div');area.setAttribute('aria-live','polite');
  const official=document.createElement('p');official.hidden=true;
  const link=document.createElement('a');link.className='text-link';link.href=/^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/.test(b.id)?`https://capitol.texas.gov/BillLookup/Text.aspx?LegSess=90R&Bill=${b.id}`:officialUrl(b);link.target='_blank';link.rel='noopener noreferrer';link.textContent='Read the official text on Texas Legislature Online ↗';
  official.append(link);
  section.append(heading,intro,button,picker,area,official);
  const idOk=/^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/.test(b.id);
  const fetchText=async url=>{const r=await fetch(url,{cache:'no-cache',signal:timeoutSignal(20000)});if(r.status===404)return null;if(!r.ok)throw Error('HTTP '+r.status);return r};
  let selected=null,versions=[],select=null,highlightsPromise=null;
  const highlightsOnce=()=>highlightsPromise||(highlightsPromise=(async()=>{try{const hr=await fetchText(`./live/luna/highlights/${b.id}.json`);return hr?await hr.json():null}catch{return null}})());
  const loadVersion=async(index,version)=>{
    selected=version.code;area.textContent='Loading bill text…';
    const stale=()=>state.openBill!==b.id||selected!==version.code;
    try{
      if(!/^[A-Z0-9]{1,3}$/.test(version.code))throw Error('Unexpected version code');
      const textResponse=await fetchText(`./live/text/${b.id}/${version.code}.md`);
      if(!textResponse)throw Error('This version is not available yet');
      const raw=await textResponse.text();
      let highlights=null,note,other=null;
      const candidate=await highlightsOnce();
      if(candidate&&typeof candidate.text_version==='string'){
        if(candidate.text_version===version.code){
          if(validHighlights(candidate,b.id,version.code,await sha256Hex(raw)))highlights=candidate;
          else note='Luna highlights do not match this version of the text.';
        }else{
          const idx=versions.findIndex(v=>v.code===candidate.text_version);
          if(idx>=0){other={idx,name:versions[idx].name||versions[idx].code};note=' '}
        }
      }
      const parsed=parseBillMarkdown(raw);
      if(stale())return;
      renderBillText(area,parsed,highlights,{highlightsNote:note,idPrefix:`bt-${b.id}`});
      if(other){
        const line=document.createElement('p');line.className='bt-note';
        const go=document.createElement('button');go.type='button';go.className='outline-button';go.textContent=`Luna's highlights are on the ${other.name} text`;
        go.addEventListener('click',()=>{if(select){select.value=String(other.idx)}loadVersion(other.idx,versions[other.idx])});
        line.append(go);area.prepend(line);
      }
    }catch(error){
      if(stale())return;
      area.textContent='The bill text could not be shown: '+error.message;
    }
  };
  button.addEventListener('click',async()=>{
    button.disabled=true;official.hidden=false;area.textContent='Loading bill text…';
    try{
      if(!idOk)throw Error('Unexpected bill id');
      const response=await fetchText(`./live/text/${b.id}/index.json`);
      if(state.openBill!==b.id)return;
      if(!response){
        area.replaceChildren(document.createTextNode('The bill text is not on this site yet; it is added within a few hours of filing. Read it on '),link,document.createTextNode('.'));
        official.hidden=true;button.hidden=true;return;
      }
      const index=await response.json();
      versions=Array.isArray(index?.versions)?index.versions.filter(v=>v&&/^[A-Z0-9]{1,3}$/.test(v.code)):[];
      if(index?.format!=='texas-bill-text-index-v1'||index.bill_id!==b.id||!versions.length)throw Error('The text index is not valid');
      if(state.openBill!==b.id)return;
      button.hidden=true;
      select=document.createElement('select');select.setAttribute('aria-label','Bill text version');
      versions.forEach((v,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=v.name?`${v.name} (${v.code})`:v.code;select.append(o)});
      select.value=String(versions.length-1);
      select.addEventListener('change',()=>loadVersion(Number(select.value),versions[Number(select.value)]));
      picker.append(select);
      await loadVersion(versions.length-1,versions[versions.length-1]);
    }catch(error){
      button.disabled=false;area.textContent='The bill text could not be loaded: '+error.message;
    }
  });
  return section;
}

function stageSections(b){
  const holder=document.createElement('div');
  if(!/^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/.test(b.id))return holder;
  const getJson=async url=>{try{const r=await fetch(url,{cache:'no-cache',signal:timeoutSignal(20000)});return r.ok?await r.json():null}catch{return null}};
  const show=node=>{if(node&&state.openBill===b.id&&holder.isConnected!==false)holder.append(node)};
  (async()=>{
    const [index,changes,witH,witS,fiscal,highlights]=await Promise.all([
      getJson(`./live/text/${b.id}/index.json`),getJson(`./live/luna/changes/${b.id}.json`),
      getJson(`./live/history/${b.id}/witnesses-H.json`),getJson(`./live/history/${b.id}/witnesses-S.json`),
      getJson(`./live/luna/fiscal/${b.id}.json`),getJson(`./live/luna/highlights/${b.id}.json`)]);
    if(state.openBill!==b.id)return;
    try{if(changes&&validChanges(changes,b.id,index))show(renderChanges(changes,index))}catch(e){console.warn('Changes hidden',e.message)}
    try{show(renderHearing([witH,witS]))}catch(e){console.warn('Hearing hidden',e.message)}
    try{
      // Current review = the tags entry's text_version plus the highlights file made on that same version (it carries the sha).
      const current=b.luna&&highlights&&highlights.text_version===b.luna.text_version?{text_version:b.luna.text_version,text_sha256:highlights.text_sha256}:null;
      if(fiscal&&validFiscal(fiscal,b.id,current))show(renderFiscal(fiscal,b.id));
    }catch(e){console.warn('Fiscal check hidden',e.message)}
  })();
  return holder;
}

// The bill page's section groups, in page order; the header's section menu jumps to each.
const BILL_GROUPS=[['overview','Overview'],['text','Text'],['law','Changes to law'],['people','People'],['impact','Agencies and impact'],['history','History'],['sources','Sources']];
// The bill view's content: every section of one bill, drawn into the page after the router renders its container.
function fillBillPage(){
  const page=$('#bill-page');if(!page)return;
  const b=state.bills.find(b=>b.id===state.openBill);
  if(!b){page.innerHTML=`<div class="drawer-top"><button type="button" class="outline-button bill-back" id="bill-back">← Back to results</button></div><div class="empty-state"><h3>${esc(state.openBill||'This bill')} is not in this snapshot</h3><p>It may not be filed yet, or the bill list could not be loaded.</p></div>`;return}
  const h=assessHearing(b),influence=authorInfluence(b),party=authorshipParty(b),last=lastActionInfo(b);
  const agencyRows=b.agencies.length?b.agencies.map(a=>`<div class="agency-row"><div><strong>${esc(agencyName(a.id))}</strong><p>${esc(a.reason||'Relationship not yet annotated')}</p></div><span class="confidence ${a.relationship==='direct'?'direct':''}">${a.source==='luna'?`Luna · ${a.relationship==='direct'?'direct':'inferred'}`:a.relationship==='direct'?'Direct':'Possible'}</span></div>`).join(''):'<p>No agency has been tagged yet. This does not establish that none are affected.</p>';
  const watched=state.watch.has(b.id);
  page.innerHTML=`<header class="bill-head"><div class="bill-bar"><button type="button" class="outline-button bill-back" id="bill-back">← Back to results</button><span class="drawer-number">90R / ${esc(b.number)}</span><div class="drawer-actions"><a class="primary-button" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Read official bill ↗</a><button class="outline-button" data-watch="${b.id}">${watched?'★ Remove from watchlist':'☆ Follow this bill'}</button><a class="outline-button" href="./live/feeds/${esc(b.id)}.xml" target="_blank" rel="noopener noreferrer" title="Follow this bill's actions in Outlook or a feed reader">RSS feed</a><button type="button" class="outline-button" data-copy-ai title="Copy a short prompt with links to this bill, for pasting into an AI assistant">Copy for AI</button></div></div><nav class="bill-menu" aria-label="Sections of this bill">${BILL_GROUPS.map(([id,label])=>`<button type="button" data-bill-jump="${id}">${label}</button>`).join('')}</nav></header><div class="bill-intro"><div class="drawer-pills"><span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span><span class="party-pill party-${party.tint}" title="${esc(party.detail)}">${esc(party.label)}</span></div><h1 id="bill-page-title" tabindex="-1">${esc(b.title)}</h1><p class="drawer-caption">${esc(b.caption)}</p></div><div class="bill-layout"><div class="bill-main"><section class="bill-group" id="bill-g-overview" aria-labelledby="bill-h-overview"><h2 class="bill-group-title" tabindex="-1" id="bill-h-overview">Overview</h2>${headlineLine(b,'drawer')}${lunaBlock(b)}<div class="drawer-pills">${b.topics.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>${b.subjects?.length?`<section class="drawer-section"><h3>Official subjects</h3><p>The Legislative Council's subject index for this bill. Search matches these, so a bill with a vague caption is still found by its subject.</p><div class="bill-tags">${b.subjects.map(s=>`<span class="tag subject-tag">${esc(s)}</span>`).join('')}</div></section>`:''}${companionBlock(b)}${relatedBlock(b)}</section><section class="bill-group" id="bill-g-text" aria-labelledby="bill-h-text"><h2 class="bill-group-title" tabindex="-1" id="bill-h-text">Text</h2></section><section class="bill-group" id="bill-g-law" aria-labelledby="bill-h-law"><h2 class="bill-group-title" tabindex="-1" id="bill-h-law">Changes to law</h2><section class="drawer-section law-section" id="drawer-statutes" hidden></section><section class="drawer-section bracket-section" id="drawer-brackets" hidden></section></section><section class="bill-group" id="bill-g-people" aria-labelledby="bill-h-people"><h2 class="bill-group-title" tabindex="-1" id="bill-h-people">People</h2><section class="drawer-section"><h3>Authors & sponsors</h3><p>Authors and coauthors serve in the originating chamber; sponsors and cosponsors serve in the other chamber. Authors include primary and joint/additional primary authors as listed by TLC. Counts reflect this source snapshot.</p><div class="evidence-card"><strong><span class="party-pill party-${party.tint}">${esc(party.label)}</span></strong><p>${esc(party.detail)}</p><p><small>Party, district and tenure come from the Texas Legislative Reference Library's latest recorded service; for members-elect not yet in its records, party and district come from the Secretary of State's unofficial 2026 general election results. Authorship does not indicate a vote or caucus position.</small></p></div>${[['Authors','authors'],['Coauthors','coauthors'],['Sponsors','sponsors'],['Cosponsors','cosponsors']].map(([label,key])=>{const names=b[key];const people=b.people?.[key];return `<h4>${label}${names===null?'':` (${names.length})`}</h4>${names===null?'<p>Not reported in this dataset</p>':!names.length?'<p>None listed in the source snapshot</p>':people?`<ul class="member-list">${people.map(p=>memberItem(p)).join('')}</ul>`:`<p>${names.map(esc).join(' · ')}</p>`}`}).join('')}</section><section class="drawer-section"><h3>Author prominence</h3><div class="evidence-card"><strong>${esc(influence.label)}</strong><p>${esc(influence.factors.join(' · '))}</p>${safeHref(b.author_profile?.source)?`<p><a class="text-link" href="${esc(safeHref(b.author_profile.source))}" target="_blank" rel="noopener noreferrer">Verified member biography ↗</a></p>`:''}</div></section></section><section class="bill-group" id="bill-g-impact" aria-labelledby="bill-h-impact"><h2 class="bill-group-title" tabindex="-1" id="bill-h-impact">Agencies and impact</h2><section class="drawer-section"><h3>Potentially affected agencies (${realAgencies(b).length})</h3><p>All known tags are listed. Possible links are model/rule inferences, not confirmed legal obligations.</p>${agencyRows}</section><section class="drawer-section"><h3>Types of impact</h3><div class="drawer-pills">${b.impacts.length?b.impacts.map(t=>`<span class="tag related">${esc(t)}</span>`).join(''):'<span class="tag">Pending analysis</span>'}</div></section>${b.constituencies?.length?`<section class="drawer-section"><h3>People and institutions affected</h3><div class="drawer-pills">${b.constituencies.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></section>`:''}</section><section class="bill-group" id="bill-g-history" aria-labelledby="bill-h-history"><h2 class="bill-group-title" tabindex="-1" id="bill-h-history">History</h2><section class="drawer-section"><h3>Hearing progress & evidence</h3><div class="evidence-card"><strong>${esc(h.label)} · ${h.level===0?'No rating yet':'Verified procedural signal'}</strong><p>${esc(h.detail)}</p><ul>${h.facts.map(f=>`<li>${esc(f)}</li>`).join('')}</ul></div></section></section><section class="bill-group" id="bill-g-sources" aria-labelledby="bill-h-sources"><h2 class="bill-group-title" tabindex="-1" id="bill-h-sources">Sources</h2><section class="drawer-section"><h3>Source & verification</h3><p>Review the bill history and latest text before relying on any classification. <a class="text-link" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Texas Legislature Online ↗</a></p><div class="ai-copy"><a class="text-link" href="${esc(agentUrl(b))}" target="_blank" rel="noopener noreferrer">AI-readable version ↗</a></div></section></section></div><aside class="bill-rail" aria-label="Key facts"><div class="drawer-meta-grid"><div><small>Filed by</small><strong>${authorHtml(b,b.author)}</strong></div><div><small>Filed on</small><strong>${dateText(b.filed_at)}</strong></div><div><small>Most recent action</small><strong>${esc(last.label)}${last.chamber?` · ${esc(last.chamber)}`:''} · ${esc(dateText(last.date))}</strong><small>${esc(last.text)}</small></div><div><small>Hearing status</small><strong>${esc(h.label)}</strong></div></div></aside></div>`;

  const reviewSection=document.createElement('section');reviewSection.className='drawer-section';
  const heading=document.createElement('h3');heading.textContent='Full text & highlighted evidence';
  const area=document.createElement('div');
  const local=document.createElement('input');local.type='file';local.accept='.json,application/json';local.hidden=true;
  const load=document.createElement('button');load.className='outline-button';load.textContent='Open a review file';
  load.addEventListener('click',()=>local.click());
  const draw=()=>{if(reviews.has(b.id))renderReview(area,reviews.get(b.id),true);else area.textContent='A reviewed full-text analysis is not yet available. Review files open only in this browser session.';};
  local.addEventListener('change',async()=>{try{const file=local.files[0];if(!file)return;if(file.size>15*1024*1024)throw Error('Select a file smaller than 15 MB');const bundle=JSON.parse(await file.text());reviewModel(bundle);if(bundle.bill_id!==b.id)throw Error('This review belongs to '+bundle.bill_id);reviews.set(b.id,bundle);draw();toast('Private review opened');}catch(error){toast('Review could not be opened: '+error.message)}});
  reviewSection.append(heading,load,local,area);
  $('#bill-g-text').append(billTextSection(b),reviewSection);draw();
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
  clickOn('nav','[data-view]',(nav,e)=>{e.preventDefault();location.hash=nav.dataset.view;setView(nav.dataset.view)});
  clickOn('open-bill','[data-open]',(open,e)=>{
    // A modified or non-primary click on a link keeps the browser's own behavior (new tab, new window).
    if(open.tagName!=='A'||cardClickOpens({button:e.button,metaKey:e.metaKey,ctrlKey:e.ctrlKey,shiftKey:e.shiftKey,altKey:e.altKey})){e.preventDefault();openBillPage(open.dataset.open,true)}
  });
  clickOn('copy-ai','[data-copy-ai]',copyAi=>copyForAi(copyAi));
  clickOn('near-locate','#near-locate',()=>nearLocate());
  clickOn('near-forget','#near-forget',()=>{saveNear(null);toast('Your districts were removed from this device')});
  clickOn('near-change','#near-change',()=>{state.near=null;state.nearError='';renderContent()});
  clickOn('near-county-use','#near-county-use',()=>{const c=countyDistricts(state.nearGeo?.tables,state.nearPick);if(c)saveNear({county:state.nearPick,source:'county',
    house:$('#near-house-pick')?.value||c.house[0]?.district,senate:$('#near-senate-pick')?.value||c.senate[0]?.district,near:c.house.length>1||c.senate.length>1})});
  clickOn('near-numbers-use','#near-numbers-use',()=>{const near=cleanNear({house:$('#near-house-num')?.value,senate:$('#near-senate-num')?.value,source:'district'},state.nearGeo?.tables);
    if(!near){state.nearError='Enter a House district from 1 to 150, a Senate district from 1 to 31, or both.';renderContent();return}saveNear(near)});
  clickOn('near-more','[data-near-more]',nearMore=>{state.nearShow[nearMore.dataset.nearMore]+=30;renderContent()});
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
  clickOn('copy-page-ai','#copy-page-ai',copyPage=>copyPageForAi(copyPage));
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
  clickOn('topic','[data-topic]',topic=>{state.topic=topic.dataset.topic;state.visibleCount=30;renderContent()});
  clickOn('agency-pick','[data-agency-pick]',pick=>{switchFilters('all');state.agency=pick.dataset.agencyPick;state.visibleCount=30;state.view='all';location.hash='all';setView('all')});
  clickOn('clear-filters','#clear-filters',()=>{Object.assign(state,{query:'',topic:'',agency:'',chamber:'',party:'',stage:'',action:'',outlook:'',sort:'newest',onlyWatch:false,visibleCount:30});renderContent()});
  clickOn('watch-filter','#watch-filter',()=>{state.onlyWatch=!state.onlyWatch;state.visibleCount=30;renderContent()});
  clickOn('load-more','#load-more',()=>{state.visibleCount+=30;renderResults()});
  clickOn('export-csv','#export-csv',()=>exportCsv());
  clickOn('import-trigger','#import-trigger',()=>$('#import-file').click());
  clickOn('bill-back','#bill-back',()=>leaveBillPage());
  clickOn('bill-jump','[data-bill-jump]',jump=>{const group=$(`#bill-g-${jump.dataset.billJump}`);if(group){group.scrollIntoView({block:'start'});group.querySelector('h2')?.focus?.({preventScroll:true})}});
  // Empty space on a card opens its bill page, unless the click was on a control or the reader is selecting text.
  onClick('card',e=>{
    const card=e.target.closest('[data-bill-id]');
    if(card&&cardClickOpens({interactive:Boolean(e.target.closest(CARD_CONTROLS)),selection:window.getSelection?.().toString()||'',button:e.button,metaKey:e.metaKey,ctrlKey:e.ctrlKey,shiftKey:e.shiftKey,altKey:e.altKey}))openBillPage(card.dataset.billId,true);
    return true;
  });
}
const CARD_CONTROLS='a,button,input,select,textarea,label,summary,[data-topic],[data-today-topic],[data-open],[data-watch],[data-watch-group]';

async function copyToClipboard(text){
  try{await navigator.clipboard.writeText(text);return true}catch{}
  try{
    const t=document.createElement('textarea');t.value=text;t.setAttribute('readonly','');t.style.cssText='position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(t);t.select();const ok=document.execCommand('copy');t.remove();return ok;
  }catch{return false}
}
// Top-bar button: the open bill, or the list/page on screen, as text for an AI assistant.
async function copyPageForAi(button){
  const bill=state.openBill?state.bills.find(x=>x.id===state.openBill):null;
  const member=state.view==='member'?memberByCode(state.roster,state.memberCode):null;
  const labels={home:'Home',all:'Bill explorer',watchlist:'Watchlist',following:'Following',today:'Today',local:'Near you',member:member?`Bills by ${memberTitle(member)}`:'Member'};
  const today=state.view==='today'?todayData():null;
  const text=pageAiText({view:state.view,label:labels[state.view]||state.view,pageUrl:location.href,bill,agencyName,
    companions:companionsOf,via:state.view==='today'||state.view==='member'?null:agencyVia(),
    bills:today?today.shown.map(r=>r.bill):['all','watchlist'].includes(state.view)?filteredBills():state.view==='local'&&state.near?(d=>[...d.members,...d.local].map(r=>r.bill).filter((b,i,a)=>a.indexOf(b)===i))(nearData()):member?Object.values(memberData(member)).flat().map(r=>r.bill):state.view==='following'&&state.roster?followedBills(state.bills,state.roster,state.follow,newestFirst).map(r=>r.bill):[],
    day:today?today.day:null,filters:{query:state.query,topic:state.view==='today'?state.todayTopic:state.topic,
      agency:state.agency,chamber:state.chamber}});
  const label=button.dataset.label||(button.dataset.label=button.textContent);
  if(await copyToClipboard(text)){button.textContent='Copied';clearTimeout(button.timer);button.timer=setTimeout(()=>{button.textContent=label},2000)}
  else toast('Copy failed; your browser blocked the clipboard');
}

async function copyForAi(button){
  const b=state.bills.find(x=>x.id===state.openBill);if(!b)return;
  const text=aiPrompt(b,companionsOf(b.id));
  if(await copyToClipboard(text)){
    button.textContent='Copied';clearTimeout(button.timer);button.timer=setTimeout(()=>{button.textContent='Copy for AI'},2000);
  }else{
    // Last resort: show the text, selected, so it can be copied by hand.
    let box=$('#ai-fallback');
    if(!box){box=document.createElement('textarea');box.id='ai-fallback';box.className='ai-fallback';box.readOnly=true;box.rows=6;button.closest('.ai-copy').append(box)}
    box.value=text;box.focus();box.select();toast('Press Ctrl+C to copy');
  }
}

function handleInput(e){
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
  const m={'filter-topic':'topic','filter-chamber':'chamber','filter-party':'party','filter-stage':'stage','filter-outlook':'outlook','filter-action':'action'};
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
    const previous={bills:state.bills,meta:state.meta,topic:state.topic,agency:state.agency,chamber:state.chamber,party:state.party,stage:state.stage,action:state.action,outlook:state.outlook,query:state.query,visibleCount:state.visibleCount,view:state.view};
    try{
      state.bills=valid;state.meta={session:'90R',data_mode:'local import',source_file:file.name,generated_at:new Date().toISOString(),coverage_note:`Local file: ${file.name}. Imported rows are visible only during this session.`};
      switchFilters('all');Object.assign(state,{topic:'',agency:'',chamber:'',party:'',stage:'',action:'',outlook:'',query:'',visibleCount:30});setView('all');
    }catch(renderError){Object.assign(state,previous);setView(previous.view);throw renderError}
    location.hash='all';toast(`Imported ${valid.length} bills`);
  }catch(err){toast(`Import failed: ${err.message}`)}
}

init();
