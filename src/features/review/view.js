// The review progress page (#review): the live run, each pass's backlog, recent reviews and updates, and the one-bill
// lookup. app.js passes its formatters and row renderers in, and keeps the refresh timer.
import {state} from '../../core/state.js';
import {esc} from '../../core/dom.js';
import {auditLine, reviewProgress, reviewSummary} from '../../taxonomy.js';
import {newestReviewed} from '../home/model.js';
import {runState, passRows, passJobs, lookup, RUN_LIMIT_MINUTES} from './model.js';
import {updateEntries} from './updates.js';

const clockText=ms=>new Date(ms).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/Chicago'})+' CT';
export function reviewParts(){
  const ids=state.bills.map(b=>b.id),status=state.reviewStatus,tagged=state.luna?.bills||{};
  return {ids,status,tagged,summary:reviewSummary(reviewProgress(ids,status,Object.keys(tagged))),run:runState(status,Date.now())};
}
// One bill's state, for the lookup box: a chip that opens the bill, and what is happening to it.
export function reviewLookupHtml(text,{dateText}){
  const {ids,summary,tagged}=reviewParts(),found=lookup(text,summary,ids);
  if(!found)return String(text||'').trim()?'<span class="review-lookup-hint">Type a bill number, such as HB 474 or SJR 9.</span>':'';
  if(found.state==='unknown')return `<span class="review-lookup-hint">${esc(found.id)}: ${esc(found.label)}.</span>`;
  const reviewedAt=tagged[found.id]&&state.bills.find(b=>b.id===found.id)?.luna?.reviewed_at;
  const extra=found.state==='reviewed'||found.state==='questions'?(tagged[found.id]?` · tags published${reviewedAt?` ${esc(dateText(reviewedAt))}`:''}`:' · no verified tags published yet'):'';
  return `<button class="review-chip${tagged[found.id]?' tagged':''}" data-open="${esc(found.id)}">${esc(found.id)}</button> <span class="review-lookup-state ${found.state}">${esc(found.label)}${extra}</span>`;
}
// Each publish that changed something, newest first: when, the overall counts, then every bill it changed.
function updatesSection({stampText,changeCounts,changeRows}){
  const entries=updateEntries(state.lunaUpdates).slice(0,8);
  if(!entries.length)return '';
  return `<section class="review-updates" aria-labelledby="review-updates-title"><h3 id="review-updates-title">What changed</h3>${entries.map((u,i)=>`<details class="review-update"${i?'':' open'}><summary><strong>${esc(stampText(u.at))}</strong> · ${u.bills.length.toLocaleString()} ${u.bills.length===1?'bill':'bills'}${changeCounts(u.counts)}</summary>${changeRows(u.bills,50)}</details>`).join('')}</section>`;
}
export function reviewMarkup({stampText,dateText,changeCounts,changeRows,todayRow}){
  const {ids,status,tagged,summary:s,run}=reviewParts();
  const total=ids.length||1,pct=n=>Math.round(n/total*1000)/10;
  const line=run.kind==='unavailable'?'Live worker status is unavailable, so bills with published Luna tags are counted as reviewed.'
    :run.kind==='stale'?`The worker last reported ${esc(stampText(status.updated_at))} and may have stopped.`
    :run.kind==='quiet'?`No hourly run has reported since ${esc(stampText(status.updated_at))}; the worker may be stopped.`
    :run.kind==='waiting'?`Waiting for Luna capacity · ${status.current?`retrying ${esc(status.current)}`:'resuming'} at ${esc(stampText(status.waiting_until))}`
    :run.kind==='running'?`Reviewing now · updated ${esc(stampText(status.updated_at))}`
    :`Idle until the next hourly run · last update ${esc(stampText(status.updated_at))}`;
  const chip=(id,note='')=>`<button class="review-chip${tagged[id]?' tagged':''}" data-open="${esc(id)}" title="${tagged[id]?'Luna tags published':'Reviewed; no verified tags published'}${note?' · '+esc(note):''}">${esc(id)}</button>`;
  const group=(title,list,empty,open=false)=>`<details class="review-group"${open?' open':''}><summary><strong>${title}</strong> <span>${list.length.toLocaleString()}</span></summary>${list.length?`<div class="review-chips">${list.join('')}</div>`:`<p class="review-empty">${empty}</p>`}</details>`;
  const counts=[['Reviewed',s.reviewed.length,'done'],...(s.active.length?[['Reviewing now',s.active.length,'progress']]:[]),
    ['Waiting for bill text',s.noText.length,'notext'],...(s.failed.length?[['Failed',s.failed.length,'failed']]:[]),
    ['Not started',s.notStarted.length,'waiting']];
  const live=run.kind==='running'||run.kind==='waiting';
  const rows=passRows(status,s,run);
  const current=rows.find(r=>r.now);
  const jobs=passJobs(status,run);
  const jobList=jobs.length?`<div class="pass-jobs"><small>${jobs.length>1?`${jobs.length} bills at once`:'Working on'}</small>${jobs.map(j=>`<span class="pass-job">${chip(j.id,j.job||'')}${j.job?`<span>${esc(j.job)}</span>`:''}</span>`).join('')}</div>`:'';
  const runTitle={running:current?`Working on: ${current.label}`:'Reviewing now',waiting:'Waiting for Luna capacity',idle:'Idle',
    quiet:'No recent run',stale:'May have stopped',unavailable:'Status unavailable'}[run.kind];
  const runDetail=live?[run.startedAt?`Started ${clockText(run.startedAt)}`:'',run.minutesUsed!==null?`${Math.min(run.minutesUsed,RUN_LIMIT_MINUTES)} of ${RUN_LIMIT_MINUTES} minutes used`:'',
      run.waitingUntil?`retrying at ${clockText(run.waitingUntil)}`:''].filter(Boolean).join(' · ')
    :`Next run about ${clockText(run.nextRun)}`;
  const passes=`<ol class="review-passes" aria-label="Review passes, in run order">${rows.map((r,i)=>`<li class="review-pass${r.now?' now':''}${r.known&&r.left===0?' clear':''}"${r.now?' aria-current="step"':''}><span class="pass-step" aria-hidden="true">${i+1}</span><div class="pass-name"><strong>${r.label}</strong><small>${r.note}</small></div><div class="pass-count">${r.known?`<strong>${r.left.toLocaleString()}</strong><span>${r.estimate?'not started':r.left!==r.due?`bills left of ${r.due.toLocaleString()}`:'bills left'}</span>`:'<strong>—</strong><span>counted after the next run</span>'}${r.checked?`<span class="pass-checked">${r.checked.toLocaleString()} done this run</span>`:''}</div>${r.now?jobList:''}</li>`).join('')}</ol>`;
  const runCard=`<section class="review-run ${run.kind}" aria-label="Review worker"><div class="review-run-state">${live?'<span class="review-pulse" aria-hidden="true"></span>':'<span class="review-run-dot" aria-hidden="true"></span>'}<div><strong>${esc(runTitle)}</strong><span>${esc(runDetail)}</span></div></div>${passes}</section>`;
  const now=s.active.length&&run.kind!=='stale'?`<div class="review-now"><span class="review-pulse" aria-hidden="true"></span><div><small>${run.kind==='waiting'?'Waiting to retry':'Reviewing now'}</small>${s.active.map(id=>chip(id)).join('')}</div>${s.upcoming.length?`<div><small>Up next</small>${s.upcoming.map(id=>chip(id)).join('')}</div>`:''}</div>`:'';
  const auditText=auditLine(state.audit);
  const headline=`<p class="review-headline"><strong>${s.reviewed.length.toLocaleString()} of ${ids.length.toLocaleString()} bills reviewed</strong> (${pct(s.reviewed.length)}%)${s.questionsQueued.length?` · ${s.questionsQueued.length.toLocaleString()} of them have follow-up questions queued`:''}</p>`;
  const recent=newestReviewed(state.bills).slice(0,20);
  return `<div class="section-head"><div><div class="section-overline">LUNA FULL-TEXT REVIEW</div><h2>Review progress</h2></div><span class="subtitle">${line}</span></div>
  ${runCard}
  ${headline}
  <div class="review-bar" role="img" aria-label="${counts.map(([label,n])=>`${n} ${label.toLowerCase()}`).join(', ')} of ${ids.length}">${counts.map(([,n,cls])=>`<span class="seg ${cls}" style="width:${pct(n)}%"></span>`).join('')}</div>
  <div class="review-counts">${counts.map(([label,n,cls])=>`<div class="review-count ${cls}"><span class="dot"></span><strong>${n.toLocaleString()}</strong><span>${label} · ${pct(n)}%</span></div>`).join('')}</div>
  ${now}
  ${updatesSection({stampText,changeCounts,changeRows})}
  <div class="review-columns">
    <section class="review-recent" aria-labelledby="review-recent-title"><h3 id="review-recent-title">Recently reviewed</h3>${recent.length?`<div class="today-list">${recent.map(b=>todayRow({bill:b,actions:[`Reviewed ${dateText(b.luna.reviewed_at)}`]})).join('')}</div>`:'<p class="review-empty">No reviews published yet.</p>'}</section>
    <div class="review-side">
      <form class="review-lookup" id="review-lookup-form" role="search"><label for="review-lookup">Check one bill</label><input id="review-lookup" maxlength="20" placeholder="Bill number, such as HB 474" autocomplete="off"><p class="review-lookup-result" id="review-lookup-result" aria-live="polite"></p></form>
      ${group('Follow-up questions queued',s.questionsQueued.map(id=>chip(id,'first-pass review published; follow-up questions run on a later visit')),'No follow-up questions waiting.')}
      ${group('Waiting for bill text',s.noText.map(id=>chip(id,'the legislature has not posted text yet')),'Every bill has text.')}
      ${s.failed.length?group('Failed',s.failed.map(f=>chip(f.id,f.stage?`${f.stage} failed`:'failed')),'No failures.'):''}
      ${auditText?`<p class="review-audit">${esc(auditText)}</p>`:''}
    </div>
  </div>
  <p class="review-legend"><span class="review-chip tagged">HB1</span> verified Luna tags published · <span class="review-chip">HB1</span> reviewed, no claims verified against the text yet. Bills waiting for text are retried automatically once the legislature posts it. Follow-up questions refine a review that is already published.</p>`;
}
