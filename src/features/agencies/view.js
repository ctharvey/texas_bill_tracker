// The agencies directory (#agencies) and the explorer's affected-agency picker: typing to filter, keyboard moves, the
// sort toggle and choosing one. Results redraw through core/router.js.
import {$, esc} from '../../core/dom.js';
import {state} from '../../core/state.js';
import {realAgencies, agencyName} from '../../core/labels.js';
import {unique} from '../../core/format.js';
import {AGENCIES, SCOPE_AGENCY_ID} from '../../taxonomy.js';
import {options, AGENCY_SORT_KEY, agencyOptionsMarkup} from '../explorer/controls.js';
import {renderResults} from '../../core/router.js';

// An agency id is shown as a code only when it is a short form the name does not already spell out (TCEQ, not HOUSE or TX-COURTS).
const agencyCode=a=>/^[a-z]{2,6}$/.test(a.id)&&!a.name.toLowerCase().includes(a.id)?a.id.toUpperCase():'';
export function filterAgencyCards(text){
  const words=text.toLowerCase().split(/\s+/).filter(Boolean),list=$('#agency-list');
  if(!list)return;
  // Agencies with no bills stay hidden until "Show all", but a search looks through every agency.
  const rows=[...list.children],all=list.dataset.all==='1';
  let shown=0;for(const li of rows){const hit=words.every(w=>li.firstElementChild.dataset.find.includes(w))&&(words.length>0||all||!li.classList.contains('agency-none'));li.hidden=!hit;if(hit)shown++}
  $('#agency-find-note').textContent=words.length?(shown?`${shown} of ${rows.length} agencies`:'No agency matches. Try part of the name.'):'';
  const more=$('#agency-more');if(more)more.hidden=words.length>0;
}
export function agenciesMarkup(){
  const counts=new Map();for(const b of state.bills)for(const id of new Set(realAgencies(b).map(a=>a.id)))counts.set(id,(counts.get(id)||0)+1);
  const agencies=unique([...AGENCIES.map(a=>a.id),...Object.keys(state.luna?.agencies||{})]).filter(id=>id!==SCOPE_AGENCY_ID).map(id=>({id,name:agencyName(id)})).sort((a,b)=>(counts.get(b.id)||0)-(counts.get(a.id)||0)||a.name.localeCompare(b.name));
  const max=Math.max(1,...agencies.map(a=>counts.get(a.id)||0)),none=agencies.filter(a=>!counts.has(a.id)).length;
  const row=a=>{
    const n=counts.get(a.id)||0,code=agencyCode(a);
    return `<li${n?'':' class="agency-none" hidden'}><button class="agency-row" data-agency-pick="${esc(a.id)}" data-find="${esc(`${a.name} ${a.id} ${code}`.toLowerCase())}"><span class="agency-name">${code?`<span class="agency-code">${esc(code)}</span>`:''}<strong>${esc(a.name)}</strong></span><i aria-hidden="true" class="agency-bar"><i style="width:${(100*n/max).toFixed(1)}%"></i></i><span class="hits">${n.toLocaleString()} <small>${n===1?'bill':'bills'}</small></span></button></li>`;
  };
  return `<div class="section-head"><div><div class="section-overline">IMPACT DIRECTORY</div><h2>Texas state agencies</h2></div><span class="subtitle">${agencies.length-none} with possible links in this snapshot</span></div><div class="info-callout"><details class="agency-why"><summary><strong>Why an agency index?</strong> One bill can change the work of several state agencies. <span class="agency-why-more">More</span></summary> “Direct” means the supplied material names an agency; “possible” means an inferred policy connection. An agency absent from a caption is not proof it is unaffected—full bill text review is needed for comprehensive coverage.</details></div><div class="agency-find"><label for="agency-find">Find an agency</label><input id="agency-find" type="search" maxlength="80" placeholder="Name or short form, e.g. TCEQ" autocomplete="off"><span id="agency-find-note" class="tools-note" aria-live="polite"></span></div><ul class="agency-list" id="agency-list">${agencies.map(row).join('')}</ul>${none?`<p class="agency-more" id="agency-more">${none} more ${none===1?'agency has':'agencies have'} no bills in this snapshot. <button type="button" class="text-link" id="agency-show-all" aria-expanded="false">Show all ${agencies.length}</button></p>`:''}`;
}


export function showAgencyChoices(query=''){
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
  popup.querySelectorAll('[data-agency-group]').forEach(group=>{group.hidden=!group.querySelector('[data-agency-option]:not([hidden])')});
  $('#agency-no-results').hidden=visible!==0;
  popup.hidden=false;
  $('#agency-panel').hidden=false;
  input.setAttribute('aria-expanded','true');
  input.removeAttribute('aria-activedescendant');
  popup.scrollTop=0;
}

export function hideAgencyChoices(){
  const input=$('#filter-agency'),popup=$('#agency-options');
  if(!input||!popup)return;
  popup.hidden=true;
  $('#agency-panel').hidden=true;
  input.value=state.agency?agencyName(state.agency):'';
  input.setAttribute('aria-expanded','false');
  input.removeAttribute('aria-activedescendant');
}

// Re-sort the open list in place, keeping what has been typed.
export function setAgencySort(mode){
  state.agencySort=mode==='count'?'count':'name';
  try{localStorage.setItem(AGENCY_SORT_KEY,state.agencySort)}catch{}
  const input=$('#filter-agency'),popup=$('#agency-options');
  if(!input||!popup)return;
  popup.innerHTML=agencyOptionsMarkup(agencyName);
  document.querySelectorAll('[data-agency-sort]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.agencySort===state.agencySort)));
  showAgencyChoices(input.value);
}

export function pickAgency(id){
  state.agency=id;
  state.visibleCount=30;
  hideAgencyChoices();
  renderResults();
}

export function handleAgencyKeydown(event){
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
