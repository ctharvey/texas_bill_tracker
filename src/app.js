import {AGENCIES, AGENCY_NAME, autoTagBill, assessHearing, authorInfluence, officialUrl} from './taxonomy.js';

const $ = (selector, root=document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {view:'all',bills:[],watch:new Set(),query:'',topic:'',agency:'',chamber:'',stage:'',outlook:'',sort:'newest',onlyWatch:false,visibleCount:30,meta:null};
const storageKey = 'tx-bill-atlas-watch-90r';
const STORAGE_OK = (()=>{try{localStorage.setItem('__txb_test','1');localStorage.removeItem('__txb_test');return true}catch{return false}})();
try{state.watch=new Set(JSON.parse(localStorage.getItem(storageKey)||'[]'))}catch{}

const dateText = iso => iso ? new Date(`${String(iso).slice(0,10)}T12:00:00Z`).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}) : 'Not available';
const stampText = iso => iso ? new Date(iso).toLocaleString('en-US',{dateStyle:'medium',timeStyle:'short',timeZone:'America/Chicago'})+' CT' : 'Unknown';
const unique = a => [...new Set(a)];

function normalized(raw){
  const key=String(raw.id||raw.number||raw.bill_number||'').replace(/\s/g,'').toUpperCase();
  if(!/^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/.test(key))return null;
  const number=key.replace(/^(HJR|SJR|HCR|SCR|HB|SB|HR|SR)/,'$1 ');
  const chamber=key.startsWith('H')?'House':'Senate';
  const bill={...raw,id:key,number,chamber,
    title:raw.title||raw.description||raw.caption||'No caption available',
    caption:raw.caption||raw.description||raw.title||'',
    author:raw.author||raw.primary_author||'Author not yet available',
    author_profile:raw.author_profile||state.meta?.author_profiles?.[raw.author||raw.primary_author]||{},
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
    // Repository JSON is the source of truth for deployed readers. If GitHub
    // is unreachable, fall back to the last successfully deployed snapshot.
    const local=location.hostname==='localhost'||location.hostname==='127.0.0.1'||location.hostname==='terminal.local';
    const urls=local?['./data/bills.json','https://raw.githubusercontent.com/ctharvey/texas_bill_tracker/main/data/bills.json']:[
      'https://raw.githubusercontent.com/ctharvey/texas_bill_tracker/main/data/bills.json','./data/bills.json'
    ];
    let data,loadedFrom;
    for(const url of urls){
      try{
        const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(7500)});
        if(!response.ok)throw Error(`HTTP ${response.status}`);
        const candidate=await response.json();
        if(candidate.session!=='90R'||!Array.isArray(candidate.bills)||!candidate.bills.length)throw Error('Invalid bill snapshot');
        data=candidate;loadedFrom=url;break;
      }catch(error){console.warn(`Bill source unavailable: ${url}`,error.message)}
    }
    if(!data)throw Error('Unable to load bill snapshot');
    data.loaded_from=loadedFrom.includes('raw.githubusercontent.com')?'GitHub source snapshot':'Bundled fallback snapshot';
    state.meta=data;
    state.bills=(data.bills||[]).map(normalized).filter(Boolean);
  }catch(error){
    state.meta={data_mode:'unavailable',coverage_note:'The current dataset could not be loaded. Use Data & imports to load a local CSV or JSON file.'};
  }
  document.addEventListener('click',handleClick);
  document.addEventListener('change',handleChange);
  document.addEventListener('input',handleInput);
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeDrawer()});
  $('#drawer-scrim').addEventListener('click',closeDrawer);
  window.addEventListener('hashchange',()=>setView(location.hash.slice(1)||'all'));
  setView(['all','watchlist','agencies','method','data'].includes(location.hash.slice(1))?location.hash.slice(1):'all');
}

function setView(view){
  state.view=view;
  document.querySelectorAll('[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===view));
  const heads={all:['See what’s moving.<br><em>Know what it changes.</em>','Track legislation by policy, affected agency, author influence, and its path through the Capitol.'],watchlist:['Your watchlist.<br><em>Keep the signal.</em>','Bills you are following on this device, with a clear view of their movement.'],agencies:['Follow the agencies.<br><em>Not just the bills.</em>','Explore where legislation might land across Texas government.'],method:['The scoring method.<br><em>No black boxes.</em>','Signals and uncertainty are displayed separately from verified legislative actions.'],data:['Behind the tracker.<br><em>Follow the source.</em>','Understand coverage, refreshes, and how to load or export bill data.']};
  $('#page-title').innerHTML=heads[view][0];$('#page-subtitle').textContent=heads[view][1];
  $('#overview').hidden=!['all','watchlist'].includes(view);
  renderNotice();renderOverview();renderContent();
}

function renderNotice(){
  const curated=state.meta?.data_mode==='curated';
  const unavailable=state.meta?.data_mode==='unavailable';
  const copy=unavailable?'<strong>Dataset unavailable.</strong> '+esc(state.meta.coverage_note):curated?'<strong>Curated opening-day snapshot.</strong> This is a selection of confirmed filings, not the full 90R docket. Automated official bulk-feed sync is prepared but not yet verified.':'<strong>Bulk-data snapshot.</strong> Derived from the legislature’s published files; changes may lag the official record.';
  $('#source-notice').innerHTML=`<span class="notice-icon">${curated?'◷':unavailable?'!':'✓'}</span><div>${copy} <a href="#data" data-view="data">Coverage & sources →</a></div>`;
  $('#footer-timestamp').textContent=`Snapshot: ${stampText(state.meta?.generated_at)}`;
}

function renderOverview(){
  const bills=state.view==='watchlist'?state.bills.filter(b=>state.watch.has(b.id)):state.bills;
  const agencies=unique(bills.flatMap(b=>b.agencies.map(a=>a.id))).filter(id=>id!=='all-state-agencies').length;
  const scheduled=bills.filter(b=>assessHearing(b).level>=3).length;
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
}

function renderContent(){
  const el=$('#dynamic-content');
  if(state.view==='all'||state.view==='watchlist')el.innerHTML=explorerMarkup();
  else if(state.view==='agencies')el.innerHTML=agenciesMarkup();
  else if(state.view==='method')el.innerHTML=methodMarkup();
  else el.innerHTML=dataMarkup();
  if(state.view==='all'||state.view==='watchlist')renderResults();
}

function options(values,selected,placeholder){return `<option value="">${esc(placeholder)}</option>`+values.map(v=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(v)}</option>`).join('')}

function explorerMarkup(){
  const topics=unique(state.bills.flatMap(b=>b.topics)).sort();
  const agencies=unique(state.bills.flatMap(b=>b.agencies.map(a=>a.id))).sort((a,b)=>(AGENCY_NAME[a]||a).localeCompare(AGENCY_NAME[b]||b));
  const agencyOpts=agencies.map(id=>`<option value="${esc(id)}" ${state.agency===id?'selected':''}>${esc(AGENCY_NAME[id]||id)}</option>`).join('');
  const popular=['Education','Healthcare','Elections','Taxes','Immigration','Data centers','Local government','Energy & utilities'];
  return `<div class="section-head"><div><div class="section-overline">EXPLORE LEGISLATION</div><h2>${state.view==='watchlist'?'Watched bills':'Bill explorer'}</h2></div><span class="subtitle">90R · House & Senate · All bill types</span></div>
    <div class="explorer-controls"><div class="search-row"><div class="search-wrap"><input aria-label="Search bills" id="bill-search" placeholder="Search bill number, author, subject, or keyword…" value="${esc(state.query)}" autocomplete="off"></div><button class="outline-button" id="clear-filters">Clear filters</button><button class="primary-button" id="export-csv">↓ Export results</button></div>
    <div class="filter-row"><select aria-label="Policy area" id="filter-topic">${options(topics,state.topic,'All policy areas')}</select><select aria-label="Affected agency" id="filter-agency"><option value="">All affected agencies</option>${agencyOpts}</select><select aria-label="Chamber" id="filter-chamber">${options(['House','Senate'],state.chamber,'Both chambers')}</select><select aria-label="Stage" id="filter-stage">${options(['Filed','Referred','Scheduled','Heard','Advanced','Passed','Enacted'],state.stage,'Any stage')}</select><select aria-label="Hearing status" id="filter-outlook">${options(['Not rated','Referred','Scheduled','Heard'],state.outlook,'Hearing status')}</select><button class="check-filter ${state.onlyWatch?'selected':''}" id="watch-filter">☆ Watched only</button></div></div>
    <div class="topic-strip" aria-label="Quick topic filters"><button class="topic-chip ${state.topic===''?'selected':''}" data-topic="">All topics</button>${popular.map(t=>`<button class="topic-chip ${state.topic===t?'selected':''}" data-topic="${esc(t)}">${esc(t)}</button>`).join('')}</div>
    <div class="results-header"><div><strong id="result-count">—</strong><span id="result-note"></span></div><select id="sort-order" aria-label="Sort bills">${options(['Newest filed','Bill number','Most agencies','Hearing progress','Author influence'],({'newest':'Newest filed','number':'Bill number','agencies':'Most agencies','hearing':'Hearing progress','influence':'Author influence'})[state.sort],'Sort by')}</select></div><div class="bill-list" id="bill-list"></div><div class="explorer-bottom" id="results-bottom"></div>`;
}

function filteredBills(){
  let list=state.bills.filter(b=>{
    if(state.view==='watchlist'&&!state.watch.has(b.id))return false;
    if(state.onlyWatch&&!state.watch.has(b.id))return false;
    if(state.topic&&!b.topics.includes(state.topic))return false;
    if(state.agency&&!b.agencies.some(a=>a.id===state.agency))return false;
    if(state.chamber&&b.chamber!==state.chamber)return false;
    if(state.outlook&&assessHearing(b).label!==state.outlook)return false;
    if(state.stage){const st=(b.status||'').toLowerCase();const outlook=assessHearing(b).label.toLowerCase();if(!st.includes(state.stage.toLowerCase())&&outlook!==state.stage.toLowerCase())return false}
    const q=state.query.trim().toLowerCase();
    return !q||[b.id,b.title,b.caption,b.author,b.last_action,...b.topics,...b.impacts,...b.agencies.map(a=>AGENCY_NAME[a.id]||a.id)].join(' ').toLowerCase().includes(q);
  });
  const sorters={newest:(a,b)=>(b.filed_at||'').localeCompare(a.filed_at||'')||a.id.localeCompare(b.id,undefined,{numeric:true}),number:(a,b)=>a.id.localeCompare(b.id,undefined,{numeric:true}),agencies:(a,b)=>b.agencies.length-a.agencies.length,hearing:(a,b)=>assessHearing(b).level-assessHearing(a).level,influence:(a,b)=>authorInfluence(b).level-authorInfluence(a).level};
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
  const agencyTags=b.agencies.slice(0,2).map(a=>`<span class="tag agency" title="${esc(a.reason||'')}">${esc((AGENCY_NAME[a.id]||a.id).replace(/^Texas /,'').replace(/ Department of /,' · '))}</span>`).join('');
  return `<article class="bill-card"><div class="bill-left"><div class="bill-head"><span class="bill-number">${esc(b.number)}</span><span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span>${influence.level?`<span class="influence-pill">◆ ${esc(influence.label)}</span>`:''}</div><h3 class="bill-title">${esc(b.title)}</h3><p class="bill-description">${esc(b.caption)}</p><div class="bill-tags">${b.topics.slice(0,3).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}${agencyTags}${b.agencies.length>2?`<span class="tag agency">+${b.agencies.length-2} agencies</span>`:''}</div><div class="bill-meta"><span>By <b>${esc(b.author)}</b></span><span>Filed ${dateText(b.filed_at)}</span><span>${b.agencies.length} agency ${b.agencies.length===1?'link':'links'}</span></div></div><div class="bill-right"><button class="watch-button" data-watch="${b.id}" aria-label="${watched?'Remove from':'Add to'} watchlist" aria-pressed="${watched}">${watched?'★':'☆'}</button><div><div class="outlook-label">Hearing progress</div><div class="outlook-value">${esc(h.label)}</div><button class="bill-open" data-open="${b.id}">Bill details →</button></div></div></article>`;
}

function agenciesMarkup(){
  const counts=new Map();for(const b of state.bills)for(const a of b.agencies)counts.set(a.id,(counts.get(a.id)||0)+1);
  const agencies=AGENCIES.slice().sort((a,b)=>(counts.get(b.id)||0)-(counts.get(a.id)||0)||a.name.localeCompare(b.name));
  return `<div class="section-head"><div><div class="section-overline">IMPACT DIRECTORY</div><h2>Texas state agencies</h2></div><span class="subtitle">${counts.size} with possible links in this snapshot</span></div><div class="info-callout"><strong>Why an agency index?</strong> One bill can change the work of several state agencies. “Direct” means the supplied material names an agency; “possible” means an inferred policy connection. An agency absent from a caption is not proof it is unaffected—full bill text review is needed for comprehensive coverage.</div><div class="agency-grid" style="margin-top:18px">${agencies.map(a=>`<button class="agency-card" data-agency-pick="${esc(a.id)}"><span class="agency-code">${esc(a.id.toUpperCase())}</span><strong>${esc(a.name)}</strong><span class="hits">${counts.get(a.id)||0} ${counts.get(a.id)===1?'bill':'bills'} in snapshot →</span></button>`).join('')}</div>`;
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
  return `<div class="section-head"><div><div class="section-overline">DATA PROVENANCE</div><h2>Source, coverage & export</h2></div></div><div class="subpage-card"><div class="data-field"><span class="data-label">Legislative session</span><span class="data-value">90R · 2027</span></div><div class="data-field"><span class="data-label">Loaded records</span><span class="data-value">${state.bills.length}</span></div><div class="data-field"><span class="data-label">Snapshot mode</span><span class="data-value">${esc(state.meta?.data_mode||'Unknown')}</span></div><div class="data-field"><span class="data-label">Read from</span><span class="data-value">${esc(state.meta?.loaded_from||'User import')}</span></div><div class="data-field"><span class="data-label">Last generated</span><span class="data-value">${stampText(state.meta?.generated_at)}</span></div><p style="font-size:12px;color:#748697;line-height:1.65;margin:18px 0">${esc(state.meta?.coverage_note||'Coverage is not guaranteed complete.')}</p><div class="info-callout"><strong>Official source policy:</strong> The Texas Legislative Council publishes bulk material through anonymous FTP and discourages data mining the public Legislature Online pages. The project includes an updater for the official bulk files, with snapshot validation so a failed import cannot silently replace data with an empty result. <a class="text-link" href="https://capitol.texas.gov/billlookup/filedownloads.aspx" target="_blank" rel="noopener noreferrer">Read the source policy ↗</a></div><div class="data-actions"><button class="primary-button" id="import-trigger">↑ Import CSV or JSON</button><button class="outline-button" id="export-csv">↓ Export current results</button><a class="outline-button" href="https://github.com/ctharvey/texas_bill_tracker" target="_blank" rel="noopener noreferrer">Source code ↗</a><input type="file" id="import-file" accept=".csv,.json,text/csv,application/json" hidden></div><p style="font-size:11px;color:#91a0ad;margin:14px 0 0">Imports are temporary to this browser session; they do not alter the public dataset. Watchlist stars are stored on this device.</p></div>`;
}

function showDrawer(id){
  const b=state.bills.find(b=>b.id===id);if(!b)return;
  const h=assessHearing(b),influence=authorInfluence(b);
  const agencyRows=b.agencies.length?b.agencies.map(a=>`<div class="agency-row"><div><strong>${esc(AGENCY_NAME[a.id]||a.id)}</strong><p>${esc(a.reason||'Relationship not yet annotated')}</p></div><span class="confidence ${a.relationship==='direct'?'direct':''}">${a.relationship==='direct'?'Direct':'Possible'}</span></div>`).join(''):'<p>No agency has been tagged yet. This does not establish that none are affected.</p>';
  const watched=state.watch.has(b.id);
  $('#detail-drawer').innerHTML=`<div class="drawer-top"><span class="drawer-number">90R / ${esc(b.number)}</span><button class="drawer-close" id="drawer-close" aria-label="Close bill details">×</button></div><div class="drawer-pills"><span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span></div><h2 style="margin-top:14px">${esc(b.title)}</h2><p class="drawer-caption">${esc(b.caption)}</p><div class="drawer-pills">${b.topics.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div><div class="drawer-meta-grid"><div><small>Filed by</small><strong>${esc(b.author)}</strong></div><div><small>Filed on</small><strong>${dateText(b.filed_at)}</strong></div><div><small>Most recent action</small><strong>${esc(b.last_action)}</strong></div><div><small>Hearing status</small><strong>${esc(h.label)}</strong></div></div><section class="drawer-section"><h3>Hearing progress & evidence</h3><div class="evidence-card"><strong>${esc(h.label)} · ${h.level===0?'No rating yet':'Verified procedural signal'}</strong><p>${esc(h.detail)}</p><ul>${h.facts.map(f=>`<li>${esc(f)}</li>`).join('')}</ul></div></section><section class="drawer-section"><h3>Author prominence</h3><div class="evidence-card"><strong>${esc(influence.label)}</strong><p>${esc(influence.factors.join(' · '))}</p>${b.author_profile?.source?`<p><a class="text-link" href="${esc(b.author_profile.source)}" target="_blank" rel="noopener noreferrer">Verified member biography ↗</a></p>`:''}</div></section><section class="drawer-section"><h3>Potentially affected agencies (${b.agencies.length})</h3><p>All known tags are listed. Possible links are model/rule inferences, not confirmed legal obligations.</p>${agencyRows}</section><section class="drawer-section"><h3>Types of impact</h3><div class="drawer-pills">${b.impacts.length?b.impacts.map(t=>`<span class="tag related">${esc(t)}</span>`).join(''):'<span class="tag">Pending analysis</span>'}</div></section>${b.constituencies?.length?`<section class="drawer-section"><h3>People and institutions affected</h3><div class="drawer-pills">${b.constituencies.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></section>`:''}<section class="drawer-section"><h3>Source & verification</h3><p>Review the bill history and latest text before relying on any classification. <a class="text-link" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Texas Legislature Online ↗</a></p></section><div class="drawer-actions"><a class="primary-button" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Read official bill ↗</a><button class="outline-button" data-watch="${b.id}">${watched?'★ Remove from watchlist':'☆ Follow this bill'}</button></div>`;
  $('#detail-drawer').hidden=false;$('#drawer-scrim').hidden=false;document.body.style.overflow='hidden';$('#drawer-close').focus();
}

function closeDrawer(){$('#detail-drawer').hidden=true;$('#drawer-scrim').hidden=true;document.body.style.overflow=''}
function toast(message){const t=$('#toast');t.textContent=message;t.classList.add('visible');clearTimeout(toast.timer);toast.timer=setTimeout(()=>t.classList.remove('visible'),2500)}

function handleClick(e){
  const nav=e.target.closest('[data-view]');if(nav){e.preventDefault();location.hash=nav.dataset.view;setView(nav.dataset.view);return}
  const open=e.target.closest('[data-open]');if(open){showDrawer(open.dataset.open);return}
  const star=e.target.closest('[data-watch]');if(star){const id=star.dataset.watch;state.watch.has(id)?state.watch.delete(id):state.watch.add(id);if(STORAGE_OK)localStorage.setItem(storageKey,JSON.stringify([...state.watch]));renderOverview();if(state.view==='all'||state.view==='watchlist')renderResults();if(!$('#detail-drawer').hidden)showDrawer(id);toast(state.watch.has(id)?`${id} added to your watchlist`:`${id} removed from your watchlist`);return}
  const topic=e.target.closest('[data-topic]');if(topic){state.topic=topic.dataset.topic;state.visibleCount=30;renderContent();return}
  const pick=e.target.closest('[data-agency-pick]');if(pick){state.agency=pick.dataset.agencyPick;state.visibleCount=30;state.view='all';location.hash='all';setView('all');return}
  if(e.target.closest('#clear-filters')){Object.assign(state,{query:'',topic:'',agency:'',chamber:'',stage:'',outlook:'',sort:'newest',onlyWatch:false,visibleCount:30});renderContent();return}
  if(e.target.closest('#watch-filter')){state.onlyWatch=!state.onlyWatch;state.visibleCount=30;renderContent();return}
  if(e.target.closest('#load-more')){state.visibleCount+=30;renderResults();return}
  if(e.target.closest('#export-csv')){exportCsv();return}
  if(e.target.closest('#import-trigger')){$('#import-file').click();return}
  if(e.target.closest('#drawer-close')){closeDrawer();return}
}

function handleInput(e){if(e.target.id==='bill-search'){state.query=e.target.value;state.visibleCount=30;renderResults()}}
function handleChange(e){
  const m={'filter-topic':'topic','filter-agency':'agency','filter-chamber':'chamber','filter-stage':'stage','filter-outlook':'outlook'};
  if(m[e.target.id]){state[m[e.target.id]]=e.target.value;state.visibleCount=30;renderResults();return}
  if(e.target.id==='sort-order'){state.sort=({'Newest filed':'newest','Bill number':'number','Most agencies':'agencies','Hearing progress':'hearing','Author influence':'influence'})[e.target.value]||'newest';state.visibleCount=30;renderResults();return}
  if(e.target.id==='import-file'&&e.target.files?.length)importFile(e.target.files[0]);
}

function csvCell(value){const s=String(value??'');return /[",\n\r]/.test(s)?`"${s.replaceAll('"','""')}"`:s}
function exportCsv(){
  const rows=[['id','title','author','chamber','status','filed_at','hearing_progress','policy_areas','agencies','agency_relationships','official_url'],...filteredBills().map(b=>[b.id,b.title,b.author,b.chamber,b.status,b.filed_at,assessHearing(b).label,b.topics.join('|'),b.agencies.map(a=>AGENCY_NAME[a.id]||a.id).join('|'),b.agencies.map(a=>a.relationship||'related').join('|'),officialUrl(b)])];
  const blob=new Blob([rows.map(row=>row.map(csvCell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});const u=URL.createObjectURL(blob);const a=document.createElement('a');a.href=u;a.download='texas-90R-bills.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
}

function parseCsv(text){
  const rows=[];let row=[],field='',quoted=false;
  for(let i=0;i<text.length;i++){const c=text[i];if(quoted){if(c==='"'&&text[i+1]==='"'){field+='"';i++}else if(c==='"')quoted=false;else field+=c}else if(c==='"')quoted=true;else if(c===','){row.push(field);field=''}else if(c==='\n'){row.push(field.replace(/\r$/,''));rows.push(row);row=[];field=''}else field+=c}
  if(field||row.length){row.push(field);rows.push(row)}
  const headers=rows.shift()?.map(s=>s.trim().replace(/^\uFEFF/,'').toLowerCase())||[];
  return rows.filter(row=>row.some(Boolean)).map(row=>Object.fromEntries(headers.map((key,i)=>[key,row[i]||'']))).map(o=>({...o,topics:o.topics?o.topics.split('|'):[],agencies:o.agencies?o.agencies.split('|'):[],impacts:o.impacts?o.impacts.split('|'):[]}));
}

async function importFile(file){
  try{
    if(file.size>15*1024*1024)throw Error('Select a file smaller than 15 MB');
    const contents=await file.text();const data=file.name.toLowerCase().endsWith('.csv')?parseCsv(contents):JSON.parse(contents);
    const rows=Array.isArray(data)?data:data.bills;
    if(!Array.isArray(rows))throw Error('Expected an array of bills or an object with a bills array');
    const valid=rows.map(normalized).filter(Boolean);
    if(!valid.length)throw Error('No valid Texas bill numbers found');
    state.bills=valid;state.meta={session:'90R',data_mode:'local import',generated_at:new Date().toISOString(),coverage_note:`Local file: ${file.name}. Imported rows are visible only during this session.`};
    Object.assign(state,{topic:'',agency:'',chamber:'',stage:'',outlook:'',query:'',visibleCount:30});setView('all');location.hash='all';toast(`Imported ${valid.length} bills`);
  }catch(err){toast(`Import failed: ${err.message}`)}
}

init();
