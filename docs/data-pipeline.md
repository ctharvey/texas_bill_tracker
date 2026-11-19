# Data pipeline

Everything the site shows is built on the VPS by systemd jobs that write under
`/var/www/html/texas-bill-atlas/live/`, served at `/live/`. The site loads `live/bills.json` first and falls back to
the bundled `data/bills.json` (accepted only as an official-FTP snapshot of at least 1,000 bills).

| Unit | Schedule | Runs | Writes |
|---|---|---|---|
| `texas-bill-data` | hourly at :17 | `sync_ftp.py`, then `build_feeds.py`, then a Cloudflare purge | most of `live/` (below) |
| `texas-bill-review` | 2 min after the last run, :35 backstop | `review_pipeline.py` | `live/luna/` (see [review-pipeline.md](review-pipeline.md)) |
| `texas-bill-og` | hourly at :40 | `build_og.mjs` in a network-less container | `live/og/<ID>.png`, `rendered.json` |
| `texas-bill-agent` | hourly at :50 | `build_agent.mjs` in a network-less container | `live/agent/` (agent.billatlas.org) |
| `texas-bill-members` | daily at 09:47 | `sync_members.py` | `live/members.json` |
| `texas-bill-law` | weekly, Sunday 08:23 | `sync_law.py` | `live/law/` (current law) |

Each unit takes the whole `scripts/` folder from one `main` commit of the deployer's repository, so code can move
between files without reinstalling units. A push that changes a job's code or inputs reruns that job (see
[deployment.md](deployment.md)). Failures start `texas-bill-alert@<unit>`.

## Data run (`texas-bill-data`)

`sync_ftp.py` reads TLC's bulk FTP (`/bills/90r/billhistory` and the text folders):

- **Snapshot**: `live/bills.json`, replaced atomically only when at least a third of the files read parse. When
  nothing changed it keeps `generated_at` until it is six hours old, then writes a heartbeat; an eight-hour-old
  snapshot therefore means the job has stopped.
- **Run status**: every run that publishes a snapshot writes `live/sync-status.json` (`checked_at`, the snapshot's
  `generated_at`, transfer errors, reconnects, the run's failures). `daily_check.py` judges the job by `checked_at`
  (one missed hourly run passes, two fail), so a quiet Legislature no longer reads as stale. It is outside the purged
  paths, so rewriting it every hour purges nothing.
- **Connection errors**: TLC's server sometimes answers out of step (`200 Type set to I.`) or drops the connection.
  The listing, or the one file, is read again on a new connection, at most 3 times per run; `error_perm` (550) is
  about the file and is not retried.
- **Incremental reads**: it LISTs each folder and reads only new or changed history files, plus 1/24 of the rest as
  a daily re-check, at most `--max-histories` (3000) or `--history-minutes` (20) per run. `--full` reads everything.
  Fingerprints are in `live/ftp-history-state.json`.
- **History**: `live/history/<BILL>/history.json` (last 400 coded actions, document links), analyses and fiscal
  notes as Markdown with `documents.json` (at most `--max-docs` 200 downloads per run), and committee witness lists
  (`witnesses-<H|S>.json`) once a bill has a hearing.
- **Bill text**: each version's official HTML as Markdown in `live/text/<BILL>/<code>.md` with `index.json`
  (`<ins>`/`<del>` for changes, one paragraph per line), at most `--max-texts` (400) per run. Each version records the
  SHA-256 of the official file (`source_sha256`) and of our copy (`sha256`). Texts TLC has not posted yet are
  remembered in `live/ftp-text-pending.json`.

`build_feeds.py` then builds from the snapshot, Luna's tags and the roster:

- RSS feeds: `live/feeds/<ID>.xml` per bill, `live/feeds/members/<CODE>.xml` per legislator and
  `live/feeds/law/<CODE>-<section>.xml` per law section a bill changes (every action on those bills, newest 200 items,
  with the matching limits and the official link, plus a "Now amends/adds/repeals" item dated the run that first
  indexed the bill on the section, from `live/statutes/first-seen.json`). A law feed whose section no bill changes any more is rewritten
  empty, never removed, so a followed link keeps working.
- Share pages `live/share/<ID>.html`, served at `/bill/<ID>` to every visitor (people are sent on to the app), with the
  official record, a `text/markdown` alternate link to the agent edition, schema.org `Legislation` data and the first 3,000 characters of text. Rewritten pages are submitted to
  IndexNow (`--no-indexnow` turns this off).
- Law pages `live/share/law/<CODE>/<section>.html`, one per section in `live/statutes/` (about 3,900), served at
  `/law/<CODE>/<section>` to crawlers and AI agents by the gateway (people get the app): the bills that change the
  section, its current text from `live/law` (up to 3,000 characters; new sections have none) and the official link.
  Pages for sections no bill changes any more are removed. Written quietly after the statute index.
- `live/sitemap.xml` (home, every `/bill/<ID>` and every `/law/<CODE>/<section>`); the API docs from `scripts/api/` (`api-catalog.json`, `openapi.json`, `auth.md`).
- Share-card inputs `live/og/cards.json`, and bill art `live/og/art/<ID>.jpg` with `art.json`.
- Statutes: `live/statutes/` lists the law sections each bill amends, adds or repeals, with the quoted wording.
- Population limits: `live/brackets/` lists each population test and the places that meet it under the 2020 Census
  (`data/census/tx_population_2020.json`, from `scripts/census_places.py`; skipped if absent).

The edge keeps the files only this run writes (`bills.json`, `feeds/`, `share/`, `sitemap.xml`, `statutes/`,
`brackets/`, `text/`, `history/`, the API docs) for 30 days, so after every run, finished or not, `purge_cache.py`
purges the ones that changed. It compares each file's modification time and size with `live/purge-state.json`, the
fingerprint from the last successful purge, and purges added, rewritten and deleted files by exact path (a folder with
too many changes goes whole; at most 100 paths per request). A typical run purges a few dozen paths; a run that
changed nothing sends no request. A failed purge keeps the old fingerprint, so the next run purges both runs' changes,
and sets `pending_since`; `daily_check.py` warns while a purge is pending and fails after 2 hours. Without a usable
state file it purges every prefix.

## Other jobs

- **Members**: `sync_members.py` joins the TLO roster (member code and the display name bill histories use) to the
  Legislative Reference Library for party, district and service. Authors match by exact chamber and display name.
  Members-elect without an LRL record take party and district from `data/members_elect_2026.json`; delete it once
  LRL lists the 90th Legislature.
- **Current law**: `sync_law.py` copies the Texas Constitution and every code from the Legislative Council's own
  per-code downloads (zipped HTML listed in statutes.capitol.texas.gov's `assets/StatuteCodeDownloads.json`, served
  from tcss.legis.texas.gov; about 42 MB for all 31). Each chapter becomes `live/law/<CODE>/<chapter>.md` (wording
  unchanged, one `## Sec.` or `## Art.` line per section); `live/law/<CODE>/index.json` lists each chapter's file,
  SHA-256 and section headings, and `live/law/index.json` the codes, their zip's ETag, Last-Modified and SHA-256, and
  chapter headings. One file per chapter keeps it to about 5,000 files and 140 MB (one per section would be 123,000
  files and over 500 MB in 4 KB blocks); no zip or HTML is kept. A refresh asks for each zip with its ETag, so only
  changed codes are downloaded, rewrites only chapters whose text changed and deletes chapters that left a code. A code
  that suddenly loses half its chapters is refused and keeps its old copy; stray files in the official zips
  (`cr.17 - Copy.htm`) are skipped and listed. Agent bill pages show the current text of each section the bill amends
  or repeals (from `live/statutes/`), inlined up to 4,000 characters.
- **Share cards**: `build_og.mjs` (layout in `og_card.mjs`) draws a 1200x630 card per bill with satori and resvg,
  only where `cards.json` shows a new version. A bill with art in `scripts/og_art/<ID>.jpg` gets a poster card. npm
  packages are installed on the VPS once per lockfile with `sudo sh scripts/install_og_deps.sh`; the unit refuses to
  run without them.
- **Agent edition**: `build_agent.mjs` reuses the site's own code (`src/taxonomy.js`, `src/prefs.js`, `src/geo.js`)
  to write a Markdown and JSON page per bill, index pages per filter, district pages, `llms.txt`, `robots.txt`,
  `sitemap.xml` and `index.html`. Search (`agent.billatlas.org/search`) is served by the sync service
  (`search_bills.py`).

## Site flags

`live/site-flags.json` holds operator switches the page reads on every load. Today: `"bill_art_banner": true` shows
the art banner on bill pages; a missing or unreadable file means off.

```sh
echo '{"bill_art_banner": true}' | sudo -u texas-bill-atlas tee /var/www/html/texas-bill-atlas/live/site-flags.json
```

## District maps

`data/geo/` is built on a desktop, never on the server: download the TLC plan shapefiles (`planh2316.zip`,
`plans2168.zip`), reports `h_r150.xls`, `s_r150.xls`, `h_r125.xls`, `s_r125.xls` (data.capitol.texas.gov) and
`cb_2024_us_county_500k.zip` (census.gov) into one folder, then run
`python scripts/build_districts.py --inputs <folder>` (needs `xlrd==2.0.1` and mapshaper via `npx`). The build checks
150 House and 31 Senate districts and 254 counties, or stops.
