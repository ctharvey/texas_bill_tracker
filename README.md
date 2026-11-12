# Texas Bill Atlas

An independent, open-source bill tracker for the Texas Legislature's **90th Regular Session (2027)**. Built for fast exploration by policy, state agency, author prominence and the verifiable legislative path to a hearing. It loads the official FTP snapshot (1,262 legislative measures as of November 10, 2026); the interface displays the dataset's source and timestamp and warns when it is showing the bundled fallback, a local import, or a snapshot more than eight hours old.

## What it does now

- Search and filter by bill number, author, topic, chamber, affected agency, procedural stage, and hearing status.
- Surface **multiple potentially affected agencies per bill**, distinguishing directly supported mentions from inferred connections. The agency catalog is an extensible starting vocabulary, not a claim of complete statutory review.
- Include the Texas State Board of Public Accountancy for CPA certification and licensing bills, and a separate **All state agencies (cross-cutting)** scope tag for general agency-wide requirements. Explicit broad language gets a direct tag; broader compliance inferences are marked possible. The cross-cutting scope is not counted as another physical state agency.
- Show author institutional influence **only when a verified role or tenure fact has been entered**. No party-only influence assumptions.
- Show referral, scheduled hearing and hearing held as separate procedural signals. A prefiled bill without committee evidence is *not rated*, never assigned an invented probability.
- Maintain a device-local watchlist, view bill details and source links, export filtered CSV, and import CSV/JSON datasets locally.
- Include a conservative bulk updater for the [Texas Legislative Council's official FTP service](https://capitol.texas.gov/billlookup/filedownloads.aspx) run hourly by a server timer (a manual GitHub workflow refreshes the bundled fallback).
- On the hosted app, read the repository's current `data/bills.json` snapshot, falling back to the locally bundled snapshot if GitHub cannot be reached. The UI reports which source was loaded.

## Running locally

Requires only Python 3.10+ and optionally Node 18+ for JS tests.

```bash
python3 -m http.server 8787
# open http://localhost:8787
node --test tests/*.test.mjs
python3 -m unittest discover -s tests -v
```

No package installation, database, cookies, or API credentials are needed for the UI.

## Data pipeline and provenance

The TLC specifically provides bulk documents over anonymous FTP and warns against mining public `capitol.texas.gov` pages. The updater honors that constraint:

```bash
python3 scripts/sync_ftp.py
```

`scripts/sync_ftp.py` enumerates `/bills/90r/billhistory`, parses each XML document, validates the bill number and caption, then atomically replaces `data/bills.json` **only if enough records parse successfully**. The previous file stays unchanged on a connectivity or schema failure. Manually reviewed impact tags survive metadata refreshes. The parser intentionally does not claim unobserved hearings or manufacture agency facts.
The full coded action history (`actionNumber`, date, text; last 400) and the links to bill analyses and fiscal
notes go to `live/history/<BILL>/history.json` (`texas-bill-history-v1`, `--history-dir`), written only on
change and never into `bills.json`; a history-write failure never fails the snapshot.
The same folder gets each listed analysis and fiscal note as Markdown (`<type>-<code>.md` plus `documents.json`,
`texas-bill-documents-v1`) and, once a bill has a hearing or testimony action (H215/H216/H240, S260/S270/S290),
its committee witness list as `witnesses-<H|S>.json` (`texas-bill-witnesses-v1`: committee, hearings, and each
witness's name, organization, for/against/on and whether they testified). Downloads skip unchanged files by FTP
modification time and stop at `--max-docs` (200) per run; a missing witness list is normal, not a failure.

The first verified official import read 1,059 bill histories on November 9, 2026. GitHub Actions is scheduled hourly, at minute 17 UTC (GitHub may delay scheduled jobs). Each snapshot records its actual generation time and coverage; it is a dated bulk snapshot rather than a real-time feed. When nothing changed, the importer keeps the previous `generated_at` (so no commit is made) until it is six hours old, then writes a heartbeat; a snapshot more than eight hours old therefore means the refresh has stopped. Concurrent pushes to `main` are rebased and retried up to five times.

### Automated private review and highlighted evidence

Bill details now include **Full text & highlighted evidence**. Open a `texas-bill-review-v1` JSON file from
the private worker to inspect the complete normalized PDF text, select a highlight, and read its supporting
classification, agency impact or reviewed correction. Statutory evidence retains separate official links.
Imported reviews stay in the browser session; they do not replace the official bill snapshot or publish
classifications. Unresolved questions and validation issues remain visible. Watchlists remain device-local.

The worker is `scripts/review_pipeline.py`. It classifies complete introduced bill PDFs from official TLC FTP,
checks excerpts and questions, then submits only targeted questions. Both model-raised questions and code
checks participate: missing/ambiguous citations, unresolved agency identities, and potentially omitted
conditions in the supporting sentence. These checks are review signals, not proof of semantic correctness.
The resolver selects evidence from verbatim source-generated options and can change only fields present in
the affected claim's schema. Unsupported, invalid or unanswered corrections stay queued for review.

```sh
python scripts/review_pipeline.py --cache-dir /private/texas-bill-review --bill-id HB273 --execute
```

Omit `--execute` to prepare/replay without spending; a dry run never marks bills as seen. Without bill IDs,
each run works serially through up to three retries, unseen bills, previously failed bills, and then rotating
known bills from the official snapshot, until a spending guard or the `--max-minutes` limit (default 55,
checked between bills) stops it; `--max-bills` optionally caps the count. A bill whose PDF cannot be downloaded
or read (for example, not yet posted) is recorded under `failed` in the queue and is never marked seen; five
consecutive new download failures stop the run as a likely FTP outage. Requests too large to price, or already
billed without a cached response, mark only that bill for review; budget and unresolved-billing stops end the
run. Introduced PDFs use FTP
modification times to avoid unchanged downloads. The complete normalized text/configuration controls model
reuse, so metadata-only changes do not cause another classification. Discovery of later text-version suffixes
is not yet implemented; the worker explicitly processes introduced text and labels it accordingly.

The authorized hard ceiling is **$1 per `America/Chicago` calendar day** (the ledger day is computed in that
zone on every call, so a run spanning midnight books spend to the correct day), with a
default **$0.10 per run**. A private durable ledger reserves a conservative upper bound before each provider
call, accounts for cache writes and output, and records actual estimates afterward. Unknown outcomes retain
their reservation and block new calls until reconciled. A worker lock prevents concurrent spending races.
Cache hits make no provider call. When Flex capacity is unavailable (first pass or a review question), the bill
is set aside until the provider's retry-after (about 300 s in practice) and the run continues immediately with
other bills, revisiting it once ready. Back-to-back rejections pause the run 30 s, then 60 s at most; the only
longer wait is for a cooling bill when nothing else is left. The rejected call was never billed and every
resubmission passes the same reservation and cache checks; a bill whose cooldown would pass `--max-minutes`
stays queued. Budget, quota/auth and unknown outcomes still stop the worker.
`--no-spending-cap` skips the daily and per-run ceilings only (reservations, the ledger and the
double-billing checks still apply); `--order reverse` works through the snapshot from the bottom up.
`--question-effort` (default `medium`) sets reasoning for follow-up questions; the first pass stays `high`.
By default every unseen bill's first pass comes before any follow-up questions: a bill's first visit records its
questions as deferred (it joins the retry list), and they are asked on its next visit, after the unseen bills.
A bill with an earlier review always asks them at once, as do `--bill-id` runs and `--questions-inline`.
Before any model call, a bill whose companion is listed as Identical reuses that companion's first-hand review
when the texts match after the author line and each bill's own number are masked (checked on four real House and
Senate pairs, which differ only there) and the copy, re-validated against this bill's own text, verifies the same
claims with no more errors. A bill that already has its own review is never overwritten, and a reused review is
never copied again; anything else gets a normal review (`--no-companion-reuse` turns reuse off).
`--max-minutes` defaults to 55; a timer start that finds the previous run still holding the worker lock logs it
and exits successfully.
Reviews read only the official Markdown. The PDF path is retired: `--input pdf` stops the run before any connection
or call, and `classify_bill.py`/`extract_bill.py` refuse `--execute`. A run that publishes must read the text the
site serves (`live/text`, beside `--publish-tags`). Every publisher (tags, highlights, changes, fiscal, extras, audit
counts, related summaries) includes a bill only when its review was read from Markdown and its `text_sha256` equals
both the served `index.json` entry and the served file's bytes for that version (any served version, not only the
newest). Other reviews are withheld and logged, and their highlight files removed; highlights are built from the
exact bytes the check verified. Before planning, each run re-attaches a review whose served text changed bytes but
not content: when the rebuilt document's `text_hash` and spans equal the stored ones (exactly what Luna was sent),
the review takes the new hash and records `text_rebindings` evidence, at no cost. A real content change stays
withheld until re-reviewed; when many change at once the converter breaker visits only an operator-approved number
(`--allow-text-rereview N`, default 0).
`--input markdown` reads the data run's official Markdown (`live/text/<BILL>/I.md`, checked
against `index.json`): one span per paragraph (`P###S###`, page = paragraph), with `<ins>`
and `<del>` shown to Luna plus `scripts/markdown_input_note.txt`, and quotes matched with the tags removed.
Missing or mismatched text is a download failure, retried after the next data run. Markdown requests have
different cache keys, so switching re-reviews every bill. See
`.agent/plans/texas-bill-tracker-staged-luna-review-plan-2026-11-10.md` (workspace) for the staged design.
With `--publish-tags` and `--execute`, the worker also writes `live/luna/status.json`
(`texas-bill-luna-status-v1`: `in_progress`, every bill a worker holds now, up to `--workers`; `current`, one of
them, kept for older readers; the next five; and the reviewed, retry and failed bill ids, with the failure stage
only). It is rewritten when each bill starts and finishes, and on every exit. The tracker's
**Review progress** view reads it, refreshes it every minute while open, and treats a running status older
than 90 minutes as possibly stopped; without it, bills with published tags count as reviewed.
The limit cannot be raised above $1 via CLI. Do not remove the ledger or uncertain response records to retry.
`--transport flex` (default `legacy`) sends through the vendored cth.flex library (`scripts/vendor/cth_flex`,
see its `VENDORED.json`; `scripts/flex_boundary.py` is the only importer). It uses the same `budget.json` and
`responses/` files and the same retry schedule. Differences:
- an error that provably never reached OpenAI (quota, auth, a rejected request, most 5xx, no connection) releases
  its reservation instead of blocking later calls;
- quota and auth end the run;
- an incomplete or wrong-tier reply is kept as `refused` with its real cost.
The production unit runs `--transport flex --input markdown`.

`--workers N` (default 1, needs `--transport flex`) reviews up to N bills at once. Workers only download and call
the model; queue, status and review files are written by the main thread. A capacity refusal pauses new bills for
every worker; an unknown outcome, quota/auth error or budget stop lets in-flight bills finish and starts no new
one. The ledger and response cache stop two workers from sending the same request. The production unit runs 3.

`--suggest-topics` adds a lowest-priority second pass (`scripts/topic_suggestions.py`). It runs only after a run's
review queue is empty. For each settled review (no follow-up questions queued) it sends one low-effort call built from the
review, the bill text and the current topic list, asking for topics the tracker lacks. Repeats are cache hits. A bill is
asked again only when its review, its text or the topic list changes.
Results stay private in `cache/suggestions/`; `python scripts/topic_suggestions.py --cache-dir <cache>` tallies them so
recurring topics can be added to `POLICY_AREAS` by hand. The same call returns a plain-language headline, search terms
and opposing-side terms (e.g. "gun control" and "gun rights"), built only from the review's verified claims. They are
published to `live/luna/extras.json` while the record matches the bill's current verified review; the site shows the
headline as "In brief" and adds the terms to search. No headline is shown when the summary is unverified.
The same call also decides the **All state agencies** scope marker from the bill text, under a stricter rule than the
first pass had (federal-waiver riders, savings and applicability clauses, cooperation-with-a-task-force duties and
mixed state/local classes do not count). It is published in `tags.json` (and as a highlight) only when every quote is
current, undeleted bill text, and only for the review and text content it was made for. It is a vote: the call above
is vote 1, a second identical call (its own request, cache entry and ledger row, told apart by a trailing `RUN: 2`
line) is vote 2, and a third runs only when the two disagree; the marker publishes once two votes agree. A true vote
whose quotes fail abstains. Every bill's vote 1 runs before any vote 2, so headlines are not held back. The first
pass's own marker is no longer published (a 2026-11-11 audit found about half wrong); until two votes agree, the site
falls back to the caption inference.

`--audit-sample` runs after the topic pass: an independent medium-effort Luna re-check of about 2% of settled reviews
(a deterministic sample by bill and review), against the exact text version reviewed. Findings stay private in
`cache/audit/`; only counts go to `live/luna/audit.json`, shown on the review progress page.

`--related-bills` (with `--execute`) publishes `live/luna/related.json`: OpenAI `text-embedding-3-small` vectors (256
dimensions) of each bill's caption and verified summary, cached by content in `cache/embeddings/`, with each call's
tokens and cost logged to `cache/embeddings/usage.jsonl`. The top five neighbours at or above 0.5 cosine are kept, excluding
listed companions and identical text. Embeddings do not go through the Luna ledger; a failure keeps the previous file.

`--stages` (needs `--input markdown`) runs the staged review
(`scripts/review_stages.py`). Each visit is planned from durable files: the review, `live/text/<BILL>/index.json`,
`live/history/<BILL>/documents.json` and `cache/fiscal/<BILL>.json`.
- A new bill is reviewed on its newest text version.
- A new version gets a version update. Luna reclassifies the new text with the previous review and a paragraph
  diff as context, and lists what changed. This is published to `live/luna/changes/<BILL>.json`, and the old
  version's pending questions are dropped.
- Text revised under the same version code is reviewed again from scratch. When more than max(5, 2% of
  reviewed bills) change at once, none are re-reviewed (a converter change, not new text).
- A fiscal note or bill analysis for the reviewed version gets a fiscal check. Luna compares it with the
  review, and verified claims go to `live/luna/fiscal/<BILL>.json`, bound to the review and document hashes.
- Hearing witness lists (`live/history/<BILL>/witnesses-<H|S>.json`) are shown on the site with no model call.

At most three new targeted queries per bill run; cached resolutions do not consume this allowance. Later
runs progress through remaining questions. Requested official statute chapters are cached privately for
seven days and reused across bills. Supported code mappings fetch only fixed official URLs, include chapter
definitions alongside the requested section, and never follow model-supplied URLs or crawl bill pages.
Source-content changes invalidate targeted reuse; retrieval-date-only changes do not. Other codes and
oversized/missing sources remain explicit review work. Raw first-pass and resolution responses are preserved.

Worker results are written to `<cache-dir>/reviews/<bill-id>.json`. The full bundles (evidence, raw
responses, statutes) stay private. With `--publish-tags <path>`, each run ends by writing a public
`texas-bill-luna-tags-v1` overlay containing only claims whose citations resolved against the bill text:
summary, policy tags, agencies, statewide scope, locations, affected groups and major effects. A field whose
claims all failed verification is left out, and the tracker keeps its caption inference for that field.

On the VPS the overlay is `/var/www/html/texas-bill-atlas/live/luna/tags.json`, served as `./live/luna/tags.json`
through a `live -> ../../live` symlink the deployer adds to every release. The tracker labels Luna-tagged bills
"Luna · full text" and shows the summary, review date and locations in the drawer.

### Member roster and party tint

`scripts/sync_members.py` builds `texas-bill-members-v1`: every 90th Legislature member from Texas Legislature
Online (member code and the exact display name bill histories use), joined to the Legislative Reference
Library for party, district and service history through the 89th. Authors resolve only by exact
(chamber, display name); the LRL join needs the same surname and an agreeing given name (nickname or prefix),
and ambiguity leaves a member unmatched. Members-elect without an LRL record take party and district from
`data/members_elect_2026.json`, the winners in the Secretary of State's unofficial 2026 general election
results (read in a browser session, since the feed sits behind a bot check), and only when the ballot name
agrees with the TLO name. Representatives elected to the Senate (Ashby, David Cook, Paul) have LRL records from
the House, so their Senate district comes from the same file; those rows came from NBC 5 DFW's results page
(projected winners at 99% of the expected vote) and carry their own source. The party stays the LRL one unless the
ballot says otherwise. The drawer labels that party "2026 ballot, unofficial". Delete the file once LRL
adds the 90th Legislature.

Cards are tinted by authorship: blue for a Democratic primary author, red for Republican, purple when the
authors and coauthors include both parties, neutral when the primary author's party is unknown. Every tint
has a text label. The drawer lists each author, coauthor, sponsor and cosponsor with party, district and
tenure, linked to LRL or TLO. Roster tenure feeds author influence when no curated profile exists.
`data/members.json` ships with each release; `texas-bill-members.timer` refreshes `live/members.json` daily
on the VPS (about 180 page requests at one per second), and the tracker prefers the live copy.

### Last action

Each card carries a last-action tag (category, chamber and date) parsed from TLO's `MM/DD/YYYY H|S|E text`
last action: filed, referred, hearing scheduled, heard, reported, on calendar, floor action, passed chamber,
received in other chamber, sent to governor, signed or effective, vetoed, withdrawn or failed, other.
The explorer can filter by that category and sort by latest action, oldest last action (stalled bills first)
or last-action stage. This is separate from the "stage" filter, which is the furthest stage ever reached.

### Today view, opening bills, Copy for AI

- **Today** (`#today`, `#today?bill=HB5`) lists bills with an action dated today in America/Chicago (from
  `action_dates` when present, else `last_action_date`), grouped by action type, with a topic chip row that filters
  the list. When nothing is dated today it shows the most recent day with activity and says so. It uses only the
  published snapshot (no extra fetching); an interim note (`TODAY_INTERIM_NOTE` in `src/app.js`) explains that
  floor calendars and hearings arrive with the session. The helpers (`chicagoDate`, `activityOn`,
  `latestActivityDay`, `topicCounts`, `groupByActionType`) live in `src/taxonomy.js`, because the static deployer
  ships a fixed list of `src` files.
- A bill's title and number are real links (`#<view>?bill=<ID>`); empty card space opens the drawer too, but not
  clicks on controls, links or a text selection.
- The drawer's **Copy for AI** button copies a short prompt (bill, agent-edition Markdown URL, official text URL, one
  neutral instruction); next to it is a plain link to the AI-readable `.md`. No prefilled links to AI services.
- **Copy page for AI** (top bar): copies the view on screen as text (`pageAiText` in `src/taxonomy.js`). Explorer,
  watchlist and Today copy their filters, an equivalent agent-edition search link when one exists, and up to 50 of
  the bills shown with each bill's `.md` link; reference views copy their agent-edition page. With a bill open the
  drawer covers the top bar, so the drawer's own Copy for AI is used there. Both copies name each bill's companions.
- **Agency filter and companions**: filtering by an agency also lists a bill whose companion (any relation the
  Legislative Council records) carries that agency, with a dashed "via companion" tag; the agent-edition search and
  the Agency index counts still count direct tags only.

### Near you

**Near you** (`#local`) shows a visitor's Texas House member and Senator, the bills they filed or signed onto
(author, coauthor, sponsor, cosponsor, matched by roster code and chamber), and bills that name their county or a city
in it (Luna `named_place` locations, or "X County" in the caption; a bare name is a city, "X County" a county, no
fuzzy matching). Statewide bills are counted but not listed; bills written for areas by population size are not
matched yet.

A location comes from one of: the browser's location (after a notice), a county (with a district picker when the
county is split), district numbers, or an optional address lookup. The address lookup is the only time anything
leaves the browser: the typed address goes to the US Census geocoder (JSONP, after a notice), which returns
coordinates only. Everything else runs in the page (`src/geo.js`: point in polygon, with a "close to a line" warning
within the simplification tolerance plus accuracy). Only district numbers, the county and how they were found are kept,
in this device's storage (`texas-bill-atlas-near-you-v1`); coordinates and addresses are never stored, sent to this
site or put in a URL. "Forget on this device" clears it.

Data (`data/geo/`, built on the desktop by `scripts/build_districts.py`, never on the server):

- `house.json`, `senate.json`: Texas Legislative Council plans PLANH2316 and PLANS2168 (2023-2026, used for the 90th
  Legislature), simplified to 100 m; `counties.json`: Census `cb_2024_us_county_500k` (Texas), simplified to 250 m.
  GeoJSON, WGS84, 4 decimals.
- `districts.json`: TLC report 150 (districts by county, with population shares) and report 125 (cities and CDPs by
  district), checked against the shapes (150 House and 31 Senate districts, 254 counties, consistent names) or the
  build stops.

To rebuild after a redistricting: download the two plan shapefiles (`planh2316.zip`, `plans2168.zip`) and the
`h_r150.xls`, `s_r150.xls`, `h_r125.xls`, `s_r125.xls` reports from data.capitol.texas.gov, and
`cb_2024_us_county_500k.zip` from census.gov, into one folder; then
`python scripts/build_districts.py --inputs <folder>` (needs `xlrd==2.0.1`; mapshaper 0.7.98 via `npx` by default,
or `--mapshaper <path>`). Checked on 2026-11-11: 40 random points (half in the five largest counties) matched the
Census geocoder's 2026 state legislative district layers 40 of 40.

A district with no member who has a known district shows "No member listed yet" rather than a guess. As of
2026-11-11 that is Senate districts 14 and 16: they were not up in 2026, and Texas Legislature Online lists no 90th
Legislature member for them.

### Saving and sharing without accounts

There are no logins. People keep and move their choices in five ways:

- **Links:** the address always reflects the view, filters, sort and open bill (`#all?chamber=Senate&bill=HB5`),
  so any view can be bookmarked or sent. A share link (`#all?list=HB5,SB12`) opens a read-only shared list that
  never changes the recipient's own watchlist until they choose "Add all".
- **This browser:** the watchlist and the last filters are kept in localStorage (`src/prefs.js`).
- **Files:** the watchlist exports to `texas-bill-atlas-watchlist-v1` JSON; import also accepts plain text or CSV
  containing bill numbers, and merges.
- **Feeds:** `scripts/build_feeds.py` writes `live/feeds/<ID>.xml` (RSS, one per bill) after each hourly sync,
  from the dated actions `sync_ftp.py` now records in `action_dates`. Item ids are stable as the 12-action
  window slides. A published Luna full-text review (`live/luna/tags.json`, read by default from beside the
  snapshot) is also an item, dated by its review, and a re-review is a new item; watchlist feeds pick reviews up as
  soon as the tags file changes. There is no iCal: the data has no hearing dates or times.
- **Private sync links** (`scripts/sync_service.py`, `src/sync.js`): a random edit key and a derived view key;
  only SHA-256 hashes are stored (SQLite), no email, name or IP. The edit key travels in the URL fragment and
  the `X-Sync-Key` header only and is removed from the address bar once read. Saves are versioned; on a conflict
  the client replays its unsaved adds/removes onto the newer list. Limits: 16 KB body, 500 bills, per-client
  rate limits (one IPv4 address or one IPv6 /64), 100,000 lists, deletion after a year unused. A view key also serves a combined watchlist RSS at
  `/api/sync/feed/<view key>.xml`. The tracker hides sync when `/api/sync/health` is unavailable.
  Live since 2026-11-10: the shared gateway (cth.hosting) proxies `/api/sync*` to the `texas-bill-sync`
  container on `edge-bills`; deployment and updates are in `deploy/sync/README.md`.

### Agent edition (agent.bills.ctharvey.me)

The tracker draws everything with JavaScript, so agents get the same information as static Markdown and JSON at
`https://agent.bills.ctharvey.me/` (`index.md` = `llms.txt`). `scripts/build_agent.mjs` reuses the tracker's own
pipeline (`normalizeBill`, Luna overlay, roster, hearing and last-action rules in `src/taxonomy.js`, links from
`src/prefs.js`) and writes `bills/<ID>.md|.json`, index pages that stand in for each filter (topics, agencies, last
action, hearing status, chamber, members; full-name member addresses point to the listed-name page) plus filing
date, authorship party and full-text review, `recent.md`, `review-progress.md` (with pace and queue order),
`saving.md` and `data/bills.json`. Group tables carry each bill's topics, agencies and review status and are split
into pages of 150 (`<group>--page-N.md`) so page-reading tools see every row. Bill pages link the official text, and
the overview states coverage (reviews, coauthors, sponsors, hearings) so a zero reads as "none yet", not missing data.
Empty fields say whether the full-text review found nothing or is still pending (queued, queued for a retry, failed
and to be retried), and "reviewed" always means a published review. `404.md` (served by the gateway for missing
paths) says which bill numbers exist. Output is deterministic; files change only when their data does and stale
pages are removed.

With `--districts data/geo/districts.json` it also writes `districts/house-<n>.md` and `districts/senate-<n>.md`
(the member, their bills, bills naming the district's counties or cities, same matching as Near you) and
`districts/index.md`. Without the flag `src/geo.js` is never loaded, so an older unit that copies only
`taxonomy.js` and `prefs.js` keeps building, just without district pages. The agent edition takes no location.

Search: `https://agent.bills.ctharvey.me/search?q=<words>` (Markdown, or `format=json`) is served by the sync
service (`scripts/search_bills.py`) from `live/agent/data/bills.json`, reloaded when it changes. It matches word
forms, quoted phrases, two-way synonym groups (gun/firearm/rifle, voucher/"school choice"/"education savings
account") and bill numbers across titles, captions, topics, agencies, full-text summaries, members, affected groups,
locations and actions, with filters for chamber, topic, agency, location, party, review and filing dates (a known
topic name or agency id matches exactly, as in the tracker; `/search` lists the topic names). It replaced the old
`words/<word>.md` keyword pages. `OR` splits the query into alternatives, each several words or a quoted phrase and
matched on its own (`school safety OR "school police"`); the page shows how it read the query, with a count per
alternative. A partial match without OR shows only the bills matching the most words and names the words that matched
nothing. Misspelled member names get a "did you mean", a name with no bills says so, results list authors and
authorship party, filter-only results say which filter matched, and results say how many bills are searchable by
caption only; it says when nothing matches, why that may be, and which named bills are not in the data yet.

`scripts/texas-bill-agent.service`/`.timer` (root, hourly at :50) runs it in a pinned, network-less node container
as `texas-bill-atlas`, writing only `live/agent`. The gateway serves that folder for the subdomain (cth.hosting
`08-agent.bills.ctharvey.me.caddy`). The main page links to it in its head, footer and `<noscript>`.

### Live bill snapshot

`scripts/texas-bill-data.service` and `.timer` run `sync_ftp.py` hourly at :17 on the VPS as `texas-bill-atlas`,
reading the script from the deployer's bare repository and writing `/var/www/html/texas-bill-atlas/live/bills.json`.
The tracker loads `./live/bills.json` first and falls back to the bundled `data/bills.json` with a warning
banner. The GitHub workflow `refresh-bills.yml` is now manual only and refreshes that bundled fallback.

Hourly operation uses `scripts/texas-bill-review.service` and `.timer`, a dedicated `texas-bill-review` account,
and `/var/lib/texas-bill-review/{repository,venv,cache}`. The repository stays on `main` and pulls with
`--ff-only`. Install optional dependencies into the dedicated venv; install the units under `/etc/systemd/system`.
Set `OPENAI_API_KEY` only in root-owned mode-0600 `/etc/texas-bill-review.env`, outside the web root and git.
Enable `texas-bill-review.timer` after the pilot; it runs hourly at minute 35, with up to two minutes jitter,
processing bills serially for up to 55 minutes. The production unit currently runs with `--no-spending-cap
--order reverse` so the backlog completes; restore `--daily-budget 1 --run-budget 0.10` to re-enable the guard. Inspect `journalctl -u texas-bill-review.service` and the private
ledger/review queue. To pause spending, stop/disable this timer; the public tracker and metadata refresh remain
independent. Reinstall dependencies when their requirements change.

Operators can retrieve a review with the existing authenticated SSH path and `sudo cat` its JSON, then open
it in that bill's detail drawer. Private source/cache directories must never be added to the static web root
or public GitHub artifacts. Publication approval remains separate from classification and source validation.

### Focused classifier contract

`scripts/classify_bill.py` reads the complete official bill using **Luna Flex/high** and returns a concise
summary, canonical policy tags, direct/inferred state-agency impacts, separate all-agencies scope,
substantive locations, affected groups, major effects and short supporting excerpts. It does not enumerate
every obligation, deadline or exception. Author/party/member counts and legislative events remain official
metadata. The policy and agency vocabularies come from `src/taxonomy.js`; the agency list is still incomplete.

Reviewed statutory definitions live in `scripts/statutory_definitions.json`, initially Water Code
16.001(1)-(2): Board/TWDB and Commission/TCEQ. An explicit matching chapter or section amendment selects
the chapter context; a topical mention or another code does not. In-bill definitions take precedence.
Each entry retains its official source URL, section, chapter scope and verification date. This is a small
reviewed registry, not an automatic or exhaustive statute lookup; unsupported amendment forms and missing
chapters provide no external definitions. Expand it with verified sources before broader deployment.

A second, publish-time table, `scripts/agency_name_definitions.json`, is never sent to Luna (so editing it costs
nothing). When a verified agency label is a bare generic name ("the department", "the commission", "the agency",
"the board") with no registry ID, the publisher finds the last amendment header ("Section 225.300, Transportation
Code", "Subchapter B, Chapter 29, Education Code") before the label's first cited span and, if the table has a
verified definition for that code, chapter and term, publishes the registry agency instead (tags and highlights).
It stays unmapped when the bill defines the term itself, no header precedes the evidence, or the chapter is not
listed; a mapped label whose agency is already listed is dropped. Add chapters only from the statute's own
"In this chapter/title" definition.

Definitions follow the full bill in the variable request suffix, preserving the shared prompt cache.
Their text/scope/provenance affect response-cache identity; verification-date-only changes do not. A `D_`
evidence ID cites a statutory definition and is validated separately from bill-page evidence. Agency impact
still requires a bill citation, and identity derived from a supplied definition requires that citation too.
External identity context does not itself establish substantive impact. Definition quotes cannot match an
unrelated chapter or silently fall back to bill text.

```sh
python scripts/classify_bill.py --pdf /path/to/HB00529I.pdf --bill-id HB529 --session 90R --version introduced --source-url ftp://ftp.legis.state.tx.us/bills/90R/billtext/PDF/house_bills/HB00500_HB00599/HB00529I.pdf
```

Install `requirements-extraction.txt` first. Preparation is free; `--execute` authorizes a cache-miss call
using `OPENAI_API_KEY`. This path reuses the detailed extractor's complete-text reader, private persistent
response cache, prompt-cache breakpoints, bounded capacity backoff and uncertain-call protection. Its model,
schema and prompt produce a distinct cache key. A response hit makes no provider call. Shared instructions
and vocabulary target a 12-hour prompt cache; the complete changing bill remains the variable suffix.

The tool verifies canonical IDs/tags and finds literal supporting excerpts in the complete source text.
It derives page offsets and all overlapping span IDs, including excerpts crossing span or page boundaries.
A model-provided span is only a hint: repeated quotes require one uniquely matching source context or stay
flagged as ambiguous. Missing or fuzzy quotes are rejected. `verified_citations` stores source-derived text
and zero-based, end-exclusive offsets into normalized page text, separately from the unchanged model output.
The tool flags unresolved/inferred agency impacts and keeps every output private and pending review.
It does not require every operative span to be
cited. Valid excerpts do not prove semantic accuracy. Nothing is written to `data/bills.json` or published;
classification is not part of the hourly metadata job. Luna Flex short-context cost estimates use the
[official pricing](https://developers.openai.com/api/docs/pricing) verified November 9, 2026, including
cache writes. Review pricing before rollout or use with long-context requests.

The first focused HB529 pilot used all 21 pages and returned 5 policy tags, 2 agency entries, 3 location
scopes, 3 affected groups and 7 major effects. It cost an estimated $0.002208825 in 95 seconds. Six excerpt
locations initially failed validation (four neighboring-span references and two excerpts crossing span
boundaries). Deterministic source matching resolved all six offline: all 43 citations now have verified
locations, with no missing or ambiguous matches. Subsequent statutory review identified the unnamed board
as TWDB under Water Code 16.001(1). The revised HB529 request includes those definitions; it was prepared
offline without another paid pass. The original response remains unchanged and unapproved. This is one pilot, not a claim
of corpus-wide accuracy or demonstrated provider prompt-cache hits across bills.

The detailed version is preserved at
[`archive/detailed-extraction-v1`](https://github.com/ctharvey/texas_bill_tracker/tree/archive/detailed-extraction-v1)
(commit `a78c67d`) and the local tag `detailed-extraction-v1`. Its script and contract remain available below.

### Detailed full-text extraction (preserved, pending evaluation)

`scripts/extract_bill.py` prepares a single Terra Flex/high request from a local official TLC full-bill PDF.
It extracts entities, authority changes, obligations and timing into a **private review cache**. It does not
write `data/bills.json`, run on the hourly history job, or publish classifications. The current tool does not
implement the planned complete policy/geography taxonomy. The existing UI and metadata importer keep working
without these optional dependencies:

```sh
python -m pip install -r requirements-extraction.txt
python scripts/extract_bill.py --pdf /path/to/official-bill.pdf --bill-id HJR31 --session 90R --version introduced --source-url ftp://ftp.legis.state.tx.us/bills/90R/billtext/PDF/house_joint_resolutions/HJ00001_HJ00099/HJ00031I.pdf
```

By default this only prepares the request, or replays and revalidates an existing response. A **new paid call**
requires `--execute` and `OPENAI_API_KEY` in the process environment. The tool does not load repository `.env`
files or credentials from another project. It uses `gpt-6.1-terra`, Flex, high reasoning and a 48,000-token
output allowance with SDK retries disabled. Only explicit capacity/rate rejections get bounded retries;
quota/auth errors and unknown timeouts stop. No automatic model/tier fallback or repair/audit call is made.

The cache persists across invocations at `%LOCALAPPDATA%/texas-bill-atlas/extraction` on Windows or
`$XDG_CACHE_HOME/texas-bill-atlas/extraction` (default `~/.cache/...`) elsewhere. `--cache-dir` selects another
private persistent location **outside the checkout/web root**, including the primary checkout when using a
Git worktree. Ephemeral CI storage would need a persistent cache restored across jobs; no such job is enabled.

Call reduction and cache rules:

- Hash complete whitespace-normalized pages, text version and semantic request configuration. Preserve all
  non-whitespace characters and page boundaries. A blank/image-only page stops extraction rather than silently
  dropping it. PDF bytes and official source URL are retained as provenance.
- Authors, status/actions, refresh timestamps and PDF metadata are excluded from model input and cache identity.
  Repeating an hourly history update cannot invalidate an otherwise identical full-text request.
- Model/settings, prompt, schema, canonical vocabulary, source text or text-version changes invalidate reuse.
  The agency vocabulary is read from the app's `src/taxonomy.js`; the all-agencies marker stays separate.
  If that declaration changes syntax, the reader fails rather than using a stale vocabulary.
- A response hit avoids client construction, credentials and provider calls. Historical token usage/cost is
  labelled separately; new estimated spending is zero. Returned invalid/incomplete output is retained and
  revalidated, not silently paid for again. Validator improvements can recheck saved output without generation.
- OS locks prevent identical concurrent submissions; writes are atomic. A pending crash, timeout or corrupt
  entry blocks resubmission until its outcome is reconciled. Do not delete uncertain entries merely to retry:
  inspect the private request/time and provider logs first. Known capacity rejections have a cooldown.

Shared instructions/schema and vocabulary precede bill-specific content. An explicit 12-hour breakpoint targets
prompt reuse across bills/hourly runs; the changing full bill has no write breakpoint in this single-call path.
Provider prompt caching reduces input cost, while the application response cache skips a request entirely.
Write lifetime details and reasoning-inclusive output usage are used for estimates at the documented Terra Flex
rates; missing lifetime details produce a range. Provider prices and model aliases can change: review rates
before rollout and change the prompt/schema revision or model identity deliberately when regeneration is intended.
See [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) and
[Terra model pricing](https://developers.openai.com/api/docs/models/gpt-6.1-terra) for provider behavior and rates.

Schema/validation fixes include actor certainty (`explicit`, `inferred`, or null/`unspecified`), one actor/action/
modality per obligation, coupled deadline/duration shapes, ordinal-weekday/event-relative calendar relationships,
qualifying-year selection and nullable interval inclusivity. For example, first Monday in June three years after
the census remains an event-relative rule. `resolve_calendar` resolves supported calendar types only after a
verified anchor date is supplied. It rejects nonexistent dates instead of rolling them to another month.
Unmatched/grouped/proposed entities use a null registry ID; only canonical matches use a nonempty ID.
Business-day counts have an explicit `business_days` unit. They are not converted to calendar days or resolved
against a guessed holiday calendar.

Code derives counts and evidence reverse links; the model does not repeat a second bookkeeping table. Unknown
evidence, bad references/dates, unresolved/inferred actors, embedded modal verbs, uncited potentially operative
spans and a stable 5% quality sample generate review signals. These are conservative checks, not a proof of
semantic accuracy or exhaustive coverage. Every result remains `pending_review` or `needs_review`, with
`publishable: false`. No reviewer pass is automatically billed. The private `results/<request-key>.json` contains
the extraction and validation; `responses/` retains the raw response and call state, and `requests/` the exact input.

Before enabling classification, validate the revised contract on varied unseen bills and establish an explicit
approval/publication path. Pilot results showed why valid JSON and resolvable citations alone are insufficient.
No live call or unseen-bill evaluation was performed as part of implementing these fixes.

Run all offline checks with optional dependencies installed:

```sh
python -m unittest discover -s tests -v
node --test tests/*.test.mjs
```

The SDK test uses a mocked HTTP transport and no real credential. Optional schema/SDK tests skip when those
dependencies are absent so the standard-library-only FTP workflow remains usable.

### Production deployment

Production: https://bills.ctharvey.me on the existing VPS, 147.93.132.141.
The Cloudflare A record `bills` points there and is proxied. Cache rules for that host only: `/live/*` and `/data/*`
5 minutes at the edge, `/api/sync/health` 30 seconds, `/assets/*` a year at the edge and in browsers; the page,
`src/` and the rest of the sync API are not cached. Shared Caddy routing
is owned by `ctharvey/cth.hosting`; its site root is
`/srv/static/texas-bill-atlas/current`, through the existing read-only `/var/www/html` mount.
Caddy manages HTTPS and the HTTP redirect. No application server or build is required.

`texas-bill-atlas.timer` checks public GitHub `main` every two minutes, including commits
from the data-refresh workflow. No deployment credential is needed. `scripts/deploy_static.py`
reads all six application files at one commit, requires an official-FTP 90R snapshot
of at least 1,000 unique valid measures, writes an immutable release, and atomically
switches `current`. Each release also copies `src/` to `assets/<digest>/` (a hash of every module) and points
`index.html` there, so browsers can cache the scripts for good; the previous release's folder is carried over for
pages loaded just before a switch. Fetch or validation failure leaves the previous release online.
The bundled fallback updates with each release. The frontend prefers live GitHub JSON
(accepted only as an official-FTP snapshot of at least 1,000 bills) and shows a warning
banner for the bundled fallback, local imports and stale snapshots.

One-time VPS installation as root, from a reviewed Git archive of this repository:

```sh
useradd --system --home-dir /var/lib/texas-bill-atlas --shell /usr/sbin/nologin texas-bill-atlas
install -d -m 755 -o texas-bill-atlas -g texas-bill-atlas /var/www/html/texas-bill-atlas
install -d -m 755 /usr/local/lib/texas-bill-atlas
install -m 644 scripts/deploy_static.py /usr/local/lib/texas-bill-atlas/deploy_static.py
install -m 644 scripts/texas-bill-atlas.service scripts/texas-bill-atlas.timer /etc/systemd/system/
systemctl daemon-reload
systemctl start texas-bill-atlas.service
systemctl enable --now texas-bill-atlas.timer
```

Requires existing Python 3, Git and systemd. The unprivileged service writes only its
state directory and this site's directory. Check `systemctl status texas-bill-atlas.timer`
and `journalctl -u texas-bill-atlas.service`. Deployer or unit changes require reinstalling
the reviewed files; application and data changes deploy automatically. The ten newest releases
(plus the live one) are retained; older releases and crashed staging directories are pruned after
each publish.

Rollback: stop the timer, make a temporary relative symlink to a retained `releases/<commit>`,
then atomically rename it over `current` using `mv -Tf`. Fix or revert main before restarting
the timer. This affects only the bills site.

Deferred improvements: incremental FTP imports; an authoritative agency registry; full-text
agency classification; and out-of-band alerts for importer failures (the site itself now warns
on stale snapshots and fallback use).

### Data model

Member roles from official FTP are stored separately in `authors`, `coauthors`, `sponsors` and
`cosponsors` arrays. Counts are derived from those lists. Bill cards show author/coauthor/cosponsor
counts; details list every member by role. Search and CSV export include these fields.
Empty official lists mean none listed in the snapshot; missing fields in local imports are
shown as not reported. Authors/coauthors belong to the originating chamber and sponsors/
cosponsors to the other chamber. The `author` display string remains for compatibility.

Bill text: `sync_ftp.py` reads each history's text versions and writes `live/text/<BILL>/<code>.md` (code is the
TLC file suffix, `I` = introduced) and `index.json`. The Markdown keeps one paragraph per line, `### SECTION n.`
headings, `<ins>` for added and `<del>` for deleted wording, and backslash-escapes Markdown characters. Highlight
positions use the plain projection of each paragraph (headings marker, ins/del tags and escapes removed; offsets
in code points, paragraph 0 = title), computed identically by `sync_ftp.plain_paragraphs`,
`review_pipeline.plain_paragraphs` and `src/billtext.js`. The review worker writes
`live/luna/highlights/<BILL>.json` (format `texas-bill-luna-highlights-v1`) for reviewed bills whose introduced
text is present. The format spec is in the workspace plan
`.agent/plans/texas-bill-tracker-bill-text-and-luna-highlights-plan-2026-11-10.md`.

`subjects` is the Legislative Council's subject index from the history's `<subjects>` field, without the index
codes ("Artificial Intelligence (IQ7C5)" becomes "Artificial Intelligence"); it is absent in older snapshots.
Both searches match it, so bills with vague captions are found before their full-text review.

`companions` is a list of `{id, author, relation}` parsed from the history's `<companions>` field
("SB 132 by Menendez, Identical"); it is absent when the source has no such field. The tracker links
companions in both directions, since the other chamber's bill may not list it back yet, shows them on
cards and in the drawer. When companions both appear in a result list, they are moved next to each other (to
where the first sits in the sort) and drawn as one framed block; agent search lists them together the same way.

### Input data schema

`data/bills.json` contains:

```json
{
  "session": "90R",
  "generated_at": "2026-11-09T19:35:18Z",
  "data_mode": "curated",
  "coverage_note": "selected filings, not exhaustive",
  "bills": [{
    "id": "HB164", "title": "...", "caption": "...", "author": "...",
    "status": "Filed", "filed_at": "2026-11-09",
    "topics": ["Education"],
    "agencies": [{"id":"comptroller","relationship":"direct","reason":"..."}],
    "impacts": ["Program repeal"], "constituencies": ["Students & families"]
  }]
}
```

CSV import accepts columns such as `id`, `title`, `caption`, `author`, `status`, `filed_at`, `topics` and `agencies` (multi-value columns separated by `|`). Imports are in-memory and don't alter the shared file.

## Analysis dimensions

| Dimension | Current behavior | Next addition |
|---|---|---|
| Policy areas | Multi-tag rules + curated overrides | Review full text with evidence snippets |
| State agencies | All detected links, direct or inferred, with explanation | Complete authoritative agency registry and exhaustive bill-text references |
| Impact mechanism | Funding, mandates, eligibility, regulation, reporting etc. | Section-level statutory diff and implementation burden |
| Geography | Counties/local government in topic tags | Geographic district/MUD/ETJ effects |
| Author prominence | Verified leadership/committee/tenure fields only | 90R roster, historical effectiveness and committee membership |
| Hearing outlook | Referral/scheduled/heard facts only | Calibrated, historical hearing model with confidence intervals |
| Passage outlook | Deliberately unscored | Separate chamber and governor conditional model |
| Companions | Source model can be extended | Cross-chamber companion graph |
| Fiscal impacts | Broad tags | Fiscal note amounts and state/local cost allocation |
| Civil liberties | Rights/privacy tag | Dedicated rights, preemption and enforcement review |

## Editorial principles

1. **Traceability.** Each bill links to its official TLO history; source snapshots state their scope and time.
2. **Uncertainty.** A policy-keyword agency relation is a *possible impact*, not a formal agency assignment.
3. **No false probabilities.** Early prefiling is a poor basis for precise forecast percentages. Keep hearing and passage outcomes separate.
4. **No silent fallback.** A failed FTP sync exits nonzero and leaves the last good dataset in place.
5. **Versioning.** Keep the underlying snapshot in Git history so changes can be audited.

## References

- [Official Texas Legislature Online](https://capitol.texas.gov/)
- [TLC bulk file downloads and acceptable use](https://capitol.texas.gov/billlookup/filedownloads.aspx)
- [Official “How to Follow a Bill” guide](https://capitol.texas.gov/resources/FollowABill.aspx)
- [Legislative Reference Library prefiling FAQ](https://lrl.texas.gov/whatsNew/client/print.cfm?id=A9F890FC-DFF4-76F1-BF4CFDF37B910F6B)
