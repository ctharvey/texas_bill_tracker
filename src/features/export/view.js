// The #export page: everything this browser has saved, and one button that downloads it as a profile file
// (profileFile in prefs.js), which Import file on any copy of the site reads back.
import {esc} from '../../core/dom.js';
import {THEMES} from '../theme/model.js';

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// watch: bill ids; follows: member codes; searches: cleaned saved searches; theme: saved theme id or null.
// memberName(code) returns a display name or null; synced is true when this browser holds a sync edit link.
export function exportMarkup({watch = [], follows = [], searches = [], theme = null, memberName = () => null, synced = false} = {}) {
  const bills = [...watch], people = [...follows], total = bills.length + people.length + searches.length;
  const section = (title, items, empty) => `<section class="export-part"><h3>${esc(title)}</h3>${items.length
    ? `<ul class="export-list">${items.map(x => `<li>${x}</li>`).join('')}</ul>` : `<p class="tools-note">${esc(empty)}</p>`}</section>`;
  const summary = total
    ? `This browser has ${plural(bills.length, 'bill', 'bills')} on its watchlist, ${plural(people.length, 'followed legislator', 'followed legislators')} and ${plural(searches.length, 'saved search', 'saved searches')}.`
    : 'This browser has nothing saved yet: no starred bills, followed legislators or saved searches.';
  return `<div class="info-callout"><strong>${esc(summary)}</strong> The file holds your watchlist, followed legislators, saved searches${theme ? ' and colour theme' : ''}. Use <strong>Import file</strong> on the Watchlist, on any device, to add them back; importing only adds.</div>`
    + `<div class="tools-row"><button class="primary-button" id="export-watch" ${total || theme ? '' : 'disabled'}>Download file</button><button class="outline-button" data-view="watchlist">Open your watchlist</button></div>`
    + section('Watchlist', bills.map(id => esc(id)), 'No starred bills.')
    + section('Followed legislators', people.map(code => esc(memberName(code) || code)), 'No followed legislators.')
    + section('Saved searches', searches.map(s => esc(s.name || 'Saved search')), 'No saved searches.')
    + (theme ? `<p class="tools-note">Colour theme: ${esc(THEMES.find(t => t.id === theme)?.name || theme)}.</p>` : '')
    + `<p class="tools-note">Not in the file: your Near you location, remembered filters${synced ? ' and this device’s sync link (open the edit link on another device to sync it there)' : ''}. Nothing on this page is sent anywhere.</p>`;
}
