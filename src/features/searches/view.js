// Saved searches on the Following page: each search's summary line and counts, and the page itself with followed
// legislators. Saving a search stays with the list and sync code (sync/lists.js).
import {state} from '../../core/state.js';
import {esc} from '../../core/dom.js';
import {buildHash} from '../../prefs.js';
import {shortDate} from '../../core/format.js';
import {followedMarkup} from '../follows/view.js';
import {SORTS, agencyName, areaName} from '../../core/labels.js';
import {searchCounts} from '../sync/lists.js';

function searchSummary(f){
  const parts=[f.query&&`Search “${f.query}”`,f.area&&`Area: ${areaName(f.area)}`,f.topic&&`Topic: ${f.topic}`,f.agency&&`Agency: ${agencyName(f.agency)}`,f.chamber,f.party&&`Party: ${f.party} authors`,f.stage&&`Stage: ${f.stage}`,
    f.outlook&&`Hearing: ${f.outlook}`,f.action&&`Last action: ${f.action}`,f.companion&&'Has a companion bill',f.onlyWatch&&'Watched bills only',f.sort&&f.sort!=='newest'&&`Sorted by ${SORTS[f.sort]||f.sort}`].filter(Boolean);
  return parts.join(' · ')||'All bills';
}
function savedSearchesMarkup(){
  if(!state.searches.length)return `<section class="followed-section"><h3>Saved searches</h3><p class="tools-note">Set filters or a search in the <a class="text-link" href="#all" data-view="all">Bill explorer</a>, then choose <strong>Save search</strong> to keep it here, with a count of bills that moved since you last opened it.</p></section>`;
  const rows=state.searches.map(s=>{
    const {total,fresh}=searchCounts(s);
    const name=state.renamingSearch===s.id
      ?`<form class="search-rename" data-search-rename-form="${esc(s.id)}"><input name="name" maxlength="80" value="${esc(s.name)}" aria-label="Name for this search" autocomplete="off"><button class="outline-button" type="submit">Save</button></form>`
      :`<a class="text-link saved-search-name" href="${esc(buildHash('all',s.filters))}" data-search-open="${esc(s.id)}">${esc(s.name)}</a>`;
    return `<div class="saved-search">${name}<p>${esc(searchSummary(s.filters))}</p><p class="saved-search-counts"><strong>${total.toLocaleString()}</strong> ${total===1?'bill':'bills'}${fresh?` · <span class="saved-search-new">${fresh.toLocaleString()} with new actions</span>`:''}${s.seen?` · opened ${esc(shortDate(s.seen))}`:''}</p><div class="tools-row">${state.renamingSearch===s.id?'':`<button class="text-button" data-search-rename="${esc(s.id)}">Rename</button>`}<button class="text-button danger" data-search-delete="${esc(s.id)}">Delete</button></div></div>`;
  }).join('');
  return `<section class="followed-section"><h3>Saved searches <span>${state.searches.length}</span></h3><p class="tools-note">“New actions” counts bills with an action dated after the day you last opened the search.</p><div class="saved-searches">${rows}</div></section>`;
}
// Following: saved searches and followed legislators; later also named watchlists.
export function followingMarkup(){
  return `<div class="section-head"><div><div class="section-overline">FOLLOWING</div><h2>Your searches and legislators</h2></div><span class="subtitle">Saved in this browser, files and sync links</span></div>${savedSearchesMarkup()}${followedMarkup()}`;
}
