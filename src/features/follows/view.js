// Following legislators: the follow button, each member's RSS feed link, and the Following page's section of followed
// members and their bills. Saving a follow stays with app.js's list and sync code (changeFollow, toggleFollow).
import {state} from '../../core/state.js';
import {esc} from '../../core/dom.js';
import {memberByCode, followedBills} from '../../geo.js';
import {newestFirst} from '../../taxonomy.js';
import {memberNameHtml, memberTitle} from '../members/names.js';
import {nearRow} from '../near/view.js';

export const followButton=m=>{if(!m?.code)return '';const on=state.follow.includes(m.code);
  return `<button class="${on?'outline-button following':'primary-button'} follow-button" data-follow="${esc(m.code)}" aria-pressed="${on}">${on?'✓ Following':'+ Follow'}</button>`};
export const memberFeedHref=code=>`./live/feeds/members/${encodeURIComponent(code)}.xml`;

export function followedMarkup(){
  if(!state.follow.length)return `<section class="followed-section"><h3>Followed legislators</h3><p class="tools-note">Follow a legislator from their member page or from <a class="text-link" href="/near-you" data-view="local">Near you</a> to see every bill they file or sign onto here.</p></section>`;
  if(!state.roster)return `<section class="followed-section"><h3>Followed legislators</h3><p class="tools-note">The member roster could not be loaded, so followed legislators' bills are not shown right now.</p></section>`;
  const members=state.follow.map(code=>memberByCode(state.roster,code)).filter(Boolean);
  const rows=followedBills(state.bills,state.roster,state.follow,newestFirst),limit=state.followShow||30;
  const chips=members.map(m=>`<span class="followed-member">${memberNameHtml(m,memberTitle(m))} <a class="text-link" data-feed href="${esc(memberFeedHref(m.code))}" target="_blank" rel="noopener noreferrer" title="RSS feed of this legislator's bills">RSS</a> <button class="text-button" data-follow="${esc(m.code)}" aria-label="Unfollow ${esc(memberTitle(m))}">Unfollow</button></span>`).join('');
  return `<section class="followed-section"><h3>Followed legislators <span>${members.length}</span></h3><div class="followed-members">${chips}</div><p class="tools-note">Saved in this browser, in exported files and with your sync link; never in share or view-only links. Newest bills first.</p>${rows.length?`${rows.slice(0,limit).map(r=>nearRow(r,{showWho:true})).join('')}${rows.length>limit?`<button class="outline-button" id="follow-more">Show 30 more · showing ${limit} of ${rows.length}</button>`:''}`:'<p class="review-empty">No bills by the legislators you follow in this snapshot yet.</p>'}</section>`;
}
