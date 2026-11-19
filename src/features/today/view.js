// The Today view (#today): the day's bills by action type with a topic filter. todayData is shared with the home
// dashboard and "Copy page for AI". The row renderer is a parameter: home/view.js, which draws it, imports this file.
import {chicagoDate, highestNumberFirst, activityOn, latestActivityDay, topicCounts, groupByActionType} from '../../taxonomy.js';
import {state} from '../../core/state.js';
import {esc} from '../../core/dom.js';
import {topicHue} from '../home/rows.js';
import {dateText} from '../../core/format.js';

// Remove this line once the Legislature is in session and the view has real floor and hearing content.
const TODAY_INTERIM_NOTE='The 90th Legislature convenes in January 2027; floor calendars and hearings will appear here then.';

// The Today view's day and rows, shared by its markup and "Copy page for AI".
export function todayData(){
  const today=chicagoDate(new Date());
  let day=today,rows=highestNumberFirst(activityOn(state.bills,day)),note='';
  if(!rows.length){
    const last=latestActivityDay(state.bills,today);
    if(last){day=last;rows=highestNumberFirst(activityOn(state.bills,day))}
    note=`No recorded activity today${last?`; showing ${esc(dateText(last))}`:''}.`;
  }
  const counts=topicCounts(rows.map(r=>r.bill));
  if(state.todayTopic&&!counts.some(c=>c.topic===state.todayTopic))state.todayTopic='';
  const shown=state.todayTopic?rows.filter(r=>r.bill.topics.includes(state.todayTopic)):rows;
  return {today,day,rows,note,counts,shown};
}

export function todayMarkup({todayRow}){
  const {today,day,rows,note,counts,shown}=todayData();
  // Every topic is reachable: the 12 largest show first, the rest behind "+N more"; a selected topic always shows.
  const TOP=12,listed=state.todayAllTopics?counts:counts.filter((c,i)=>i<TOP||c.topic===state.todayTopic);
  const dot=topic=>topicHue(topic)===null?'':`<i class="topic-dot" style="--topic-h:${topicHue(topic)}"></i>`;
  const chip=(topic,label)=>`<button class="topic-chip ${state.todayTopic===topic?'selected':''}" data-today-topic="${esc(topic)}" aria-pressed="${state.todayTopic===topic}">${dot(topic)}${label}</button>`;
  // The day's topic mix as one bar. Mouse users can click a segment; the chips below are the accessible control.
  const barTotal=counts.reduce((n,c)=>n+c.count,0);
  const bar=counts.length>1?`<div class="topic-bar" aria-hidden="true">${counts.map(c=>`<button type="button" tabindex="-1" class="topic-seg${state.todayTopic===c.topic?' selected':''}" data-today-topic="${esc(c.topic)}" style="--topic-h:${topicHue(c.topic)??220};flex:${c.count} 1 0" title="${esc(c.topic)} · ${c.count}"><span>${c.count/barTotal>=.09?`${esc(c.topic)} · ${c.count}`:''}</span></button>`).join('')}</div>`:'';
  const chips=`<div class="today-topics" role="group" aria-label="Filter this day's bills by topic">${chip('',`All · ${rows.length}`)}${listed.map(c=>chip(c.topic,`${esc(c.topic)} · ${c.count}`)).join('')}${counts.length>TOP?`<button class="text-button" id="today-topics-toggle">${state.todayAllTopics?'Show fewer':`+${counts.length-listed.length} more topics`}</button>`:''}</div>`;
  let budget=state.todayLimit;
  const sections=groupByActionType(shown).map(g=>{
    const part=g.rows.slice(0,Math.max(0,budget));budget-=part.length;
    return part.length?`<section class="today-group"><h3>${esc(g.label)} <span>${g.rows.length}</span></h3>${part.map(r=>todayRow(r,{by:true})).join('')}</section>`:'';
  }).join('');
  return `<div class="section-head"><div><div class="section-overline">${day===today?'TODAY':'MOST RECENT ACTIVITY'}</div><h2>${esc(dateText(day))}</h2></div><span class="subtitle">${shown.length} ${shown.length===1?'bill':'bills'} with recorded action</span></div>
    <div class="info-callout today-note">${note?`<p>${note}</p>`:''}<p>${esc(TODAY_INTERIM_NOTE)}</p></div>
    ${rows.length?bar+chips:''}${sections||'<div class="empty-state"><h3>No activity to show</h3><p>Nothing is recorded for this day yet.</p></div>'}
    ${shown.length>state.todayLimit?`<button class="outline-button" id="today-more">Show 100 more · showing ${state.todayLimit} of ${shown.length}</button>`:''}`;
}
