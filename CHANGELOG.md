# Changelog

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
