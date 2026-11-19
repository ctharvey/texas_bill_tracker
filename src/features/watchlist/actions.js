// The watchlist's save, share and sync buttons, and importing a saved-items file (bills, follows, searches, theme).
// List changes go through sync/lists.js; redraws and the address save through core/router.js.
import {sync, changeWatch, refreshWatch, listStore, changeFollow, changeSearch} from '../sync/lists.js';
import {copyText, download} from '../../core/copy.js';
import {siteBase} from '../../core/links.js';
import {buildHash, profileFile, parseProfileFile, MAX_SEARCHES} from '../../prefs.js';
import {state} from '../../core/state.js';
import {isLawFollowQuery, lawFollowsOf} from '../statutes/model.js';
import {savedTheme, setTheme} from '../theme/view.js';
import {toast, $} from '../../core/dom.js';
import {readWatch, readFollows, readSearches} from '../../core/lists.js';
import {storageKey, followKey, searchesKey, loadSaved} from '../../core/storage.js';
import {persistState, renderContent} from '../../core/router.js';

export async function handleSaveClick(target){
  const hit=sel=>target.closest(sel);
  if(hit('#copy-view-link')){persistState();return copyText(location.href,'Link to this view')}
  if(hit('#share-watch'))return copyText(siteBase()+buildHash('all',{},{list:[...state.watch]}),'Share link');
  if(hit('#export-watch')){download('texas-bill-atlas-saved.json',profileFile({watch:state.watch,follows:state.follow,searches:state.searches,theme:savedTheme()}),'application/json');return toast('Watchlist, followed legislators and saved searches exported')}
  if(hit('#import-watch')){$('#import-watch-file').click();return}
  if(hit('#shared-add')){const before=state.watch.size;changeWatch('add',state.sharedList);refreshWatch();return toast(`Added ${state.watch.size-before} bills to your watchlist`)}
  if(hit('#shared-close')){Object.assign(state,{sharedList:null,sharedMode:null,sharedSyncKey:null,visibleCount:30});return renderContent()}
  if(hit('#sync-create')){try{await sync.create(readWatch(listStore,storageKey),readFollows(listStore,followKey),readSearches(listStore,searchesKey));loadSaved();renderContent();toast('Sync link created. Copy the edit link to your other devices.')}catch(error){toast(error.message)}return}
  if(hit('#sync-copy-edit'))return copyText(siteBase()+'#watchlist?sync='+sync.linked.editKey,'Edit link');
  if(hit('#sync-copy-view'))return copyText(siteBase()+'#watchlist?sync='+sync.linked.viewKey,'View-only link');
  if(hit('#sync-forget')){sync.forget();renderContent();return toast('This device stopped syncing; your list stays here')}
  const del=hit('#sync-delete');
  if(del){
    if(del.dataset.armed!=='1'){del.dataset.armed='1';del.textContent='Click again to delete for every device';return}
    try{await sync.remove();renderContent();toast('Sync link deleted; your list stays on this device')}catch(error){toast(error.message)}
  }
}

export async function importWatchlist(file){
  try{
    if(file.size>1024*1024)throw Error('Select a file smaller than 1 MB');
    const {bills,follows,searches,theme}=parseProfileFile(await file.text()),before=state.watch.size,followed=state.follow.length;
    if(theme){const id=setTheme(theme);if(sync.linked?.mode==='edit')sync.record('theme',id)}  // Like the bills below, a linked device syncs it.
    changeWatch('add',bills);changeFollow('follow',follows);
    // A law already followed here is skipped, so importing another device's file does not follow it twice.
    const lawOf=s=>isLawFollowQuery(s.filters?.query)&&lawFollowsOf([s],s.filters.query).length?s.filters.query:null;
    const known=new Set(state.searches.map(s=>s.id)),laws=new Set(state.searches.map(lawOf).filter(Boolean));
    const added=searches.filter(s=>{if(known.has(s.id))return false;const law=lawOf(s);
      if(law){if(laws.has(law))return false;laws.add(law)}return true}).slice(0,Math.max(0,MAX_SEARCHES-state.searches.length));
    for(const s of added)changeSearch('save-search',s);
    refreshWatch();
    toast(`Added ${state.watch.size-before} of ${bills.length} bills${follows.length?`, ${state.follow.length-followed} of ${follows.length} legislators`:''}${searches.length?`, ${added.length} of ${searches.length} saved searches`:''}`);
  }catch(error){toast(`Import failed: ${error.message}`)}
}
