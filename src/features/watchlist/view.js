// The watchlist page's top: the banner for a shared or view-only list, and the save, share and sync tools. The click
// handlers are in actions.js.
import {state, runtime} from '../../core/state.js';
import {STORAGE_OK} from '../../core/storage.js';
import {heldCount} from '../../core/move.js';
import {esc} from '../../core/dom.js';
import {sync, listStore} from '../sync/lists.js';

export function sharedBanner(){
  if(!state.sharedList)return '';
  const view=state.sharedMode==='sync-view';
  return `<div class="info-callout shared-banner"><div><strong>${view?'Shared watchlist (view-only)':'Shared list'} · ${state.sharedList.length} ${state.sharedList.length===1?'bill':'bills'}.</strong> ${view?'It stays current as its owner edits it.':'Opened from a link; your own watchlist is unchanged.'}</div><div class="tools-row"><button class="outline-button" id="shared-add">Add all to my watchlist</button><button class="outline-button" id="shared-close">Show all bills</button></div></div>`;
}

// Items a sync limit or a move kept aside are listed on the Export page; say so where saving is managed.
function keptNote(){const n=STORAGE_OK?heldCount(listStore):0;
  return n?`<p class="tools-note">${n} saved ${n===1?'item is':'items are'} kept aside because ${n===1?'it':'they'} did not fit a list limit or ${n===1?'was':'were'} not valid. <a class="text-link" href="#export" data-view="export">See them on the Export page</a>.</p>`:''}
export function watchTools(){
  const linked=sync.linked,n=state.watch.size,none=n?'':'disabled';
  const syncPart=runtime.syncAvailable===false?'<p class="tools-note">Private sync links aren’t switched on for this site yet. Use a share link or a file to move your list for now.</p>'
    :linked?.editKey?`<p class="tools-note">This device is synced; changes save automatically.</p><div class="tools-row"><button class="outline-button" id="sync-copy-edit">Copy edit link</button><button class="outline-button" id="sync-copy-view">Copy view-only link</button><a class="outline-button" href="./api/sync/feed/${esc(linked.viewKey||'')}.xml" target="_blank" rel="noopener noreferrer">Watchlist RSS</a></div><p class="tools-note">Open the <strong>edit link</strong> on your other devices. Anyone who has it can change this list, so keep it private, like a password. The <strong>view-only link</strong> is safe to share.</p><div class="tools-row"><button class="text-button" id="sync-forget">Stop syncing on this device</button><button class="text-button danger" id="sync-delete">Delete sync link</button></div>`
    :`<p class="tools-note">Get a private link that keeps this watchlist the same on your phone, laptop and work computer. No account, email or name.</p><div class="tools-row"><button class="primary-button" id="sync-create" ${runtime.syncAvailable?'':'disabled'}>Create sync link</button></div><p class="tools-note">Already have one? Open it on this device.</p>`;
  const synced=Boolean(linked?.editKey);
  const syncState=synced?'Synced across your devices':'This device only';
  return `<details class="watch-save" id="watch-save"${state.watchSaveOpen?' open':''}><summary><span>Save, share and sync</span><span class="watch-sync-state${synced?' synced':''}">${syncState}</span></summary><div class="watch-tools">${keptNote()}<section><h3>Save and share</h3><p class="tools-note">Your watchlist is kept in this browser. To move it to another device or person:</p><div class="tools-row"><button class="outline-button" id="share-watch" ${none}>Copy share link</button><button class="outline-button" id="export-watch" ${n||state.follow.length||state.searches.length?'':'disabled'} title="Your watchlist, followed legislators and saved searches, in one file">Export file</button><button class="outline-button" id="import-watch">Import file</button><input type="file" id="import-watch-file" accept=".json,.txt,.csv,application/json,text/plain,text/csv" hidden></div><p class="tools-note">Each bill also has an RSS feed in its details, for following it in Outlook or a feed reader. <a href="#saving" data-view="saving">How saving works →</a></p></section><section><h3>Sync across devices</h3>${syncPart}</section></div></details>`;
}
