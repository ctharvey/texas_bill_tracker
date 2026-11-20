// Agency page (/agency/<id>) and topic page (/topic/<slug>): the bills tied to one agency or policy topic.
import {state} from '../../core/state.js';
import {esc} from '../../core/dom.js';
import {nearRow} from '../near/view.js';
import {agencyName} from '../../core/labels.js';
import {AGENCY_NAME} from '../../taxonomy.js';
import {buildUrl} from '../../prefs.js';
import {agencyBills, topicName, topicBills} from './model.js';

const known = id => Boolean(id && (AGENCY_NAME[id] || state.luna?.agencies?.[id]));
// The name of the agency or topic on screen, or null when the address names none.
export function groupTitle(view) {
  if (view === 'agency') return known(state.agencyId) ? agencyName(state.agencyId) : null;
  return topicName(state.topicSlug);
}
const head = (kind, title) => `<div class="section-head"><div><div class="section-overline">${kind}</div><h2>${esc(title)}</h2></div><span class="subtitle">90th Legislature</span></div>`;
function list(key, rows) {
  const limit = state.groupShow?.[key] || 30;
  return `${rows.slice(0, limit).map(bill => nearRow({bill, notes: []})).join('')}${rows.length > limit ? `<button class="outline-button" data-group-more="${esc(key)}">Show 30 more · showing ${limit} of ${rows.length}</button>` : ''}`;
}
const body = (rows, url, what) => `<p class="near-hint">${rows.length ? `${rows.length} ${rows.length === 1 ? 'bill' : 'bills'} in this snapshot. ` : ''}<a class="text-link" href="${esc(url)}" data-view="all">All of them in the Bill explorer</a></p>${rows.length ? `<section class="today-group">${list(what, rows)}</section>` : '<p class="review-empty">No bills in this snapshot yet.</p>'}`;

export function agencyMarkup() {
  const id = state.agencyId, rows = id ? agencyBills(state.bills, id) : [];
  if (!known(id) && !rows.length) return `${head('AGENCY', 'Agency not found')}<div class="info-callout callout-warn">No agency in this snapshot matches ${id ? `<strong>${esc(id)}</strong>` : 'this address'}. See the <a class="text-link" href="/agencies" data-view="agencies">agency index</a>.</div>`;
  return `${head('AGENCY', agencyName(id))}<div class="info-callout">Links to an agency are possible effects, not confirmed legal obligations. They come from Luna’s full-text review where a bill has one (Luna is an AI model and can be wrong) and from caption rules otherwise. <a class="text-link" href="/about/method" data-view="method">How it works</a>.</div>${body(rows, buildUrl('all', {agency: id}), 'agency')}`;
}

export function topicMarkup() {
  const name = topicName(state.topicSlug);
  if (!name) return `${head('TOPIC', 'Topic not found')}<div class="info-callout callout-warn">No policy topic matches ${state.topicSlug ? `<strong>${esc(state.topicSlug)}</strong>` : 'this address'}. Browse topics in the <a class="text-link" href="/explorer" data-view="all">Bill explorer</a>.</div>`;
  return `${head('TOPIC', name)}${body(topicBills(state.bills, name), buildUrl('all', {topic: name}), 'topic')}`;
}
