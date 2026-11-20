// Addresses of the app's own pages, as real links (new tab, copy link) that also open in place.
import {state} from './state.js';
import {buildUrl} from '../prefs.js';

// A bill's page address (/bill/<ID>), so a bill title is a real link (new tab, copy link) as well as a click target.
export function billHref(id){
  return buildUrl('bill',{},{list:state.sharedMode==='link'?state.sharedList:null,bill:id,
    sync:state.sharedMode==='sync-view'?state.sharedSyncKey:null});
}
export const memberHref=code=>buildUrl('member',{},{member:code});
// The site root, whatever page is open: a bill page's path is /bill/<ID>.
export const siteBase=()=>`${location.origin}/`;
