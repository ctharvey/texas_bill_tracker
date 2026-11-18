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

Each unit takes the whole `scripts/` folder from one `main` commit of the deployer's repository, so code can move
between files without reinstalling units. A push that changes a job's code or inputs reruns that job (see
[deployment.md](deployment.md)). Failures start `texas-bill-alert@<unit>`.

## Data run (`texas-bill-data`)

`sync_ftp.py` reads TLC's bulk FTP (`/bills/90r/billhistory` and the text folders):

- **Snapshot**: `live/bills.json`, replaced atomically only when at least a third of the files read parse. When
  nothing changed it keeps `generated_at` until it is six hours old, then writes a heartbeat; an eight-hour-old
  snapshot therefore means the job has stopped.
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

- RSS feeds: `live/feeds/<ID>.xml` per bill and `live/feeds/members/<CODE>.xml` per legislator (newest 200 items).
- Share pages `live/share/<ID>.html`, served at `/bill/<ID>` to search and link-preview crawlers, with the official
  record, schema.org `Legislation` data and the first 3,000 characters of text. Rewritten pages are submitted to
  IndexNow (`--no-indexnow` turns this off).
- `live/sitemap.xml`; the API docs from `scripts/api/` (`api-catalog.json`, `openapi.json`, `auth.md`).
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
