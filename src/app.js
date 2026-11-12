import {reviewModel, renderReview, parseBillMarkdown, validHighlights, sha256Hex, renderBillText, validChanges, renderChanges, renderHearing, validFiscal, renderFiscal} from './review.js';
import {FILTER_DEFAULTS, parseHash, buildHash, pickFilters, cleanFilters, watchlistFile, parseWatchlistFile} from './prefs.js';
import {createSyncClient} from './sync.js';
import {NEAR_KEY, placeFromPoint, cleanNear, countyDistricts, countiesOf, membersFor, memberByCode, billsByMember, ROLES, gazetteer, areaReasons, areaFor, censusUrl, censusPoint} from './geo.js';
import {AGENCIES, AGENCY_NAME, SCOPE_AGENCY_ID, autoTagBill, applyLunaTags, applyLunaExtras, relatedFor, auditLine, attachMembers, authorshipParty, memberSummary, lastActionInfo, LAST_ACTION_TYPES, reviewProgress, reviewSummary, POLICY_AREAS, assessHearing, authorInfluence, officialUrl, memberNames, matchAuthorProfile, snapshotAgeHours, normalizeBill, companionIndex, companionGroups, searchTerms, newestFirst, aiPrompt, agentUrl, cardClickOpens, openLinkHtml, chicagoDate, activityOn, latestActivityDay, topicCounts, groupByActionType, pageAiText, companionLabel, agencyViaCompanion} from './taxonomy.js';

const $ = (selector, root=document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {view:'all',bills:[],watch:new Set(),query:'',topic:'',agency:'',chamber:'',stage:'',action:'',outlook:'',sort:'newest',onlyWatch:false,visibleCount:30,meta:null,luna:null,related:null,audit:null,roster:null,reviewStatus:null,sharedList:null,sharedMode:null,sharedSyncKey:null,openBill:null,todayTopic:'',todayLimit:100,todayAllTopics:false,near:null,nearGeo:null,nearPick:null,nearBusy:'',nearError:'',nearShow:{members:30,area:30},memberCode:null,memberShow:{},geoTables:null};
const SORTS={newest:'Newest filed',latest:'Latest action',oldest:'Oldest last action',actionstage:'Last action stage',number:'Bill number',agencies:'Most agencies',hearing:'Hearing progress',influence:'Author influence'};
const agencyName = id => AGENCY_NAME[id]||state.luna?.agencies?.[id]||id;
const reviews = new Map();
const storageKey = 'tx-bill-atlas-watch-90r';
const STORAGE_OK = (()=>{try{localStorage.setItem('__txb_test','1');localStorage.removeItem('__txb_test');return true}catch{return false}})();
try{state.watch=new Set(JSON.parse(localStorage.getItem(storageKey)||'[]'))}catch{}

const shortDate = iso => iso ? new Date(`${String(iso).slice(0,10)}T12:00:00Z`).toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'}) : '';
const dateText = iso => iso ? new Date(`${String(iso).slice(0,10)}T12:00:00Z`).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}) : 'Not available';
const stampText = iso => iso ? new Date(iso).toLocaleString('en-US',{dateStyle:'medium',timeStyle:'short',timeZone:'America/Chicago'})+' CT' : 'Unknown';
const unique = a => [...new Set(a)];

const realAgencies = b => b.agencies.filter(a=>a.id!==SCOPE_AGENCY_ID);
const safeHref = value => {try{const u=new URL(String(value));return u.protocol==='https:'||u.protocol==='http:'?u.href:''}catch{return ''}};
const timeoutSignal = ms => {if(typeof AbortSignal!=='undefined'&&typeof AbortSignal.timeout==='function')return AbortSignal.timeout(ms);const c=new AbortController();setTimeout(()=>c.abort(),ms);return c.signal};
const NAME_TO_AGENCY_ID = new Map(AGENCIES.flatMap(a=>[[a.name.toLowerCase(),a.id],[a.id.toLowerCase(),a.id]]));

const normalized=normalizeBill;

async function init(){
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
  document.addEventListener('click',handleClick);
  document.addEventListener('change',handleChange);
  document.addEventListener('input',handleInput);
  document.addEventListener('submit',e=>{if(e.target.id==='near-address-form'){e.preventDefault();nearAddress($('#near-address')?.value)}});
  document.addEventListener('focusin',event=>{
    if(event.target.id==='filter-agency')showAgencyChoices('');
  });
  document.addEventListener('keydown',event=>{
    if(event.target.id==='filter-agency'&&handleAgencyKeydown(event))return;
    if(event.key==='Escape')closeDrawer();
  });
  $('#drawer-scrim').addEventListener('click',closeDrawer);
  // A sync link pasted into an open tab arrives as a hash change, not a page load.
  window.addEventListener('hashchange',()=>{const key=applyLocation(false);if(key)openSyncLink(key)});
  state.near=cleanNear(readJson(NEAR_KEY),null);
  const syncKey=applyLocation(true);
  setupDisclaimer();
  setupSync(syncKey);
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

const disclaimerKey='tx-bill-atlas-disclaimer-v1';
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
const prefsKey='tx-bill-atlas-prefs-v1';
const readJson=key=>{try{return JSON.parse(localStorage.getItem(key)||'null')}catch{return null}};
const writeJson=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value))}catch{}};
const memoryStorage=()=>{const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)}};
const sync=createSyncClient({storage:STORAGE_OK?localStorage:memoryStorage(),getWatch:()=>[...state.watch]});
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

// Returns a sync key from the URL, if any, for setupSync to resolve.
// The address without its open bill; when only the bill differs, Back/Forward just open or close the drawer.
const withoutBill=hash=>String(hash||'').replace(/([?&])bill=[^&]*&?/,'$1').replace(/[?&]$/,'');
let drawerPushed=false;  // The open bill added a history entry, so closing it steps back over that entry.

function applyLocation(initial){
  const p=parseHash(location.hash);
  if(!initial&&withoutBill(location.hash)===withoutBill(currentHash())){
    // Forward onto a bill entry: the entry below it is the same page without the bill, so closing steps back.
    if(p.bill&&p.bill!==state.openBill&&state.bills.some(b=>b.id===p.bill)){showDrawer(p.bill);drawerPushed=true}
    else if(!p.bill&&state.openBill){drawerPushed=false;closeDrawer()}
    return p.sync;
  }
  if(!p.bill&&state.openBill){drawerPushed=false;closeDrawer()}
  // Filters in the address belong to the view it names; otherwise each view gets its own remembered set.
  let urlFilters=true;
  if(!initial&&(p.hasFilters||p.list)&&FILTERED_VIEWS.has(p.view)&&filtersFor!==p.view)viewFilters[filtersFor]=pickFilters(state);
  if(p.hasFilters)applyFilters(p.filters);
  else if(p.list)applyFilters({});  // A share link shows its whole list, even in a tab with filters set.
  else if(initial&&!p.bill&&!p.sync){
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
  setView(p.view);
  if(p.bill&&state.bills.some(b=>b.id===p.bill))showDrawer(p.bill);
  return p.sync;
}

function currentHash(){
  return buildHash(state.view,pickFilters(state),{list:state.sharedMode==='link'?state.sharedList:null,bill:state.openBill,
    sync:state.sharedMode==='sync-view'?state.sharedSyncKey:null,member:state.memberCode});
}

// Address of this view with `id` open, so a bill title is a real link (new tab, copy link) as well as a click target.
function billHref(id){
  return buildHash(state.view,pickFilters(state),{list:state.sharedMode==='link'?state.sharedList:null,bill:id,
    sync:state.sharedMode==='sync-view'?state.sharedSyncKey:null,member:state.memberCode});
}

// push=true adds a history entry (opening a bill), so Back closes it instead of leaving the site.
function persistState(push=false){
  const hash=currentHash();
  let pushed=false;
  if(location.hash!==hash)try{if(push){history.pushState(null,'',hash);pushed=true}else history.replaceState(null,'',hash)}catch{}
  if(state.view==='all'&&filtersFor==='all'&&!state.sharedList)writeJson(prefsKey,{filters:pickFilters(state)});
  return pushed;
}

function saveWatchLocal(){if(STORAGE_OK)writeJson(storageKey,[...state.watch])}
function setWatch(ids){state.watch=new Set(ids);saveWatchLocal()}
function refreshWatch(){renderOverview();if(state.view==='all'||state.view==='watchlist')renderContent()}
const onSynced=(watch,error)=>{if(error){toast(`Sync: ${error.message}`);return}setWatch(watch);renderOverview();if(state.view==='all'||state.view==='watchlist')renderResults()};
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
  if(state.view==='watchlist'||state.view==='saving')renderContent();
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
    const {watch}=await sync.pull();
    const local=[...state.watch];
    setWatch(watch);
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
  return `<div class="watch-tools"><section><h3>Save and share</h3><p class="tools-note">Your watchlist is kept in this browser. To move it to another device or person:</p><div class="tools-row"><button class="outline-button" id="share-watch" ${none}>Copy share link</button><button class="outline-button" id="export-watch" ${none}>Export file</button><button class="outline-button" id="import-watch">Import file</button><input type="file" id="import-watch-file" accept=".json,.txt,.csv,application/json,text/plain,text/csv" hidden></div><p class="tools-note">Each bill also has an RSS feed in its details, for following it in Outlook or a feed reader. <a href="#saving" data-view="saving">How saving works →</a></p></section><section><h3>Sync across devices</h3>${syncPart}</section></div>`;
}

async function handleSaveClick(target){
  const hit=sel=>target.closest(sel);
  if(hit('#copy-view-link')){persistState();return copyText(location.href,'Link to this view')}
  if(hit('#share-watch'))return copyText(siteBase()+buildHash('all',{},{list:[...state.watch]}),'Share link');
  if(hit('#export-watch')){download('texas-bill-atlas-watchlist.json',watchlistFile(state.watch),'application/json');return toast('Watchlist exported')}
  if(hit('#import-watch')){$('#import-watch-file').click();return}
  if(hit('#shared-add')){const before=state.watch.size;changeWatch('add',state.sharedList);refreshWatch();return toast(`Added ${state.watch.size-before} bills to your watchlist`)}
  if(hit('#shared-close')){Object.assign(state,{sharedList:null,sharedMode:null,sharedSyncKey:null,visibleCount:30});return renderContent()}
  if(hit('#sync-create')){try{await sync.create([...state.watch]);renderContent();toast('Sync link created. Copy the edit link to your other devices.')}catch(error){toast(error.message)}return}
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
    const ids=parseWatchlistFile(await file.text()),before=state.watch.size;
    changeWatch('add',ids);refreshWatch();
    toast(`Added ${state.watch.size-before} of ${ids.length} bills to your watchlist`);
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

function setView(view){
  switchFilters(view);
  state.view=view;
  document.querySelectorAll('[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===view));
  const heads={all:['See what’s moving.<br><em>Know what it changes.</em>','Track legislation by policy, affected agency, author influence, and its path through the Capitol.'],watchlist:['Your watchlist.<br><em>Keep the signal.</em>','Bills you are following on this device, with a clear view of their movement.'],today:['Today at the Lege.<br><em>What moved, by topic.</em>','Bills with a recorded action today, grouped by type of action. Dates follow Texas time.'],local:['Near you.<br><em>Your legislators, your bills.</em>','Your Texas House member and Senator, what they filed, and bills that name your county or city.'],member:['One legislator.<br><em>Every bill they’re on.</em>','A member’s district and the bills they author, coauthor or sponsor in this snapshot.'],agencies:['Follow the agencies.<br><em>Not just the bills.</em>','Explore where legislation might land across Texas government.'],review:['Full-text review.<br><em>Bill by bill.</em>','Which bills Luna has read in full, which it is working on, and what is still waiting.'],method:['The scoring method.<br><em>No black boxes.</em>','Signals and uncertainty are displayed separately from verified legislative actions.'],saving:['Save your work.<br><em>No account needed.</em>','Keep your watchlist and views on one device, carry them in a link or file, or sync them privately.'],data:['Behind the tracker.<br><em>Follow the source.</em>','Understand coverage, refreshes, and how to load or export bill data.']};
  $('#page-title').innerHTML=heads[view][0];$('#page-subtitle').textContent=heads[view][1];
  $('#overview').hidden=!['all','watchlist'].includes(view);
  renderNotice();renderOverview();renderContent();persistState();
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
  $('#source-notice').className=`source-notice${warn?' warn':''}`;
  $('#source-notice').innerHTML=`<span class="notice-icon">${curated?'◷':warn?'!':'✓'}</span><div>${copy} <a href="#data" data-view="data">Coverage & sources →</a></div>`;
  $('#footer-timestamp').textContent=`${imported?'Imported':'Snapshot'}: ${stampText(state.meta?.generated_at)}`;
}

function renderOverview(){
  const bills=state.view==='watchlist'?state.bills.filter(b=>state.watch.has(b.id)):state.bills;
  const agencies=unique(bills.flatMap(b=>b.agencies.map(a=>a.id))).filter(id=>id!=='all-state-agencies').length;
  const scheduled=bills.filter(b=>assessHearing(b).level===3).length;
  const today=bills.filter(b=>b.filed_at===new Date().toLocaleDateString('sv-SE',{timeZone:'America/Chicago'})).length;
  const cards=[
    ['Bills in view',bills.length,'▦',state.meta?.data_mode==='curated'?'Curated sample, not session total':'Imported dataset'],
    ['Agencies connected',agencies,'◈','Explicit + possible impact tags','accent'],
    ['Filed today',today,'↗','According to imported filing dates','gold'],
    ['Hearings scheduled',scheduled,'◷','Confirmed by recorded actions','violet']
  ];
  $('#overview').innerHTML=cards.map(([label,count,icon,foot,accent])=>`<div class="stat-card"><div class="stat-top"><span>${label}</span><span class="stat-icon">${icon}</span></div><div class="stat-value ${accent||''}">${count.toLocaleString()}</div><div class="stat-foot">${foot}</div></div>`).join('');
  $('#nav-all').textContent=state.bills.length;
  $('#nav-watch').textContent=state.watch.size;
  const progress=reviewProgress(state.bills.map(b=>b.id),state.reviewStatus,Object.keys(state.luna?.bills||{}));
  $('#nav-review').textContent=progress.reviewed.length+progress.inProgress.length;
}

function renderContent(){
  const el=$('#dynamic-content');
  if(state.view==='all'||state.view==='watchlist')el.innerHTML=explorerMarkup();
  else if(state.view==='today')el.innerHTML=todayMarkup();
  else if(state.view==='local')el.innerHTML=nearMarkup();
  else if(state.view==='member')el.innerHTML=memberMarkup();
  else if(state.view==='agencies')el.innerHTML=agenciesMarkup();
  else if(state.view==='review')el.innerHTML=reviewMarkup();
  else if(state.view==='method')el.innerHTML=methodMarkup();
  else if(state.view==='saving')el.innerHTML=savingMarkup();
  else el.innerHTML=dataMarkup();
  if(state.view==='all'||state.view==='watchlist')renderResults();
}

function options(values,selected,placeholder){return `<option value="">${esc(placeholder)}</option>`+values.map(v=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(v)}</option>`).join('')}

function explorerMarkup(){
  const topics=unique([...POLICY_AREAS.map(t=>t.name),...state.bills.flatMap(b=>b.topics)]).sort();
  const agencyCounts=new Map();
  for(const bill of state.bills)for(const agency of bill.agencies)agencyCounts.set(agency.id,(agencyCounts.get(agency.id)||0)+1);
  const agencies=unique([...AGENCIES.map(a=>a.id),...Object.keys(state.luna?.agencies||{})]).sort((a,b)=>a==='all-state-agencies'?-1:b==='all-state-agencies'?1:agencyName(a).localeCompare(agencyName(b)));
  const agencyOpts=agencies.map((id,i)=>`<div id="agency-option-${i+1}" role="option" class="agency-option" data-agency-option="${esc(id)}" data-agency-label="${esc(agencyName(id))}" aria-selected="${state.agency===id}"><span>${esc(agencyName(id))}</span><span class="agency-option-count">${agencyCounts.get(id)||0}</span></div>`).join('');
  const popular=['Education','Healthcare','Elections','Taxes','Immigration','Data centers','Local government','Energy & utilities'];
  return `<div class="section-head"><div><div class="section-overline">EXPLORE LEGISLATION</div><h2>${state.view==='watchlist'?'Watched bills':'Bill explorer'}</h2></div><span class="subtitle">90R · House & Senate · All bill types</span></div>
    ${sharedBanner()}${state.view==='watchlist'?watchTools():''}
    <div class="explorer-controls"><div class="search-row"><div class="search-wrap"><input aria-label="Search bills" id="bill-search" placeholder="Search bill number, author, subject, or keyword…" value="${esc(state.query)}" autocomplete="off"></div><button class="outline-button" id="clear-filters">Clear filters</button><button class="outline-button" id="copy-view-link" title="Copy a link to this view, with its filters">Copy link</button><button class="primary-button" id="export-csv">↓ Export results</button></div>
    <div class="filter-row"><select aria-label="Policy area" id="filter-topic">${options(topics,state.topic,'All policy areas')}</select><div class="agency-combobox" id="agency-combobox"><input aria-label="Affected agency" aria-controls="agency-options" aria-expanded="false" aria-autocomplete="list" role="combobox" id="filter-agency" placeholder="All affected agencies" value="${esc(state.agency?agencyName(state.agency):'')}" autocomplete="off"><span class="agency-chevron" aria-hidden="true">⌄</span><div class="agency-options" id="agency-options" role="listbox" hidden><div id="agency-option-0" role="option" class="agency-option" data-agency-option="" data-agency-label="All affected agencies" aria-selected="${!state.agency}"><span>All affected agencies</span></div>${agencyOpts}<p class="agency-no-results" id="agency-no-results" hidden>No matching agencies</p></div></div><select aria-label="Chamber" id="filter-chamber">${options(['House','Senate'],state.chamber,'Both chambers')}</select><select aria-label="Stage" id="filter-stage">${options(['Filed','Referred','Scheduled','Heard','Advanced','Passed','Enacted'],state.stage,'Any stage')}</select><select aria-label="Hearing status" id="filter-outlook">${options(['Not rated','Referred','Scheduled','Heard'],state.outlook,'Hearing status')}</select><select aria-label="Last action" id="filter-action">${options(unique([...LAST_ACTION_TYPES.map(t=>t.label),'Other action']).filter(l=>l===state.action||state.bills.some(b=>lastActionInfo(b).label===l)),state.action,'Any last action')}</select><button class="check-filter ${state.onlyWatch?'selected':''}" id="watch-filter">☆ Watched only</button></div></div>
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
const viaCache={bills:null,agency:null,map:new Map()};
function agencyVia(){
  if(!state.agency)return new Map();
  if(viaCache.bills!==state.bills||viaCache.agency!==state.agency){companionsOf('');
    Object.assign(viaCache,{bills:state.bills,agency:state.agency,map:agencyViaCompanion(state.bills,state.agency,companionCache.index)})}
  return viaCache.map;
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
    return `<div class="companion-row"><div><strong>${other?`<button class="text-link companion-open" data-open="${esc(c.id)}">${esc(c.number)}</button>`:esc(c.number)}</strong> <span class="chamber-pill">${esc(c.id.startsWith('H')?'House':'Senate')}</span> <small>${esc(relationText(c))}${c.author?` · by ${esc(c.author)}`:''}</small><p>${other?esc(other.title):'Not in this snapshot yet; it appears here within about an hour of the Legislative Council publishing it.'}</p></div>${last?`<span class="tag action-tag action-${esc(last.key)}">${esc(last.label)}${last.date?` · ${esc(shortDate(last.date))}`:''}</span>`:''}</div>`}).join('');
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

function filteredBills(){
  const shared=state.sharedList?new Set(state.sharedList):null;
  const {q,compact}=searchTerms(state.query);
  let list=state.bills.filter(b=>{
    if(shared&&!shared.has(b.id))return false;
    if(state.view==='watchlist'&&!state.watch.has(b.id))return false;
    if(state.onlyWatch&&!state.watch.has(b.id))return false;
    if(state.topic&&!b.topics.includes(state.topic))return false;
    if(state.agency&&!b.agencies.some(a=>a.id===state.agency)&&!agencyVia().has(b.id))return false;
    if(state.chamber&&b.chamber!==state.chamber)return false;
    if(state.outlook&&assessHearing(b).label!==state.outlook)return false;
    if(state.action&&lastActionInfo(b).label!==state.action)return false;
    if(state.stage){const st=(b.status||'').toLowerCase();const outlook=assessHearing(b).label.toLowerCase();if(!st.includes(state.stage.toLowerCase())&&outlook!==state.stage.toLowerCase())return false}
    return !q||b.id.toLowerCase().includes(compact)||[b.id,b.number,b.title,b.caption,b.author,...b.authors,...(b.coauthors||[]),...(b.sponsors||[]),...(b.cosponsors||[]),b.last_action,...b.topics,...(b.subjects||[]),...(b.search_terms||[]),...b.impacts,...b.agencies.map(a=>agencyName(a.id))].join(' ').toLowerCase().includes(q);
  });
  const byNumber=(a,b)=>a.id.localeCompare(b.id,undefined,{numeric:true});
  const newerNumber=(a,b)=>newestFirst(a.id,b.id);
  const info=new Map(list.map(b=>[b.id,lastActionInfo(b)]));const la=b=>info.get(b.id);
  // Filing dates have no time, so within a day the higher number in each bill type was filed later.
  const sorters={newest:(a,b)=>(b.filed_at||'').localeCompare(a.filed_at||'')||newerNumber(a,b),
    latest:(a,b)=>(la(b).date||'').localeCompare(la(a).date||'')||la(b).rank-la(a).rank||byNumber(a,b),
    oldest:(a,b)=>(la(a).date||'9').localeCompare(la(b).date||'9')||la(a).rank-la(b).rank||byNumber(a,b),
    actionstage:(a,b)=>la(b).rank-la(a).rank||(la(b).date||'').localeCompare(la(a).date||'')||byNumber(a,b),number:byNumber,agencies:(a,b)=>realAgencies(b).length-realAgencies(a).length||byNumber(a,b),hearing:(a,b)=>assessHearing(b).level-assessHearing(a).level||byNumber(a,b),influence:(a,b)=>authorInfluence(b).level-authorInfluence(a).level||byNumber(a,b)};
  return list.sort(sorters[state.sort]);
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
  $('#bill-list').innerHTML=list.length?shown.map(g=>g.length>1?groupMarkup(g):card(g[0])).join(''):`<div class="empty-state"><h3>Nothing matches yet</h3><p>${state.view==='watchlist'?'Star bills from the explorer to follow them here.':'Try a broader topic, agency, or keyword.'}</p></div>`;
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
  return `<article class="bill-card party-${party.tint}${unwatchedCompanion?' unwatched-companion':''}" data-bill-id="${esc(b.id)}"><div class="bill-left"><div class="bill-head">${unwatchedCompanion?'<span class="unwatched-pill">Companion · not watched</span>':''}${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span><span class="party-pill party-${party.tint}" title="${esc(party.detail)}">${esc(party.label)}</span>${influence.level?`<span class="influence-pill">◆ ${esc(influence.label)}</span>`:''}${b.luna?`<span class="luna-pill" title="Tags from the bill's full text, reviewed ${esc(dateText(b.luna.reviewed_at))}">Luna · full text</span>`:''}</div><h3 class="bill-title">${openLinkHtml(b.id,billHref(b.id),'bill-title-link',b.title)}</h3><p class="bill-description">${esc(b.caption)}</p>${headlineLine(b,'card')}<div class="bill-tags">${actionTag}${viaTag}${companionTags}${b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}${agencyTags}${real.length>2?`<span class="tag agency">+${real.length-2} agencies</span>`:''}</div><div class="bill-meta"><span>By <b>${esc(b.authors[0]||b.author)}</b></span><span>${b.authors.length?`${b.authors.length} ${b.authors.length===1?'author':'authors'}`:'Authors not reported'}</span><span>${b.coauthors===null?'Coauthors not reported':`${b.coauthors.length} ${b.coauthors.length===1?'coauthor':'coauthors'}`}</span><span>${b.cosponsors===null?'Cosponsors not reported':`${b.cosponsors.length} ${b.cosponsors.length===1?'cosponsor':'cosponsors'}`}</span><span>Filed ${dateText(b.filed_at)}</span><span>${real.length} agency ${real.length===1?'link':'links'}</span></div></div><div class="bill-right"><button class="watch-button" data-watch="${b.id}" aria-label="${watched?'Remove from':'Add to'} watchlist" aria-pressed="${watched}">${watched?'★':'☆'}</button><div><div class="outlook-label">Hearing progress</div><div class="outlook-value">${esc(h.label)}</div><button class="bill-open" data-open="${b.id}">Bill details →</button></div></div></article>`;
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
function loadNearGeo(){
  if(state.nearGeo||nearLoading)return nearLoading;
  nearLoading=Promise.all(Object.entries(NEAR_FILES).map(async([k,url])=>{
    const r=await fetch(url,{signal:timeoutSignal(15000)});if(!r.ok)throw Error(`HTTP ${r.status}`);return [k,await r.json()];
  })).then(parts=>{
    const geo=Object.fromEntries(parts);
    if(geo.tables?.format!=='texas-bill-districts-v1'||!Array.isArray(geo.house?.features))throw Error('Unrecognized district files');
    state.nearGeo=geo;state.nearError='';
  }).catch(error=>{state.nearError='District maps could not be loaded; try again later.';console.warn('Near you data unavailable',error.message)})
    .finally(()=>{nearLoading=null;if(state.view==='local')renderContent()});
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
  return people.map(m=>`<div class="near-member"><small>${title} · District ${esc(district)}</small><strong>${m.code?`<a class="text-link" href="${esc(memberHref(m.code))}">${esc(memberTitle(m))}</a>`:esc(memberTitle(m))}</strong><p>${esc(m.party||'Party not recorded')}${m.new_to_chamber?' · new to the chamber':''}</p>${m.code?`<a class="text-link" href="${esc(memberHref(m.code))}">All their bills →</a> `:''}${safeHref(m.links?.tlo)?`<a class="text-link" href="${esc(safeHref(m.links.tlo))}" target="_blank" rel="noopener noreferrer">Texas Legislature Online ↗</a>`:''}</div>`).join('');
}
function nearData(){
  const near=state.near,geo=state.nearGeo;
  const members=[...membersFor(state.roster,'house',near.house),...membersFor(state.roster,'senate',near.senate)];
  const byBill=new Map();
  for(const m of members)for(const {bill,role} of billsByMember(state.bills,m)){
    const who=`${m.chamber==='house'?'Rep.':'Sen.'} ${m.display_name}`;
    const entry=byBill.get(bill.id)||{bill,notes:[]};entry.notes.push(`${who} · ${role}`);byBill.set(bill.id,entry);
  }
  const area=geo?areaFor(near,geo.tables):null,gaz=geo?gazetteer(geo.tables):null;
  const local=area?state.bills.map(bill=>({bill,notes:(areaReasons(bill,area,gaz)||[]).map(r=>r.text)})).filter(x=>x.notes.length):[];
  const order=(a,b)=>newestFirst(a.bill,b.bill);
  return {members:[...byBill.values()].sort(order),local:local.sort(order),area,
    statewide:state.bills.filter(b=>(b.locations||[]).some(l=>l.kind==='statewide')).length};
}
function nearRow({bill:b,notes}){
  return `<article class="today-row" data-bill-id="${esc(b.id)}"><div class="today-row-head">${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}<span class="chamber-pill">${esc(b.chamber)}</span>${openLinkHtml(b.id,billHref(b.id),'bill-title-link',b.title)}</div>${headlineLine(b,'card')}${notes.length?`<p class="today-action">${notes.map(esc).join(' · ')}</p>`:''}<div class="bill-tags">${b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}<span class="tag">${esc(lastActionInfo(b).label)}</span></div></article>`;
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
  return `${head(esc(memberTitle(m)))}<div class="info-callout member-profile"><div><small>${where}</small><strong>${esc(memberSummary(m))}</strong>${countyLine}${m.new_to_chamber?'<p class="near-hint">New to this chamber in the 90th Legislature.</p>':''}${links?`<p>${links}</p>`:''}</div></div>
    <p class="near-hint">${total?`${total} ${total===1?'bill':'bills'} in this snapshot. `:''}${roleNote} Sponsors and cosponsors are listed once a bill crosses chambers, so early in the session most bills show authors only.</p>
    ${sections||'<p class="review-empty">No bills by this member in this snapshot yet.</p>'}`;
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
    ['05','Export and import a file','<strong>Export file</strong> saves your watchlist as a small file you can keep or email. <strong>Import file</strong> adds bills from that file, or from any text or spreadsheet export that mentions bill numbers such as “HB 5” or “SJR 9”. Importing only adds; it never removes bills.'],
    ['06','Private sync links','<strong>Create sync link</strong> on the Watchlist keeps one list the same on your phone, laptop and work computer, with no account. Open the <strong>edit link</strong> on each device; treat it like a password, because anyone with it can change the list. The <strong>view-only link</strong> is safe to share and stays current as you edit. You can stop syncing one device, or delete the link for every device.'],
    ['07','RSS feeds','Each bill’s details include an <strong>RSS feed</strong> of its recorded actions, for Outlook or any feed reader. A synced watchlist also has one feed for all of its bills, linked from the Watchlist.']
  ];
  return `<div class="section-head"><div><div class="section-overline">NO ACCOUNT NEEDED</div><h2>Saving and sharing your info</h2></div><button class="outline-button" data-view="watchlist">Open your watchlist →</button></div><div class="info-callout"><strong>There are no logins on this site.</strong> Everything below works without an account, email address or name. Pick whichever fits: keep things on one device, carry them in a link or file, or sync a private link across devices.</div><div class="method-grid">${parts.map(([n,title,body])=>`<article class="method-card"><span class="n">${n}</span><h3>${title}</h3><p>${body}</p></article>`).join('')}</div><div class="section-head"><div><div class="section-overline">PRIVACY</div><h2>What is stored, and where</h2></div></div><div class="subpage-card"><div class="data-field long"><span class="data-label">On this device</span><span class="data-value">Watchlist, last filters, that you saw the disclaimer, and your sync link if you made one</span></div><div class="data-field long"><span class="data-label">On the server (sync links only)</span><span class="data-value">The watched bill numbers, a version number and dates. Links are stored only as one-way fingerprints, so the database cannot be used to open a list.</span></div><div class="data-field long"><span class="data-label">Never collected</span><span class="data-value">Names, email addresses, accounts, tracking cookies or analytics</span></div><div class="data-field long"><span class="data-label">Abuse limits</span><span class="data-value">The sync service counts requests per address in memory for up to an hour, and never writes addresses down</span></div><div class="data-field long"><span class="data-label">Retention</span><span class="data-value">A sync link unused for a year is deleted. Deleting it yourself removes it at once; each device keeps its own copy of the list.</span></div><div class="data-field"><span class="data-label">Sync on this site</span><span class="data-value">${esc(syncState)}</span></div><div class="data-field"><span class="data-label">This device</span><span class="data-value">${esc(deviceState)} · ${state.watch.size} ${state.watch.size===1?'bill':'bills'} watched</span></div><p style="font-size:11px;color:#91a0ad;margin:14px 0 0">Limits: up to 500 bills per synced list. Lost your edit link? Your list is still on each device that had it; create a new sync link from any of them.</p></div>`;
}

function dataMarkup(){
  return `<div class="section-head"><div><div class="section-overline">DATA PROVENANCE</div><h2>Source, coverage & export</h2></div></div><div class="subpage-card"><div class="data-field"><span class="data-label">Legislative session</span><span class="data-value">90R · 2027</span></div><div class="data-field"><span class="data-label">Loaded records</span><span class="data-value">${state.bills.length}</span></div><div class="data-field"><span class="data-label">Snapshot mode</span><span class="data-value">${esc(state.meta?.data_mode||'Unknown')}</span></div><div class="data-field"><span class="data-label">Read from</span><span class="data-value">${esc(state.meta?.loaded_from||'User import')}</span></div><div class="data-field"><span class="data-label">Last generated</span><span class="data-value">${stampText(state.meta?.generated_at)}</span></div><div class="data-field"><span class="data-label">Luna reviews</span><span class="data-value">${state.luna?`${Object.keys(state.luna.bills).length} bills · updated ${esc(stampText(state.luna.generated_at))}`:'not available'}</span></div><div class="data-field"><span class="data-label">Member roster</span><span class="data-value">${state.roster?`${state.roster.counts?.house??'?'} House · ${state.roster.counts?.senate??'?'} Senate · updated ${esc(stampText(state.roster.generated_at))}`:'not available'}</span></div><p style="font-size:12px;color:#748697;line-height:1.65;margin:18px 0">${esc(state.meta?.coverage_note||'Coverage is not guaranteed complete.')}</p><div class="info-callout"><strong>Official source policy:</strong> The Texas Legislative Council publishes bulk material through anonymous FTP and discourages data mining the public Legislature Online pages. The project includes an updater for the official bulk files, with snapshot validation so a failed import cannot silently replace data with an empty result. <a class="text-link" href="https://capitol.texas.gov/billlookup/filedownloads.aspx" target="_blank" rel="noopener noreferrer">Read the source policy ↗</a></div><div class="data-actions"><button class="primary-button" id="import-trigger">↑ Import CSV or JSON</button><button class="outline-button" id="export-csv">↓ Export current results</button><a class="outline-button" href="https://github.com/ctharvey/texas_bill_tracker" target="_blank" rel="noopener noreferrer">Source code ↗</a><input type="file" id="import-file" accept=".csv,.json,text/csv,application/json" hidden></div><p style="font-size:11px;color:#91a0ad;margin:14px 0 0">Imports are temporary to this browser session; they do not alter the public dataset. Watchlist stars are stored on this device.</p></div>`;
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
  return `<li><span class="party-dot party-${letter}" aria-hidden="true"></span>${who} <small>${esc(memberSummary(member))}</small>${official?` <a class="text-link member-official" href="${esc(official)}" target="_blank" rel="noopener noreferrer" aria-label="Official record for ${esc(label)}">official ↗</a>`:''}</li>`;
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

function showDrawer(id,push=false){
  const b=state.bills.find(b=>b.id===id);if(!b)return;
  const h=assessHearing(b),influence=authorInfluence(b),party=authorshipParty(b),last=lastActionInfo(b);
  const agencyRows=b.agencies.length?b.agencies.map(a=>`<div class="agency-row"><div><strong>${esc(agencyName(a.id))}</strong><p>${esc(a.reason||'Relationship not yet annotated')}</p></div><span class="confidence ${a.relationship==='direct'?'direct':''}">${a.source==='luna'?`Luna · ${a.relationship==='direct'?'direct':'inferred'}`:a.relationship==='direct'?'Direct':'Possible'}</span></div>`).join(''):'<p>No agency has been tagged yet. This does not establish that none are affected.</p>';
  const watched=state.watch.has(b.id);
  $('#detail-drawer').innerHTML=`<div class="drawer-top"><span class="drawer-number">90R / ${esc(b.number)}</span><button class="drawer-close" id="drawer-close" aria-label="Close bill details">×</button></div><div class="drawer-pills"><span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span><span class="party-pill party-${party.tint}" title="${esc(party.detail)}">${esc(party.label)}</span></div><h2 style="margin-top:14px">${esc(b.title)}</h2><p class="drawer-caption">${esc(b.caption)}</p>${headlineLine(b,'drawer')}${lunaBlock(b)}<div class="drawer-pills">${b.topics.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div><div class="drawer-meta-grid"><div><small>Filed by</small><strong>${esc(b.author)}</strong></div><div><small>Filed on</small><strong>${dateText(b.filed_at)}</strong></div><div><small>Most recent action</small><strong>${esc(last.label)}${last.chamber?` · ${esc(last.chamber)}`:''} · ${esc(dateText(last.date))}</strong><small>${esc(last.text)}</small></div><div><small>Hearing status</small><strong>${esc(h.label)}</strong></div></div>${b.subjects?.length?`<section class="drawer-section"><h3>Official subjects</h3><p>The Legislative Council's subject index for this bill. Search matches these, so a bill with a vague caption is still found by its subject.</p><div class="bill-tags">${b.subjects.map(s=>`<span class="tag subject-tag">${esc(s)}</span>`).join('')}</div></section>`:''}${companionBlock(b)}${relatedBlock(b)}<section class="drawer-section"><h3>Hearing progress & evidence</h3><div class="evidence-card"><strong>${esc(h.label)} · ${h.level===0?'No rating yet':'Verified procedural signal'}</strong><p>${esc(h.detail)}</p><ul>${h.facts.map(f=>`<li>${esc(f)}</li>`).join('')}</ul></div></section><section class="drawer-section"><h3>Authors & sponsors</h3><p>Authors and coauthors serve in the originating chamber; sponsors and cosponsors serve in the other chamber. Authors include primary and joint/additional primary authors as listed by TLC. Counts reflect this source snapshot.</p><div class="evidence-card"><strong><span class="party-pill party-${party.tint}">${esc(party.label)}</span></strong><p>${esc(party.detail)}</p><p><small>Party, district and tenure come from the Texas Legislative Reference Library's latest recorded service; for members-elect not yet in its records, party and district come from the Secretary of State's unofficial 2026 general election results. Authorship does not indicate a vote or caucus position.</small></p></div>${[['Authors','authors'],['Coauthors','coauthors'],['Sponsors','sponsors'],['Cosponsors','cosponsors']].map(([label,key])=>{const names=b[key];const people=b.people?.[key];return `<h4>${label}${names===null?'':` (${names.length})`}</h4>${names===null?'<p>Not reported in this dataset</p>':!names.length?'<p>None listed in the source snapshot</p>':people?`<ul class="member-list">${people.map(p=>memberItem(p)).join('')}</ul>`:`<p>${names.map(esc).join(' · ')}</p>`}`}).join('')}</section><section class="drawer-section"><h3>Author prominence</h3><div class="evidence-card"><strong>${esc(influence.label)}</strong><p>${esc(influence.factors.join(' · '))}</p>${safeHref(b.author_profile?.source)?`<p><a class="text-link" href="${esc(safeHref(b.author_profile.source))}" target="_blank" rel="noopener noreferrer">Verified member biography ↗</a></p>`:''}</div></section><section class="drawer-section"><h3>Potentially affected agencies (${realAgencies(b).length})</h3><p>All known tags are listed. Possible links are model/rule inferences, not confirmed legal obligations.</p>${agencyRows}</section><section class="drawer-section"><h3>Types of impact</h3><div class="drawer-pills">${b.impacts.length?b.impacts.map(t=>`<span class="tag related">${esc(t)}</span>`).join(''):'<span class="tag">Pending analysis</span>'}</div></section>${b.constituencies?.length?`<section class="drawer-section"><h3>People and institutions affected</h3><div class="drawer-pills">${b.constituencies.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></section>`:''}<section class="drawer-section"><h3>Source & verification</h3><p>Review the bill history and latest text before relying on any classification. <a class="text-link" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Texas Legislature Online ↗</a></p><div class="ai-copy"><button type="button" class="outline-button" data-copy-ai title="Copy a short prompt with links to this bill, for pasting into an AI assistant">Copy for AI</button> <a class="text-link" href="${esc(agentUrl(b))}" target="_blank" rel="noopener noreferrer">AI-readable version ↗</a></div></section><div class="drawer-actions"><a class="primary-button" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Read official bill ↗</a><button class="outline-button" data-watch="${b.id}">${watched?'★ Remove from watchlist':'☆ Follow this bill'}</button><a class="outline-button" href="./live/feeds/${esc(b.id)}.xml" target="_blank" rel="noopener noreferrer" title="Follow this bill's actions in Outlook or a feed reader">RSS feed</a></div>`;
  const reviewSection=document.createElement('section');reviewSection.className='drawer-section';
  const heading=document.createElement('h3');heading.textContent='Full text & highlighted evidence';
  const area=document.createElement('div');
  const local=document.createElement('input');local.type='file';local.accept='.json,application/json';local.hidden=true;
  const load=document.createElement('button');load.className='outline-button';load.textContent='Open a review file';
  load.addEventListener('click',()=>local.click());
  const draw=()=>{if(reviews.has(b.id))renderReview(area,reviews.get(b.id),true);else area.textContent='A reviewed full-text analysis is not yet available. Review files open only in this browser session.';};
  local.addEventListener('change',async()=>{try{const file=local.files[0];if(!file)return;if(file.size>15*1024*1024)throw Error('Select a file smaller than 15 MB');const bundle=JSON.parse(await file.text());reviewModel(bundle);if(bundle.bill_id!==b.id)throw Error('This review belongs to '+bundle.bill_id);reviews.set(b.id,bundle);draw();toast('Private review opened');}catch(error){toast('Review could not be opened: '+error.message)}});
  $('#detail-drawer').append(billTextSection(b),stageSections(b));
  reviewSection.append(heading,load,local,area);$('#detail-drawer').append(reviewSection);draw();
  $('#detail-drawer').hidden=false;$('#drawer-scrim').hidden=false;document.body.style.overflow='hidden';$('#drawer-close').focus();
  state.openBill=b.id;
  if(persistState(push&&!drawerPushed))drawerPushed=true;
}

function closeDrawer(){
  $('#detail-drawer').hidden=true;$('#drawer-scrim').hidden=true;document.body.style.overflow='';
  if(!state.openBill)return;
  state.openBill=null;
  // Step back over the entry the bill added, so a later Back does not land on the same page again.
  if(drawerPushed){drawerPushed=false;history.back()}else persistState();
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
  input.setAttribute('aria-expanded','true');
  input.removeAttribute('aria-activedescendant');
  popup.scrollTop=0;
}

function hideAgencyChoices(){
  const input=$('#filter-agency'),popup=$('#agency-options');
  if(!input||!popup)return;
  popup.hidden=true;
  input.value=state.agency?agencyName(state.agency):'';
  input.setAttribute('aria-expanded','false');
  input.removeAttribute('aria-activedescendant');
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
function toast(message){const t=$('#toast');t.textContent=message;t.classList.add('visible');clearTimeout(toast.timer);toast.timer=setTimeout(()=>t.classList.remove('visible'),2500)}

function handleClick(e){
  const agencyOption=e.target.closest('[data-agency-option]');
  if(agencyOption){pickAgency(agencyOption.dataset.agencyOption);return}
  if(e.target.closest('#agency-combobox')){
    const input=$('#filter-agency');
    if(e.target!==input)input.focus();
    if($('#agency-options').hidden)showAgencyChoices('');
    return;
  }
  hideAgencyChoices();
  const nav=e.target.closest('[data-view]');if(nav){e.preventDefault();location.hash=nav.dataset.view;setView(nav.dataset.view);return}
  const open=e.target.closest('[data-open]');if(open){
    // A modified or non-primary click on a link keeps the browser's own behavior (new tab, new window).
    if(open.tagName!=='A'||cardClickOpens({button:e.button,metaKey:e.metaKey,ctrlKey:e.ctrlKey,shiftKey:e.shiftKey,altKey:e.altKey})){e.preventDefault();showDrawer(open.dataset.open,true)}
    return}
  const copyAi=e.target.closest('[data-copy-ai]');if(copyAi){copyForAi(copyAi);return}
  if(e.target.closest('#near-locate')){nearLocate();return}
  if(e.target.closest('#near-forget')){saveNear(null);toast('Your districts were removed from this device');return}
  if(e.target.closest('#near-change')){state.near=null;state.nearError='';renderContent();return}
  if(e.target.closest('#near-county-use')){const c=countyDistricts(state.nearGeo?.tables,state.nearPick);if(c)saveNear({county:state.nearPick,source:'county',
    house:$('#near-house-pick')?.value||c.house[0]?.district,senate:$('#near-senate-pick')?.value||c.senate[0]?.district,near:c.house.length>1||c.senate.length>1});return}
  if(e.target.closest('#near-numbers-use')){const near=cleanNear({house:$('#near-house-num')?.value,senate:$('#near-senate-num')?.value,source:'district'},state.nearGeo?.tables);
    if(!near){state.nearError='Enter a House district from 1 to 150, a Senate district from 1 to 31, or both.';renderContent();return}saveNear(near);return}
  const nearMore=e.target.closest('[data-near-more]');if(nearMore){state.nearShow[nearMore.dataset.nearMore]+=30;renderContent();return}
  const memberMore=e.target.closest('[data-member-more]');if(memberMore){const role=memberMore.dataset.memberMore;state.memberShow[role]=(state.memberShow[role]||30)+30;renderContent();return}
  const copyPage=e.target.closest('#copy-page-ai');if(copyPage){copyPageForAi(copyPage);return}
  const todayTopic=e.target.closest('[data-today-topic]');if(todayTopic){state.todayTopic=todayTopic.dataset.todayTopic;state.todayLimit=100;renderContent();return}
  if(e.target.closest('#today-more')){state.todayLimit+=100;renderContent();return}
  if(e.target.closest('#today-topics-toggle')){state.todayAllTopics=!state.todayAllTopics;renderContent();return}
  if(e.target.closest('#copy-view-link,#share-watch,#export-watch,#import-watch,#shared-add,#shared-close,[id^="sync-"]')){handleSaveClick(e.target);return}
  const group=e.target.closest('[data-watch-group]');if(group){
    const known=new Set(state.bills.map(b=>b.id));const ids=group.dataset.watchGroup.split(',').filter(id=>known.has(id));
    if(!ids.length)return;
    const op=ids.every(id=>state.watch.has(id))?'remove':'add';changeWatch(op,ids);
    renderOverview();if(state.view==='all'||state.view==='watchlist')renderResults();if(!$('#detail-drawer').hidden&&state.openBill)showDrawer(state.openBill);
    const names=ids.map(id=>state.bills.find(b=>b.id===id)?.number||id).join(', ');
    toast(op==='add'?`Watching ${names}`:`Removed ${names} from your watchlist`);return}
  const star=e.target.closest('[data-watch]');if(star){const id=star.dataset.watch;changeWatch(state.watch.has(id)?'remove':'add',[id]);renderOverview();if(state.view==='all'||state.view==='watchlist')renderResults();if(!$('#detail-drawer').hidden)showDrawer(id);toast(state.watch.has(id)?`${id} added to your watchlist`:`${id} removed from your watchlist`);return}
  const topic=e.target.closest('[data-topic]');if(topic){state.topic=topic.dataset.topic;state.visibleCount=30;renderContent();return}
  const pick=e.target.closest('[data-agency-pick]');if(pick){switchFilters('all');state.agency=pick.dataset.agencyPick;state.visibleCount=30;state.view='all';location.hash='all';setView('all');return}
  if(e.target.closest('#clear-filters')){Object.assign(state,{query:'',topic:'',agency:'',chamber:'',stage:'',action:'',outlook:'',sort:'newest',onlyWatch:false,visibleCount:30});renderContent();return}
  if(e.target.closest('#watch-filter')){state.onlyWatch=!state.onlyWatch;state.visibleCount=30;renderContent();return}
  if(e.target.closest('#load-more')){state.visibleCount+=30;renderResults();return}
  if(e.target.closest('#export-csv')){exportCsv();return}
  if(e.target.closest('#import-trigger')){$('#import-file').click();return}
  if(e.target.closest('#drawer-close')){closeDrawer();return}
  // Empty space on a card opens its drawer, unless the click was on a control or the reader is selecting text.
  const card=e.target.closest('[data-bill-id]');
  if(card&&cardClickOpens({interactive:Boolean(e.target.closest(CARD_CONTROLS)),selection:window.getSelection?.().toString()||'',button:e.button,metaKey:e.metaKey,ctrlKey:e.ctrlKey,shiftKey:e.shiftKey,altKey:e.altKey}))showDrawer(card.dataset.billId,true);
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
  const labels={all:'Bill explorer',watchlist:'Watchlist',today:'Today',local:'Near you',member:member?`Bills by ${memberTitle(member)}`:'Member'};
  const today=state.view==='today'?todayData():null;
  const text=pageAiText({view:state.view,label:labels[state.view]||state.view,pageUrl:location.href,bill,agencyName,
    companions:companionsOf,via:state.view==='today'||state.view==='member'?null:agencyVia(),
    bills:today?today.shown.map(r=>r.bill):['all','watchlist'].includes(state.view)?filteredBills():state.view==='local'&&state.near?(d=>[...d.members,...d.local].map(r=>r.bill).filter((b,i,a)=>a.indexOf(b)===i))(nearData()):member?Object.values(memberData(member)).flat().map(r=>r.bill):[],
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
  if(e.target.id==='bill-search'){state.query=e.target.value;state.visibleCount=30;renderResults()}
  if(e.target.id==='filter-agency'){
    if(state.agency){state.agency='';state.visibleCount=30;renderResults()}
    showAgencyChoices(e.target.value);
  }
}
function handleChange(e){
  if(e.target.id==='near-county'){state.nearPick=e.target.value||null;state.nearError='';renderContent();$('#near-county')?.focus();return}
  const m={'filter-topic':'topic','filter-chamber':'chamber','filter-stage':'stage','filter-outlook':'outlook','filter-action':'action'};
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
    const previous={bills:state.bills,meta:state.meta,topic:state.topic,agency:state.agency,chamber:state.chamber,stage:state.stage,action:state.action,outlook:state.outlook,query:state.query,visibleCount:state.visibleCount,view:state.view};
    try{
      state.bills=valid;state.meta={session:'90R',data_mode:'local import',source_file:file.name,generated_at:new Date().toISOString(),coverage_note:`Local file: ${file.name}. Imported rows are visible only during this session.`};
      switchFilters('all');Object.assign(state,{topic:'',agency:'',chamber:'',stage:'',action:'',outlook:'',query:'',visibleCount:30});setView('all');
    }catch(renderError){Object.assign(state,previous);setView(previous.view);throw renderError}
    location.hash='all';toast(`Imported ${valid.length} bills`);
  }catch(err){toast(`Import failed: ${err.message}`)}
}

init();
