# Changelog

## 2026-11-10
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
