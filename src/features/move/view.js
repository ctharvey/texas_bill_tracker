// Move screens. Old site: the banner that offers the move, its progress and outcome. New site: what arrived.
import {esc} from '../../core/dom.js';

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const host = origin => origin.replace(/^https?:\/\//, '');
const and = parts => (parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}` : parts[0] || '');

// What this browser holds, from receive(): '3 bills, 1 followed legislator and your settings'.
export function savedSummary(c) {
  const bad = c.refused.watch.length + c.refused.follows.length + c.refused.searches.length;
  return and([c.watch.length && plural(c.watch.length, 'bill', 'bills'), c.follows.length && plural(c.follows.length, 'followed legislator', 'followed legislators'),
    c.searches.length && plural(c.searches.length, 'saved search', 'saved searches'), c.editKey && 'your sync link',
    Object.keys(c.settings).length && 'your settings', bad && plural(bad, 'other saved item', 'other saved items')].filter(Boolean));
}

const FAILED = {
  blocked: 'Your browser blocked the new window. Allow pop-ups for this site and try again, or export a file instead.',
  closed: 'The new window closed before the move finished. Nothing was changed here; try again.',
  timeout: 'The move did not finish. Nothing was changed here; try again, or export a file instead.',
  failed: 'The new address could not save everything (its storage may be full). Nothing was changed here; export a file instead.',
  read: 'This browser’s saved data could not be read. Export a file instead.',
  sync: 'Everything arrived, but joining your sync link failed. Nothing was changed here; try again in a minute.',
};

// status: 'offer' | 'moving' | 'moved' | 'gone' (nothing to move) | 'failed:<reason>'. goHref: same page on the new site.
// what: savedSummary() of this browser's data.
export function oldSiteBanner({status, target, goHref, what = ''}) {
  const name = esc(host(target));
  const go = `<a class="primary-button" href="${esc(goHref)}">Go to ${name}</a>`;
  if (status === 'moving') return `<div class="info-callout move-banner" role="status"><div><strong>Moving your saved data to ${name}.</strong> Keep the new window open until it says it is done.</div></div>`;
  if (status === 'moved') return `<div class="info-callout move-banner" role="status"><div><strong>Your saved data is on ${name} now.</strong> It is still here too; nothing was removed.</div><div class="tools-row">${go}</div></div>`;
  if (status === 'gone') return `<div class="info-callout move-banner"><div><strong>Texas Bill Atlas has moved to ${name}.</strong></div><div class="tools-row">${go}</div></div>`;
  const reason = status?.startsWith('failed:') ? FAILED[status.slice(7)] || FAILED.timeout : '';
  return `<div class="info-callout move-banner${reason ? ' callout-warn' : ''}" role="status"><div><strong>Texas Bill Atlas has moved to ${name}.</strong> This browser has ${esc(what || 'saved data')} saved at this address. Copy it all to ${name} in one step; nothing here is removed.${reason ? ` <span class="move-error">${esc(reason)}</span>` : ''}</div>`
    + `<div class="tools-row"><button class="primary-button" id="move-start">Move my saved lists</button><a class="outline-button" href="#export" data-view="export">Export a file instead</a></div></div>`;
}

// result: applyMove's {ok, counts, previousKey} or {ok:false, reason}. source: the old site's origin.
export function newSiteResult(result, source) {
  const from = esc(host(source));
  const close = '<button class="outline-button" id="move-close">Close</button>';
  if (!result.ok && result.reason === 'no-opener') return `<div class="info-callout move-banner callout-warn" role="status"><div><strong>This page was opened without the move window.</strong> On ${from}, choose <strong>Move my saved lists</strong>. If your browser keeps opening it like this, use <strong>Export a file instead</strong> there, then <strong>Import file</strong> on the Watchlist page here.</div><div class="tools-row">${close}</div></div>`;
  if (!result.ok && result.reason === 'timeout') return `<div class="info-callout move-banner callout-warn" role="status"><div><strong>Your saved lists did not arrive.</strong> Close this window and choose <strong>Move my saved lists</strong> on ${from} again.</div><div class="tools-row">${close}</div></div>`;
  const c = result.counts || {};
  const parts0 = [c.watch && plural(c.watch, 'bill', 'bills'), c.follows && plural(c.follows, 'followed legislator', 'followed legislators'),
    c.searches && plural(c.searches, 'saved search', 'saved searches'), c.settings && 'your settings'].filter(Boolean);
  const list = and(parts0);
  const lines = [
    result.ok ? (list ? `<strong>Moved from ${from}: ${esc(list)}.</strong>` : `<strong>Everything from ${from} was already here.</strong>`)
      : `<strong>Some saved items could not be saved here.</strong> Nothing was removed from ${from}; export a file there to keep a copy.`,
    c.sync === 'join' ? 'This browser joined your sync link, so your other synced devices see these too.' : '',
    c.sync === 'same' ? 'They were added to the sync link this browser already uses.' : '',
    c.held ? `${plural(c.held, 'item was', 'items were')} over a limit or not valid, so they were kept aside in this browser (listed on the Export page). <button class="text-button" id="move-held">Download them</button>` : '',
    result.previousKey ? 'Your old browser used a different sync link. This browser kept its own; <button class="text-button" id="move-previous">copy the other edit link</button> if you still need it.' : '',
  ].filter(Boolean);
  return `<div class="info-callout move-banner${result.ok ? '' : ' callout-warn'}" role="status"><div>${lines.join(' ')}</div><div class="tools-row">${close}</div></div>`;
}
