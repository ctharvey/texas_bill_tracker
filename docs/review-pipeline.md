# Luna review pipeline

`scripts/review_pipeline.py` reviews each bill's full official text with Luna (OpenAI, Flex tier) and publishes
only what it can verify. It runs as `texas-bill-review.service` under its own account; results land in
`live/luna/`.

## What it does

- **Input**: the official Markdown the site serves (`live/text/<BILL>/<code>.md`, checked against `index.json`).
  Missing or mismatched text counts as a download failure and is retried after the next data run. The PDF path is
  retired.
- **First pass** (`classify_bill.py`): summary, policy tags, affected agencies (direct or inferred), locations,
  groups, major effects, each with quotes. Quotes are matched against the text; unmatched or ambiguous quotes are
  rejected, never fuzzy-matched.
- **Follow-up questions**: up to three targeted questions per bill per run for unresolved citations or agencies,
  answered from source-generated options. Official statute chapters are fetched from fixed URLs only and cached
  privately for seven days.
- **Staged review** (`--stages`): a new text version gets a version update ("What changed",
  `live/luna/changes/<BILL>.json`); a fiscal note or analysis gets a fiscal check (`live/luna/fiscal/<BILL>.json`).
- **Second pass** (`--suggest-topics`): an "In brief" headline and search terms (`extras.json`), topic suggestions
  (private), and the "All state agencies" marker, published once two votes agree.
- **Audit** (`--audit-sample`): an independent re-check of about 2% of reviews; only counts are published
  (`audit.json`).
- **Related bills** (`--related-bills`): embeddings of caption and summary; top five neighbours at 0.5 cosine or
  more (`related.json`).

## Publishing rule

A bill appears in any published file only while its review was read from Markdown whose hash matches a text version
the site serves. Re-rendered but identical text keeps its review at no cost; a real content change waits for
re-review, and when many texts change at once (a converter change) only `--allow-text-rereview N` of them are
re-reviewed. A field whose claims all failed verification is left out, and the site falls back to caption rules.

Published: `tags.json` (also as content-addressed shards under `shards/` with `tags-index.json`), `extras.json`
(likewise sharded), `highlights/<BILL>.json`, `changes/`, `fiscal/`, `audit.json`, `related.json` and `status.json`
(what the worker is doing, read by the Review progress page). Full review bundles stay private in the cache.

Two reviewed tables refine agencies: `scripts/statutory_definitions.json` (statute definitions sent to Luna) and
`scripts/agency_name_definitions.json` (publish time only, maps "the department" to a registry agency when the
amended chapter defines it).

## Production

The unit runs `--execute --input markdown --stages --suggest-topics --audit-sample --related-bills --workers 6
--order reverse --restart-on-update --no-spending-cap` (see `scripts/texas-bill-review.service` for the full line).

- Each run lasts up to `--max-minutes` (55). The timer starts the next run two minutes after one ends. A run that
  spent nothing and changed nothing makes the next start wait up to 30 minutes for new data or code; delete
  `<cache>/idle.json` to start at once.
- **Deploying**: with `--restart-on-update` a run checks for new code every five minutes, finishes the bills in
  progress and exits, and the next start pulls. Never kill a run to deploy: a call cut off mid-request is held.
- **Pausing**: stop and disable `texas-bill-review.timer`. The site and data jobs are independent of it.
- **Logs**: `journalctl -u texas-bill-review.service`. Every stopped, failed, held or deferred line ends with the
  next step.

## Spending guard

Every provider call goes through the vendored cth.flex library (`scripts/vendor/cth_flex`, imported only by
`scripts/flex_boundary.py`). Before each call a durable ledger (`<cache>/budget.json`) reserves an upper bound;
cached responses (`<cache>/responses/`) make no call.

- Ceilings: `--daily-budget` (default and maximum $1 per Chicago day) and `--run-budget` ($0.10). Production runs
  `--no-spending-cap`, which skips only the ceilings; reservations, the ledger and double-billing checks still apply.
- **Held calls**: a call whose outcome is unknown (timeout, 5xx after sending) is booked at its upper bound, never
  resent, and only its bill waits. Three held calls in 30 minutes, or ten in 24 hours, stop all new calls.
- **Releasing**: after checking the provider's usage log, with no run active, as the service user:
  `python scripts/flex_boundary.py --cache-dir <cache>` lists held calls; `--release <key>` releases one (its bill
  sends once more); `--hold <key>` holds a row a stopped run left pending. Never hand-edit the ledger.
- Quota, billing or key errors stop the worker and later starts wait an hour; delete `<cache>/account_stop.json` to
  retry sooner. Flex capacity refusals only set the bill aside until the provider's retry-after.

## Server setup

Account `texas-bill-review`, with `/var/lib/texas-bill-review/{repository,venv,cache}`. The repository stays on
`main` and pulls with `--ff-only`. `OPENAI_API_KEY` lives only in root-owned, mode 0600
`/etc/texas-bill-review.env`. Private cache directories must never be added to the web root or to git.

The earlier detailed extraction contract is preserved on the
[`archive/detailed-extraction-v1`](https://github.com/ctharvey/texas_bill_tracker/tree/archive/detailed-extraction-v1)
branch.
