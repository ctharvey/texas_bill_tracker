export const $ = (selector, root=document) => root.querySelector(selector);
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// hold: the message stays, selectable, until its Close button (text someone must copy by hand, like a refused clipboard).
export function toast(message,{hold=false}={}){const t=$('#toast');clearTimeout(toast.timer);t.classList.toggle('held',hold);t.textContent=message;
  if(hold){const close=document.createElement('button');close.type='button';close.className='toast-close';close.textContent='Close';close.addEventListener('click',()=>t.classList.remove('visible','held'));t.append(' ',close)}
  t.classList.add('visible');if(!hold)toast.timer=setTimeout(()=>t.classList.remove('visible'),2500)}
