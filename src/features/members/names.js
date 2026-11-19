// Legislators' names as the app shows them: titles, roster lookups, tenure and influence pills, and author names
// linked to member pages. Used by bill cards and pages, Near you, member pages and Today.
import {state} from '../../core/state.js';
import {esc} from '../../core/dom.js';
import {tenureTag} from '../../taxonomy.js';
import {memberHref} from '../../core/links.js';

export const memberTitle=m=>`${m.chamber==='house'?'Rep.':'Sen.'} ${m.full_name||m.display_name}`;
// A name as the bill lists it, linked to the member page only when the roster places that exact (chamber, name).
export const rosterMember=(chamber,name)=>{const m=state.roster?.members?.[`${chamber}|${name}`];return m&&typeof m==='object'?m:null};
// First term / Mid-tenure / Senior, by time in the current chamber; the detail is in the tooltip and on member pages.
// Cards show a verified role, or only the ends of the tenure scale; mid-tenure and unknown authors show nothing.
export const influencePill=i=>i.level>=4?`<span class="influence-pill" title="${esc(i.factors.join(' · '))}">◆ ${esc(i.label)}</span>`
  :i.key==='senior'||i.key==='newcomer'?`<span class="tenure-pill tenure-${i.key}" title="${esc(i.factors.join(' · '))}">${esc(i.label)}</span>`:'';
export const tenurePill=m=>{const t=tenureTag(m);return t?`<span class="tenure-pill tenure-${t.key}" title="${esc(t.detail)}">${esc(t.label)}</span>`:''};
export const memberNameHtml=(member,label)=>member?.code?`<a class="text-link member-name" href="${esc(memberHref(member.code))}">${esc(label)}</a>`:esc(label);
// Authors serve in the bill's own chamber.
export const authorMember=(b,name)=>b.people?.authors?.find(p=>p.name===name)?.member||rosterMember(String(b.chamber||'').toLowerCase(),name);
export const authorHtml=(b,name)=>memberNameHtml(authorMember(b,name),name);
// The primary author by title and full name ("Rep. Ann Johnson") when the roster knows them; else the bill's own name.
export const filerHtml=b=>{const m=authorMember(b,b.author);return memberNameHtml(m,m?.full_name||m?.display_name?memberTitle(m):b.author)};
