import {validBracketIndex, bracketRows, placeCount, BRACKET_RELATIONS} from './model.js';

import {state} from '../../core/state.js';
import {$, esc} from '../../core/dom.js';
import {timeoutSignal} from '../../core/net.js';

// Appended after styles.css, so these rules keep the cascade position they had at the end of its law block.
const sheet = document.createElement('link');
sheet.rel = 'stylesheet';
sheet.href = new URL('./brackets.css', import.meta.url).href;
document.head.append(sheet);

// ---- Population brackets: the places that meet each population test in a bill, under the 2020 Census ----
// The index (live/brackets/index.json) is optional and loads on the first open drawer; without it the section stays hidden.
let bracketsLoad=null;
function loadBrackets(){
  return bracketsLoad||(bracketsLoad=(async()=>{
    try{
      const r=await fetch('./live/brackets/index.json',{cache:'no-cache',signal:timeoutSignal(15000)});
      if(!r.ok)throw Error(`HTTP ${r.status}`);
      const index=await r.json();
      if(!validBracketIndex(index))throw Error('Unrecognized bracket index');
      state.brackets=index;
    }catch(error){state.brackets=null;console.warn('Population brackets unavailable',error.message)}
    if(state.openBill)fillDrawerBrackets(state.openBill);
  })());
}
const BRACKET_NAMES_SHOWN=12;
const shortNames=names=>names.length>BRACKET_NAMES_SHOWN?`${names.slice(0,BRACKET_NAMES_SHOWN).join(', ')} and ${names.length-BRACKET_NAMES_SHOWN} more`:names.join(', ');
function bracketNames(names,n,kind){
  if(!names)return `<span class="bracket-many">${esc(placeCount(n,kind))}</span>`;
  if(!names.length)return `<span class="bracket-many">No Texas ${kind==='county'?'county':'city'} meets this test.</span>`;
  const shown=names.slice(0,BRACKET_NAMES_SHOWN),rest=names.slice(BRACKET_NAMES_SHOWN);
  return `${esc(shown.join(', '))}${rest.length?`<details class="law-more"><summary>and ${rest.length} more</summary>${esc(rest.join(', '))}</details>`:''}`;
}
function bracketItem(r){
  const noun=r.kind==='county'?'Counties':'Cities';
  const where=r.section?` · ${esc(r.section.replace(/^SECTION/i,'Section'))}`:'';
  const related=r.rel?`<p class="bracket-related"><small>Describes ${esc(BRACKET_RELATIONS[r.rel])}.</small></p>`:'';
  const head=`<strong>${noun} with a population ${/^between /i.test(r.test)?'':'of '}${esc(r.test)}</strong> <small>${r.status==='changed'?'· threshold changed':r.status==='new'?'· new in this bill':''}${where}${r.times>1?` · appears ${r.times} times`:''}</small>`;
  if(r.census)return `<li${r.rel?' class="bracket-rel"':''}>${head}${related}<p><small>Tied to the ${r.census} census, so not matched to places here.</small></p></li>`;
  const meets=r.n===null?'':`<p>${r.n===0||!r.names?'':`${esc(placeCount(r.n,r.kind))} ${r.n===1?'meets':'meet'} this test: `}${r.names||!r.n?bracketNames(r.names,r.n,r.kind):`${esc(placeCount(r.n,r.kind))} meet this test.`}</p>`;
  const was=r.was?`<p class="bracket-was"><small>Was ${esc(r.was.test)}${r.was.n!==null?` (${esc(placeCount(r.was.n,r.kind))})`:''}.${r.was.added?` Newly meets the test: ${r.was.addedNames?esc(shortNames(r.was.addedNames)):esc(placeCount(r.was.added,r.kind))}.`:''}${r.was.dropped?` No longer meets it: ${r.was.droppedNames?esc(shortNames(r.was.droppedNames)):esc(placeCount(r.was.dropped,r.kind))}.`:''}</small></p>`:'';
  const cond=r.cond?'<p><small>The bill adds other conditions here, so fewer places may qualify; see the bill text.</small></p>':'';
  const near=r.near.length?`<p><small>Close to the line: ${esc(r.near.map(p=>`${p.name}${Number.isInteger(p.pop)?` (${p.pop.toLocaleString('en-US')})`:''}`).join(', '))}. The 2030 census could move them across it.</small></p>`:'';
  return `<li${r.rel?' class="bracket-rel"':''}>${head}${related}${meets}${was}${r.rel?'':cond}${near}</li>`;
}
export function fillDrawerBrackets(id){
  const el=$('#drawer-brackets');
  if(!el||state.openBill!==id)return;
  if(!state.brackets){el.hidden=true;el.innerHTML='';loadBrackets();return}
  const entry=state.brackets.bills[id];
  const rows=bracketRows(entry,state.brackets.places);
  if(!rows.length&&!entry?.u){el.hidden=true;el.innerHTML='';return}
  const mine=rows.filter(r=>r.status==='new'||r.status==='changed'),quoted=rows.filter(r=>r.status==='existing'),struck=rows.filter(r=>r.status==='removed');
  el.innerHTML=`<h3>Population limits</h3>
    <p>Texas often aims a law at certain places by population. Each list shows the places that meet the population test under the 2020 Census.</p>
    ${mine.length?`<ul class="bracket-list">${mine.map(bracketItem).join('')}</ul>`:'<p><small>This bill adds no new population limits.</small></p>'}
    ${quoted.length?`<details class="law-more"><summary>Limits already in the law this bill quotes (${quoted.length})</summary><ul class="bracket-list">${quoted.map(bracketItem).join('')}</ul></details>`:''}
    ${struck.length?`<details class="law-more"><summary>Limits this bill strikes (${struck.length})</summary><ul class="bracket-list">${struck.map(bracketItem).join('')}</ul></details>`:''}
    ${entry?.u?`<p><small>${entry.u} population ${entry.u===1?'limit':'limits'} in this bill could not be read; see the bill text.</small></p>`:''}`;
  el.hidden=false;
}
