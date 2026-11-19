// The explorer's matching: each bill's search text, why a result matched, and the filtered, sorted list for the
// explorer's own filters or a saved search's. No DOM.
import {state} from '../../core/state.js';
import {statuteKeysFor, parseStatuteQuery} from '../statutes/model.js';
import {authorshipParty, searchTerms, partyFilterMatches, assessHearing, lastActionInfo, textMatches, newestFirst, authorInfluence} from '../../taxonomy.js';
import {searchFields, searchText, matchReasons} from '../search/model.js';
import {agencyName, realAgencies} from '../../core/labels.js';
import {shortDate} from '../../core/format.js';
import {companionsOf, agencyVia} from '../companions/view.js';
import {inArea} from '../areas/model.js';

export const lawKeysFor=query=>state.statutes?statuteKeysFor(state.statutes,parseStatuteQuery(query,state.statutes.codes)):[];

// What a card shows about its authors' parties ("Republican author"), so a search can find it.
const partyWords=b=>{if(!b.people)return[];const p=authorshipParty(b);return[p.label,p.detail]};

const billSearchFields=b=>searchFields(b,{agencyName,partyWords,shortDate});
// Each bill's search text, kept across keystrokes. Bills are replaced, not edited, when their data changes; agency
// names also come from Luna's file, so a new one starts the cache over.
const searchTextCache={luna:undefined,texts:new WeakMap()};
function billSearchText(b){
  if(searchTextCache.luna!==state.luna)Object.assign(searchTextCache,{luna:state.luna,texts:new WeakMap()});
  let text=searchTextCache.texts.get(b);
  if(text===undefined){text=searchText(billSearchFields(b));searchTextCache.texts.set(b,text)}
  return text;
}
// Why a shown result matched the explorer's search words, in the same order of checks as filteredBills.
export function reasonFor(){
  const {q,compact}=searchTerms(state.query||'');
  if(!q)return ()=>null;
  const lawBills=new Set(lawKeysFor(state.query).flatMap(k=>state.statutes.sections[k].b.map(p=>p[0])));
  return b=>matchReasons(billSearchFields(b),q,lawBills.has(b.id)?'law':b.id.toLowerCase().includes(compact)?'number':'');
}

// The explorer's list for its own filters, or for a saved search's (`f`: the explorer as a plain, unshared view).
export function filteredBills(f=state){
  const own=f===state;
  const shared=own&&state.sharedList?new Set(state.sharedList):null;
  const {q,compact}=searchTerms(f.query||'');
  // A section number ("48.160", "Penal Code 46.06") also finds the bills that change that section.
  const lawBills=new Set(lawKeysFor(f.query).flatMap(k=>state.statutes.sections[k].b.map(p=>p[0])));
  let list=state.bills.filter(b=>{
    if(shared&&!shared.has(b.id))return false;
    if(own&&state.view==='watchlist'&&!state.watch.has(b.id))return false;
    if(f.onlyWatch&&!state.watch.has(b.id))return false;
    if(f.companion&&!companionsOf(b.id).length)return false;
    if(f.area&&!inArea(b,f.area))return false;
    if(f.topic&&!b.topics.includes(f.topic))return false;
    if(f.agency&&!b.agencies.some(a=>a.id===f.agency)&&!agencyVia(f.agency).has(b.id))return false;
    if(f.chamber&&b.chamber!==f.chamber)return false;
    if(!partyFilterMatches(b,f.party))return false;
    if(f.outlook&&assessHearing(b).label!==f.outlook)return false;
    if(f.action&&lastActionInfo(b).label!==f.action)return false;
    if(f.stage){const st=(b.status||'').toLowerCase();const outlook=assessHearing(b).label.toLowerCase();if(!st.includes(f.stage.toLowerCase())&&outlook!==f.stage.toLowerCase())return false}
    if(lawBills.has(b.id))return true;
    return !q||b.id.toLowerCase().includes(compact)||textMatches(billSearchText(b),q);
  });
  const byNumber=(a,b)=>a.id.localeCompare(b.id,undefined,{numeric:true});
  const newerNumber=(a,b)=>newestFirst(a.id,b.id);
  const info=new Map(list.map(b=>[b.id,lastActionInfo(b)]));const la=b=>info.get(b.id);
  // Filing dates have no time, so within a day the higher number in each bill type was filed later.
  const sorters={newest:(a,b)=>(b.filed_at||'').localeCompare(a.filed_at||'')||newerNumber(a,b),
    latest:(a,b)=>(la(b).date||'').localeCompare(la(a).date||'')||la(b).rank-la(a).rank||byNumber(a,b),
    oldest:(a,b)=>(la(a).date||'9').localeCompare(la(b).date||'9')||la(a).rank-la(b).rank||byNumber(a,b),
    actionstage:(a,b)=>la(b).rank-la(a).rank||(la(b).date||'').localeCompare(la(a).date||'')||byNumber(a,b),number:byNumber,agencies:(a,b)=>realAgencies(b).length-realAgencies(a).length||byNumber(a,b),hearing:(a,b)=>assessHearing(b).level-assessHearing(a).level||byNumber(a,b),influence:(a,b)=>authorInfluence(b).level-authorInfluence(a).level||byNumber(a,b)};
  return list.sort(Object.hasOwn(sorters,f.sort)?sorters[f.sort]:sorters.newest);  // own keys only: "__proto__" is not a sort
}
