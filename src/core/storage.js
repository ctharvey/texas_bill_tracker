// Browser storage: keys and value shapes are unchanged, so saves made by earlier versions still load.
import {state} from './state.js';
import {readWatch, readFollows, readSearches} from './lists.js';

export const storageKey = 'tx-bill-atlas-watch-90r';
// Followed legislators (member codes): this browser, exported files and sync links; never share or view-only links.
export const followKey = 'tx-bill-atlas-follow-90r';
// Saved searches: same rules as follows (browser, files, sync links; never share or view-only links).
export const searchesKey = 'tx-bill-atlas-searches-90r';
export const prefsKey = 'tx-bill-atlas-prefs-v1';
export const disclaimerKey = 'tx-bill-atlas-disclaimer-v1';
// The dashboard's last-visit stamp {day, prev} (features/home/model.js). Its own key: loading never rewrites prefs-v1.
export const visitKey = 'tx-bill-atlas-visit-v1';
export const STORAGE_OK = (()=>{try{localStorage.setItem('__txb_test','1');localStorage.removeItem('__txb_test');return true}catch{return false}})();
export const readJson=key=>{try{return JSON.parse(localStorage.getItem(key)||'null')}catch{return null}};
export const writeJson=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value))}catch{}};
export const memoryStorage=()=>{const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)}};

// The watchlist, follows and saved searches this browser kept: read at startup and again when another tab saves.
export function loadSaved(){
  try{state.watch=new Set(readWatch(localStorage,storageKey));state.follow=readFollows(localStorage,followKey);state.searches=readSearches(localStorage,searchesKey)}catch{}
}
