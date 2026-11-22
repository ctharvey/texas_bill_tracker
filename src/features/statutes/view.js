// Statutes in the app: the index and section files, the bill page's "Laws this bill changes" list, the section page
// with its side-by-side comparison, and the explorer's section-search hint. Redraws go through core/router.js.
import {state} from '../../core/state.js';
import {$, esc} from '../../core/dom.js';
import {timeoutSignal, httpError} from '../../core/net.js';
import {buildUrl} from '../../prefs.js';
import {lastActionInfo, openLinkHtml} from '../../taxonomy.js';
import {STATUTE_KINDS, statuteFile, statuteLabel, officialStatuteUrl, validStatuteIndex, validStatuteSection, statutesByBill, compareLaw, currentLaw, lawCopyVersions, closestLawVersion, STATUTE_KEY, groupStatuteEntries, lawFollowOf, isLawFollowQuery,
  CHAPTER_KEY, isChapterKey, chapterOf, chapterWord, canonicalLawKey, lawEntries, lawChapterOutline, lawSearchTerms, lawSearchPrefixes, lawSearchMatches,
  parseStatuteQuery, parseChapterQuery, statuteKeysFor, LAW_CODES, LAW_CODE_NAMES, lawNamedMatches, lawTermMatcher} from './model.js';
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
    else if(['following','statute','laws','lawcode'].includes(state.view))renderContent();
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
// The section in this site's copy of current law (live/law/<CODE>/<chapter>.md), for sections the bills do not quote
// whole: {units, url, asOf}, 'loading' or 'missing'. Chapters are named by the number before the first dot.
const lawCopies=new Map();
function lawCopy(key){
  const have=lawCopies.get(key);
  if(have)return have;
  const m=STATUTE_KEY.exec(key);
  if(!m)return 'missing';
  lawCopies.set(key,'loading');
  (async()=>{
    let out='missing';
    const chapter=m[2].split('.')[0];
    // The Constitution's copy is one file per article, whose sections are numbered within it ("Sec. 1-b.").
    const number=m[1]==='CN'?m[2].slice(chapter.length+1):m[2];
    for(const c of new Set([chapter,chapter.toLowerCase()])){
      try{
        const url=`./live/law/${m[1]}/${encodeURIComponent(c)}.md`;
        const r=await fetch(url,{signal:timeoutSignal(15000)});
        if(!r.ok)continue;
        // Every section with this number: two laws can each have added one (CN 3.49-d-14).
        const versions=lawCopyVersions(await r.text(),number);
        if(!versions.length)continue;
        const when=Date.parse(r.headers.get('last-modified')||'');
        out={units:versions[0],versions,url,asOf:Number.isNaN(when)?'':new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'America/Chicago'}).format(when)};
        break;
      }catch(error){console.warn('Current law unavailable',key,error.message)}
    }
    lawCopies.set(key,out);
    if(state.view==='statute'&&state.statuteKey===key)renderContent();
  })();
  return 'loading';
}
// A chapter's outline from the law copy: {heading, sections, url}, 'loading' or 'missing'.
const lawChapters=new Map();
function lawChapter(key){
  const have=lawChapters.get(key);
  if(have)return have;
  const m=CHAPTER_KEY.exec(key);
  if(!m)return 'missing';
  lawChapters.set(key,'loading');
  (async()=>{
    let out='missing';
    for(const c of new Set([m[2],m[2].toLowerCase()])){
      try{
        const url=`./live/law/${m[1]}/${encodeURIComponent(c)}.md`;
        const r=await fetch(url,{signal:timeoutSignal(15000)});
        if(!r.ok)continue;
        const outline=lawChapterOutline(await r.text());
        if(!outline.sections.length)continue;
        out={...outline,url};
        break;
      }catch(error){console.warn('Current law unavailable',key,error.message)}
    }
    lawChapters.set(key,out);
    if(state.view==='statute'&&state.statuteKey===key)renderContent();
  })();
  return 'loading';
}
// Heading search: the prefix counts (live/law/search/index.json) once, then one prefix file per search.
let searchManifest=null;
const searchShards=new Map();  // prefix -> entries, 'loading' or 'error'
function redrawSearch(){if(state.view==='all'||state.view==='watchlist')renderResults()}
async function fetchJson(url){const r=await fetch(url,{signal:timeoutSignal(15000)});if(!r.ok)throw httpError(r);return r.json()}
// Keys bills are changing: every section in the index, its chapter, and chapters changed whole. Ranks search results.
let changedFor=null,changedSet=new Set();
export function lawChanged(key){
  if(!state.statutes)return false;
  if(changedFor!==state.statutes){changedFor=state.statutes;changedSet=new Set();
    for(const k of Object.keys(state.statutes.sections||{})){changedSet.add(k);const c=chapterOf(k);if(c)changedSet.add(c)}
    for(const k of Object.keys(state.statutes.chapters||{}))changedSet.add(k)}
  return changedSet.has(key);
}
// Laws whose heading has every search word, best first: [[key, heading]], 'loading', or null (no usable words, or
// unavailable). A term with aliases ("guns": firearm, handgun) can need more than one prefix file.
function lawSearch(terms){
  if(!terms.length)return null;
  if(!state.statutes&&!state.statutesFailed)loadStatutes();  // Ranks laws bills change first; redraws when it arrives.
  if(!searchManifest){
    searchManifest='loading';
    fetchJson('./live/law/search/index.json').then(m=>{searchManifest=m?.format==='texas-bill-law-search-v1'?m:'error'})
      .catch(error=>{searchManifest='error';console.warn('Law search unavailable',error.message)}).finally(redrawSearch);
  }
  if(searchManifest==='loading')return 'loading';
  if(searchManifest==='error')return null;
  const prefixes=lawSearchPrefixes(searchManifest,terms);
  if(!prefixes)return [];
  let loading=false;const entries=[];
  for(const prefix of prefixes){
    const shard=searchShards.get(prefix);
    if(!shard){
      searchShards.set(prefix,'loading');loading=true;
      fetchJson(`./live/law/search/${prefix}.json`).then(e=>searchShards.set(prefix,Array.isArray(e)?e:'error'))
        .catch(error=>{searchShards.set(prefix,'error');console.warn('Law search unavailable',error.message)}).finally(redrawSearch);
    }else if(shard==='loading')loading=true;
    else if(shard==='error')return null;
    else entries.push(...shard);
  }
  return loading?'loading':lawSearchMatches(entries,terms,lawChanged);
}
const statuteHref=key=>buildUrl('statute',{},{statute:key});
const billNumber=id=>state.bills.find(b=>b.id===id)?.number||id;
const SMALL_WORDS=new Set(['a','an','and','as','at','by','for','in','of','on','or','the','to','with','from','under']);
// "FUNDING FOR CERTAIN SCHOOLS" -> "Funding for Certain Schools"
const titleCase=text=>String(text||'').toLowerCase().split(' ').map((w,i)=>i&&SMALL_WORDS.has(w)?w:w.charAt(0).toUpperCase()+w.slice(1)).join(' ');
// A heading in title case with the words the search matched marked.
const markedHeading=(h,match)=>titleCase(h).split(' ').map(w=>match&&match(w)?`<mark class="law-match">${esc(w)}</mark>`:esc(w)).join(' ');
const statuteLink=key=>`<a class="text-link" href="${esc(statuteHref(key))}">${esc(statuteLabel(key,state.statutes?.codes))}</a>`;

export function fillDrawerStatutes(id){
  const el=$('#drawer-statutes');
  if(!el||state.openBill!==id)return;
  const rows=(statuteBills.get(id)||[]).slice().sort((a,b)=>b.others-a.others||a.key.localeCompare(b.key,undefined,{numeric:true}));
  const meta=state.statutes?.bills?.[id];
  if(!state.statutes||(!rows.length&&!meta?.u)){el.hidden=true;el.innerHTML='';return}
  // A bill's own heading where it differs from the section's (an unrelated new section under a number in use).
  const item=r=>{const s=state.statutes.sections[r.key],h=s?.hb?.[id]??s?.h;
    return `<li>${statuteLink(r.key)}${h?` <span class="law-heading">${esc(titleCase(h))}</span>`:''} <small>· ${esc(STATUTE_KINDS[r.kind])}${r.others?` · <strong>${r.others} other ${r.others===1?'bill':'bills'}</strong>`:''}</small></li>`};
  const shown=rows.slice(0,8),rest=rows.slice(8);
  const contested=rows.filter(r=>r.others&&r.kind==='m').length;
  el.innerHTML=`<h3>Laws this bill changes${rows.length?` (${rows.length})`:''}</h3>
    <p>Sections of Texas law named in this bill's latest text${contested?`. ${contested} ${contested===1?'is':'are'} also amended by other bills: open one to compare the versions side by side`:''}.</p>
    ${rows.length?`<ul class="law-list">${shown.map(item).join('')}</ul>`:''}${rest.length?`<details class="law-more"><summary>Show all ${rows.length}</summary><ul class="law-list">${rest.map(item).join('')}</ul></details>`:''}
    ${meta?.u?`<p><small>${meta.u} ${meta.u===1?'change':'changes'} in this bill could not be matched to a section; see the bill text.</small></p>`:''}`;
  el.hidden=false;
}

// A version's bills: "HB 655 = SB 60", or "HB 101 and 10 other bills" for a long same-wording group.
const groupName=g=>{const n=g.entries.map(e=>billNumber(e.bill));return n.length>3?`${n[0]} and ${n.length-1} other bills`:n.join(' = ')};
// One side of the comparison: Current law, or one version (a group of bills with the same wording).
function lawOptions(doc,groups,copy=null){
  const law=currentLaw(doc.entries),options=[];
  const names=groupName;
  if(copy)options.push({id:'law',name:'current law',label:`Current law${copy.asOf?` as of ${copy.asOf}`:''}, statute files${copy.of?` (the closest of ${copy.of} sections with this number)`:''}`,units:copy.units,partial:false,copy});
  else if(law.units.length)options.push({id:'law',name:'current law',label:`Current law, as quoted in ${law.sources.map(billNumber).join(', ')}`,units:law.units,partial:law.partial});
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
function lawCompareMarkup(options,right,leftId=state.statuteCompare.left){
  const left=options.find(o=>o.id===leftId)||options[0];
  const select=`<label class="law-pick"><span>Compare against</span><select data-law-side="left">${options.map(o=>`<option value="${esc(o.id)}" ${o===left?'selected':''}>${esc(o.label)}</option>`).join('')}</select></label>`;
  const rows=left===right?[]:compareLaw({name:left.name,units:left.units,partial:left.partial},{name:right.name,units:right.units,partial:right.partial});
  const label=l=>l==='head'?'Heading':l===''?'Text':`(${l})`;
  // A part one side leaves alone (a partial quote) is unchanged, not different.
  const changed=rows.filter(r=>!r.same&&!(r.right===null&&right.partial)&&!(r.left===null&&left.partial)).length;
  // data-name labels each cell when the columns stack on a phone.
  const cell=(words,note,cls,name)=>words?`<div class="law-cell" data-name="${esc(name)}">${lawWords(words,cls)}</div>`:`<div class="law-cell law-missing" data-name="${esc(name)}">${esc(note)}</div>`;
  const body=rows.map(r=>`<div class="law-row${r.same?' law-same':''}"><div class="law-label">${esc(label(r.label))}${r.same?' · same':''}</div>${cell(r.left,r.leftNote,'law-out',left.name)}${cell(r.right,r.rightNote,'law-in',right.name)}</div>`).join('');
  // With no current law there is one column worth showing, so no column toggle.
  const show=left.none?'both':state.statuteShow||'both';
  const first=n=>esc(n.split(/ = | and /)[0]);
  // No current law to compare with: everything on the right is new.
  const legend=left.none?`<span class="law-legend-long">This section is not in current law yet, so <mark class="law-in">all of ${first(right.name)}'s wording is new</mark>.</span><span class="law-legend-short"><mark class="law-in">All new</mark>: not in current law yet.</span>`
    :`<span class="law-legend-long"><mark class="law-out">Highlighted on the left</mark> is wording only the left has; <mark class="law-in">highlighted on the right</mark> is wording only the right has.</span><span class="law-legend-short"><mark class="law-out">Only in ${first(left.name)}</mark> <mark class="law-in">Only in ${first(right.name)}</mark></span> ${left===right?'Pick a different version for the left.':`${changed} of ${rows.length} ${rows.length===1?'part differs':'parts differ'}.`}`;
  return `<section class="law-compare-wrap"><h3>${left.id==='law'?'Current law':esc(left.name)} → ${esc(right.name)}</h3>
    ${options.length>2?`<div class="law-picks">${select}</div>`:''}
    <p class="law-legend">${legend}${rows.some(r=>r.approximate)?' Some parts are too long to compare word by word and are marked whole.':''}</p>
    ${left.none?'':`<div class="law-toggle" role="group" aria-label="Columns to show">${[['both','Both'],['left','Left'],['right','Right']].map(([v,t])=>`<button type="button" class="outline-button${show===v?' active':''}" data-law-show="${v}" aria-pressed="${show===v}">${t}</button>`).join('')}</div>`}
    <div class="law-compare${left.none?' law-none':''}" data-show="${show}"><div class="law-row law-head"><div class="law-label"></div><div class="law-cell">${esc(left.label)}</div><div class="law-cell">${esc(right.label)}</div></div>${body}</div></section>`;
}
// One version on its own: a proposed new section, or an amendment with no current law to set it against.
function lawSingleMarkup(title,units,note=''){
  return `<section class="law-compare-wrap"><h3>${esc(title)}</h3>${note?`<p class="law-legend">${note}</p>`:''}<div class="law-single">${units.map(u=>`<p>${esc(u.text).replaceAll('\n','<br>')}</p>`).join('')}</div></section>`;
}
// "Sec. 545.4575. EMERGENCY RESPONSE PROCEDURES." -> "Emergency Response Procedures"
const unitHeading=units=>{const h=units.find(u=>u.label==='head')?.text||'';return titleCase(h.replace(/^Sec\.\s*[0-9A-Za-z.-]+?\.\s+/,'').replace(/\.$/,''))};
const KIND_WORDS={amend:'Amends it',add:'Proposes a new section',repeal:'Repeals it'};

// Same limits the law share page and feed state (scripts/build_feeds.py LAW_LIMITS).
const LAW_LIMITS='Bills are matched to sections automatically from their text and can be missed: changes to a whole chapter at once, renumbering and unusual wording. No bill listed here does not mean no bill changes this section.';
export const lawFeedHref=key=>`./live/feeds/law/${encodeURIComponent(key.replace(' ','-'))}.xml`;
// Follow (a saved search for the section) and, once a bill changes it, the section's RSS feed.
function lawToolsMarkup(key,label,hasFeed){
  if(!isLawFollowQuery(key))return '';  // Only codes the parser tracks can ever gain bills.
  const on=!!lawFollowOf(state.searches,key);
  const button=`<button class="${on?'outline-button following':'primary-button'} follow-button" data-follow-law="${esc(key)}" data-follow-label="${esc(label)}" aria-pressed="${on}">${on?'✓ Following':isChapterKey(key)?key.startsWith('CN ')?'+ Follow this article':'+ Follow this chapter':'+ Follow this law'}</button>`;
  const feed=hasFeed?`<a class="outline-button" data-feed href="${esc(lawFeedHref(key))}" target="_blank" rel="noopener noreferrer">RSS feed</a>`:'';
  // A section links its whole chapter, which can be followed as one.
  const ch=chapterOf(key);
  const chapter=ch&&isChapterKey(ch)?`<a class="outline-button" href="${esc(statuteHref(ch))}">${chapterWord(ch.slice(0,2))} ${esc(ch.split(' ')[1])}</a>`:'';
  return `<div class="tools-row law-tools">${button}${feed}${chapter}</div>`;
}

const CHAPTER_KINDS={r:'repeals the whole chapter',m:'amends the whole chapter',n:'adds this chapter'};
// A whole chapter: the bills that change the chapter at once, the sections bills change, and every section in it.
function chapterMarkup(key,label,head,official){
  const whole=state.statutes.chapters?.[key],outline=lawChapter(key);
  const sections=Object.keys(state.statutes.sections).filter(k=>chapterOf(k)===key).sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  const bills=new Set(lawEntries(state.statutes,key).flatMap(s=>(s.b||[]).map(p=>p[0])));
  const sign=key.startsWith('CR ')?'Art.':'§';
  const heading=whole?.h||(typeof outline==='object'?outline.heading:'');
  const billLink=id=>{const b=state.bills.find(x=>x.id===id);return b?openLinkHtml(b.id,billHref(b.id),'bill-number',b.number):esc(id)};
  const status=id=>{const b=state.bills.find(x=>x.id===id);return b?` <span class="law-status">${esc(lastActionInfo(b).label)}</span>`:''};
  const wholeRows=(whole?.b||[]).filter(p=>Array.isArray(p)&&CHAPTER_KINDS[p[1]]).map(([id,kind])=>`<li>${billLink(id)} <small>· ${esc(CHAPTER_KINDS[kind])}</small>${status(id)}</li>`).join('');
  // A bill quoting only some subsections gives the index no heading; the law copy has every section's.
  // The Constitution's copy numbers sections within the article, so its keys add the article ("CN 8.1-b").
  const code=key.split(' ')[0],cn=code==='CN',unit=cn?'article':'chapter';
  const fullNumber=n=>cn?`${key.split(' ')[1]}.${n}`:n;
  const copied=new Map(typeof outline==='object'?outline.sections.map(([n,h])=>[fullNumber(n).toUpperCase(),h]):[]);  // Keys are upper case (CR 42.04a).
  const sectionRows=sections.map(k=>{const s=state.statutes.sections[k],h=s.h||copied.get(k.split(' ')[1].toUpperCase())||'';
    const kinds=(s.b||[]).filter(Array.isArray).map(([id,kind])=>`${billLink(id)} <small>${esc(STATUTE_KINDS[kind]||'')}</small>`).join(', ');
    return `<li>${statuteLink(k)}${h?` <span class="law-heading">${esc(titleCase(h))}</span>`:''}<div>${kinds}</div></li>`}).join('');
  const all=typeof outline==='object'?`<details class="law-more"><summary>All ${outline.sections.length} sections in this ${unit}</summary><ul class="law-list">${outline.sections.map(([n,h])=>
      `<li><a class="text-link" href="${esc(statuteHref(`${code} ${cn?fullNumber(n):n.toUpperCase()}`))}">${sign} ${esc(n)}</a> <span class="law-heading">${esc(titleCase(h))}</span></li>`).join('')}</ul></details>`
    :outline==='loading'?`<p class="near-hint">Loading the ${unit}'s sections…</p>`:'';
  const count=bills.size;
  return `${head(heading?esc(titleCase(heading)):esc(label),`${esc(label)} · ${count?`${count} ${count===1?'bill changes':'bills change'} something in it`:'no bill changes it yet'}`)}${lawToolsMarkup(key,label,count>0)}
    <div class="info-callout law-intro"><p>Following this ${unit} counts any bill that changes a section in it or the whole ${unit} at once. ${official}</p><details class="law-limits"><summary>How bills are matched</summary><p>${LAW_LIMITS}</p></details></div>
    ${wholeRows?`<section class="law-chapter-part"><h3>Bills that change the whole chapter</h3><ul class="law-list">${wholeRows}</ul></section>`:''}
    ${sectionRows?`<section class="law-chapter-part"><h3>Sections bills change <span>${sections.length}</span></h3><ul class="law-list">${sectionRows}</ul></section>`:count?'':`<p class="near-hint">No bill in this snapshot changes anything in ${esc(label)}.</p>`}
    ${all}`;
}

export function statuteMarkup(){
  const key=state.statuteKey;
  // A title that repeats the page's h1 is shown only where that h1 is hidden (phones), and never read twice.
  const head=(title,sub='90th Legislature · every bill that changes it')=>{const same=title===esc(statuteLabel(key||'',state.statutes?.codes));
    return `<div class="section-head law-section-head"><div><div class="section-overline">TEXAS LAW</div>${same?`<div class="law-title-same" aria-hidden="true">${title}</div>`:`<h2>${title}</h2>`}</div><span class="subtitle">${sub}</span></div>`};
  if(!key)return `${head('Section not found')}<div class="info-callout callout-warn" data-not-found>This address does not name a section of Texas law. Open one from a bill's "Laws this bill changes" list, or search the explorer for a section number such as 48.160.</div>`;
  // Following needs only the key, so the button is there while the index loads and when it failed.
  if(!state.statutes){const label=statuteLabel(key);return state.statutesFailed?`${head(esc(label))}${lawToolsMarkup(key,label,false)}<div class="info-callout callout-warn">The list of laws each bill changes is not available right now. Try again later.</div>`:`${head(esc(label))}${lawToolsMarkup(key,label,false)}<p class="near-hint">Loading…</p>`}
  const label=statuteLabel(key,state.statutes.codes),info=state.statutes.sections[key];
  const official=`<a class="text-link" href="${esc(officialStatuteUrl(key))}" target="_blank" rel="noopener noreferrer">Current law on statutes.capitol.texas.gov ↗</a>`;
  const tools=lawToolsMarkup(key,label,!!info);
  if(isChapterKey(key))return chapterMarkup(key,label,head,official);
  if(!info){
    // No bill changes it: the section as it stands, from the site's copy of the statutes.
    const copy=lawCopy(key),many=typeof copy==='object'&&copy.versions.length>1;
    const text=typeof copy==='object'?lawSingleMarkup(`Current law${copy.asOf?` as of ${copy.asOf}`:''}`,many?copy.versions.flat():copy.units,
      `${many?`Current law has ${copy.versions.length} sections with this number, each added by a different law; all are shown. `:''}From the Legislative Council's statute files (<a class="text-link" href="${esc(copy.url)}" target="_blank" rel="noopener noreferrer">this chapter</a>); it can trail the official text if a later law changed it.`)
      :copy==='loading'?'<p class="near-hint">Loading current law…</p>':'';
    const title=typeof copy==='object'&&!many&&unitHeading(copy.units)?esc(unitHeading(copy.units)):esc(label);
    return `${head(title,'90th Legislature · no bill changes it yet')}${tools}<div class="info-callout">No bill in this snapshot changes ${esc(label)}.${tools?' Follow it to hear when one does.':''} ${official}</div>${text}<p class="tools-note">${LAW_LIMITS}</p>`;
  }
  const doc=statuteDoc(key);
  const loadingTitle=head(info.h?esc(titleCase(info.h)):esc(label))+tools;
  if(doc==='loading')return `${loadingTitle}<p class="near-hint">Loading the bills' versions…</p>`;
  if(doc==='error')return `${loadingTitle}<div class="info-callout callout-warn">The versions of this section could not be loaded. ${official}</div>`;
  if(state.statuteCompare?.key!==key)state.statuteCompare={key,left:null,right:null};
  const groups=groupStatuteEntries(doc.entries,id=>(state.statutes.bills[id]?.n||0)>BROAD_BILL);
  // Bills quote only the parts they change: a repeal, or a partial amendment, takes current law from our copy.
  const quoted=currentLaw(doc.entries);
  const copy=doc.entries.some(e=>e.kind!=='add')&&(!quoted.units.length||quoted.partial)?lawCopy(key):'missing';
  let options=lawOptions(doc,groups,typeof copy==='object'?copy:null),law=options.find(o=>o.id==='law');
  const lawSource=law?.copy?`from the Legislative Council's statute files${law.copy.asOf?` as of ${esc(law.copy.asOf)}`:''} (<a class="text-link" href="${esc(law.copy.url)}" target="_blank" rel="noopener noreferrer">this chapter</a>)`:'as the bills quote it';
  const gid=g=>g.entries[0].bill,names=groupName;
  // Every bill adds a section with this number and none quotes current wording: it is not law yet.
  const proposed=!law&&groups.every(g=>g.kind==='add');
  // A heading only when every proposal shares it (an index from older code can carry one bill's heading for all).
  const oneHead=info.h&&new Set(groups.map(g=>unitHeading(g.units)).filter(Boolean)).size<=1;
  // A proposed section is laid out like an amended one: current law (none) on the left, all of the bill's wording new
  // on the right. Another version can be picked for the left to set two proposals side by side.
  const versions=groups.filter(g=>g.kind==='add'&&g.units.length);
  const sides=proposed?[{id:'law',name:'current law',label:'Current law: no such section yet',units:[],partial:false,none:true},...options]:options;
  const largest=proposed&&versions.length?versions.reduce((a,g)=>g.entries.length>a.entries.length?g:a):null;
  // The bar's pick, else (proposed) the wording most bills share, else the first focused amendment, else the first
  // version with wording.
  const chosen=groups.find(g=>gid(g)===state.statuteCompare.right)||largest
    ||groups.find(g=>g.kind==='amend'&&!g.broad&&g.units.length)||groups.find(g=>g.kind!=='repeal'&&g.units.length)||groups[0];
  // A number used for several sections: set the bill against the one its wording is closest to.
  if(typeof copy==='object'&&copy.versions.length>1&&chosen?.units.length){
    options=lawOptions(doc,groups,{...copy,units:closestLawVersion(copy.versions,chosen.units),of:copy.versions.length});
    law=options.find(o=>o.id==='law');
  }
  const count=groups.reduce((n,g)=>n+g.entries.length,0);
  const version=g=>g.entries[0].version_name||g.entries[0].version;
  let main='';
  if(chosen?.kind==='repeal')main=law?lawSingleMarkup(`Current law · ${names(chosen)} would repeal it`,law.units,`${esc(names(chosen))} removes this section; this is the wording it would remove, ${lawSource}.`)
    :copy==='loading'?`<p class="near-hint">Loading current law…</p>`:`<div class="info-callout">${esc(names(chosen))} would repeal this section. ${official}</div>`;
  else if(chosen&&!chosen.units.length)main=`<div class="info-callout">The wording of ${esc(names(chosen))} for this section could not be read. Open the bill to see its text.</div>`;
  else if(chosen?.kind==='amend'&&law)main=lawCompareMarkup(options,options.find(o=>o.id===gid(chosen)));
  else if(chosen?.kind==='amend'&&!law&&copy==='loading')main=`<p class="near-hint">Loading current law…</p>`;
  else if(proposed&&chosen?.kind==='add'){
    // The left is the reader's pick when it is another version, else current law (none).
    const left=state.statuteCompare.left;
    main=lawCompareMarkup(sides,sides.find(o=>o.id===gid(chosen)),sides.some(o=>o.id===left&&o.id!==gid(chosen))?left:'law');
  }
  else if(chosen)main=lawSingleMarkup(`${names(chosen)} · ${chosen.kind==='add'?'proposed new section':'amended'} · ${version(chosen)}`,chosen.units,
    chosen.kind==='add'?'This bill adds a different section with the same number; it does not change the current section.'
      :`The bills do not quote the current wording, so there is nothing to set this against. ${official}`);
  const card=g=>{
    const e=g.entries[0],on=g===chosen,own=g.kind==='add'?unitHeading(g.units):'',heading=own&&!(oneHead&&own===titleCase(info.h))?own:'';  // Not again when it is the page title.
    // One status for the card when every bill shares it (a long same-wording group stays short).
    const found=g.entries.map(x=>state.bills.find(y=>y.id===x.bill)),labels=new Set(found.map(b=>b?lastActionInfo(b).label:''));
    const one=found.length>1&&labels.size===1&&found[0]?[...labels][0]:'';
    const link=(x,i)=>{const b=found[i];return b?`${openLinkHtml(b.id,billHref(b.id),'bill-number',b.number)}${one?'':` <span class="law-status">${esc(lastActionInfo(b).label)}</span>`}`:esc(x.bill)};
    const same='<span class="law-same-text"> = </span>',links=g.entries.map(link),shown=links.length>4?links.slice(0,3):links;
    const bills=shown.join(same)+(links.length>shown.length?` <details class="law-more-bills"><summary>and ${links.length-shown.length} more</summary>${links.slice(shown.length).join(same)}</details>`:'')+(one?` <span class="law-status">· all ${esc(one)}</span>`:'');
    const parts=g.kind==='amend'&&g.partial&&e.subsections?.length?`subsections ${e.subsections.map(s=>`(${s})`).join(', ')}`:g.kind==='amend'?'whole section':'';
    const notes=[KIND_WORDS[g.kind],version(g),parts,g.entries.length>1?'same wording':'',g.broad?`broad bill · changes ${state.statutes.bills[e.bill]?.n} sections`:''].filter(Boolean);
    const caption=g.entries.length===1?state.bills.find(b=>b.id===e.bill)?.caption:'';
    // The button covers the card (CSS), so the whole card picks it; the bill links sit above it.
    return `<li class="law-version${on?' active':''}${g.broad?' law-broad':''}"><div class="law-pick-bills">${bills}</div>${heading?`<strong class="law-pick-head">${esc(heading)}</strong>`:''}
      <button type="button" class="law-pick-btn" data-law-compare="${esc(gid(g))}" aria-pressed="${on}" aria-label="Show ${esc(names(g))}">${esc(notes.join(' · '))}</button>${caption?`<span class="law-caption">${esc(caption)}</span>`:''}</li>`;
  };
  const bar=`<aside class="law-bills" aria-label="Bills that change this section"><h3>${proposed?'Proposals':'Bills'} <span>${count}${groups.length<count?` · ${groups.length} versions`:''}</span></h3><p class="near-hint">${groups.length>1?'Pick one to show its version.':'The only version so far.'}</p><ul class="law-versions">${groups.map(card).join('')}</ul></aside>`;
  const title=proposed?head(oneHead?esc(titleCase(info.h)):esc(label),'Proposed new section · not in current law yet')+tools:loadingTitle;
  const limits=`<details class="law-limits"><summary>How bills are matched</summary><p>${LAW_LIMITS}</p></details>`;
  const say=count===1?'One bill proposes a section with this number'
    :oneHead&&versions.length>1?`${count} bills propose this new section in ${versions.length} versions`
    :oneHead&&groups.length===1?`${count} bills propose this new section in the same words`
    :`${count} bills propose a section with this number${groups.length>1?'. Bills drafted separately can reuse a number for unrelated subjects':''}`;
  const intro=proposed?`<div class="info-callout law-intro"><p>${say}.${isLawFollowQuery(key)?' Following it follows every bill that uses this section number.':''}</p>${limits}</div>`
    :law?`<div class="info-callout law-intro"><details class="law-limits"><summary>About this comparison</summary><p>Current law is on the left, ${lawSource}; it can trail the official text if a later law changed it. ${official}</p><p>${LAW_LIMITS}</p></details></div>`
    :`<div class="info-callout law-intro"><p>Each bill quotes the wording it would change. ${official}</p>${limits}</div>`;
  return `${title}${intro}<div class="law-layout">${bar}<div class="law-main">${main}</div></div>`;
}

// What opening a section shows: a proposed new section has no current law to compare with.
const openHint=key=>(state.statutes.sections[key]?.b||[]).every(p=>p[1]==='n')?'Open it to read the proposals.':'Open it to compare with current law.';
// Explorer: a search for a section number lists the bills that change it; this links to their comparison.
export function statuteHintMarkup(keys,query='',headings=true){
  // Exactly a section key ("PE 46.06", what a law follow saves): only that section's bills, never text matches.
  if(isLawFollowQuery(query)){
    if(!state.statutes)return `<div class="info-callout${state.statutesFailed?' callout-warn':''} statute-hint">${state.statutesFailed?`The list of laws each bill changes is not available right now, so the bills that change ${esc(query)} cannot be shown. Try again later.`:`Loading the bills that change ${esc(query)}…`}</div>`;
    if(isChapterKey(query))return `<div class="info-callout statute-hint">Showing only bills that change something in ${statuteLink(query)}${lawEntries(state.statutes,query).length?'. Open it to see which sections.':': none yet.'}</div>`;
    return `<div class="info-callout statute-hint">Showing only bills that change ${statuteLink(query)}${state.statutes.sections[query]?`. ${openHint(query)}`:': none yet.'}</div>`;
  }
  if(keys.length)return `<div class="info-callout statute-hint">Bills that change ${keys.map(statuteLink).join(', ')} are included. ${keys.length===1?openHint(keys[0]):'Open one to see what its bills change.'}</div>`;
  return headings?lawHeadingHint(query):'';
}

// ---- The explorer's Laws results (the Laws button on, Bills off) ----
// {status, kind, items: [[key, heading]], bare?}. status: 'empty' (no words), 'loading', 'error' or 'ok' (items may be
// empty). kind 'key': the query names sections or a chapter by number (bare: a number with no code); 'words': heading
// search, with any law the query names ("Public Information Act") first.
const lawHeading=key=>state.statutes?.sections?.[key]?.h||state.statutes?.chapters?.[key]?.h||'';
export function lawResults(query){
  const q=String(query||'').trim().replace(/\s+/g,' ');
  if(!q)return {status:'empty',kind:'words',items:[]};
  const key=canonicalLawKey(q);
  // An exact key ("PE 46.06", "PE 46"): that law, whether or not a bill changes it (every law has a page).
  if(isLawFollowQuery(key))return {status:'ok',kind:'key',items:[[key,lawHeading(key)]]};
  const codes=state.statutes?.codes||LAW_CODE_NAMES;  // Naming a code needs no index.
  const parsed=parseStatuteQuery(q,codes);
  if(parsed){
    if(parsed.code&&LAW_CODES.has(parsed.code)){const k=`${parsed.code} ${parsed.sec}`;return {status:'ok',kind:'key',items:[[k,lawHeading(k)]]}}
    // A bare number ("62.051"): the sections bills change with that number; others need their code named.
    if(!state.statutes){if(!state.statutesFailed)loadStatutes();return {status:state.statutesFailed?'error':'loading',kind:'key',items:[],bare:parsed.sec}}
    return {status:'ok',kind:'key',items:statuteKeysFor(state.statutes,parsed).map(k=>[k,lawHeading(k)]),bare:parsed.sec};
  }
  const chapter=parseChapterQuery(q,codes);
  if(chapter)return {status:'ok',kind:'key',items:[[chapter,lawHeading(chapter)]]};
  const named=lawNamedMatches(q),terms=lawSearchTerms(q),found=lawSearch(terms);
  if(found==='loading')return {status:'loading',kind:'words',items:[]};
  if(found===null&&!named.length)return terms.length?{status:'error',kind:'words',items:[]}:{status:'ok',kind:'words',items:[]};
  const pinned=new Set(named.map(n=>n[0]));
  return {status:'ok',kind:'words',items:[...named,...(found||[]).filter(e=>!pinned.has(e[0]))]};
}
const billsChanging=key=>new Set(lawEntries(state.statutes,key).flatMap(e=>(e.b||[]).map(p=>p[0]))).size;
// The list itself, the first `shown` items. The count, paging and the "Changed by bills" filter are the explorer's
// (explorer/view.js).
export function lawResultsMarkup(result,shown,query=''){
  if(result.status==='empty')return `<div class="info-callout law-results-intro"><p>Search Texas law by words in a section's or chapter's heading (<em>unlawful carrying</em>), by a law's name (<em>Public Information Act</em>), or by its number (<em>Penal Code 46.06</em>, <em>Penal Code chapter 46</em>). Every section and chapter opens on its own page, where you can follow it.</p></div>`;
  if(result.status==='loading')return `<div class="info-callout law-results-intro" role="status">Searching Texas law…</div>`;
  if(result.status==='error')return `<div class="info-callout callout-warn law-results-intro">Law search is not available right now. Try again later, or turn Bills on to search bills.</div>`;
  const bare=result.bare?esc(result.bare):'';
  if(!result.items.length)return `<div class="empty-state"><h3>No law matches yet</h3><p>${result.kind==='key'?`No bill changes a section numbered “${bare||esc(query.trim())}”. Add its code to open it anyway, as in <em>Penal Code ${bare||'46.06'}</em>.`:`No section or chapter heading has all of these words. Try fewer words, or a section number.`}</p></div>`;
  const match=result.kind==='words'?lawTermMatcher(lawSearchTerms(query)):null;
  const item=([k,h])=>{const n=state.statutes?billsChanging(k):0;
    return `<li class="law-result">${statuteLink(k)}${h?` <span class="law-heading">${markedHeading(h,match)}</span>`:''}${n?` <small>· ${n} ${n===1?'bill changes':'bills change'} it</small>`:''}</li>`};
  const note=bare?`<p class="near-hint law-results-note">Sections numbered ${bare} that bills change. For another code's ${bare}, add the code, as in <em>Penal Code ${bare}</em>.</p>`:'';
  return `${note}<ul class="law-list law-result-list">${result.items.slice(0,shown).map(item).join('')}</ul>`;
}
// Laws whose heading has the search words ("unlawful carrying" -> Penal Code § 46.02), shown above the bills; the
// full list is the Laws view.
const HEADING_SHOWN=5;
function lawHeadingHint(query){
  const hits=lawSearch(lawSearchTerms(query));
  if(hits==='loading')return '';
  // Named laws first, as in the Laws view, so "See all N" is the count it shows.
  const named=lawNamedMatches(query),pinned=new Set(named.map(n=>n[0]));
  const found=[...named,...(Array.isArray(hits)?hits:[]).filter(e=>!pinned.has(e[0]))];
  if(!found.length)return '';
  const match=lawTermMatcher(lawSearchTerms(query));
  const item=([k,h])=>`<li>${statuteLink(k)} <span class="law-heading">${markedHeading(h,match)}</span>${lawChanged(k)?' <small>· bills change it</small>':''}</li>`;
  const more=found.length>HEADING_SHOWN?`<button type="button" class="text-button law-see-all" id="law-see-all">See all ${found.length.toLocaleString()} laws →</button>`:'';
  return `<div class="info-callout statute-hint law-heading-hint"><p>Texas law with “${esc(lawSearchTerms(query).join(' '))}” in its heading:</p><ul class="law-list">${found.slice(0,HEADING_SHOWN).map(item).join('')}</ul>${more}</div>`;
}
