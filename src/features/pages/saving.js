// The #saving page: how saving and sharing work without accounts. linked is the sync client's linked state
// (sync.linked); syncAvailable is true, false, or null while the check is still running.
import {esc} from '../../core/dom.js';
import {state} from '../../core/state.js';

export function savingMarkup({linked,syncAvailable}){
  const syncState=syncAvailable===false?'Not switched on for this site':syncAvailable?'Available':'Checking…';
  const deviceState=linked?.editKey?'Synced (edit link)':'Not synced';
  const parts=[
    ['01','Your watchlist','Star any bill to follow it. The list is kept in this browser on this device, with nothing sent anywhere. Clearing site data, or using a private window, removes it, so use one of the options below if you want a copy.'],
    ['02','Remembered filters','Your last filters and sort order are remembered on this device and come back the next time you visit.'],
    ['03','Links to any view','The address bar always describes what you are looking at: the page, filters, sort and any open bill. Use <strong>Copy link</strong> above the results, or bookmark the page, to return to it or send it to someone.'],
    ['05','Export and import a file','<strong>Export file</strong> saves your watchlist, followed legislators, saved searches and colour theme as one small file you can keep or email. <strong>Import file</strong> adds them from that file (or an older watchlist export), or from any text or spreadsheet export that mentions bill numbers such as “HB 5” or “SJR 9”. Importing only adds; it never removes bills.'],
    ['06','Private sync links','<strong>Create sync link</strong> on the Watchlist keeps your watchlist, followed legislators, saved searches and colour theme the same on your phone, laptop and work computer, with no account. Light or dark stays a choice for each device. Open the <strong>edit link</strong> on each device; treat it like a password, because anyone with it can change the list. The <strong>view-only link</strong> is safe to share: it shows your watchlist’s bills only, never who you follow or what you saved, and stays current as you edit. You can stop syncing one device, or delete the link for every device.'],
    ['07','RSS feeds','Each bill’s details include an <strong>RSS feed</strong> of its recorded actions, for Outlook or any feed reader. A synced watchlist also has one feed for all of its bills, linked from the Watchlist. Each legislator has a feed too, linked from their member page.'],
    ['08','Followed legislators','<strong>Follow</strong> a legislator on their member page or in Near you, and their bills appear under <strong>Following</strong>. Follows are kept in this browser like the watchlist, and go into exported files and sync links. Share links and view-only links never include them.'],
    ['09','Saved searches','On the Bill explorer, <strong>Save search</strong> keeps the current search words and filters under <strong>Following</strong>, with how many bills have new actions since you last opened it. Saved searches go into exported files and sync links like follows; share and view-only links never include them.']
  ];
  // Both examples start with two bills. Only the live link gains the third bill.
  const example=live=>`<div class="share-example" aria-hidden="true">
    <div><span>When shared</span><b class="bill-slips"><i></i><i></i></b></div>
    <span class="share-arrow">→</span>
    <div><span>After you add a bill</span><b class="bill-slips"><i></i><i></i>${live?'<i class="added-slip"></i>':''}</b></div>
  </div>`;
  return `<div class="section-head"><div><div class="section-overline">NO ACCOUNT NEEDED</div><h2>Saving and sharing your info</h2></div><button class="outline-button" data-view="watchlist">Open your watchlist →</button></div><div class="info-callout"><strong>There are no logins on this site.</strong> Everything below works without an account, email address or name. Pick whichever fits: keep things on one device, carry them in a link or file, or sync a private link across devices.</div>
    <h2 class="saving-reference-title">Share your watchlist</h2>
    <p class="share-intro">Both links show only your watched bills. On your watchlist, open <strong>Save, share and sync</strong> to choose one.</p>
    <div class="sharing-options">
      <article><h3>Share a snapshot</h3>${example(false)}
        <p>Readers see the bills you picked that day. They can add those bills to their own watchlist.</p>
        <p class="sharing-instruction">Star the bills you want to include, then choose <strong>Copy share link</strong>.</p></article>
      <article><h3>Share a live list</h3>${example(true)}
        <p>Readers see your latest list at the same address, including bills you add or remove later.</p>
        <p class="sharing-instruction">${syncAvailable===false?'Sync is unavailable on this site right now.':linked?.editKey?'Choose <strong>Copy view-only link</strong>.':'Choose <strong>Create sync link</strong>, then <strong>Copy view-only link</strong>.'} Keep your edit link private.</p></article>
    </div>
    <h2 class="saving-reference-title">Saving on your devices</h2>
    <div class="saving-reference">${parts.map(([,title,body])=>`<details><summary>${title}</summary><p>${body}</p></details>`).join('')}</div><div class="section-head"><div><div class="section-overline">PRIVACY</div><h2>What is stored, and where</h2></div></div><div class="subpage-card"><div class="storage-map">
      <section class="data-field long"><span class="storage-icon device-icon" aria-hidden="true"></span><h3>On this device</h3><ul><li>Watched bills, followed legislators and saved searches</li><li>Last filters, theme and disclaimer preference</li><li>Your browser stores your sync link if you made one</li></ul></section>
      <section class="data-field long"><span class="storage-icon server-icon" aria-hidden="true"></span><h3>On the server</h3><p>Only when you use a sync link</p><ul><li>Watched bill numbers, followed member codes and colour theme</li><li>Saved search names, search words and filters</li><li>A version number and dates</li><li>Links only as one-way fingerprints, so the database cannot be used to open a list</li></ul></section>
    </div><div class="data-field long"><span class="data-label">Never collected</span><span class="data-value">Names, email addresses, accounts, tracking cookies or analytics</span></div><div class="data-field long"><span class="data-label">Abuse limits</span><span class="data-value">The sync service counts requests per address in memory for up to an hour, and never writes addresses down</span></div><div class="data-field long"><span class="data-label">Retention</span><span class="data-value">A sync link unused for a year is deleted. Deleting it yourself removes it at once; each device keeps its own copy of the list.</span></div><div class="data-field"><span class="data-label">Sync on this site</span><span class="data-value">${esc(syncState)}</span></div><div class="data-field"><span class="data-label">This device</span><span class="data-value">${esc(deviceState)} · ${state.watch.size} ${state.watch.size===1?'bill':'bills'} watched</span></div><p style="font-size:var(--fs-xs);color:color-mix(in srgb,var(--ink) 45%,var(--surface));margin:14px 0 0">Limits: up to 500 bills per synced list. Lost your edit link? Your list is still on each device that had it; create a new sync link from any of them.</p></div>`;
}
