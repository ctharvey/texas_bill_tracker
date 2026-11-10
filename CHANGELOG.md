# Changelog

## 2026-11-10
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
