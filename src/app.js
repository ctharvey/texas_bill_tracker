import {reviewModel, renderReview} from './review.js';
import {AGENCIES, AGENCY_NAME, SCOPE_AGENCY_ID, autoTagBill, applyLunaTags, attachMembers, authorshipParty, memberSummary, lastActionInfo, LAST_ACTION_TYPES, reviewProgress, POLICY_AREAS, assessHearing, authorInfluence, officialUrl, memberNames, matchAuthorProfile, snapshotAgeHours} from './taxonomy.js';

const $ = (selector, root=document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {view:'all',bills:[],watch:new Set(),query:'',topic:'',agency:'',chamber:'',stage:'',action:'',outlook:'',sort:'newest',onlyWatch:false,visibleCount:30,meta:null,luna:null,roster:null,reviewStatus:null};
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

function normalized(raw,profiles){
  const key=String(raw.id||raw.number||raw.bill_number||'').replace(/\s/g,'').toUpperCase();
  if(!/^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/.test(key))return null;
  const number=key.replace(/^(HJR|SJR|HCR|SCR|HB|SB|HR|SR)/,'$1 ');
  const chamber=key.startsWith('H')?'House':'Senate';
  const bill={...raw,id:key,number,chamber,
    title:raw.title||raw.description||raw.caption||'No caption available',
    caption:raw.caption||raw.description||raw.title||'',
    author:raw.author||raw.primary_author||'Author not yet available',
    authors:memberNames(raw.authors??(typeof raw.author==='string'&&!raw.author.startsWith('Author not')?raw.author:raw.primary_author)),
    coauthors:raw.coauthors==null?null:memberNames(raw.coauthors),
    sponsors:raw.sponsors==null?null:memberNames(raw.sponsors),
    cosponsors:raw.cosponsors==null?null:memberNames(raw.cosponsors),
    author_profile:raw.author_profile||matchAuthorProfile(raw.author||raw.primary_author,profiles)||{},
    filed_at:raw.filed_at||raw.status_date||'',
    last_action:raw.last_action||raw.status||'Filed',
    status:raw.status||'Filed',
    last_action_date:raw.last_action_date||raw.filed_at||''};
  return autoTagBill(bill);
}

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
        const response=await fetch(url,{cache:'no-store',signal:timeoutSignal(7500)});
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
      const response=await fetch('./live/luna/tags.json',{cache:'no-store',signal:timeoutSignal(7500)});
      if(!response.ok)throw Error(`HTTP ${response.status}`);
      const tags=await response.json();
      if(tags?.format!=='texas-bill-luna-tags-v1'||!tags.bills||typeof tags.bills!=='object'||Array.isArray(tags.bills))throw Error('Unrecognized tags format');
      state.luna={...tags,agencies:tags.agencies&&typeof tags.agencies==='object'?tags.agencies:{}};
      loadedBills=loadedBills.map(b=>Object.hasOwn(tags.bills,b.id)&&tags.bills[b.id]&&typeof tags.bills[b.id]==='object'?applyLunaTags(b,tags.bills[b.id],state.luna.agencies):b);
    }catch(error){state.luna=null;console.warn('Luna tags unavailable',error.message)}
    await loadReviewStatus();
    for(const url of ['./live/members.json','./data/members.json']){
      try{
        const response=await fetch(url,{cache:'no-store',signal:timeoutSignal(7500)});
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
  document.addEventListener('focusin',event=>{
    if(event.target.id==='filter-agency')showAgencyChoices('');
  });
  document.addEventListener('keydown',event=>{
    if(event.target.id==='filter-agency'&&handleAgencyKeydown(event))return;
    if(event.key==='Escape')closeDrawer();
  });
  $('#drawer-scrim').addEventListener('click',closeDrawer);
  const knownView=hash=>['all','watchlist','agencies','review','method','data'].includes(hash)?hash:'all';
  window.addEventListener('hashchange',()=>setView(knownView(location.hash.slice(1))));
  setView(knownView(location.hash.slice(1)));
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

async function loadReviewStatus(){
  try{
    const response=await fetch('./live/luna/status.json',{cache:'no-store',signal:timeoutSignal(7500)});
    if(!response.ok)throw Error(`HTTP ${response.status}`);
    const status=await response.json();
    if(status?.format!=='texas-bill-luna-status-v1'||!Array.isArray(status.reviewed))throw Error('Unrecognized status format');
    state.reviewStatus=status;
  }catch(error){console.warn('Review status unavailable',error.message)}
}

function setView(view){
  state.view=view;
  document.querySelectorAll('[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===view));
  const heads={all:['See what’s moving.<br><em>Know what it changes.</em>','Track legislation by policy, affected agency, author influence, and its path through the Capitol.'],watchlist:['Your watchlist.<br><em>Keep the signal.</em>','Bills you are following on this device, with a clear view of their movement.'],agencies:['Follow the agencies.<br><em>Not just the bills.</em>','Explore where legislation might land across Texas government.'],review:['Full-text review.<br><em>Bill by bill.</em>','Which bills Luna has read in full, which it is working on, and what is still waiting.'],method:['The scoring method.<br><em>No black boxes.</em>','Signals and uncertainty are displayed separately from verified legislative actions.'],data:['Behind the tracker.<br><em>Follow the source.</em>','Understand coverage, refreshes, and how to load or export bill data.']};
  $('#page-title').innerHTML=heads[view][0];$('#page-subtitle').textContent=heads[view][1];
  $('#overview').hidden=!['all','watchlist'].includes(view);
  renderNotice();renderOverview();renderContent();
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
  else if(state.view==='agencies')el.innerHTML=agenciesMarkup();
  else if(state.view==='review')el.innerHTML=reviewMarkup();
  else if(state.view==='method')el.innerHTML=methodMarkup();
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
    <div class="explorer-controls"><div class="search-row"><div class="search-wrap"><input aria-label="Search bills" id="bill-search" placeholder="Search bill number, author, subject, or keyword…" value="${esc(state.query)}" autocomplete="off"></div><button class="outline-button" id="clear-filters">Clear filters</button><button class="primary-button" id="export-csv">↓ Export results</button></div>
    <div class="filter-row"><select aria-label="Policy area" id="filter-topic">${options(topics,state.topic,'All policy areas')}</select><div class="agency-combobox" id="agency-combobox"><input aria-label="Affected agency" aria-controls="agency-options" aria-expanded="false" aria-autocomplete="list" role="combobox" id="filter-agency" placeholder="All affected agencies" value="${esc(state.agency?agencyName(state.agency):'')}" autocomplete="off"><span class="agency-chevron" aria-hidden="true">⌄</span><div class="agency-options" id="agency-options" role="listbox" hidden><div id="agency-option-0" role="option" class="agency-option" data-agency-option="" data-agency-label="All affected agencies" aria-selected="${!state.agency}"><span>All affected agencies</span></div>${agencyOpts}<p class="agency-no-results" id="agency-no-results" hidden>No matching agencies</p></div></div><select aria-label="Chamber" id="filter-chamber">${options(['House','Senate'],state.chamber,'Both chambers')}</select><select aria-label="Stage" id="filter-stage">${options(['Filed','Referred','Scheduled','Heard','Advanced','Passed','Enacted'],state.stage,'Any stage')}</select><select aria-label="Hearing status" id="filter-outlook">${options(['Not rated','Referred','Scheduled','Heard'],state.outlook,'Hearing status')}</select><select aria-label="Last action" id="filter-action">${options(unique([...LAST_ACTION_TYPES.map(t=>t.label),'Other action']).filter(l=>l===state.action||state.bills.some(b=>lastActionInfo(b).label===l)),state.action,'Any last action')}</select><button class="check-filter ${state.onlyWatch?'selected':''}" id="watch-filter">☆ Watched only</button></div></div>
    <div class="topic-strip" aria-label="Quick topic filters"><button class="topic-chip ${state.topic===''?'selected':''}" data-topic="">All topics</button>${popular.map(t=>`<button class="topic-chip ${state.topic===t?'selected':''}" data-topic="${esc(t)}">${esc(t)}</button>`).join('')}</div>
    <div class="results-header"><div><strong id="result-count">—</strong><span id="result-note"></span></div><select id="sort-order" aria-label="Sort bills">${options(Object.values(SORTS),SORTS[state.sort],'Sort by')}</select></div><div class="bill-list" id="bill-list"></div><div class="explorer-bottom" id="results-bottom"></div>`;
}

function filteredBills(){
  let list=state.bills.filter(b=>{
    if(state.view==='watchlist'&&!state.watch.has(b.id))return false;
    if(state.onlyWatch&&!state.watch.has(b.id))return false;
    if(state.topic&&!b.topics.includes(state.topic))return false;
    if(state.agency&&!b.agencies.some(a=>a.id===state.agency))return false;
    if(state.chamber&&b.chamber!==state.chamber)return false;
    if(state.outlook&&assessHearing(b).label!==state.outlook)return false;
    if(state.action&&lastActionInfo(b).label!==state.action)return false;
    if(state.stage){const st=(b.status||'').toLowerCase();const outlook=assessHearing(b).label.toLowerCase();if(!st.includes(state.stage.toLowerCase())&&outlook!==state.stage.toLowerCase())return false}
    const q=state.query.trim().toLowerCase();
    const compact=q.replace(/\s+/g,'');
    return !q||b.id.toLowerCase().includes(compact)||[b.id,b.number,b.title,b.caption,b.author,...b.authors,...(b.coauthors||[]),...(b.sponsors||[]),...(b.cosponsors||[]),b.last_action,...b.topics,...b.impacts,...b.agencies.map(a=>agencyName(a.id))].join(' ').toLowerCase().includes(q);
  });
  const byNumber=(a,b)=>a.id.localeCompare(b.id,undefined,{numeric:true});
  const info=new Map(list.map(b=>[b.id,lastActionInfo(b)]));const la=b=>info.get(b.id);
  const sorters={newest:(a,b)=>(b.filed_at||'').localeCompare(a.filed_at||'')||a.id.localeCompare(b.id,undefined,{numeric:true}),
    latest:(a,b)=>(la(b).date||'').localeCompare(la(a).date||'')||la(b).rank-la(a).rank||byNumber(a,b),
    oldest:(a,b)=>(la(a).date||'9').localeCompare(la(b).date||'9')||la(a).rank-la(b).rank||byNumber(a,b),
    actionstage:(a,b)=>la(b).rank-la(a).rank||(la(b).date||'').localeCompare(la(a).date||'')||byNumber(a,b),number:(a,b)=>a.id.localeCompare(b.id,undefined,{numeric:true}),agencies:(a,b)=>realAgencies(b).length-realAgencies(a).length,hearing:(a,b)=>assessHearing(b).level-assessHearing(a).level,influence:(a,b)=>authorInfluence(b).level-authorInfluence(a).level};
  return list.sort(sorters[state.sort]);
}

function renderResults(){
  const list=filteredBills();
  $('#result-count').textContent=`${list.length} ${list.length===1?'bill':'bills'}`;
  $('#result-note').textContent=state.meta?.data_mode==='curated'?' · within curated sample':' · matching filters';
  const visible=list.slice(0,state.visibleCount);
  $('#bill-list').innerHTML=list.length?visible.map(billCard).join(''):`<div class="empty-state"><h3>Nothing matches yet</h3><p>${state.view==='watchlist'?'Star bills from the explorer to follow them here.':'Try a broader topic, agency, or keyword.'}</p></div>`;
  $('#results-bottom').innerHTML=`${list.length>state.visibleCount?`<button class="outline-button" id="load-more">Load 30 more · showing ${visible.length} of ${list.length}</button><div style="height:12px"></div>`:''}${esc(state.meta?.coverage_note||'Check the official record for authoritative status.')}`;
}

function billCard(b){
  const h=assessHearing(b);const watched=state.watch.has(b.id);const influence=authorInfluence(b);
  const real=realAgencies(b);
  const scopeTag=b.agencies.length>real.length?'<span class="tag" title="Cross-cutting scope marker, not an agency">Statewide scope</span>':'';
  const agencyTags=scopeTag+real.slice(0,2).map(a=>`<span class="tag agency" title="${esc(a.reason||'')}">${esc(agencyName(a.id).replace(/^Texas /,'').replace(/ Department of /,' · '))}</span>`).join('');
  const party=authorshipParty(b),last=lastActionInfo(b);
  const actionTag=`<span class="tag action-tag action-${esc(last.key)}" title="${esc(`Last action${last.chamber?` (${last.chamber})`:''}: ${last.text}`)}">${esc(last.label)}${last.chamber&&last.key!=='filed'?` · ${esc(last.chamber)}`:''}${last.date?` · ${esc(shortDate(last.date))}`:''}</span>`;
  return `<article class="bill-card party-${party.tint}"><div class="bill-left"><div class="bill-head"><span class="bill-number">${esc(b.number)}</span><span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span><span class="party-pill party-${party.tint}" title="${esc(party.detail)}">${esc(party.label)}</span>${influence.level?`<span class="influence-pill">◆ ${esc(influence.label)}</span>`:''}${b.luna?`<span class="luna-pill" title="Tags from the bill's full text, reviewed ${esc(dateText(b.luna.reviewed_at))}">Luna · full text</span>`:''}</div><h3 class="bill-title">${esc(b.title)}</h3><p class="bill-description">${esc(b.caption)}</p><div class="bill-tags">${actionTag}${b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}${agencyTags}${real.length>2?`<span class="tag agency">+${real.length-2} agencies</span>`:''}</div><div class="bill-meta"><span>By <b>${esc(b.authors[0]||b.author)}</b></span><span>${b.authors.length?`${b.authors.length} ${b.authors.length===1?'author':'authors'}`:'Authors not reported'}</span><span>${b.coauthors===null?'Coauthors not reported':`${b.coauthors.length} ${b.coauthors.length===1?'coauthor':'coauthors'}`}</span><span>${b.cosponsors===null?'Cosponsors not reported':`${b.cosponsors.length} ${b.cosponsors.length===1?'cosponsor':'cosponsors'}`}</span><span>Filed ${dateText(b.filed_at)}</span><span>${real.length} agency ${real.length===1?'link':'links'}</span></div></div><div class="bill-right"><button class="watch-button" data-watch="${b.id}" aria-label="${watched?'Remove from':'Add to'} watchlist" aria-pressed="${watched}">${watched?'★':'☆'}</button><div><div class="outlook-label">Hearing progress</div><div class="outlook-value">${esc(h.label)}</div><button class="bill-open" data-open="${b.id}">Bill details →</button></div></div></article>`;
}

function agenciesMarkup(){
  const counts=new Map();for(const b of state.bills)for(const a of realAgencies(b))counts.set(a.id,(counts.get(a.id)||0)+1);
  const agencies=unique([...AGENCIES.map(a=>a.id),...Object.keys(state.luna?.agencies||{})]).filter(id=>id!==SCOPE_AGENCY_ID).map(id=>({id,name:agencyName(id)})).sort((a,b)=>(counts.get(b.id)||0)-(counts.get(a.id)||0)||a.name.localeCompare(b.name));
  return `<div class="section-head"><div><div class="section-overline">IMPACT DIRECTORY</div><h2>Texas state agencies</h2></div><span class="subtitle">${counts.size} with possible links in this snapshot</span></div><div class="info-callout"><strong>Why an agency index?</strong> One bill can change the work of several state agencies. “Direct” means the supplied material names an agency; “possible” means an inferred policy connection. An agency absent from a caption is not proof it is unaffected—full bill text review is needed for comprehensive coverage.</div><div class="agency-grid" style="margin-top:18px">${agencies.map(a=>`<button class="agency-card" data-agency-pick="${esc(a.id)}"><span class="agency-code">${esc(a.id.toUpperCase())}</span><strong>${esc(a.name)}</strong><span class="hits">${counts.get(a.id)||0} ${counts.get(a.id)===1?'bill':'bills'} in snapshot →</span></button>`).join('')}</div>`;
}

function reviewMarkup(){
  const ids=state.bills.map(b=>b.id),status=state.reviewStatus,tagged=state.luna?.bills||{};
  const p=reviewProgress(ids,status,Object.keys(tagged));
  const total=ids.length||1,pct=n=>Math.round(n/total*1000)/10;
  const minutes=status?.updated_at?(Date.now()-Date.parse(status.updated_at))/60000:null;
  const stale=Boolean(status?.running)&&minutes>90;
  const line=!status?'Live worker status is unavailable, so bills with published Luna tags are counted as reviewed.'
    :stale?`The worker last reported ${esc(stampText(status.updated_at))} and may have stopped.`
    :status.running?`Reviewing now · updated ${esc(stampText(status.updated_at))}`
    :`Idle between hourly runs · last update ${esc(stampText(status.updated_at))}`;
  const chip=(id,note='')=>`<button class="review-chip${tagged[id]?' tagged':''}" data-open="${esc(id)}" title="${tagged[id]?'Luna tags published':'Reviewed; no verified tags published'}${note?' · '+esc(note):''}">${esc(id)}</button>`;
  const group=(title,list,empty,open=true)=>`<details class="review-group"${open?' open':''}><summary><strong>${title}</strong> <span>${list.length.toLocaleString()}</span></summary>${list.length?`<div class="review-chips">${list.join('')}</div>`:`<p class="review-empty">${empty}</p>`}</details>`;
  const counts=[['Reviewed',p.reviewed.length,'done'],['In progress',p.inProgress.length+(p.current?1:0),'progress'],['Failed',p.failed.length,'failed'],['Not started',p.notStarted.length,'waiting']];
  const now=p.current&&!stale?`<div class="review-now"><span class="review-pulse" aria-hidden="true"></span><div><small>Reviewing now</small>${chip(p.current)}</div>${p.upcoming.length?`<div><small>Up next</small>${p.upcoming.map(id=>chip(id)).join('')}</div>`:''}</div>`:'';
  return `<div class="section-head"><div><div class="section-overline">LUNA FULL-TEXT REVIEW</div><h2>Review progress</h2></div><span class="subtitle">${line}</span></div>
  <div class="review-bar" role="img" aria-label="${p.reviewed.length} reviewed, ${p.inProgress.length} in progress, ${p.failed.length} failed, ${p.notStarted.length} not started of ${ids.length}">${counts.map(([,n,cls])=>`<span class="seg ${cls}" style="width:${pct(n)}%"></span>`).join('')}</div>
  <div class="review-counts">${counts.map(([label,n,cls])=>`<div class="review-count ${cls}"><span class="dot"></span><strong>${n.toLocaleString()}</strong><span>${label} · ${pct(n)}%</span></div>`).join('')}</div>
  ${now}
  ${group('In progress',[...(p.current?[chip(p.current,'being reviewed now')]:[]),...p.inProgress.map(id=>chip(id,'queued to finish open review questions'))],'Nothing is being reviewed or waiting on a retry.')}
  ${group('Failed',p.failed.map(f=>chip(f.id,f.stage?`${f.stage} failed`:'failed')),'No failures.',p.failed.length>0)}
  ${group('Reviewed',p.reviewed.map(id=>chip(id)),'No bills reviewed yet.')}
  ${group('Not started',p.notStarted.map(id=>chip(id)),'Every bill has been picked up.',false)}
  <p class="review-legend"><span class="review-chip tagged">HB1</span> verified Luna tags published · <span class="review-chip">HB1</span> reviewed, no claims verified against the text yet. Failed bills are usually ones whose text the legislature has not posted; they are retried automatically.</p>`;
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
  const link=safeHref(member?.links?.lrl||member?.links?.tlo);
  const label=member?.full_name||name;
  return `<li><span class="party-dot party-${letter}" aria-hidden="true"></span>${link?`<a class="text-link" href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`:`<strong>${esc(label)}</strong>`} <small>${esc(memberSummary(member))}</small></li>`;
}

function showDrawer(id){
  const b=state.bills.find(b=>b.id===id);if(!b)return;
  const h=assessHearing(b),influence=authorInfluence(b),party=authorshipParty(b),last=lastActionInfo(b);
  const agencyRows=b.agencies.length?b.agencies.map(a=>`<div class="agency-row"><div><strong>${esc(agencyName(a.id))}</strong><p>${esc(a.reason||'Relationship not yet annotated')}</p></div><span class="confidence ${a.relationship==='direct'?'direct':''}">${a.source==='luna'?`Luna · ${a.relationship==='direct'?'direct':'inferred'}`:a.relationship==='direct'?'Direct':'Possible'}</span></div>`).join(''):'<p>No agency has been tagged yet. This does not establish that none are affected.</p>';
  const watched=state.watch.has(b.id);
  $('#detail-drawer').innerHTML=`<div class="drawer-top"><span class="drawer-number">90R / ${esc(b.number)}</span><button class="drawer-close" id="drawer-close" aria-label="Close bill details">×</button></div><div class="drawer-pills"><span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span><span class="party-pill party-${party.tint}" title="${esc(party.detail)}">${esc(party.label)}</span></div><h2 style="margin-top:14px">${esc(b.title)}</h2><p class="drawer-caption">${esc(b.caption)}</p>${lunaBlock(b)}<div class="drawer-pills">${b.topics.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div><div class="drawer-meta-grid"><div><small>Filed by</small><strong>${esc(b.author)}</strong></div><div><small>Filed on</small><strong>${dateText(b.filed_at)}</strong></div><div><small>Most recent action</small><strong>${esc(last.label)}${last.chamber?` · ${esc(last.chamber)}`:''} · ${esc(dateText(last.date))}</strong><small>${esc(last.text)}</small></div><div><small>Hearing status</small><strong>${esc(h.label)}</strong></div></div><section class="drawer-section"><h3>Hearing progress & evidence</h3><div class="evidence-card"><strong>${esc(h.label)} · ${h.level===0?'No rating yet':'Verified procedural signal'}</strong><p>${esc(h.detail)}</p><ul>${h.facts.map(f=>`<li>${esc(f)}</li>`).join('')}</ul></div></section><section class="drawer-section"><h3>Authors & sponsors</h3><p>Authors and coauthors serve in the originating chamber; sponsors and cosponsors serve in the other chamber. Authors include primary and joint/additional primary authors as listed by TLC. Counts reflect this source snapshot.</p><div class="evidence-card"><strong><span class="party-pill party-${party.tint}">${esc(party.label)}</span></strong><p>${esc(party.detail)}</p><p><small>Party, district and tenure come from the Texas Legislative Reference Library's latest recorded service; for members-elect not yet in its records, party and district come from the Secretary of State's unofficial 2026 general election results. Authorship does not indicate a vote or caucus position.</small></p></div>${[['Authors','authors'],['Coauthors','coauthors'],['Sponsors','sponsors'],['Cosponsors','cosponsors']].map(([label,key])=>{const names=b[key];const people=b.people?.[key];return `<h4>${label}${names===null?'':` (${names.length})`}</h4>${names===null?'<p>Not reported in this dataset</p>':!names.length?'<p>None listed in the source snapshot</p>':people?`<ul class="member-list">${people.map(p=>memberItem(p)).join('')}</ul>`:`<p>${names.map(esc).join(' · ')}</p>`}`}).join('')}</section><section class="drawer-section"><h3>Author prominence</h3><div class="evidence-card"><strong>${esc(influence.label)}</strong><p>${esc(influence.factors.join(' · '))}</p>${safeHref(b.author_profile?.source)?`<p><a class="text-link" href="${esc(safeHref(b.author_profile.source))}" target="_blank" rel="noopener noreferrer">Verified member biography ↗</a></p>`:''}</div></section><section class="drawer-section"><h3>Potentially affected agencies (${realAgencies(b).length})</h3><p>All known tags are listed. Possible links are model/rule inferences, not confirmed legal obligations.</p>${agencyRows}</section><section class="drawer-section"><h3>Types of impact</h3><div class="drawer-pills">${b.impacts.length?b.impacts.map(t=>`<span class="tag related">${esc(t)}</span>`).join(''):'<span class="tag">Pending analysis</span>'}</div></section>${b.constituencies?.length?`<section class="drawer-section"><h3>People and institutions affected</h3><div class="drawer-pills">${b.constituencies.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></section>`:''}<section class="drawer-section"><h3>Source & verification</h3><p>Review the bill history and latest text before relying on any classification. <a class="text-link" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Texas Legislature Online ↗</a></p></section><div class="drawer-actions"><a class="primary-button" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Read official bill ↗</a><button class="outline-button" data-watch="${b.id}">${watched?'★ Remove from watchlist':'☆ Follow this bill'}</button></div>`;
  const reviewSection=document.createElement('section');reviewSection.className='drawer-section';
  const heading=document.createElement('h3');heading.textContent='Full text & highlighted evidence';
  const area=document.createElement('div');
  const local=document.createElement('input');local.type='file';local.accept='.json,application/json';local.hidden=true;
  const load=document.createElement('button');load.className='outline-button';load.textContent='Open a review file';
  load.addEventListener('click',()=>local.click());
  const draw=()=>{if(reviews.has(b.id))renderReview(area,reviews.get(b.id),true);else area.textContent='A reviewed full-text analysis is not yet available. Review files open only in this browser session.';};
  local.addEventListener('change',async()=>{try{const file=local.files[0];if(!file)return;if(file.size>15*1024*1024)throw Error('Select a file smaller than 15 MB');const bundle=JSON.parse(await file.text());reviewModel(bundle);if(bundle.bill_id!==b.id)throw Error('This review belongs to '+bundle.bill_id);reviews.set(b.id,bundle);draw();toast('Private review opened');}catch(error){toast('Review could not be opened: '+error.message)}});
  reviewSection.append(heading,load,local,area);$('#detail-drawer').append(reviewSection);draw();
  $('#detail-drawer').hidden=false;$('#drawer-scrim').hidden=false;document.body.style.overflow='hidden';$('#drawer-close').focus();
}

function closeDrawer(){$('#detail-drawer').hidden=true;$('#drawer-scrim').hidden=true;document.body.style.overflow=''}

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
  const open=e.target.closest('[data-open]');if(open){showDrawer(open.dataset.open);return}
  const star=e.target.closest('[data-watch]');if(star){const id=star.dataset.watch;state.watch.has(id)?state.watch.delete(id):state.watch.add(id);if(STORAGE_OK)localStorage.setItem(storageKey,JSON.stringify([...state.watch]));renderOverview();if(state.view==='all'||state.view==='watchlist')renderResults();if(!$('#detail-drawer').hidden)showDrawer(id);toast(state.watch.has(id)?`${id} added to your watchlist`:`${id} removed from your watchlist`);return}
  const topic=e.target.closest('[data-topic]');if(topic){state.topic=topic.dataset.topic;state.visibleCount=30;renderContent();return}
  const pick=e.target.closest('[data-agency-pick]');if(pick){state.agency=pick.dataset.agencyPick;state.visibleCount=30;state.view='all';location.hash='all';setView('all');return}
  if(e.target.closest('#clear-filters')){Object.assign(state,{query:'',topic:'',agency:'',chamber:'',stage:'',action:'',outlook:'',sort:'newest',onlyWatch:false,visibleCount:30});renderContent();return}
  if(e.target.closest('#watch-filter')){state.onlyWatch=!state.onlyWatch;state.visibleCount=30;renderContent();return}
  if(e.target.closest('#load-more')){state.visibleCount+=30;renderResults();return}
  if(e.target.closest('#export-csv')){exportCsv();return}
  if(e.target.closest('#import-trigger')){$('#import-file').click();return}
  if(e.target.closest('#drawer-close')){closeDrawer();return}
}

function handleInput(e){
  if(e.target.id==='bill-search'){state.query=e.target.value;state.visibleCount=30;renderResults()}
  if(e.target.id==='filter-agency'){
    if(state.agency){state.agency='';state.visibleCount=30;renderResults()}
    showAgencyChoices(e.target.value);
  }
}
function handleChange(e){
  const m={'filter-topic':'topic','filter-chamber':'chamber','filter-stage':'stage','filter-outlook':'outlook','filter-action':'action'};
  if(m[e.target.id]){state[m[e.target.id]]=e.target.value;state.visibleCount=30;renderResults();return}
  if(e.target.id==='sort-order'){state.sort=Object.keys(SORTS).find(k=>SORTS[k]===e.target.value)||'newest';state.visibleCount=30;renderResults();return}
  if(e.target.id==='import-file'&&e.target.files?.length)importFile(e.target.files[0]);
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
      Object.assign(state,{topic:'',agency:'',chamber:'',stage:'',action:'',outlook:'',query:'',visibleCount:30});setView('all');
    }catch(renderError){Object.assign(state,previous);setView(previous.view);throw renderError}
    location.hash='all';toast(`Imported ${valid.length} bills`);
  }catch(err){toast(`Import failed: ${err.message}`)}
}

init();
