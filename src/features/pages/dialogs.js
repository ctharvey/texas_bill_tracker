// The disclaimer dialog (shown once per browser, reopened from the footer) and the privacy dialog.
import {$} from '../../core/dom.js';
import {disclaimerKey} from '../../core/storage.js';

export function setupDisclaimer(){
  const dialog=$('#disclaimer');
  if(!dialog||typeof dialog.showModal!=='function')return;
  // Closing by button or Escape both count as seen; without storage it simply shows on each visit.
  dialog.addEventListener('close',()=>{try{localStorage.setItem(disclaimerKey,new Date().toISOString())}catch{}});
  $('#disclaimer-open')?.addEventListener('click',()=>{if(!dialog.open)dialog.showModal()});
  let seen=false;try{seen=Boolean(localStorage.getItem(disclaimerKey))}catch{}
  if(!seen)dialog.showModal();
  const privacy=$('#privacy');
  $('#privacy-open')?.addEventListener('click',()=>{if(privacy&&!privacy.open)privacy.showModal()});
}
