// Moving saved data from the old address (MOVE_FROM) to the new one (MOVE_TO); see core/move.js. The old site's banner
// and send, and the new site's receive; runtime.moveStatus holds where it stands.
import {STORAGE_OK, writeJson, prefsKey, readJson, storageKey, followKey, searchesKey, loadSaved} from '../../core/storage.js';
import {moveTarget, moveSource, moveNeeded, receive, collect, MOVED_KEY, digest} from '../../core/move.js';
import {$} from '../../core/dom.js';
import {runtime, state} from '../../core/state.js';
import {oldSiteBanner, savedSummary, newSiteResult} from './view.js';
import {sync, changeWatch, changeFollow, changeSearch, pullSync, refreshWatch} from '../sync/lists.js';
import {sendMove, receiveMove, newNonce} from './handoff.js';
import {setTheme, applyMode, savedTheme} from '../theme/view.js';
import {withMode} from '../theme/model.js';
import {keptPrefs} from '../../core/location.js';
import {NEAR_KEY, cleanNear} from '../../geo.js';
import {AGENCY_SORT_KEY} from '../explorer/controls.js';
import {applyMove} from './apply.js';
import {readWatch, readFollows, readSearches} from '../../core/lists.js';

export const MOVE_TO=STORAGE_OK?moveTarget(location.origin):null,MOVE_FROM=STORAGE_OK?moveSource(location.origin):null;
export function renderMoveBanner(){
  const el=$('#move-banner');if(!el)return;
  let html='';
  if(MOVE_TO){
    const status=runtime.moveStatus==='moving'||runtime.moveStatus?.startsWith?.('failed:')?runtime.moveStatus:moveNeeded(localStorage)?'offer':runtime.moveStatus==='moved'?'moved':'gone';
    html=oldSiteBanner({status,target:MOVE_TO,goHref:MOVE_TO+location.pathname+location.hash,what:status==='offer'||status.startsWith('failed:')?savedSummary(receive(collect(localStorage))):''});
  }else if(MOVE_FROM&&runtime.moveStatus)html=newSiteResult(runtime.moveStatus,MOVE_FROM);
  el.innerHTML=html;el.hidden=!html;
}
export async function startMove(){
  if(!MOVE_TO||runtime.moveStatus==='moving')return;
  // Opened inside the click, so the browser allows it; never noopener: the new page answers its opener.
  const win=window.open(`${MOVE_TO}${location.pathname}#move`,'_blank');
  if(!win){runtime.moveStatus='failed:blocked';renderMoveBanner();return}
  runtime.moveStatus='moving';renderMoveBanner();
  let payload=null;
  const result=await sendMove({self:window,win,target:MOVE_TO,getPayload:async()=>{try{await sync.flush()}catch{}payload=collect(localStorage);return payload}});
  if(result.ok&&payload){
    try{localStorage.setItem(MOVED_KEY,JSON.stringify({digest:digest(receive(payload)),at:new Date().toISOString()}))}catch{}
    runtime.moveStatus='moved';
  }else runtime.moveStatus=`failed:${result.counts?.why==='sync'?'sync':result.reason||'failed'}`;
  renderMoveBanner();
}
function moveSettings(settings){
  if(settings.theme){const id=setTheme(settings.theme);if(sync.linked?.mode==='edit')sync.record('theme',id)}
  if(settings.mode){writeJson(prefsKey,withMode(readJson(prefsKey),settings.mode));applyMode(settings.mode)}
  if(settings.filters)writeJson(prefsKey,{...keptPrefs(),filters:settings.filters});
  if(settings.near){writeJson(NEAR_KEY,settings.near);state.near=cleanNear(settings.near,state.nearGeo?.tables)}
  if(settings.agencySort){state.agencySort=settings.agencySort;try{localStorage.setItem(AGENCY_SORT_KEY,settings.agencySort)}catch{}}
}
export async function receiveArrivingMove(bootReady){
  if(!window.opener){await bootReady;runtime.moveStatus={ok:false,reason:'no-opener'};renderMoveBanner();return}
  const result=await receiveMove({self:window,opener:window.opener,source:MOVE_FROM,nonce:newNonce(),apply:async payload=>{await bootReady;return applyMove(payload,{
    storage:localStorage,
    current:()=>{const prefs=keptPrefs();return {watch:readWatch(localStorage,storageKey),follows:readFollows(localStorage,followKey),searches:readSearches(localStorage,searchesKey),
      settings:{theme:savedTheme(),mode:prefs.mode??null,filters:prefs.filters??null,near:readJson(NEAR_KEY),agencySort:(()=>{try{return localStorage.getItem(AGENCY_SORT_KEY)}catch{return null}})()},
      syncKey:readJson('tx-bill-atlas-sync-v1')?.key||null}},
    addWatch:ids=>changeWatch('add',ids),
    addFollows:codes=>changeFollow('follow',codes),
    addSearch:s=>changeSearch('save-search',s),
    setSettings:moveSettings,
    joinLink:async key=>{sync.connect(key);if(runtime.syncAvailable===null)runtime.syncAvailable=await sync.isAvailable();await pullSync()},
    flush:async()=>{if(runtime.syncAvailable&&sync.linked?.mode==='edit')await sync.flush()},
  })}});
  await bootReady;
  runtime.moveStatus=result;
  loadSaved();refreshWatch();renderMoveBanner();
}
export const movePreviousKey=()=>runtime.moveStatus?.previousKey||null;
