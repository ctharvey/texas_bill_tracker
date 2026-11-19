# Data model

## Bill snapshot (`live/bills.json`, bundled `data/bills.json`)

Top level: `session` ("90R"), `generated_at`, `data_mode` (`official-ftp`; the site and the deployer refuse anything
else), `coverage_note`, `sources`, `author_profiles` (curated leadership and committee facts).

Each bill (`bills[]`):

| Field | Meaning |
|---|---|
| `id`, `number`, `chamber`, `title`, `caption` | Identity and official caption |
| `status`, `filed_at`, `last_action`, `last_action_date`, `actions`, `action_dates` | Official history; `last_action` is TLO's `MM/DD/YYYY H\|S\|E text`. `actions` keeps only the last 12; `status` (Filed, Referred, Scheduled, Heard, Advanced, Passed, Enacted, Vetoed) comes from the full history |
| `hearing` | `heard`, `scheduled` or `none`, from the full history. The site falls back to `actions` when it is missing |
| `committees`, `committee` | Each referral `{chamber, name, status, votes?, subcommittee?, subcommittee_status?}` from TLC's committee attributes (`votes` once the committee has voted); `committee` is the one now holding the bill, else the last |
| `author`, `authors`, `coauthors`, `sponsors`, `cosponsors` | Members by role; authors and coauthors are from the originating chamber, sponsors from the other. `author` is a display string kept for compatibility |
| `subjects` | TLC subject index, index codes removed |
| `companions` | `{id, author, relation}` from the history ("SB 132 by Menendez, Identical") |
| `text_versions` | Official text versions and their links |
| `source_path`, `source_record`, `source_updated` | Which FTP file the record came from and when TLC last changed it |
| `topics`, `agencies`, `impacts`, `constituencies`, `source_verified` | Hand-reviewed tags, present on a few bills only; they survive refreshes |

Topics, agencies and the rest for other bills come from caption rules in `src/taxonomy.js` or from Luna's published
review (`live/luna/tags.json`), never from the snapshot itself.

CSV import accepts columns such as `id`, `title`, `caption`, `author`, `status`, `filed_at`, `topics` and `agencies`
(multi-value columns separated by `|`). Imports stay in memory.

## Other `live/` files

| Path | Format | Written by |
|---|---|---|
| `members.json` | `texas-bill-members-v1` | members job |
| `history/<BILL>/history.json`, `documents.json`, `witnesses-<H\|S>.json` | `texas-bill-history-v1`, `-documents-v1`, `-witnesses-v1` | data run |
| `text/<BILL>/<code>.md`, `index.json` | Markdown, one paragraph per line, `### SECTION n.` headings, `<ins>`/`<del>` | data run |
| `statutes/index.json`, `statutes/sections/` | `texas-bill-statutes-v1` (kinds: `m` amends, `n` adds, `r` repeals; `sections[key].f` = `{bill: day}` for pairs first seen after `first_seen_from`, copied from `first-seen.json`) | data run |
| `statutes/first-seen.json` | `texas-bill-statutes-first-seen-v1`: `{from, pairs: {key: {bill: day or null}}}`, the Chicago day of the data run that first indexed each pair (null: already indexed at the `from` baseline). Only grows: a pair that leaves keeps its day; an unreadable file is left alone and stops new stamps rather than restarting | data run |
| `brackets/index.json` | `texas-bill-brackets-v1` | data run |
| `feeds/`, `share/`, `sitemap.xml`, `og/cards.json` | RSS, HTML, sitemap, card inputs | data run |
| `luna/tags.json`, `luna/highlights/<BILL>.json`, `luna/status.json` | `texas-bill-luna-tags-v1`, `-highlights-v1`, `-status-v1` | review worker |
| `og/<ID>.png`, `og/rendered.json` | share card images | og job |
| `agent/` | agent edition | agent job |
| `site-flags.json` | operator switches | by hand |

Highlight positions use a plain projection of each paragraph (heading marker, `<ins>`/`<del>` tags and escapes
removed; offsets in code points; paragraph 0 is the title). The same projection is computed in `sync_ftp.py`,
`review_pipeline.py` and `src/review.js`; keep them in step.

## What the browser keeps

Saved data lives in `localStorage` (`src/core/storage.js`) and leaves the browser only through a sync link the
person creates. The optional Near you address lookup sends the typed address to the US Census geocoder.

- Watchlist `tx-bill-atlas-watch-90r`, followed legislators `tx-bill-atlas-follow-90r` (at most 200), saved searches
  `tx-bill-atlas-searches-90r` (at most 20), preferences and last filters `tx-bill-atlas-prefs-v1`. A followed law
  section is a saved search whose only filter is the section key as the query (`{query: "PE 46.06"}`); a query that
  is exactly a key of one of the 27 indexed codes matches only the bills the statute index lists for that section,
  never free text (so "PM 2.5" stays a text search). A follow counts a bill as new when it has a dated action after
  the day the follow was last opened, or when the index's first-seen day for that bill and section is on or after
  it. Unfollowing removes every saved search for the key; an import skips a law already followed.
- Near you `texas-bill-atlas-near-you-v1`: district numbers, county and how they were found. Coordinates and
  addresses are never stored.
- Export file `texas-bill-atlas-profile-v1`: `{lists, follows, searches, theme}`. Import also reads older
  `texas-bill-atlas-watchlist-v1` files and plain lists of bill numbers.
- Addresses: views and filters live in the hash (`#all?chamber=Senate`); a bill is `/bill/<ID>`; a law section is
  `/law/<CODE>/<section>` (old `#statute?law=PE&sec=46.06` links still open it and are rewritten); a share link
  (`#all?list=HB5,SB12`) opens a read-only list.

## Sync links

`scripts/sync_service.py` (client `src/sync.js`) stores `{watch, filters, follows, searches, theme}` per link in
SQLite, keyed by SHA-256 hashes of a random edit key and a derived view key; no email, name or IP. The edit key
travels only in the URL fragment and the `X-Sync-Key` header. Saves are versioned and a conflict replays the
device's unsaved changes onto the newer data. View-only links return `{watch, filters}` and serve a combined RSS at
`/api/sync/feed/<view key>.xml`.

Limits: 32 KB body, 500 bills, 200 follows, 20 saved searches, per-client rate limits (an IPv4 address or an IPv6
/64), 100,000 lists, deletion after a year unused. Operations: [deploy/sync/README.md](../deploy/sync/README.md).
