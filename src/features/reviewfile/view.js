// The bill page's "Full text & highlighted evidence" section: a review file opened here stays in this page session.
import {toast} from '../../core/dom.js';
import {reviewModel, renderReview} from './render.js';

const reviews = new Map();

// The caller appends `section`, then calls `draw` (it renders into the attached section).
export function reviewFileSection(b){
  const reviewSection=document.createElement('section');reviewSection.className='drawer-section';
  const heading=document.createElement('h3');heading.textContent='Full text & highlighted evidence';
  const area=document.createElement('div');area.className='review-file-area';
  const local=document.createElement('input');local.type='file';local.accept='.json,application/json';local.hidden=true;
  const load=document.createElement('button');load.className='outline-button';load.textContent='Open a review file';
  load.addEventListener('click',()=>local.click());
  const draw=()=>{if(reviews.has(b.id))renderReview(area,reviews.get(b.id),true);else{const note=document.createElement('p');note.textContent='A reviewed full-text analysis is not yet available. Review files open only in this browser session.';area.replaceChildren(note);}};
  local.addEventListener('change',async()=>{try{const file=local.files[0];if(!file)return;if(file.size>15*1024*1024)throw Error('Select a file smaller than 15 MB');const bundle=JSON.parse(await file.text());reviewModel(bundle);if(bundle.bill_id!==b.id)throw Error('This review belongs to '+bundle.bill_id);reviews.set(b.id,bundle);draw();toast('Private review opened');}catch(error){toast('Review could not be opened: '+error.message)}});
  reviewSection.append(heading,load,local,area);
  return {section:reviewSection,draw};
}
