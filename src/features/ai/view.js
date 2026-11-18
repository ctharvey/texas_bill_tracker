// "Copy for AI" on a bill and "Copy page for AI" in the top bar. The page helpers they use still live in app.js
// and arrive as the second argument.
import {state} from '../../core/state.js';
import {$, toast} from '../../core/dom.js';
import {memberByCode} from '../../geo.js';
import {aiPrompt, pageAiText} from './model.js';

async function copyToClipboard(text){
  try{await navigator.clipboard.writeText(text);return true}catch{}
  try{
    const t=document.createElement('textarea');t.value=text;t.setAttribute('readonly','');t.style.cssText='position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(t);t.select();const ok=document.execCommand('copy');t.remove();return ok;
  }catch{return false}
}
// Top-bar button: the open bill, or the list/page on screen, as text for an AI assistant.
export async function copyPageForAi(button,{memberTitle,todayData,agencyName,companionsOf,agencyVia,filteredBills,nearData,memberData}){
  const bill=state.openBill?state.bills.find(x=>x.id===state.openBill):null;
  const member=state.view==='member'?memberByCode(state.roster,state.memberCode):null;
  const labels={home:'Home',all:'Bill explorer',watchlist:'Watchlist',following:'Following',today:'Today',local:'Near you',member:member?`Bills by ${memberTitle(member)}`:'Member'};
  const today=state.view==='today'?todayData():null;
  const text=pageAiText({view:state.view,label:labels[state.view]||state.view,pageUrl:location.href,bill,agencyName,
    companions:companionsOf,via:state.view==='today'||state.view==='member'?null:agencyVia(),
    bills:today?today.shown.map(r=>r.bill):['all','watchlist'].includes(state.view)?filteredBills():state.view==='local'&&state.near?(d=>[...d.members,...d.local].map(r=>r.bill).filter((b,i,a)=>a.indexOf(b)===i))(nearData()):member?Object.values(memberData(member)).flat().map(r=>r.bill):state.view==='following'&&state.roster?followedBills(state.bills,state.roster,state.follow,newestFirst).map(r=>r.bill):[],
    day:today?today.day:null,filters:{query:state.query,topic:state.view==='today'?state.todayTopic:state.topic,
      agency:state.agency,chamber:state.chamber}});
  const label=button.dataset.label||(button.dataset.label=button.textContent);
  if(await copyToClipboard(text)){button.textContent='Copied';clearTimeout(button.timer);button.timer=setTimeout(()=>{button.textContent=label},2000)}
  else toast('Copy failed; your browser blocked the clipboard');
}

export async function copyForAi(button,{companionsOf}){
  const b=state.bills.find(x=>x.id===state.openBill);if(!b)return;
  const text=aiPrompt(b,companionsOf(b.id));
  if(await copyToClipboard(text)){
    button.textContent='Copied';clearTimeout(button.timer);button.timer=setTimeout(()=>{button.textContent='Copy for AI'},2000);
  }else{
    // Last resort: show the text, selected, so it can be copied by hand.
    let box=$('#ai-fallback');
    if(!box){box=document.createElement('textarea');box.id='ai-fallback';box.className='ai-fallback';box.readOnly=true;box.rows=6;(button.closest('.ai-copy')||button.closest('.bill-head')||button.parentElement).append(box)}
    box.value=text;box.focus();box.select();toast('Press Ctrl+C to copy');
  }
}
