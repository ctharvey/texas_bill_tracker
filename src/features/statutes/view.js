// Statutes in the app: the index and section files, the bill page's "Laws this bill changes" list, the section page
// with its side-by-side comparison, and the explorer's section-search hint. Rerenders come from app.js as parameters.
import {state} from '../../core/state.js';
import {$, esc} from '../../core/dom.js';
import {timeoutSignal, httpError} from '../../core/net.js';
import {buildHash} from '../../prefs.js';
import {lastActionInfo, openLinkHtml} from '../../taxonomy.js';
import {STATUTE_KINDS, statuteFile, statuteLabel, officialStatuteUrl, validStatuteIndex, validStatuteSection, statutesByBill, compareLaw, currentLaw, groupStatuteEntries} from './model.js';

// ---- Statutes: which sections of Texas law each bill changes, and the versions side by side ----
// The index (live/statutes/index.json) is optional; without it the drawer list, statute pages and section search hide.
const BROAD_BILL=25;  // A bill changing more sections than this is "broad"; its versions sort after focused bills.
let statutesLoad=null,statuteBills=new Map();
const statuteDocs=new Map();  // key -> section document, 'loading' or 'error'
export function loadStatutes({renderContent,renderResults}){
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
    if(state.openBill)fillDrawerStatutes(state.openBill);
  })());
}
function statuteDoc(key,renderContent){
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

export function statuteMarkup({renderContent,billHref}){
  const key=state.statuteKey;
  const head=(title,sub='90th Legislature · every bill that changes it')=>`<div class="section-head"><div><div class="section-overline">TEXAS LAW</div><h2>${title}</h2></div><span class="subtitle">${sub}</span></div>`;
  if(!key)return `${head('Section not found')}<div class="info-callout callout-warn">This address does not name a section of Texas law. Open one from a bill's "Laws this bill changes" list, or search the explorer for a section number such as 48.160.</div>`;
  if(!state.statutes)return state.statutesFailed?`${head(esc(key))}<div class="info-callout callout-warn">The list of laws each bill changes is not available right now. Try again later.</div>`:`${head(esc(key))}<p class="near-hint">Loading…</p>`;
  const label=statuteLabel(key,state.statutes.codes),info=state.statutes.sections[key];
  const official=`<a class="text-link" href="${esc(officialStatuteUrl(key))}" target="_blank" rel="noopener noreferrer">Current law on statutes.capitol.texas.gov ↗</a>`;
  if(!info)return `${head(esc(label))}<div class="info-callout">No bill in this snapshot changes ${esc(label)}. ${official}</div>`;
  const doc=statuteDoc(key,renderContent);
  const title=head(info.h?esc(titleCase(info.h)):esc(label));
  if(doc==='loading')return `${title}<p class="near-hint">Loading the bills' versions…</p>`;
  if(doc==='error')return `${title}<div class="info-callout callout-warn">The versions of this section could not be loaded. ${official}</div>`;
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
export function statuteHintMarkup(keys){
  if(!keys.length)return '';
  return `<div class="info-callout statute-hint">Bills that change ${keys.map(statuteLink).join(', ')} are included. Open ${keys.length===1?'it':'one'} to compare their versions side by side.</div>`;
}
