# Changelog

## 2026-11-19
- Law section pages, more usability fixes: where the bills do not quote a section whole (a repeal, or an amendment of only some subsections), current law comes from the site's copy of the statutes (`live/law`), dated and linked, so a repeal shows the wording it removes and a partial amendment is set against the whole section (parts a bill leaves alone count as unchanged). The bill bar comes first in reading and keyboard order (shown on the right on wide screens), switching bills is announced to screen readers, and it counts "3 bills · 2 versions". The page title is no longer repeated as a second heading, the page description fits every section, and a section no bill changes says "no bill changes it yet".
- Law section pages, usability fixes: a section's heading is its current-law heading when a bill amends or repeals it, never an unrelated new section's that reuses the number (ED 28.0022 was titled with HB 441's "Artificial Intelligence System Usage"), and a number only bills add has no heading unless they agree; each adding bill keeps its own heading on its bill page (`hb` in the statute index), so HB 1250 no longer lists § 545.4575 as "Emergency Response Procedures". On phones the page heading is kept for screen readers only, the matching limits and the comparison notes fold into a disclosure, the legend is one line, and a group of bills at the same stage shows it once ("· all Filed"), so the law text starts on the first screen. The explorer says "Open it to read the proposals" or "compare with current law" instead of always promising a side-by-side comparison.
- Law section pages: current law sits on the left and the bill picked in a bill bar on the right (beside the text on wide screens, a swipeable row above it on narrower ones); the left can still be switched to another bill. A section that only exists because bills add it ("proposed new section", 2,148 of 4,009 today) shows one bill's text at a time with its own heading and caption, never a word-by-word comparison of unrelated proposals that share a number, and no link to current law. A repeal shows the wording it would remove.
- Follow a law, review fixes: a bill that starts changing a followed section counts as new even when its latest action is older (the data run records the day it first indexed each bill on each section in `live/statutes/first-seen.json`, a history that only grows, so a run with no texts, a partial read or older code after a rollback cannot erase it; the index carries those days as `f`), and each law feed gets a "Now amends …" item that day. A run that finds no section keeps the previous statute index. A saved search or follow the list has no room for is no longer sent to the sync link. Only the 27 indexed codes make a section query, so "PM 2.5" is a text search again; an exact section query says when the index is loading, failed or lists no bill. The statute page's Follow button redraws after a sync or another tab, keeps focus, and shows while the index loads; unfollowing removes every copy, an import skips a law already followed, and a follow that did not save says so. Labels read "Penal Code § 46.06" everywhere.
- Follow a law: each law section's page has "+ Follow this law", even with no bill changing it yet. A follow is a saved search for the section (syncs, exports, counts toward the 20), so new bills and actions on it show under "Since your last visit" and on Following. The data run writes an RSS feed per section (`live/feeds/law/<CODE>-<section>.xml`), linked from the page. The page, feed and share page say matching is automatic and can miss changes. A search that is exactly a section key ("PE 46.06") now finds only the bills that change it, not text matches, and the home page redraws when the statute index arrives.
- Law sections get their own address, `/law/<CODE>/<section>` (`/law/PE/46.06`): the app reads it and writes it for the statute view, and old `#statute?law=…&sec=…` links still work. The data run writes a page for each of the ~3,900 sections a bill changes (`live/share/law/`), with the bills, the section's current text and the site card, for search and link previews; the sitemap lists them. Served by the gateway route in cth.hosting 44c2e28.
- Luna can read the current law a bill changes (`--law-context`, on in production for new texts): each new text's first pass gets the headings of the chapters it repeals, amends or names and the current text of the sections it changes, from `live/law`, and may quote them only verbatim. The statute parser now finds whole-chapter repeals (HB1094's "The following chapters of the Government Code are repealed"), telling them apart from subchapter repeals and session-law chapters.
- A copy of current Texas law: `sync_law.py` (weekly `texas-bill-law` unit) writes the Constitution and all 31 codes from the Legislative Council's statute files to `live/law/`, one Markdown file per chapter (about 5,000 files, 140 MB), downloading only codes that changed. Agent bill pages list the current text of each section the bill amends or repeals.
- Luna retries a failed first pass: a review cut off at its output limit (HB725, HB849, SB98, SB188, SB403) or whose summary could not be verified (HB747, HB1100, HB1150) is sent again, at most twice per text, as a changed request with more output room, so the cached failure is never replayed. A retry never replaces a better review.
- The hourly data run survives the Legislature's FTP answering out of step (`200 Type set to I.`, 5 of 6 failed runs in the past week) or dropping the connection: it reconnects and reads the listing or file again, up to 3 times per run. Each run writes `live/sync-status.json`, and `daily_check.py` judges the job by its last successful run, so quiet hours with no new bills no longer fail the sweep; a bill posted since the last run, or agent search waiting for its rebuild, now warns instead of failing.
- Computed-style parity check for CSS moves (`tests/e2e/style_snapshot.py`, `run_style_parity.py`).
- Feature folders, last pass: the address and remembered filters (`src/core/location.js`), the move from the old address, the explorer's file import, the home dashboard and the agencies page left `app.js`, and features import their helpers instead of taking them as parameters. `app.js` is 470 lines: imports, boot, view registration, page chrome and event wiring (no behavior change).
- "Copy page for AI" works on the Following page again (two imports were lost when AI copy moved into `src/features/ai/`).

## 2026-11-18
- A failed data fetch now releases its request at once: an unread 404 body (Luna shard indexes, `updates.json`) kept each request open until its 20 s timeout. E2E page opens drop from about 21 s to under 1 s.
- Feature folders 4.3: static pages and dialogs, AI copy, bill text, the drawer stages, the private review file, statutes, the review progress page, companions, Today, Near you, member pages, follows, saved searches, the watchlist tools and save buttons, saved lists and sync, the explorer (filters, results, preview, CSV) and the bill page moved into `src/features/`, with shared helpers, runtime values and redraw hooks in `src/core/` (no behavior change).
- Data files stay at the Cloudflare edge until they change: each data run purges only the files it added, rewrote or deleted (by modification time and size against `live/purge-state.json`), a failed purge is retried with the next run, and the daily check flags a purge pending over 2 hours. The edge TTL on those paths goes from 1 hour to 30 days.
- `/bill/<ID>` is one cached page for every visitor: Cloudflare serves the share page (people are sent on to the app), agents pick the Markdown record from its `rel="alternate"` link, and `Accept: text/markdown` is redirected to it. Before, every `/bill/<ID>` request reached the server.
- Following names which legislator and role each bill comes from again (lost in the compact rows); nightly E2E selectors follow the Nov 17 row redesign.
- Session readiness, checked against 558 real 89R histories: committees come from TLC's attributes (they were never read), hearing status from the full history (it saw only the last 12 actions), and status covers vetoes, laws without a signature and "Sent to the Governor". Referred bills no longer say "Prefiling stage".
- Cloudflare caching: the data run purges the files only it writes after every run, so the edge keeps them an hour (2aeefd2, 2202e8e).
- Removed the legacy Luna call stack; every call goes through the vendored cth.flex boundary (`--transport flex` is the only choice).
- Older bill texts gain official-file fingerprints (`source_sha256`), up to 200 per data run, with no re-review.
- Cloudflare Browser Integrity Check is off for billatlas.org (it blocked Python's default user agent).
- Bill pages can be indexed: search crawlers get the share page, which carries the official record and the first 3,000 characters of text.
- The data run submits rewritten bill pages to IndexNow; a failure never fails the run (`--no-indexnow` turns it off).

## 2026-11-17
- Bill pages get an "Ask AI" menu (ChatGPT, Claude, Copy for AI); the prompt links the bill text and has a search fallback.
- Pushes rerun only the server jobs whose code or inputs changed (`texas-bill-refresh.path`, `refresh_jobs.sh`); never the review.
- Checkable sources: text versions record the official file's SHA-256; share pages carry schema.org `Legislation` data.
- Agent bill pages separate the official record, computed fields and Luna's analysis, and include the bill text.
- Near you is about a third as long: one compact row per bill, five per section with "Show all".
- Agent readiness: `robots.txt`, `live/sitemap.xml`, an API catalog at `/.well-known/api-catalog`, `/openapi.json` and `/auth.md`.
- The site share card shows the warbler in the logo yellow.

## 2026-11-16
- Moving saved lists to billatlas.org: the old site offers "Move my saved lists" and hands lists, sync link and settings across.
- Sync never drops saved items over a limit; they are kept aside and listed on the Export page.
- Saved lists survive several open tabs, and a joined sync link keeps this browser's bills until a pull succeeds.
- The agent edition writes `robots.txt`, `sitemap.xml` and an HTML index so crawlers can find it.

## 2026-11-15
- New address: billatlas.org and agent.billatlas.org; bills.ctharvey.me keeps serving with no redirect so browser storage survives.
- Export page (`#export`) downloads this browser's saved lists as a profile file.
- Less repeated work: idle review runs stop rewriting unchanged files, and data runs read only changed history and text files.
- Luna tags and extras load as 32 content-addressed shards instead of the whole map.
- Security fixes M1 and M2: an edit link asks before joining, and a `__proto__` sort no longer crashes pages.
- Today is back in the nav; search reuses each bill's search text between keystrokes (about 15 ms per keystroke).

## 2026-11-14
- Reader areas (#13): 29 audience-based areas with an Area filter, a dashboard card and links from bill pages.
- Layout pass (#14) and review follow-ups (#15): faster first render, clearer empty states, two-column dashboard.
- Accessibility: one visible focus ring, 4.5:1 text contrast, page titles and focus per view, a skip link, 24px targets.
- Dark mode fixes for drop-downs and panels.

## 2026-11-13
- Remembered filters are no longer rewritten on load; views and click handlers moved to registries under `src/core/` (no behavior change).

## 2026-11-12
- Statute tracking: each bill lists the law sections it changes, and each section has a page with every bill that changes it.
- Population limits: bill pages show each population test and the places that meet it under the 2020 Census.
- Saved searches (up to 20), a Following page for followed legislators, and one profile file for all saved data.
- Follow a legislator, with an RSS feed of the actions on their bills.
- Tags made consistent: tenure reads First term / Mid-tenure / Senior; "Not rated" is now "No hearing yet".
- Party filter in the explorer; a held (unknown-outcome) review call now waits alone instead of stopping every lane.
- Deploys copy whole `src/` and `scripts/` folders, so code can move between files without reinstalling units.

## 2026-11-11
- Near you (`#local`): your House member and Senator, their bills, and bills naming your county or city.
- Member pages (`#member?code=...`) for every legislator; names link to them everywhere.
- Today view (`#today`), "Copy page for AI", and Copy for AI on each bill.
- Luna's second pass adds an "In brief" headline, search terms, a 2% audit sample and related bills.
- The "All state agencies" marker is decided by vote in the second pass under a stricter rule.
- Reviews use only the official Markdown text; a review is published only while it matches the served text.

## 2026-11-10
- Bill text on the site: the data run converts each official version to Markdown with insertions and deletions marked.
- Saving without accounts: links carry views and filters, share links, export/import, RSS feeds and private sync links.
- Agent edition (Markdown/JSON for every bill and view) with its own search.
- Companion bills are linked, grouped in results and can be watched together.
- Member roster with party tint, tenure and members-elect; last-action tags, filter and sorts.
- Review worker: Markdown input, `--workers N`, flex transport, Flex capacity waits instead of ending the run.
- Live data moves to `texas-bill-data.timer` writing `live/bills.json`; assets are content-hashed and cached for a year.
- First-visit disclaimer and a privacy policy in the footer.
