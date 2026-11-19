// Explorer filter controls: select options, and the affected-agency dropdown's options and A-Z / most-bills sort.
import {esc} from '../../core/dom.js';
import {state} from '../../core/state.js';
import {groupAgencyIds, AGENCIES} from '../../taxonomy.js';
import {unique} from '../../core/format.js';
import {agencyName} from '../../core/labels.js';

export function options(values,selected,placeholder){return `<option value="">${esc(placeholder)}</option>`+values.map(v=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(v)}</option>`).join('')}

// The agency dropdown's sort, A-Z or most bills first; remembered in this browser only.
export const AGENCY_SORT_KEY='tx-bill-atlas-agency-sort';
function agencySortMode(){
  if(!state.agencySort){try{state.agencySort=localStorage.getItem(AGENCY_SORT_KEY)==='count'?'count':'name'}catch{state.agencySort='name'}}
  return state.agencySort;
}
export function agencyOptionsMarkup(){
  const agencyCounts=new Map();
  for(const bill of state.bills)for(const agency of bill.agencies)agencyCounts.set(agency.id,(agencyCounts.get(agency.id)||0)+1);
  const {withBills,withoutBills}=groupAgencyIds(unique([...AGENCIES.map(a=>a.id),...Object.keys(state.luna?.agencies||{})]),agencyName,agencyCounts,agencySortMode());
  const option=(id,i)=>`<div id="agency-option-${i+1}" role="option" class="agency-option" data-agency-option="${esc(id)}" data-agency-label="${esc(agencyName(id))}" aria-selected="${state.agency===id}"><span>${esc(agencyName(id))}</span><span class="agency-option-count">${agencyCounts.get(id)||0}</span></div>`;
  const emptyGroup=withoutBills.length?`<div role="group" aria-labelledby="agency-group-empty" data-agency-group><div class="agency-group-label" id="agency-group-empty" role="presentation">No bills in this snapshot</div>${withoutBills.map((id,i)=>option(id,withBills.length+i)).join('')}</div>`:'';
  return `<div id="agency-option-0" role="option" class="agency-option" data-agency-option="" data-agency-label="All affected agencies" aria-selected="${!state.agency}"><span>All affected agencies</span></div>${withBills.map(option).join('')}${emptyGroup}<p class="agency-no-results" id="agency-no-results" hidden>No matching agencies</p>`;
}
export function agencySortButtons(){
  const mode=agencySortMode();
  return [['name','A–Z'],['count','Most bills']].map(([value,label])=>`<button type="button" data-agency-sort="${value}" aria-pressed="${mode===value}">${label}</button>`).join('');
}
