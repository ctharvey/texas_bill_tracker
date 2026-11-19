// The bill page (/bill/<ID>): its header, chamber summary, Luna's review and the drawer sections, plus the banner art
// and the share-card versions it loads once per page load.
import {artEntries, artBanner, heroFits, HERO_MEDIA} from '../art/view.js';
import {$, esc} from '../../core/dom.js';
import {state} from '../../core/state.js';
import {dateText, safeHref, shortDate} from '../../core/format.js';
import {memberHref} from '../../core/links.js';
import {tenurePill, memberNameHtml, rosterMember, authorHtml} from '../members/names.js';
import {memberSummary, assessHearing, authorInfluence, authorshipParty, lastActionInfo, officialUrl} from '../../taxonomy.js';
import {buildHash} from '../../prefs.js';
import {agencyName, areaName, realAgencies} from '../../core/labels.js';
import {aiChatLinks, agentUrl} from '../ai/model.js';
import {companionsOf, companionBlock} from '../companions/view.js';
import {sameText, headlineLine, relatedBlock} from '../explorer/view.js';
import {billAreas} from '../areas/model.js';
import {reviewFileSection} from '../reviewfile/view.js';
import {billTextSection} from '../billtext/view.js';
import {stageSections} from '../stages/view.js';
import {fillDrawerStatutes} from '../statutes/view.js';
import {fillDrawerBrackets} from '../brackets/view.js';

// Bill id -> drawn share card version, loaded once when a bill page opens so Share can copy synchronously
// (Safari drops clipboard access after an await). Until it loads, or if it fails, Share copies the plain link.
export let cardVersions=null,cardVersionsLoad=null;
function loadCardVersions(){
  if(cardVersionsLoad)return;
  // A 404 body is read too: Chrome counts an unread body as a request still open, so the page never goes idle.
  cardVersionsLoad=fetch('./live/og/rendered.json',{cache:'no-cache'}).then(r=>r.ok?r.json():r.text().then(()=>null))
    .then(d=>{cardVersions=d?.format==='texas-bill-og-rendered-v1'&&d.bills&&typeof d.bills==='object'?d.bills:{}})
    .catch(()=>{cardVersionsLoad=null});
}

// Bill page banner (features/art/view.js): read once per page load, so flipping live/site-flags.json takes effect on
// the next load. Either file missing or unreadable means no banner.
let billArt=null,siteFlags=null,billArtLoad=null;
function loadBillArt(){
  if(billArtLoad)return;
  const get=url=>fetch(url,{cache:'no-cache'}).then(r=>r.ok?r.json():r.text().then(()=>null)).catch(()=>null);
  billArtLoad=Promise.all([get('./live/site-flags.json'),get('./live/og/art.json'),document.fonts?.ready.catch(()=>null)])
    .then(([flags,art])=>{siteFlags=flags;billArt=artEntries(art);placeBillArt()});
}
function placeBillArt(){
  const intro=$('#bill-page .bill-intro');if(!intro)return;
  const old=intro.querySelector(':scope > .bill-art');
  if(old){unheroBillArt(old);old.remove()}
  const b=state.bills.find(b=>b.id===state.openBill);
  const html=b?artBanner(b.id,b.number,siteFlags,billArt):'';
  if(html){intro.insertAdjacentHTML('afterbegin',html);layoutBillArt()}
}
// Moves the pills and title back under the banner; the overlay holds the only copies.
function unheroBillArt(fig){
  const media=fig.querySelector('.bill-art-media');if(!media)return;
  const over=media.querySelector('.bill-art-over');
  if(over)fig.after(...over.children);
  fig.prepend(...media.querySelectorAll(':scope > img'));media.remove();fig.classList.remove('hero');
}
// Re-run on width changes: wrapping, and so whether the title fits, depends on it. Moving a focused title drops focus.
function layoutBillArt(){
  const intro=$('#bill-page .bill-intro'),fig=intro?.querySelector(':scope > .bill-art');if(!fig)return;
  const h1=intro.querySelector('#bill-page-title'),focused=h1&&document.activeElement===h1;
  unheroBillArt(fig);
  const pills=intro.querySelector(':scope > .drawer-pills'),img=fig.querySelector(':scope > img');
  if(HERO_WIDE.matches&&pills&&h1&&h1.parentElement===intro&&img){
    const media=document.createElement('div'),over=document.createElement('div');
    media.className='bill-art-media';over.className='bill-art-over';
    fig.classList.add('hero');fig.prepend(media);media.append(img,over);over.append(pills,h1);
    const num=h1.querySelector('.bill-h1-number');
    if(!heroFits(h1.getBoundingClientRect().height,num?num.getBoundingClientRect().height:0,parseFloat(getComputedStyle(h1).lineHeight)))unheroBillArt(fig);
  }
  if(focused&&document.activeElement!==h1)h1.focus({preventScroll:true});
}
const HERO_WIDE=typeof matchMedia==='function'?matchMedia(HERO_MEDIA):{matches:false,addEventListener(){}};
let billArtFrame=0;
if(typeof addEventListener==='function')addEventListener('resize',()=>{cancelAnimationFrame(billArtFrame);billArtFrame=requestAnimationFrame(layoutBillArt)});

function lunaBlock(b){
  if(!b.luna)return '';
  const locs=(b.locations||[]).map(l=>`<li><strong>${esc(l.name)}</strong>${l.kind?` (${esc(l.kind)})`:''}${l.explanation?` · ${esc(l.explanation)}`:''}</li>`).join('');
  return `<section class="drawer-section luna-block"><h3>Full-text review by Luna</h3><p><small>Reviewed ${esc(dateText(b.luna.reviewed_at))}${b.luna.text_version?` · ${esc(b.luna.text_version)} text`:''}</small></p>${b.luna.summary?`<p>${esc(b.luna.summary)}</p>`:''}<p><small>Tags from the bill's full text; fields not verified against the text use caption inference. Luna is an AI model and can be wrong; <a class="text-link" href="#method" data-view="method">how it works</a>.</small></p>${locs?`<h4>Locations</h4><ul>${locs}</ul>`:''}</section>`;
}

function memberItem({name,member}){
  const letter=member?.party==='Democratic'?'dem':member?.party==='Republican'?'rep':'unknown';
  const official=safeHref(member?.links?.lrl||member?.links?.tlo);
  const label=member?.full_name||name;
  // The name opens the member's page here; the official record stays one click away.
  const who=member?.code?`<a class="text-link" href="${esc(memberHref(member.code))}">${esc(label)}</a>`:`<strong>${esc(label)}</strong>`;
  return `<li><span class="party-dot party-${letter}" aria-hidden="true"></span>${who} ${tenurePill(member)} <small>${esc(memberSummary(member))}</small>${official?` <a class="text-link member-official" href="${esc(official)}" target="_blank" rel="noopener noreferrer" aria-label="Official record for ${esc(label)}">official ↗</a>`:''}</li>`;
}

// The bill page's section groups, in page order; the header's section menu jumps to each.
const BILL_GROUPS=[['overview','Overview'],['text','Text'],['law','Changes to law'],['people','People'],['impact','Agencies and impact'],['history','History'],['sources','Sources']];
// The bill view's content: every section of one bill, drawn into the page after the router renders its container.
function chamberSummary(b){
  const chamber=(name,role,names)=>`<span class="chamber-summary-side">
    <span class="chamber-building" aria-hidden="true"><i></i></span>
    <span><strong>Texas ${name}</strong><small>${names==null?`${role}s unreported`:names.length===0?`No ${role}s listed`:`${names.length} ${role}${names.length===1?'':'s'}`}</small></span></span>`;
  return `<button type="button" class="chamber-summary" data-bill-jump="people">
    ${chamber(b.chamber,'author',b.authors)}
    ${chamber(b.chamber==='House'?'Senate':'House','sponsor',b.sponsors)}
    <span class="chamber-summary-link">See people ↓</span></button>`;
}

function billChambers(b){
  const role=(label,key)=>{
    const names=b[key];const people=b.people?.[key];return `<h5>${label}${names===null?'':` (${names.length})`}</h5>${names===null?'<p>Not reported in this dataset</p>':!names.length?'<p>None listed in the source snapshot</p>':people?`<ul class="member-list">${people.map(p=>memberItem(p)).join('')}</ul>`:`<p>${names.map(esc).join(' · ')}</p>`}`;
  };
  const other=b.chamber==='House'?'Senate':'House';
  return `<div class="bill-chambers">
    <section><small>Originating chamber</small><h4>Texas ${esc(b.chamber)}</h4>${role('Authors','authors')}${role('Coauthors','coauthors')}</section>
    <section><small>Other chamber</small><h4>Texas ${other}</h4>${role('Sponsors','sponsors')}${role('Cosponsors','cosponsors')}</section>
  </div>`;
}

export function fillBillPage(){
  const page=$('#bill-page');if(!page)return;
  const b=state.bills.find(b=>b.id===state.openBill);
  if(!b){page.innerHTML=`<div class="drawer-top"><button type="button" class="outline-button bill-back" id="bill-back">← Back to results</button></div><div class="empty-state"><h3>${esc(state.openBill||'This bill')} is not in this snapshot</h3><p>It may not be filed yet, or the bill list could not be loaded.</p>${state.openBill?`<p class="empty-steps"><a class="outline-button" href="${esc(buildHash('all',{query:state.openBill}))}">Search for ${esc(state.openBill)}</a></p>`:''}</div>`;return}
  const h=assessHearing(b),influence=authorInfluence(b),party=authorshipParty(b),last=lastActionInfo(b);
  const agencyRows=b.agencies.length?b.agencies.map(a=>`<div class="agency-row"><div><strong>${esc(agencyName(a.id))}</strong><p>${esc(a.reason||'Relationship not yet annotated')}</p></div><span class="confidence ${a.relationship==='direct'?'direct':''}">${a.source==='luna'?`Luna · ${a.relationship==='direct'?'direct':'inferred'}`:a.relationship==='direct'?'Direct':'Possible'}</span></div>`).join(''):'<p>No agency has been tagged yet. This does not establish that none are affected.</p>';
  const watched=state.watch.has(b.id);
  page.innerHTML=`<header class="bill-head"><div class="bill-bar"><button type="button" class="outline-button bill-back" id="bill-back">← Back to results</button><span class="drawer-number">90R / ${esc(b.number)}</span><div class="drawer-actions"><a class="primary-button" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Read official bill ↗</a><button class="outline-button" data-watch="${b.id}">${watched?'★ Remove from watchlist':'☆ Add to watchlist'}</button><a class="outline-button" data-feed href="./live/feeds/${esc(b.id)}.xml" target="_blank" rel="noopener noreferrer" title="Follow this bill's actions in Outlook or a feed reader">RSS feed</a><button type="button" class="outline-button" data-share-bill="${esc(b.id)}" title="Copy a link to this bill that shows its number and caption when posted on Discord, Facebook, X or Slack">Share</button><details class="ask-ai"><summary class="outline-button" title="Ask an AI assistant about this bill">Ask AI ▾</summary><div class="ask-ai-menu">${aiChatLinks(b,companionsOf(b.id)).map(l=>`<a data-ask-ai="${esc(l.name)}" href="${esc(l.href)}" target="_blank" rel="noopener noreferrer">${esc(l.name)} ↗</a>`).join('')}<small>ChatGPT and Claude open with the prompt filled in. Copy for AI copies it for any other assistant.</small><button type="button" data-copy-ai title="Copy a short prompt with links to this bill, for pasting into any AI assistant">Copy for AI</button></div></details></div></div><nav class="bill-menu" aria-label="Sections of this bill">${BILL_GROUPS.map(([id,label])=>`<button type="button" data-bill-jump="${id}">${label}</button>`).join('')}</nav></header><div class="bill-intro"><div class="drawer-pills"><span class="chamber-pill">${esc(b.chamber)}</span><span class="status-pill">${esc(b.status)}</span><span class="party-pill party-${party.tint}" title="${esc(party.detail)}">${esc(party.label)}</span></div><h1 id="bill-page-title" tabindex="-1"><span class="bill-h1-number">${esc(b.number)}</span> ${esc(b.title)}</h1>${sameText(b.caption,b.title)?'':`<p class="drawer-caption">${esc(b.caption)}</p>`}${chamberSummary(b)}</div><div class="bill-layout"><div class="bill-main"><section class="bill-group" id="bill-g-overview" aria-labelledby="bill-h-overview"><h2 class="bill-group-title" tabindex="-1" id="bill-h-overview">Overview</h2>${headlineLine(b,'drawer')}${lunaBlock(b)}<div class="drawer-pills">${b.topics.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>${billAreas(b).length?`<p class="area-badges"><span>Reader areas:</span> ${billAreas(b).map(id=>`<a class="tag area-tag" href="${esc(buildHash('all',{area:id}))}">${esc(areaName(id))}</a>`).join('')}</p>`:''}${b.subjects?.length?`<section class="drawer-section"><h3>Official subjects</h3><p>The Legislative Council's subject index for this bill. Search matches these, so a bill with a vague caption is still found by its subject.</p><div class="bill-tags">${b.subjects.map(s=>`<span class="tag subject-tag">${esc(s)}</span>`).join('')}</div></section>`:''}${companionBlock(b)}${relatedBlock(b)}</section><section class="bill-group" id="bill-g-text" aria-labelledby="bill-h-text"><h2 class="bill-group-title" tabindex="-1" id="bill-h-text">Text</h2></section><section class="bill-group" id="bill-g-law" aria-labelledby="bill-h-law"><h2 class="bill-group-title" tabindex="-1" id="bill-h-law">Changes to law</h2><section class="drawer-section law-section" id="drawer-statutes" hidden></section><section class="drawer-section bracket-section" id="drawer-brackets" hidden></section></section><section class="bill-group" id="bill-g-people" aria-labelledby="bill-h-people"><h2 class="bill-group-title" tabindex="-1" id="bill-h-people">People</h2><section class="drawer-section"><h3>Authors & sponsors</h3>${billChambers(b)}<p>Authors include primary and joint authors listed in the Legislative Council snapshot.</p><div class="evidence-card"><strong><span class="party-pill party-${party.tint}">${esc(party.label)}</span></strong><p>${esc(party.detail)}</p><p><small>Party, district and tenure come from the Texas Legislative Reference Library's latest recorded service; for members-elect not yet in its records, party and district come from the Secretary of State's unofficial 2026 general election results. Authorship does not indicate a vote or caucus position.</small></p></div></section><section class="drawer-section"><h3>Author prominence</h3><div class="evidence-card"><strong>${esc(influence.label)}</strong><p>${esc(influence.factors.join(' · '))}</p>${safeHref(b.author_profile?.source)?`<p><a class="text-link" href="${esc(safeHref(b.author_profile.source))}" target="_blank" rel="noopener noreferrer">Verified member biography ↗</a></p>`:''}</div></section></section><section class="bill-group" id="bill-g-impact" aria-labelledby="bill-h-impact"><h2 class="bill-group-title" tabindex="-1" id="bill-h-impact">Agencies and impact</h2><section class="drawer-section"><h3>Potentially affected agencies (${realAgencies(b).length})</h3><p>All known tags are listed. Possible links are model/rule inferences, not confirmed legal obligations.</p>${agencyRows}</section><section class="drawer-section"><h3>Types of impact</h3><div class="drawer-pills">${b.impacts.length?b.impacts.map(t=>`<span class="tag related">${esc(t)}</span>`).join(''):'<span class="tag">Pending analysis</span>'}</div></section>${b.constituencies?.length?`<section class="drawer-section"><h3>People and institutions affected</h3><div class="drawer-pills">${b.constituencies.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></section>`:''}</section><section class="bill-group" id="bill-g-history" aria-labelledby="bill-h-history"><h2 class="bill-group-title" tabindex="-1" id="bill-h-history">History</h2><section class="drawer-section"><h3>Hearing progress & evidence</h3><div class="evidence-card"><strong>${esc(h.label)} · ${h.level===0?'No rating yet':'Verified procedural signal'}</strong><p>${esc(h.detail)}</p><ul>${h.facts.map(f=>`<li>${esc(f)}</li>`).join('')}</ul></div></section></section><section class="bill-group" id="bill-g-sources" aria-labelledby="bill-h-sources"><h2 class="bill-group-title" tabindex="-1" id="bill-h-sources">Sources</h2><section class="drawer-section"><h3>Source & verification</h3><p>Review the bill history and latest text before relying on any classification. <a class="text-link" href="${officialUrl(b)}" target="_blank" rel="noopener noreferrer">Texas Legislature Online ↗</a></p><div class="ai-copy"><a class="text-link" href="${esc(agentUrl(b))}" target="_blank" rel="noopener noreferrer">AI-readable version ↗</a></div></section></section></div><aside class="bill-rail" aria-label="Key facts"><div class="drawer-meta-grid"><div><small>Filed by</small><strong>${authorHtml(b,b.author)}</strong></div><div><small>Filed on</small><strong>${dateText(b.filed_at)}</strong></div><div><small>Most recent action</small><strong>${esc(last.label)}${last.chamber?` · ${esc(last.chamber)}`:''} · ${esc(dateText(last.date))}</strong><small>${esc(last.text)}</small></div><div><small>Hearing status</small><strong>${esc(h.label)}</strong></div></div></aside></div>`;
  loadCardVersions();
  loadBillArt();placeBillArt();

  const review=reviewFileSection(b);
  $('#bill-g-text').append(billTextSection(b),review.section);review.draw();
  $('#bill-g-history').append(stageSections(b));
  $('#bill-page-title').focus({preventScroll:true});
  fillDrawerStatutes(b.id);
  fillDrawerBrackets(b.id);
}
