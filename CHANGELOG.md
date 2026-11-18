# Changelog

## 2026-11-18
- Official-file fingerprints for older texts: text versions stored before `source_sha256` existed are fingerprinted,
  up to 200 per data run (`SOURCE_BACKFILL_PER_RUN`), by downloading the official file again only when its MDTM still
  matches the stored copy. Our Markdown, its `sha256` and `generated_at` are not touched, so nothing is re-reviewed.
  Bills waiting their turn cost no extra FTP calls. Counted as `fingerprinted` in the text stats.
- Cloudflare Browser Integrity Check is off for the billatlas.org zone: it answered Python's default user agent
  (used by some AI fetch tools) with error 1010.
- Bill pages can be indexed by search engines:
  - Search crawlers were getting the app at `/bill/<ID>`, whose canonical address is the home page, so the sitemap's
    1,600 bill URLs all folded into the home page and no share page or Legislation data reached them. The gateway
    (cth.hosting) now serves the share page to Googlebot, Bingbot, DuckDuckBot, Applebot, Yandex, Seznam, Naver,
    Baidu and Qwant as well as link-preview crawlers.
  - Share pages show the official record in plain HTML: caption, session, status, filed date, most recent
    action, authors and sponsors, and official subjects. They also show the AI line labelled as not official, the
    first 3,000 characters of the latest bill text with its insertions and deletions, and links to the full text,
    the agent page and the official history. Their redirect into the app skips any user agent that says
    bot/crawler/spider, so script-running crawlers stay on the bill.
  - IndexNow: the server's data run submits the bill pages it rewrote to `api.indexnow.org` (Bing, Yandex, Seznam,
    Naver, Yep) and logs `IndexNow: HTTP <status>`. A failure never fails the run. The public key file is
    `public/7b91498ed44f1a3d41b650238bfe5f85.txt`. Other runs never submit; `--no-indexnow` turns it off.

## 2026-11-17
- The Ask AI / Copy for AI prompt ends with a fallback for assistants that won't open links from a prefilled prompt
  (Claude on the web refused all of them): search the web for "Texas Bill Atlas <bill>" (billatlas.org) and use its
  bill page and the official Legislature pages. The links stay first.
- Push-triggered server jobs: after publishing, `deploy_static.py` diffs the old and new `main` and leaves a marker in
  `/var/lib/texas-bill-atlas/refresh` for each server job whose code or inputs changed (`JOB_INPUTS`: members, data,
  agent, share cards; never review). `texas-bill-refresh.path` (root) sees the folder fill and
  `texas-bill-refresh.service` runs the installed `refresh_jobs.sh`, which starts those jobs one at a time in that
  order. A job already running is waited for and then run again, since it took its code before the push. Markers are
  written only after `main` moves, so a refreshed job runs the new code. Site-only pushes rerun nothing; an unreadable
  old commit reruns everything. The hourly timers are unchanged.
- Checkable sources:
  - Text sync records `source_sha256`, the SHA-256 of the official file as the Legislative Council served it, beside
    `sha256`, which covers our Markdown copy. Versions downloaded before this change gain it on their next download.
  - Agent bill pages list each text version's official file with its last-modified time (FTP MDTM, UTC) and SHA-256,
    and our copy with when it was made and its own SHA-256.
  - Share pages (`/bill/<ID>`, served to search crawlers and link previews) carry schema.org `Legislation` data:
    identifier, type, jurisdiction, caption, filed and last-action dates, authors, subjects, the official TLO page
    (`sameAs`/`isBasedOn`), and our Markdown text copy marked `UnofficialLegalValue`. No AI-written text goes in it.
- Agent bill pages say what each part is, so AI assistants can tell the record from the analysis:
  - **Official record**: caption, bill text, authors, recorded actions, subjects and companions, copied unchanged
    from the Legislative Council files.
  - **Computed by this site**: status, action type, hearing status, authorship and prominence, worked out by rules.
  - **AI analysis (Luna)**: the summary and tags.
  - A "Record current as of" line gives the Legislative Council's last update to the bill and when this site copied it.
  - The footer no longer says the record "can contain errors"; it says the copied record can trail the Legislature
    by an hour or two, and that computed fields and the AI analysis can be wrong.
  - The JSON record adds `record_updated`.
- AI assistants can read the bill text. Agent bill pages (agent.billatlas.org/bills/<ID>.md) gain a "Bill text"
  section: each version's official wording as our Markdown copy (live/text), its source file, and the latest
  version copied in full when it is 12,000 characters or less. The JSON record adds `links.full_text` and
  `text_versions`. Copy for AI and the Ask links now point to the same copy; before, the prompt never linked the
  text at all, because the snapshot's version links are ftp:// and were filtered out. capitol.texas.gov refuses
  most AI fetchers.
- Bill pages: an "Ask AI" menu in the top bar opens ChatGPT or Claude with the Copy for AI prompt already filled in
  (first shipped as links in Sources). Copy for AI moved into the menu as its last item; it stays because the prefill
  links are not a documented feature of either assistant. The menu closes after a pick, on a click elsewhere, or on
  Escape, and on phones it spans the button grid. The AI copy E2E tests open the menu first and expect the new "Full
  bill text" prompt line.
- The site's share card (public/social-card.png) shows the warbler instead of the gold star tile, and its stripe and
  "TEXAS" take the logo yellow #f5b517, matching the per-bill cards.
- Near you is about a third as long: each bill is one compact row (Luna's one-line summary, the official caption
  on one line, tags), five per section with "Show all N", and ceremonial resolutions (memorials, "Recognizing")
  fold into one line. Who filed a bill shows only when both legislators have bills here; a place tag shows the
  city and is dropped when it only repeats the single county. The matching explanation sits behind "How matching
  works", the empty member card is one line, and the repeated section heading is gone.
- Agent readiness basics for billatlas.org (Cloudflare's scan rated it "Not Ready"): `public/robots.txt` with
  rules, a Content-Signal line (search, ai-input and ai-train all yes) and a Sitemap; the hourly data run writes
  `live/sitemap.xml` (home plus every `/bill/<ID>`, dated by last action). A Cloudflare response-header rule adds
  a `Link` header to the home page (sitemap, Markdown edition, llms.txt).
- API catalog (RFC 9727) at `/.well-known/api-catalog` and an OpenAPI 3.1 description at `/openapi.json`, covering
  search, per-bill JSON and Markdown, the full data files, RSS feeds and the search service's health. Sources are
  `scripts/api/`; the data run copies them to `live/` and Cloudflare rules serve them at those addresses.
- `/auth.md` for agents: no registration or credential is needed for public data. Agents may ask a person for
  their view-only watchlist link and read it only through the watchlist feed, which rejects edit keys; never the
  edit link. No OAuth metadata is published because the site has no accounts.

## 2026-11-16
- Sync and the move keep every saved item (review fixes, not released): a sync write never cuts an item to fit a
  limit (500 bills, 200 legislators, 20 searches); what does not fit is kept aside and listed on the Export page.
  The sync client stores a version only together with the lists it adopted, adds a joined browser's bills itself
  (also for joins left half-done by the previous version), queues changes made while a link is created, and never
  forgets or replaces a link another tab joined meanwhile. The move checks the new site's own items and settings,
  carries the old site's kept-aside items, ignores default filters, answers its opener before the app loads, and
  says why it failed.
- Moving saved lists to billatlas.org (not released): bills.ctharvey.me shows a banner offering "Move my saved
  lists", which opens billatlas.org and hands this browser's lists, sync link and settings across by
  `postMessage` (origin, window and nonce checked). The new site adds them through its normal save paths (queued
  to its sync link), keeps anything over a limit or invalid aside for download, and reads everything back before
  saying it is done. The old site keeps everything. Rules in `src/core/move.js`; hand-off in `src/features/move/`.
- Saved lists survive several open tabs: each change re-reads storage and applies only that tab's change, and the
  sync client re-reads its state per call and never writes over a link another tab changed. A joined sync link
  merges this browser's bills until a pull succeeds (`joinPending`), so a failed first pull no longer loses them.
- Agent edition is now discoverable by crawlers: the hourly build writes `robots.txt` (allows OAI-SearchBot, keeps
  live search queries out), `sitemap.xml` (every Markdown page) and an HTML `index.html` linking every bill.
  ChatGPT wouldn't open agent.billatlas.org links because OpenAI's crawler had never seen those URLs.

## 2026-11-15
- Export page at `#export` (not in the nav): lists the bills, followed legislators, saved searches and theme this
  browser holds, and downloads them as the same profile file Import file reads. A fallback for moving saved lists
  to billatlas.org, which keeps its own browser storage.
- New address: the site is billatlas.org and the agent edition agent.billatlas.org (cth.hosting PR #26).
  Canonical links in the agent pages, feeds, search, the page head/footer and README use the new names; feed
  GUIDs carry no host, so readers see no repeat items. bills.ctharvey.me and agent.bills.ctharvey.me keep
  serving the same release, since watchlists, filters and sync keys live in browser storage for the address
  they were saved under. Sync accepts writes from both origins.
- Review fixes for the redundant-work changes (reports in `.agent/reviews/texas-bill-atlas-review-*-2026-11-15.md`):
  Luna shards are immutable files named by their hash, so an index the edge cache still serves resolves to its own
  map, the shards folder is world-readable under the worker's umask, and a failed shard publish removes the index
  so the page reads the single file. A run counts as idle only if no pass was cut short and nothing was deferred,
  held, skipped or failed (and no embeddings were bought); a stop during the idle wait exits cleanly, and
  `flex_boundary --release/--hold` clears the marker. Unchanged bills' texts are still MDTM-checked once a day
  and placeholders downloaded every 6 hours, in case TLC re-posts without moving a time stamp; only "213" MDTM
  replies count. A damaged related-bills state falls back to the full computation. The agent site's review pace
  counts back from the worker's status time.
- Review service: idle runs stop repeating. It started a run two minutes after the last ended (about 230 a day at
  2.5 to 3 CPU-minutes each, $0 spent) and each rewrote the 4 MB `tags.json`, `extras.json` and `audit.json` with
  only a new time stamp. Now unchanged maps keep their file and ETag; related bills reuse the last run's lists
  (`embeddings/related-state.json`) and recompute only rows a changed bill touches (property-tested equal to the
  full computation); and a timer start after a $0 run that changed nothing waits up to 30 minutes for new data or
  code instead of re-reading every bill.
- The site loads Luna tags and extras as content-addressed shards with a small index, cached by hash, so a review of
  a few bills refetches a few of 32 shards instead of the 857 KB (gzipped) map on every visit.
- Agent edition: district pages and the paged bill index point to the overview for "as of" times instead of
  carrying them. The full-text tags time moves with every review run, so 181 district pages and the bill index were
  rewritten every hour with no bill changed. The overview, 404 and recent pages still show the times.
- Bill texts are read again only when their own file changed. Before, any new action on a bill re-read every text
  version (the bill's update time stood in for the text's), and the 24 texts TLC has not posted yet were read every
  hour, all counting against the 400-per-run limit. Now a bill whose update time is unchanged costs no FTP call; a
  changed bill costs one MDTM per version; placeholders are remembered (`live/ftp-text-pending.json`) until their
  file changes; and unchanged `index.json` files are no longer rewritten. On a copy of live data: the first run kept
  all 1,497 texts without reading them, the next took 0.9 s with no downloads.
- The hourly bill-history import only reads files that changed. Re-reading all 1,521 history files took 11
  minutes (0.4 s per file), which would be about 85 minutes at session volume, past the hour and the unit's
  45-minute limit. It now LISTs each FTP folder and reads new or changed files, plus 1/24 of the rest each hour
  as a daily re-check, capped at 3,000 files or 20 minutes per run. Checked against the real server: the first
  run reproduced the live snapshot exactly, the next read 64 files in 20 s, and a run with 3 altered fingerprints
  read exactly those 3 plus the re-check share. Plan:
  `.agent/plans/texas-bill-atlas-session-readiness-roadmap-2026-11-15.md` (item 1).
- Security audit fixes (`.agent/reviews/texas-bill-tracker-security-audit-results-2026-11-15.md`, M1 and M2):
  an edit link now asks "Join this synced list?" before it adds this device's bills, legislators and saved
  searches to someone's list or replaces this device's own link (a device with nothing saved still joins straight
  away). A sort of `__proto__` from a link, a synced saved search or a profile file is dropped by the page and the
  sync server instead of crashing the dashboard and Following page, and an impossible "last opened" date no longer
  crashes Following. The sync server change needs the sync container redeployed.
- Today is back in the nav (Browse, after Home; under More on phones), with a count when today itself has
  activity. Its rows put the action, who filed the bill ("by Rep. ...") and the tags on one line, and on phones the
  topic chips are one scrolling row so the first bill shows without scrolling.
- Search keeps each bill's search text between keystrokes instead of rebuilding it for all 1,521 bills every time
  (it starts over when bills or Luna's agency names change). Desktop: a keystroke went from about 22 to 15 ms, and a
  search that matches nothing from 9.5 to 2.3 ms; results unchanged. No debounce.
- The bill page no longer asks for its changes, fiscal and witness files twice when Luna's files arrive after it
  opens.

## 2026-11-14
- Reader areas (#13): 29 areas built around who follows them (cybersecurity & IT, procurement, accessibility,
  children & youth, courts, ...), from the Legislative Council's official subjects plus title/caption keywords
  (`src/features/areas/model.js`). The explorer has an Area filter (`#all?area=<id>`) with a header for the chosen
  area, the dashboard a "Browse by area" card, and bill pages link their areas. Kept apart from `POLICY_AREAS`, so
  Luna's requests and cached reviews are unchanged. The sync server accepts the new `area` filter.
- Visual review fixes: the Data, Saving and Near-you panels no longer show a white slab in dark mode; changing view
  starts at the top of the page; the explorer's stat line says "bills in this snapshot" (it never followed the
  filters); the bill page says "Add to watchlist" like the rest of the site, and drops a caption that repeats the
  title; the preview pager counts every match and Next loads more; the agency index shows a code only when it is a
  real short form; method and saving cards lose their 01-06 numbers; reader-area badges look like links; the bill
  section tabs fade at the edge when they scroll; the previewed card's marker is no longer a star.
- Dark mode drop-downs: the theme picker and the other native selects drew white lists with near-white text; their
  options now carry the theme's surface and ink. The agency picker panel loses its hard-coded white too.
- Accessibility pass from the design review: one visible focus ring in the accent colour (search and agency inputs
  no longer remove it); smooth scrolling only without reduced motion; the hidden agent hint is out of the tab order.
  Secondary text, the atlas muted colour and the status pill pass 4.5:1 in light themes, and input borders 3:1.
  Each view sets the page title, marks its nav item `aria-current`, and moves focus to its heading; a skip link
  leads to the content. Card buttons name their bill ("Add HB 1159 to watchlist"), truncated headlines carry the
  full text as a tooltip, re-renders keep focus on the control that was used, and phone inputs are 16px so iOS
  does not zoom.
- Layout pass (#14): the dashboard puts search beside the milestone and its cards in two columns that no longer
  share row heights (phones keep the old order). The explorer's filter selects scroll in one row on phones, beside
  More filters, and Share / save sits beside the search box; topic chips hide while an area is chosen, and the area
  header names its top three agencies in a sentence. The watchlist folds its filters under one Filters toggle.
  The agency index has a filter box and no empty band in its cards. Method and Saving read as one column, card
  titles stop at 80 characters a line, and on phones the bill page shows Overview before the key facts and its
  four buttons in two rows. The page heading no longer shows a focus box after a view change.
- On phones the bundled-copy notice reads just "Showing the bundled copy." and the Coverage & sources link.
- Review follow-ups (#15): the page shows the bills as soon as they, the roster and the review status arrive; Luna's
  files (about 1 MB) load afterwards with a 20-second limit and redraw the page, instead of holding the first render
  and being dropped after 7.5 seconds. The live bills get 15 seconds before the bundled copy takes over. Nav items
  are links (they open in a new tab); member and law-section pages name the member or section in their heading,
  and the bill page heading leads with the bill number. Restored filters say "Filters from your last visit", empty
  results offer to clear filters or search every bill, and an unknown bill offers a search for it. Problem callouts
  are amber, not green. "Scoring method" is now "How it works" (`#method` unchanged) and explains who Luna is; the
  AI badge and Luna's bill-page section point there. Data & imports shows reviewed and tagged counts separately.
  Small targets (bill numbers, footer and project links, theme select, preview close) reach 24px; gold and red
  state text passes 4.5:1; Windows high-contrast and "increase contrast" get their own rules; review highlights
  are keyboard buttons (Enter or Space).

## 2026-11-13
- Remembered filters are no longer rewritten on page load when they mean the same thing (the party filter had
  added `party: ""` to every older save on each visit). Explorer and Watchlist views now come from a view registry
  and clicks from an ordered handler registry under `src/core/`; behavior is unchanged.

## 2026-11-12
- Review worker errors are actionable: stopped, failed, held and deferred lines end with the next step (never the
  provider's error text), an unexpected stop names the code location, and an unknown-outcome stop names the pending
  request. `scripts/flex_boundary.py` lists pending rows and `--hold <key>` turns a leftover one into a held call.
- Tags made consistent:
  - Bill cards no longer show "Tenure documented" (it only said a service record existed). The author pill now uses
    the same tenure tag as member lists, by time in the current chamber: "Senior author" or "First-term author",
    nothing for mid-tenure; a verified leadership role or committee chair shows as a ◆ pill.
  - Tenure tags read First term / Mid-tenure / Senior (was Newcomer / Average tenure / Senior).
  - Hearing progress "Not rated" is now "No hearing yet"; old links, saved searches and remembered filters map to it.
    Agent pages `hearing/not-rated*.md` are now `hearing/no-hearing-yet*.md`.
- Party filter in the bill explorer: Republican, Democratic or Bipartisan authors.
- Parity suite before reorganizing code into feature folders:
  - A browser test module per feature, run on raw `src/` and on the deployer-built bundle, plus tests that load saved
    data written by the current site (browser storage, profile files, a sync database) so no one's saves are lost.
  - Golden outputs for the feeds, agent pages, search, sync service and model requests.
  - All of it runs in CI on every push.
- Deploys copy whole folders: the static deployer publishes everything under `src/`, and the data, members and agent
  units and the sync service take the whole `scripts/` folder. Code can now move between files without reinstalling
  anything on the server.
- Population limits: the bill drawer shows each population test a bill sets ("a county with a population of more
  than four million") and the places that meet it under the 2020 Census (Harris County), including threshold changes
  with the places newly covered, extra conditions flagged, and limits quoted from existing law. Built hourly into
  `live/brackets/` from a committed 2020 census table; the data unit needs reinstalling to copy that table.
- Population limits, after a hand check: tests on a neighboring or contained place ("adjacent to a county with
  ...", "contains a municipality with ...") are labeled as such instead of read as the bill's target; "between X and
  Y", "county or municipality", plural "populations" and renumbered list items are read; each limit shows its own
  SECTION; and every population phrase that could not be read is counted.
- Statute tracking: each bill lists the sections of Texas law it amends, adds or repeals ("Laws this bill changes"),
  and each section has a page (`#statute?law=LA&sec=62.051`) with every bill that changes it and any two versions
  side by side, current law included. Searching a section number ("62.051", "Penal Code 46.06") finds the bills.
  Built hourly from the bill text into `live/statutes/`; about 89% of bills with text name at least one section.
- Saved searches: "Save search" in the explorer keeps the current filters under a name (up to 20). They are
  listed on the Following page with their bill count and how many bills have new actions since the search was last
  opened, can be renamed or deleted, and go into exported files and sync links (never share or view-only links).
  The sync service accepts bodies up to 32 KB, the gateway's limit.
- Saved data as one profile: "Export file" now saves the watchlist and followed legislators together
  (`texas-bill-atlas-profile-v1`; older watchlist files still import), and sync links carry follows across devices
  once the sync service is updated. Share links and view-only links still show bills only.
- Following: a new nav item and page (`#following`) for followed legislators and their bills, separate from the
  Watchlist, which keeps starred bills and the save/share/sync tools.
- Follow a legislator: a Follow button on member pages and Near you cards, kept in this browser only; their bills
  appear in a "Followed legislators" section on the Watchlist. Every legislator also has an RSS feed of the actions
  on their bills (`live/feeds/members/<CODE>.xml`), linked from the member page.
- Luna review (flex): a call with an unknown outcome (timeout, 5xx after sending) no longer stops every lane. It
  is booked at its upper bound and held: never resent, only its bill (or question, or fiscal check) waits, and the
  other bills keep going. Three held calls stop all new calls until an operator releases them with
  `scripts/flex_boundary.py --release`, which keeps the booked cost and lets the bill send once more.

## 2026-11-11
- Tenure tags: Newcomer (first term), Average tenure, Senior (12+ years), by time in the current chamber, with other-
  chamber service shown beside it; on member pages, Near you cards and the drawer's author list.
- Near you: numbers or an address typed while the district maps were still loading were wiped when they arrived;
  they are now kept.
- Member pages (`#member?code=A4875`): each legislator's district, counties, tenure, official links and bills by
  role, for every roster member. Every legislator name (card "By" line, drawer "Filed by" and author list,
  companion rows, Near you) links to it when the roster matches the name.
- Roster: representatives elected to the Senate (Ashby SD 3, Paul SD 11, David Cook SD 22) now get their Senate
  district from the 2026 results file, instead of none; entries from NBC 5 DFW's unofficial results.
- New "Near you" view (`#local`): your Texas House member and Senator, the bills they filed or signed, and bills
  naming your county or city. Set it by browser location, county, district numbers or an optional Census address
  lookup; only district numbers and the county are kept, on this device. District data from TLC plans
  PLANH2316/PLANS2168 and Census county lines (`scripts/build_districts.py`, `data/geo/`). Agent edition gains
  `districts/house-<n>.md` and `senate-<n>.md` (agent unit copies `src/geo.js` and `districts.json`, passes `--districts`).
- "All state agencies" marker is a vote: two second-pass calls, a third only as a tie-breaker; it publishes once two
  agree (one extra call per bill, two on a disagreement; roughly $0.00015 each). Each vote is its own cached, ledgered request
  bound to the review and text it answered.
- Review progress: shows every bill under review at once (up to three with `--workers 3`), not just the last one
  started. `status.json` gains `in_progress`, rewritten as each bill starts and finishes; `current` stays.
- Data sync: TLC's "not currently available, see the PDF" placeholder text is counted as `not_posted` and logged as
  "official text not posted yet" instead of a conversion failure; it is still retried every run.
- Companions: an agency filter also lists a bill whose companion carries that agency (dashed "via companion" tag),
  and both Copy for AI texts name each bill's companions.
- "Copy page for AI" in the top bar copies the current view (filters, AI-readable links, up to 50 bills) as text.
- Frontend: bill titles and numbers are real links and empty card space opens the drawer; the drawer has "Copy for
  AI" and an AI-readable link; new "Today" view (`#today`) shows the day's activity by action type and topic.
- Generic agency names ("the department", "the commission") are published as the registry agency when the amended
  code chapter's verified definition names it (`scripts/agency_name_definitions.json`, publish time only, no cost).
  Maps 42 of 109 such labels on the current reviews; the rest stay as written.
- "All state agencies" marker moves to the second pass: decided from the bill text under a stricter rule, published
  only with verified, undeleted quotes; the first pass's marker is no longer published. The second pass now sends the
  bill text, so every bill is asked once more (about $0.0003 each) and companions no longer share one call.
- Markdown only: the PDF review path is retired, and every published Luna file includes a bill only while its
  review matches, byte for byte, a Markdown version the site serves. Re-rendered but identical text keeps its
  review (re-attached with evidence, no cost); real changes wait for re-review (`--allow-text-rereview N`).
- Audit fixes: a re-attach also moves the review's audit record and fiscal check, and runs again just before
  publishing; bills the converter breaker holds stay held across runs until approved; a new version whose reviewed
  version left the index is reviewed afresh instead of failing every run; a run that stops still withdraws reviews
  whose text is no longer served (offline publishers only).
- Second pass also writes a plain-language "In brief" headline plus search and opposing-side terms (extras.json);
  `--audit-sample` spot-checks ~2% of reviews (counts only published); `--related-bills` adds a Related bills
  section from cached embeddings. Production unit runs all three.
- Topic suggestions (`--suggest-topics`): a cheap, cacheable second pass after the review queue empties; private,
  with a tally report for promoting new topics.
- Staged review (`--stages`, off in production): version updates with a "What changed" list, a fiscal-note
  check, and the bill drawer's What changed, Hearing (official witness lists) and Fiscal note check sections.

## 2026-11-10
- Review worker runs `--workers 3` for the full Markdown re-review (earlier reviews archived on the server).
- Review worker reads the official Markdown text (`--input markdown`) instead of the introduced PDF. The prompt
  no longer has the summary repeat the standard effective-date clause, and local-government money, programs,
  powers or duties count for Local government.
- Review prompt: contiguous quotes only (no "..." joins), named Texas courts map to `tx-courts`, tags need a change
  to that area's law, programs or money, and a conditional effective date is stated in the summary. Bills reviewed
  again after this send a new request (their old cache entries no longer match).
- Review: a span ID written with its source label (`[P015S001; paragraph 15]`) is read as the bare ID before
  validation; Markdown input now labels paragraphs `[P015S001]` and tells the model to cite bare IDs. PDF requests
  are unchanged.
- Review worker: `--workers N` (flex transport only, default 1) reviews several bills at once; the main thread keeps
  every queue/status/review write, and a capacity pause, unknown outcome or quota stop applies to all workers.
- Review worker: `--transport flex` routes Luna calls through a vendored copy of cth.flex 0.1.5 (client, spend ledger
  and response cache, on the existing files) behind `scripts/flex_boundary.py`. The default stays `legacy`, so
  production is unchanged.
- Privacy policy: a "Privacy" footer link opens the policy in a dialog (it ships inside `index.html`, the only page the
  static deploy publishes).
- Identical companions share one review: a bill whose Identical companion was already reviewed reuses that review
  (no model call) when the bill texts match apart from the author line and bill number, and the copy verifies the
  same claims against this bill's own text. Two separate reviews of the same text had picked different topics.
- Review worker: every unseen bill gets its first pass before any follow-up questions (a new bill's questions are
  asked on its next visit, so a capacity refusal on a question no longer holds up new bills); runs last up to 55
  minutes, and a timer start during a still-running review exits cleanly. The data run saves analyses and fiscal
  notes as Markdown and, after a hearing, the committee witness list (who testified, for/against/on, organization)
  next to each bill's history.
- Sync service rate limits count an IPv6 visitor per /64 instead of per address, so rotating addresses inside one
  /64 no longer earns fresh limits; IPv4-mapped addresses share their IPv4 limit. A body over 16 KB still gets 413
  without being read, and the service now drops up to 1 MB of it (2 s at most) before closing, so the client
  receives the 413 instead of a connection reset (the cause of the flaky oversized-body test on Windows).
- Staged review groundwork: the data run writes each bill's coded action history and analysis/fiscal-note links
  to `live/history/<BILL>/history.json` (not `bills.json`). The review worker can read the official Markdown
  instead of the PDF (`--input markdown`, off by default) so Luna sees added and deleted language. Follow-up
  review questions use medium reasoning (`--question-effort`); the first pass stays high.
- "Newest" puts the latest filings first within a day: filing dates have no time, so same-day bills now sort by
  type and then highest number first (numbers are assigned in filing order) instead of lowest first.
- Bill text on the site: the hourly data run converts each version's official HTML to Markdown
  (`live/text/<BILL>/<code>.md` plus `index.json`; additions as `<ins>`, deletions as `<del>`, sections as
  headings), downloading only new or changed versions, at most 400 per run. The review worker publishes
  `live/luna/highlights/<BILL>.json` from existing reviews (no model calls): each verified claim's quote located
  in the text by exact match, rule-derived key points, and unmatched claims listed as unlocated. The drawer's
  "Bill text" section shows the text with a version picker, key points, highlight filters by kind and agency,
  Luna's explanation on click, and the official text link. tags.json is unchanged.
- Sorting compares bill numbers as numbers (HB 99 before HB 100): the agencies, hearing and author-prominence
  sorts break ties by number instead of the data file's order, the data file itself is ordered that way, and
  agent search breaks ties the same way.
- Official subjects: the data refresh keeps the Legislative Council's subject index from the bill history
  (`<subjects>`, e.g. "Artificial Intelligence"), and both searches match it, so a bill with a vague caption is
  found before its full-text review (HB 280 for "artificial intelligence"). The drawer and agent pages list them.
- The explorer and the Watchlist keep separate filters: opening the Watchlist no longer applies the explorer's
  search and filters, and they come back on returning to the explorer. Remembered filters are the explorer's.
- Sync service listens with a backlog of 512 instead of socketserver's 5, so a burst of connections waits instead
  of being dropped into a 1 s client retry (seen from 100 requests a second in a load test).
- Watch companion bills as a group: a "Watch all" button on each companion block and in the bill drawer's
  companion section adds every bill in the group (or removes them when all are watched); the watchlist shows them
  together. The watchlist is still a list of bill ids, so sync, share links and export are unchanged. When only
  part of a group is watched, the Watchlist still shows the whole group, with unwatched companions dimmed and
  marked "Companion · not watched" (not counted in the total).
- Companion bills in results: when a bill and its companion both match, the companion moves up next to it and the
  two cards are drawn flush in one framed block headed "Companion bills · HB 445 + SB 329 · identical"; "Load more"
  never splits a block. Agent search lists them together, adds a Companions column ("also in these results") and
  a `companions` list per JSON result.
- The page revalidates its bill, tag, roster and review-status JSON (`cache: 'no-cache'`) instead of always
  downloading it, so a returning visitor gets a 304. Sync container limits raised to 1 CPU, 512 MB and 256 pids.
- Companion bills: the data refresh keeps the `<companions>` field from the bill history (it was dropped), and links
  work in both directions. Cards get a "Companion" tag, the bill drawer lists each companion with its relation,
  author and status, adjacent companions in a list are framed together, and agent pages and JSON list companions.
- Search reads pasted bill numbers with hidden characters (zero-width spaces, non-breaking spaces) and the
  "H.B. No. 267" and "House Bill 267" forms, which used to find nothing.
- Releases serve the scripts and stylesheet from `assets/<digest>/`, a content-hashed copy of `src/`, so Cloudflare
  and browsers cache them for a year; a deploy points `index.html` at the new folder. Needs the deployer reinstalled.
- Agent search, after a fifth LLM probe: `OR` splits the query into alternatives that can be several words or a
  quoted phrase (`lottery OR casino OR sports betting` used to need every word after the first OR); the page shows
  how it read the query. A partial-match headline no longer claims "127 bills matched unicorn tax" and names the
  words that matched nothing; a name with no bills says no member by that name is in the data; results gain
  Authors and Party columns; filter-only results say which filter matched; `/search` lists the exact topic names.
- Agent search, after a fourth LLM probe: `OR` between words; THC and hemp join the cannabis synonyms; a partial
  match shows only the bills matching the most words plus a count per word; "did you mean" for misspelled member
  names; results note that unreviewed bills are searched by caption only; known topic names and agency ids match
  exactly (`agency=tea` no longer matches the Teacher Retirement System). Unreviewed bill pages give an approximate
  queue position and wait; the overview and filing-date index define "Filed" (prefiling opened 2026-11-09).
- Agent edition, after a third LLM probe: search replaces the `words/` keyword pages; synonyms work in both directions
  (firearm finds what gun finds; voucher, "school choice" and "education savings account" find each other); a
  `location` filter matches review locations and captions; review progress buckets add up (retries were counted
  twice) and give a pace estimate and queue order; full-name member addresses (`authors/house-ann-johnson.md`) point
  to the listed-name page; `recent.md` points to date search; the sync docs state the rate limits.
- Agent search at agent.bills.ctharvey.me/search (sync service, read-only): word forms, phrases, synonyms, bill
  numbers and members across every agent field, with filters, paging and JSON. Agent pages now say when data is
  missing or pending (queued, retrying, failed), review counts agree everywhere (published reviews), a 404 page lists
  the bill numbers that exist, and `llms.txt` opens with a quick reference. Bill and watchlist RSS feeds include a
  dated item when a full-text review is published or redone.
- Agent edition at agent.bills.ctharvey.me: hourly Markdown/JSON for every bill and filter view, built from the
  tracker's own pipeline in a network-less container; the main page links to it. Back now closes an open bill.
- Agent edition, after an LLM usability probe: keyword pages for caption words, filing-date, authorship-party and
  full-text-review indexes, topics/agencies/review columns in every table, 150-bill pages (the all-bills page was
  285 KB), plain wording when no hearings exist or one group holds every bill, official bill-text links, and coverage
  counts that explain empty coauthor/sponsor fields.
- "Saving your info" page (`#saving`, under Reference): how the watchlist, remembered filters, view links, share
  links, export/import, private sync links and RSS feeds work, and what is stored where; linked from the Watchlist.
- Saving without accounts: views, filters and open bills live in the URL (copy link); share links open a
  read-only shared list; last filters are remembered; watchlist export/import; per-bill RSS feeds built hourly
  from newly recorded action dates; private sync links, live via the `texas-bill-sync` container on `edge-bills`
  behind the shared gateway's `/api/sync*` route (`deploy/sync/`).
- First-visit disclaimer: independent open-source project, no accuracy warranty, automated/AI tags can be
  wrong, not advice, check the official record. Remembered per device; reopen from the footer.
- Review worker: Flex capacity rejections no longer end the run. The rejected bill waits out its retry-after
  while other bills continue, and is revisited in the same run; back-to-back rejections pause at most 60 s.
- Review progress: new tracker view showing reviewed, in-progress (current and retry), failed and not-started
  bills, with the bill under review and the next ones up; the worker publishes `live/luna/status.json`.
- Review worker: `--no-spending-cap` disables the $1/day and $0.10/run ceilings while keeping reservations,
  the ledger and double-billing checks; `--order reverse` reviews from the bottom of the snapshot up. The
  production unit uses both until the backlog completes.
- Last action: cards show a categorized last-action tag with chamber and date; new "Last action" filter and
  sorts by latest action, oldest last action and last-action stage.
- Members-elect: party and district for the 41 new members from the SOS unofficial 2026 general election
  results (`data/members_elect_2026.json`), labelled as such and used only when the ballot name agrees.
- Member roster: `sync_members.py` joins the TLO 90th roster to LRL party, district and tenure; bill cards are
  tinted blue/red by primary author party, purple for bipartisan authorship, neutral when unknown; the drawer
  shows each member's party, district and tenure; daily `texas-bill-members.timer` refreshes `live/members.json`.

- Review worker: failed downloads/reads go to a `failed` queue instead of being marked seen; five consecutive
  new download failures stop the run; oversized or already-billed requests flag only that bill; budget and
  capacity stops during review questions end the run and keep the bill in retry; dry runs never mark bills
  seen; a deferred bill no longer overwrites its earlier review; the ledger day is computed in Chicago time per
  call; add a between-bills `--max-minutes` limit (default 50). Add worker loop counterexample tests.
- Data refresh: rebase-and-retry pushes; keep `generated_at` when nothing changed (six-hour heartbeat) so idle
  runs no longer commit; a scheduled public hearing is no longer recorded as heard; tolerate 4xx FTP replies.
- Deployer: prune to the ten newest releases plus the live one and remove crashed staging directories.
- Tracker: warn on bundled fallback, local imports and snapshots older than eight hours; fall back to the bundle
  when the remote snapshot is malformed or incomplete; match author profiles by surname; stop counting the
  all-agencies scope marker as an agency; fix hashchange crash, spaced bill-number search, the scheduled-hearings
  stat, CSV round-trip and import rollback, topic word boundaries and unsafe profile links.
- Remove the unused GitHub Pages workflow and orphaned `.openai/hosting.json`.
- Public Luna tags: the review worker publishes citation-verified claims to `live/luna/tags.json`; the tracker
  overlays them on each bill (topics, agencies, effects, groups, locations, summary) with a "Luna · full text" label.
- Live data: the hourly FTP import moves to `texas-bill-data.timer` on the server writing `live/bills.json`; the
  tracker loads it before the bundled snapshot; `refresh-bills.yml` is manual only; releases get a `live` symlink.

## 2026-11-09

- Remove the review worker's per-run bill cap. Runs proceed serially until the $0.10 run or $1/day guard
  stops them; the service no longer has a start timeout that could kill a run mid-request.

- Enable the private hourly review worker on the existing VPS with the authorized $1/day ceiling, protected
  credentials/cache, and priority retries that leave capacity for new bills. Verify live annotated review,
  mobile layout, watchlist persistence and the complete 1,262-record official snapshot.

- Integrate complete-text review in bill details with selectable verified highlights, reasons, agency certainty,
  source links, open questions and reviewed corrections. Review imports remain private to the browser session.
- Add private queued Luna classification and targeted cleanup with cached official sources, source-generated
  evidence options, typed corrections, a persistent $1/day spending guard, and bounded hourly systemd operation.
  Keep publication approval separate and leave the complete official metadata dataset unchanged.

- Add scoped, citable statutory definitions to focused classification, starting with Water Code Chapter 16
  identities for TWDB and TCEQ. Keep bill-impact and definition evidence separate, prefer in-bill definitions,
  and include substantive context changes in cache identity without billing another pilot call.

- Resolve classification excerpts against complete source text, derive page offsets and span links, and
  flag ambiguous or missing quotes without fuzzy acceptance. Fix all six HB529 citation placements offline
  while preserving the original model response and semantic review requirements.

- Preserve the detailed extraction version and add focused Luna Flex full-text classification for summaries,
  policy tags, agency impacts, locations, affected groups, major effects and verifiable excerpts. Reuse the
  private response/prompt caches and leave all classifications unpublished pending evaluation.

- Fix unmatched entity IDs to accept null and reject empty strings; add explicit business-day units following
  the held-out HB529 evaluation. Schema changes invalidate response reuse; prior raw responses stay intact.

- Add optional Terra Flex full-text extraction with explicit actor certainty, atomic obligation instructions,
  event-relative calendar types and unknown interval boundaries. Keep outputs private and pending review.
- Reuse responses persistently by complete text/configuration; protect concurrent calls and uncertain failures.
  Cache shared prompts and derive evidence links, counts and review signals without additional model calls.

- Schedule the official FTP refresh hourly, at minute 17, instead of every twelve hours.
- Import separate author, coauthor, sponsor and cosponsor lists. Show counts on cards and full member lists in details; include them in search and CSV export.

- Parse official TLC authors and dated filing actions; refresh the full dataset so authors and Filed today display correctly.
- Add an unprivileged pull-based production deployer and systemd timer for bills.ctharvey.me.
- Publish complete official snapshots atomically; keep the previous release on fetch or validation failure.
- Keep GitHub Pages available by manual dispatch. Document production operations and deferred improvements.
