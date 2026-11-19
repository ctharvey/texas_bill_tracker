// Saved lists and private sync: the list store and sync client, every watch, follow and saved-search change, other
// tabs' saves, and opening or pulling a sync link. Redraws go through core/router.js hooks; runtime.syncAvailable is shared.
import {STORAGE_OK, memoryStorage, storageKey, followKey, searchesKey, loadSaved, prefsKey} from '../../core/storage.js';
import {createSyncClient} from '../../sync.js';
import {readWatch, readFollows, readSearches, adoptLists, changeFollowList, changeSearchList, changeWatchList} from '../../core/lists.js';
import {savedTheme, setTheme, applyTheme} from '../theme/view.js';
import {state, runtime} from '../../core/state.js';
import {cleanSearches, cleanFollows, MAX_FOLLOWS, FILTER_DEFAULTS, MAX_SEARCHES, cleanFilters, pickFilters, searchFitsSync, searchName, newSearchId} from '../../prefs.js';
import {keepHeld, MOVED_KEY} from '../../core/move.js';
import {toast, $} from '../../core/dom.js';
import {memberByCode} from '../../geo.js';
import {memberTitle} from '../members/names.js';
import {filteredBills} from '../explorer/model.js';
import {isLawFollowQuery, lawFollowsOf, lawFollowSearch, lawFirstSeen} from '../statutes/model.js';
import {todayDay, agencyName, areaName} from '../../core/labels.js';
import {latestActivityDay} from '../../taxonomy.js';
import {confirmJoin} from './join.js';
import {persistState, renderContent, renderResults, renderOverview, refreshHome, renderMoveBanner, setView} from '../../core/router.js';

// Lists are saved through listStore; each change re-reads it (core/lists.js), so other tabs' saves are kept.
export const listStore=STORAGE_OK?localStorage:memoryStorage();
export const sync=createSyncClient({storage:STORAGE_OK?localStorage:memoryStorage(),getWatch:()=>readWatch(listStore,storageKey),getFollows:()=>readFollows(listStore,followKey),getSearches:()=>readSearches(listStore,searchesKey),getTheme:savedTheme,
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
let lastPull=0;

export function changeFollow(op,codes){
  const {list,changed}=changeFollowList(listStore,followKey,op,codes,MAX_FOLLOWS);
  state.follow=list;for(const code of changed)sync.record(op,code,onSynced);
  if(changed.length)renderMoveBanner();
}
export function toggleFollow(code){
  const on=state.follow.includes(code);
  if(!on&&state.follow.length>=MAX_FOLLOWS){toast(`You can follow up to ${MAX_FOLLOWS} legislators`);return}
  changeFollow(on?'unfollow':'follow',[code]);
  const m=memberByCode(state.roster,code);
  toast(`${on?'Unfollowed':'Following'} ${m?memberTitle(m):code}${on||state.view==='following'?'':' · their bills are under Following'}`);
  renderOverview();renderContent();
}
// op: 'save-search' (search object) or 'delete-search' (id).
export function changeSearch(op,item){
  const id=op==='save-search'?item.id:item;
  state.searches=changeSearchList(listStore,searchesKey,op,item);
  // A save the list had no room for (another tab filled the last slot) is not sent to the sync link either.
  if(op==='save-search'&&!state.searches.some(s=>s.id===id))return;
  sync.record(op,id,onSynced,op==='save-search'?item:undefined);
  renderMoveBanner();
}
// Bills matching a saved search now, and those with a dated action after the day it was last opened.
// A followed law also counts a bill as new from the day it started changing the section (the index's first-seen
// day), since a late text or a new version can add it without a newer dated action. Same day counts: the index can
// gain the bill after the follow was opened that day.
export function searchCounts(s){
  const list=filteredBills({...FILTER_DEFAULTS,...s.filters}),today=todayDay();
  const law=isLawFollowQuery(s.filters?.query)?s.filters.query:null;
  const fresh=s.seen?list.filter(b=>(latestActivityDay([b],today)||'')>s.seen||(law&&lawFirstSeen(state.statutes,law,b.id)>=s.seen)).length:0;
  return {total:list.length,fresh};
}
export function saveCurrentSearch(){
  if(state.searches.length>=MAX_SEARCHES){toast(`You can save up to ${MAX_SEARCHES} searches`);return}
  const filters=cleanFilters(Object.fromEntries(Object.entries(pickFilters(state)).filter(([k,v])=>v!==FILTER_DEFAULTS[k])));
  if(!searchFitsSync(filters)){toast('This search is too long to save; shorten the search words');return}
  const name=searchName(filters,agencyName,areaName);
  if(state.searches.some(s=>JSON.stringify(s.filters)===JSON.stringify(filters))){toast(`Already saved as “${state.searches.find(s=>JSON.stringify(s.filters)===JSON.stringify(filters)).name}”`);return}
  changeSearch('save-search',{id:newSearchId(),name,filters,seen:todayDay()});
  renderOverview();toast(`Saved “${name}” · find it under Following`);
}
// "Follow this law": a saved search for the section key; following again unfollows, removing every copy (two
// devices can each have followed it).
export function toggleLawFollow(key,label){
  if(!isLawFollowQuery(key))return;
  const have=lawFollowsOf(state.searches,key);
  if(have.length){for(const s of have)changeSearch('delete-search',s.id);renderOverview();renderContent();
    toast(`Unfollowed ${label}${have.length>1?` (removed ${have.length} saved searches for it)`:''}`);return}
  if(state.searches.length>=MAX_SEARCHES){toast(`You can follow or save up to ${MAX_SEARCHES} searches`);return}
  const s=lawFollowSearch(key,label,newSearchId(),todayDay());
  changeSearch('save-search',s);
  renderOverview();renderContent();
  // Another tab may have filled the last slot meanwhile; the list store keeps at most MAX_SEARCHES.
  toast(state.searches.some(x=>x.id===s.id)?`Following ${label} · new bills and actions show on the home page and under Following`:`Could not follow ${label}: you already have ${MAX_SEARCHES} saved searches`);
}
// The statute page shows a Follow button, so it redraws after a sync pull or another tab's save like these pages.
const FOLLOW_VIEWS=new Set(['following','member','local','statute']);
export function refreshWatch(){renderOverview();if(state.view==='home')refreshHome();else if(state.view==='all'||state.view==='watchlist'||FOLLOW_VIEWS.has(state.view))renderContent()}
// After a debounced write: the client has already adopted the link's copy (adoptSynced); show it.
export const onSynced=(watch,error)=>{if(error){toast(`Sync: ${error.message}`);return}renderOverview();
  if(state.view==='all'||state.view==='watchlist')renderResults();else if(state.view==='home')refreshHome();else if(syncMoved&&FOLLOW_VIEWS.has(state.view))renderContent()};
export function changeWatch(op,ids){
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

export async function setupSync(key){
  runtime.syncAvailable=await sync.isAvailable();
  if(key)await openSyncLink(key);
  else if(sync.linked)await pullSync();
  window.addEventListener('focus',()=>{if(Date.now()-lastPull>30000)pullSync()});
  if(STORAGE_OK)window.addEventListener('storage',onOtherTab);
  persistState();
  if(state.view==='home')refreshHome();else if(state.view==='watchlist'||state.view==='saving'||state.view==='export')renderContent();
}

export async function openSyncLink(key){
  if(runtime.syncAvailable===null)runtime.syncAvailable=await sync.isAvailable();
  if(!runtime.syncAvailable){toast('Sync links are not available on this site yet');return}
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

// The client merges a join, adopts the link's copy and stores its version together (sync.js). True when it did.
export async function pullSync(){
  if(!runtime.syncAvailable||!sync.linked)return false;
  lastPull=Date.now();
  try{
    const pulled=await sync.pull();
    loadSaved();refreshWatch();
    return Boolean(pulled);  // Null: another tab or write changed the link meanwhile; the next pull catches up.
  }catch(error){toast(`Sync: ${error.message}`);loadSaved();refreshWatch();return false}
}
