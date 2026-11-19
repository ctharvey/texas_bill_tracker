// Copying text to the clipboard (with a toast) and downloading a generated file from the page.
import {toast} from './dom.js';

export async function copyText(text,label){
  try{await navigator.clipboard.writeText(text);toast(`${label} copied`)}catch{toast(`Copy failed. ${label}: ${text}`)}
}

export function download(name,text,type){
  const u=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
}
