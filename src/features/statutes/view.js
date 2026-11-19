// Statutes in the app: the index and section files, the bill page's "Laws this bill changes" list, the section page
// with its side-by-side comparison, and the explorer's section-search hint. Redraws go through core/router.js.
import {state} from '../../core/state.js';
import {$, esc} from '../../core/dom.js';
import {timeoutSignal, httpError} from '../../core/net.js';
import {buildHash} from '../../prefs.js';
import {lastActionInfo, openLinkHtml} from '../../taxonomy.js';
import {STATUTE_KINDS, statuteFile, statuteLabel, officialStatuteUrl, validStatuteIndex, validStatuteSection, statutesByBill, compareLaw, currentLaw, groupStatuteEntries, lawFollowOf, isLawFollowQuery} from './model.js';
import {renderContent, renderResults, refreshHome} from '../../core/router.js';
import {billHref} from '../../core/links.js';

// ---- Statutes: which sections of Texas law each bill changes, and the versions side by side ----
// The index (live/statutes/index.json) is optional; without it the drawer list, statute pages and section search hide.
const BROAD_BILL=25;  // A bill changing more sections than this is "broad"; its versions sort after focused bills.
let statutesLoad=null,statuteBills=new Map();
const statuteDocs=new Map();  // key -> section document, 'loading' or 'error'
export function loadStatutes(){
  return statutesLoad||(statutesLoad=(async()=>{
    try{
      const r=await fetch('./live/statutes/index.json',{cache:'no-cache',signal:timeoutSignal(15000)});
      if(!r.ok)throw httpError(r);
      const index=await r.json();
      if(!validStatuteIndex(index))throw Error('Unrecognized statute index');
      state.statutes=index;statuteBills=statutesByBill(index);
    }catch(error){state.statutes=null;state.statutesFailed=true;console.warn('Statute index unavailable',error.message)}
    // Views drawn before it arrived: section search results, saved-search counts, the statute page, the open drawer.
    if(state.view==='all'||state.view==='watchlist')renderResults();
    else if(state.view==='following'||state.view==='statute')renderContent();
    else if(state.view==='home')refreshHome();  // A followed law's new bills count only once the index is here.
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
      if(!r.ok)throw httpError(r);
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

export function fillDrawerStatutes(id){
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
// Left is current law unless the reader picked another version; right is the bill picked in the bar.
function lawCompareMarkup(options,right){
  const c=state.statuteCompare;
  const left=options.find(o=>o.id===c.left)||options[0];
  const select=`<label class="law-pick"><span>Left</span><select data-law-side="left">${options.map(o=>`<option value="${esc(o.id)}" ${o===left?'selected':''}>${esc(o.label)}</option>`).join('')}</select></label>`;
  const rows=left===right?[]:compareLaw({name:left.name,units:left.units,partial:left.partial},{name:right.name,units:right.units,partial:right.partial});
  const label=l=>l==='head'?'Heading':l===''?'Text':`(${l})`;
  const changed=rows.filter(r=>!r.same).length;
  // data-name labels each cell when the columns stack on a phone.
  const cell=(words,note,cls,name)=>words?`<div class="law-cell" data-name="${esc(name)}">${lawWords(words,cls)}</div>`:`<div class="law-cell law-missing" data-name="${esc(name)}">${esc(note)}</div>`;
  const body=rows.map(r=>`<div class="law-row${r.same?' law-same':''}"><div class="law-label">${esc(label(r.label))}${r.same?' · same':''}</div>${cell(r.left,r.leftNote,'law-out',left.name)}${cell(r.right,r.rightNote,'law-in',right.name)}</div>`).join('');
  const show=state.statuteShow||'both';
  return `<section class="law-compare-wrap"><h3>${left.id==='law'?'Current law':esc(left.name)} → ${esc(right.name)}</h3>
    <div class="law-picks">${select}</div>
    <p class="law-legend"><mark class="law-out">Highlighted on the left</mark> is wording only the left has; <mark class="law-in">highlighted on the right</mark> is wording only the right has. ${left===right?'Pick a different version for the left.':`${changed} of ${rows.length} ${rows.length===1?'part differs':'parts differ'}.`}${rows.some(r=>r.approximate)?' Some parts are too long to compare word by word and are marked whole.':''}</p>
    <div class="law-toggle" role="group" aria-label="Columns to show">${[['both','Both'],['left','Left'],['right','Right']].map(([v,t])=>`<button type="button" class="outline-button${show===v?' active':''}" data-law-show="${v}" aria-pressed="${show===v}">${t}</button>`).join('')}</div>
    <div class="law-compare" data-show="${show}"><div class="law-row law-head"><div class="law-label"></div><div class="law-cell">${esc(left.label)}</div><div class="law-cell">${esc(right.label)}</div></div>${body}</div></section>`;
}
// One version on its own: a proposed new section, or an amendment with no current law to set it against.
function lawSingleMarkup(title,units,note=''){
  return `<section class="law-compare-wrap"><h3>${esc(title)}</h3>${note?`<p class="law-legend">${note}</p>`:''}<div class="law-single">${units.map(u=>`<p>${esc(u.text).replaceAll('\n','<br>')}</p>`).join('')}</div></section>`;
}
// "Sec. 545.4575. EMERGENCY RESPONSE PROCEDURES." -> "Emergency Response Procedures"
const unitHeading=units=>{const h=units.find(u=>u.label==='head')?.text||'';return titleCase(h.replace(/^Sec\.\s*[0-9A-Za-z.]+?\.\s+/,'').replace(/\.$/,''))};
const KIND_WORDS={amend:'Amends it',add:'Proposes a new section',repeal:'Repeals it'};

// Same limits the law share page and feed state (scripts/build_feeds.py LAW_LIMITS).
const LAW_LIMITS='Bills are matched to sections automatically from their text and can be missed: changes to a whole chapter at once, renumbering and unusual wording. No bill listed here does not mean no bill changes this section.';
export const lawFeedHref=key=>`./live/feeds/law/${encodeURIComponent(key.replace(' ','-'))}.xml`;
// Follow (a saved search for the section) and, once a bill changes it, the section's RSS feed.
function lawToolsMarkup(key,label,hasFeed){
  if(!isLawFollowQuery(key))return '';  // Only codes the parser tracks can ever gain bills.
  const on=!!lawFollowOf(state.searches,key);
  const button=`<button class="${on?'outline-button following':'primary-button'} follow-button" data-follow-law="${esc(key)}" data-follow-label="${esc(label)}" aria-pressed="${on}">${on?'✓ Following':'+ Follow this law'}</button>`;
  const feed=hasFeed?`<a class="outline-button" href="${esc(lawFeedHref(key))}" target="_blank" rel="noopener noreferrer">RSS feed</a>`:'';
  return `<div class="tools-row law-tools">${button}${feed}</div>`;
}

export function statuteMarkup(){
  const key=state.statuteKey;
  const head=(title,sub='90th Legislature · every bill that changes it')=>`<div class="section-head"><div><div class="section-overline">TEXAS LAW</div><h2>${title}</h2></div><span class="subtitle">${sub}</span></div>`;
  if(!key)return `${head('Section not found')}<div class="info-callout callout-warn">This address does not name a section of Texas law. Open one from a bill's "Laws this bill changes" list, or search the explorer for a section number such as 48.160.</div>`;
  // Following needs only the key, so the button is there while the index loads and when it failed.
  if(!state.statutes){const label=statuteLabel(key);return state.statutesFailed?`${head(esc(label))}${lawToolsMarkup(key,label,false)}<div class="info-callout callout-warn">The list of laws each bill changes is not available right now. Try again later.</div>`:`${head(esc(label))}${lawToolsMarkup(key,label,false)}<p class="near-hint">Loading…</p>`}
  const label=statuteLabel(key,state.statutes.codes),info=state.statutes.sections[key];
  const official=`<a class="text-link" href="${esc(officialStatuteUrl(key))}" target="_blank" rel="noopener noreferrer">Current law on statutes.capitol.texas.gov ↗</a>`;
  const tools=lawToolsMarkup(key,label,!!info);
  if(!info)return `${head(esc(label))}${tools}<div class="info-callout">No bill in this snapshot changes ${esc(label)}. Follow it to hear when one does. ${official}</div><p class="tools-note">${LAW_LIMITS}</p>`;
  const doc=statuteDoc(key);
  const loadingTitle=head(info.h?esc(titleCase(info.h)):esc(label))+tools;
  if(doc==='loading')return `${loadingTitle}<p class="near-hint">Loading the bills' versions…</p>`;
  if(doc==='error')return `${loadingTitle}<div class="info-callout callout-warn">The versions of this section could not be loaded. ${official}</div>`;
  if(state.statuteCompare?.key!==key)state.statuteCompare={key,left:null,right:null};
  const groups=groupStatuteEntries(doc.entries,id=>(state.statutes.bills[id]?.n||0)>BROAD_BILL);
  const options=lawOptions(doc,groups),law=options.find(o=>o.id==='law');
  const gid=g=>g.entries[0].bill,names=g=>g.entries.map(e=>billNumber(e.bill)).join(' = ');
  // The bar's pick, else the first focused amendment, else the first version with wording.
  const chosen=groups.find(g=>gid(g)===state.statuteCompare.right)||groups.find(g=>g.kind==='amend'&&!g.broad&&g.units.length)
    ||groups.find(g=>g.kind!=='repeal'&&g.units.length)||groups[0];
  // Every bill adds a section with this number and none quotes current wording: it is not law yet.
  const proposed=!law&&groups.every(g=>g.kind==='add');
  const count=groups.reduce((n,g)=>n+g.entries.length,0);
  const version=g=>g.entries[0].version_name||g.entries[0].version;
  let main='';
  if(chosen?.kind==='repeal')main=law?lawSingleMarkup(`Current law · ${names(chosen)} would repeal it`,law.units,`${esc(names(chosen))} removes this section; this is the wording it would remove, as the bills quote it.`)
    :`<div class="info-callout">${esc(names(chosen))} would repeal this section. ${official}</div>`;
  else if(chosen&&!chosen.units.length)main=`<div class="info-callout">The wording of ${esc(names(chosen))} for this section could not be read. Open the bill to see its text.</div>`;
  else if(chosen?.kind==='amend'&&law)main=lawCompareMarkup(options,options.find(o=>o.id===gid(chosen)));
  else if(chosen)main=lawSingleMarkup(`${names(chosen)} · ${chosen.kind==='add'?'proposed new section':'amended'} · ${version(chosen)}`,chosen.units,
    chosen.kind==='add'?(proposed?'':'This bill adds a different section with the same number; it does not change the current section.')
      :`The bills do not quote the current wording, so there is nothing to set this against. ${official}`);
  const card=g=>{
    const e=g.entries[0],on=g===chosen,heading=g.kind==='add'?unitHeading(g.units):'';
    const bills=g.entries.map(x=>{const b=state.bills.find(y=>y.id===x.bill);return b?`${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)} <span class="law-status">${esc(lastActionInfo(b).label)}</span>`:esc(x.bill)}).join('<span class="law-same-text"> = </span>');
    const parts=g.kind==='amend'&&g.partial&&e.subsections?.length?`subsections ${e.subsections.map(s=>`(${s})`).join(', ')}`:g.kind==='amend'?'whole section':'';
    const notes=[KIND_WORDS[g.kind],version(g),parts,g.entries.length>1?'same wording':'',g.broad?`broad bill · changes ${state.statutes.bills[e.bill]?.n} sections`:''].filter(Boolean);
    const caption=g.entries.length===1?state.bills.find(b=>b.id===e.bill)?.caption:'';
    // The button covers the card (CSS), so the whole card picks it; the bill links sit above it.
    return `<li class="law-version${on?' active':''}${g.broad?' law-broad':''}"><div class="law-pick-bills">${bills}</div>${heading?`<strong class="law-pick-head">${esc(heading)}</strong>`:''}
      <button type="button" class="law-pick-btn" data-law-compare="${esc(gid(g))}" aria-pressed="${on}" aria-label="Show ${esc(names(g))}">${esc(notes.join(' · '))}</button>${caption?`<span class="law-caption">${esc(caption)}</span>`:''}</li>`;
  };
  const bar=`<aside class="law-bills" aria-label="Bills that change this section"><h3>${proposed?'Proposals':'Bills'} <span>${count}</span></h3><p class="near-hint">${groups.length>1?'Pick one to show its version.':'The only version so far.'}</p><ul class="law-versions">${groups.map(card).join('')}</ul></aside>`;
  const title=proposed?head(groups.length===1&&info.h?esc(titleCase(info.h)):esc(label),'Proposed new section · not in current law yet')+tools:loadingTitle;
  const intro=proposed?`<div class="info-callout law-intro"><p>This section is not in current law. ${count===1?'One bill proposes':`${count} bills propose`} a new section with this number${groups.length>1?'. Bills drafted separately can pick the same next number for unrelated subjects, so each version is shown on its own':''}.</p><p>${LAW_LIMITS}</p></div>`
    :`<div class="info-callout law-intro"><p>${law?'Current law is on the left, as the bills quote it; it can trail the official text if a later law changed it.':'Each bill quotes the wording it would change.'} ${official}</p><p>${LAW_LIMITS}</p></div>`;
  return `${title}${intro}<div class="law-layout"><div class="law-main">${main}</div>${bar}</div>`;
}

// Explorer: a search for a section number lists the bills that change it; this links to their comparison.
export function statuteHintMarkup(keys,query=''){
  // Exactly a section key ("PE 46.06", what a law follow saves): only that section's bills, never text matches.
  if(isLawFollowQuery(query)){
    if(!state.statutes)return `<div class="info-callout${state.statutesFailed?' callout-warn':''} statute-hint">${state.statutesFailed?`The list of laws each bill changes is not available right now, so the bills that change ${esc(query)} cannot be shown. Try again later.`:`Loading the bills that change ${esc(query)}…`}</div>`;
    return `<div class="info-callout statute-hint">Showing only bills that change ${statuteLink(query)}${state.statutes.sections[query]?'. Open it to compare their versions side by side.':': none yet.'}</div>`;
  }
  if(!keys.length)return '';
  return `<div class="info-callout statute-hint">Bills that change ${keys.map(statuteLink).join(', ')} are included. Open ${keys.length===1?'it':'one'} to compare their versions side by side.</div>`;
}
