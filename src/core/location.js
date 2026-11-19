// The address and remembered filters: reading /#view?... and /bill/<ID> into state, each view's own filters, opening
// and leaving a bill page, and writing the address and the explorer's remembered filters back. setView is a router hook.
import {cleanFilters, FILTER_DEFAULTS, pickFilters, parseLocation, buildHash, buildUrl, sameFilters} from '../prefs.js';
import {SORTS} from './labels.js';
import {state, runtime} from './state.js';
import {$} from './dom.js';
import {sync} from '../features/sync/lists.js';
import {readJson, prefsKey, writeJson} from './storage.js';
import {setView} from './router.js';

// Every view but a bill page lives at /#view. A plain hash change on /bill/<ID> would stay under that path, so it
// moves to / instead and is handled like any other hash change.
export let lastPath=location.pathname;
export function goTo(hash){
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
export const FILTERED_VIEWS=new Set(['all','watchlist']);
const viewFilters={};
let filtersFor='all';
export function switchFilters(view){
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
export function applyLocation(initial){
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
    runtime.restoredFilters=readJson(prefsKey)?.filters||null;
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

// Opens a bill's page with a history entry, remembering where it was opened from (not when moving bill to bill).
export function openBillPage(id,push=false){
  if(state.view!=='bill')billReturn={hash:currentHash(),visibleCount:state.visibleCount,scrollY:window.scrollY};
  state.openBill=id;
  setView('bill',push);
  window.scrollTo({top:0,behavior:'instant'});
}

// Back to results: the page the bill was opened from, or the explorer when the bill page was the first page loaded.
export function leaveBillPage(){goTo(billReturn?.hash||'#all')}

// prefs-v1 fields other than the filters (the colour theme) survive a filter save.
export const keptPrefs=()=>{const p=readJson(prefsKey);return p&&typeof p==='object'&&!Array.isArray(p)?p:{}};
// push=true adds a history entry (opening a bill), so Back closes it instead of leaving the site.
export function persistState(push=false){
  const url=currentUrl();
  let pushed=false;
  if(location.pathname+location.hash!==url)try{if(push){history.pushState(null,'',url);pushed=true}else history.replaceState(null,'',url)}catch{}
  lastPath=location.pathname;
  const canonical=document.querySelector('link[rel="canonical"]');
  if(canonical)canonical.href=state.view==='bill'&&state.openBill?`https://billatlas.org/bill/${state.openBill}`:'https://billatlas.org/';
  if(state.view==='all'&&filtersFor==='all'&&!state.sharedList&&!(readJson(prefsKey)?.filters&&sameFilters(readJson(prefsKey).filters,state)))writeJson(prefsKey,{...keptPrefs(),filters:pickFilters(state)});
  return pushed;
}
