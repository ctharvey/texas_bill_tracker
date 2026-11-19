// The dialog before this device joins a synced list from an edit link. The sync client and pulls stay in app.js.
import {state} from '../../core/state.js';
import {esc} from '../../core/dom.js';

// An edit link can come from anyone, and joining adds this device's saved items to that list and keeps syncing them
// there. A device with nothing saved and no link of its own joins straight away; otherwise it asks first.
export function confirmJoin(replacing){
  const count=(n,one,many)=>n?`${n} ${n===1?one:many}`:'';
  const items=[count(state.watch.size,'bill','bills'),count(state.follow.length,'legislator','legislators'),count(state.searches.length,'saved search','saved searches')].filter(Boolean);
  if(!replacing&&!items.length)return Promise.resolve(true);
  const dialog=document.createElement('dialog');
  if(typeof dialog.showModal!=='function')return Promise.resolve(false);
  const list=items.length>1?`${items.slice(0,-1).join(', ')} and ${items.at(-1)}`:items[0];
  dialog.className='disclaimer';dialog.id='sync-join';dialog.setAttribute('aria-labelledby','sync-join-title');
  dialog.innerHTML=`<h2 id="sync-join-title">Join this synced list?</h2>
    ${items.length?`<p>This device’s ${esc(list)} will be added to the list, and anyone with its edit link will see them and every later change.</p>`:''}
    ${replacing?'<p>This device will forget its current sync link. Copy its edit link first if you still need it.</p>':''}
    <p>Only join links you got from yourself or someone you trust.</p>
    <form method="dialog" class="sync-join-actions"><button class="outline-button" value="cancel" id="sync-join-cancel" autofocus>Cancel</button><button class="disclaimer-ok" value="join" id="sync-join-ok">Join this list</button></form>`;
  document.body.append(dialog);
  return new Promise(resolve=>{
    dialog.addEventListener('close',()=>{resolve(dialog.returnValue==='join');dialog.remove()},{once:true});
    dialog.showModal();
  });
}
