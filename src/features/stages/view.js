// The bill page's stage sections (what changed, hearing witnesses, fiscal note check): fetches the bill's stage
// files and appends each section that validates.
import {state} from '../../core/state.js';
import {timeoutSignal, discard} from '../../core/net.js';
import {validChanges, renderChanges, renderHearing, validFiscal, renderFiscal} from './render.js';

// The open bill's stage files; only the redraw after Luna loads (reuse) may share them, every opening asks again.
export const stageFiles={id:null,files:null,reuse:false};
export function stageSections(b){
  const holder=document.createElement('div');
  if(!/^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}$/.test(b.id))return holder;
  const getJson=async url=>{try{const r=await fetch(url,{cache:'no-cache',signal:timeoutSignal(20000)});return r.ok?await r.json():discard(r)}catch{return null}};
  const show=node=>{if(node&&state.openBill===b.id&&holder.isConnected!==false)holder.append(node)};
  if(!(stageFiles.reuse&&stageFiles.id===b.id&&stageFiles.files)){
    stageFiles.id=b.id;
    stageFiles.files=Promise.all([
      getJson(`./live/text/${b.id}/index.json`),getJson(`./live/luna/changes/${b.id}.json`),
      getJson(`./live/history/${b.id}/witnesses-H.json`),getJson(`./live/history/${b.id}/witnesses-S.json`),
      getJson(`./live/luna/fiscal/${b.id}.json`),getJson(`./live/luna/highlights/${b.id}.json`)]);
  }
  const files=stageFiles.files;
  (async()=>{
    const [index,changes,witH,witS,fiscal,highlights]=await files;
    if(state.openBill!==b.id)return;
    try{if(changes&&validChanges(changes,b.id,index))show(renderChanges(changes,index))}catch(e){console.warn('Changes hidden',e.message)}
    try{show(renderHearing([witH,witS]))}catch(e){console.warn('Hearing hidden',e.message)}
    try{
      // Current review = the tags entry's text_version plus the highlights file made on that same version (it carries the sha).
      const current=b.luna&&highlights&&highlights.text_version===b.luna.text_version?{text_version:b.luna.text_version,text_sha256:highlights.text_sha256}:null;
      if(fiscal&&validFiscal(fiscal,b.id,current))show(renderFiscal(fiscal,b.id));
    }catch(e){console.warn('Fiscal check hidden',e.message)}
  })();
  return holder;
}
