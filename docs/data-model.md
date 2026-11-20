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
| `statutes/index.json`, `statutes/sections/` | `texas-bill-statutes-v1` (kinds: `m` amends, `n` adds, `r` repeals; `sections[key].h` = the section's heading: as current law reads when any bill amends or repeals it, else only when every adding bill gives the same one; `sections[key].hb` = `{bill: heading}` for adding bills whose own heading differs; `sections[key].f` = `{bill: day}` for pairs first seen after `first_seen_from`, copied from `first-seen.json`) | data run |
| `statutes/first-seen.json` | `texas-bill-statutes-first-seen-v1`: `{from, pairs: {key: {bill: day or null}}}`, the Chicago day of the data run that first indexed each pair (null: already indexed at the `from` baseline). Only grows: a pair that leaves keeps its day; an unreadable file is left alone and stops new stamps rather than restarting | data run |
| `statutes/index.json` `chapters` | Additive key of `texas-bill-statutes-v1`: `{"PE 46": {h, b: [[bill, "r"\|"m"\|"n"]], f?}}` for whole-chapter changes only (a chapter repealed, amended as a part, or added; chapters a bill merely cites are left out; only the 27 codes, chapter id uppercase, key `^[A-Z]{2} \d+[A-Z]?$`). `h` = the chapter heading from the law copy without "CHAPTER 46. " and the trailing period, or "" when unknown. `b` sorts like a section's, `f` = `{bill: day}` as for sections. Section-level bills in a chapter are not copied here: derive them from `sections` (chapter = the number before the first dot). Chapter pairs live in `first-seen.json` under their dotless key; `chapters_from` there is the day chapters began to be recorded (earlier chapter pairs are null, so deploying does not flood). A run that finds no chapters leaves their history alone | data run |
| `feeds/law/<CODE>-<section>.xml`, `feeds/law/<CODE>-<chapter>.xml` | RSS. A chapter feed (e.g. `PE-46.xml`, title "Penal Code chapter 46 (Weapons)") combines the chapter's whole-chapter bills and every section-level bill in it, with "Now amends § 46.06" / "Now repeals the whole chapter" items from the first-seen days. Like section feeds, rewritten empty (never removed) when the chapter loses its bills | data run |
| `share/law/<CODE>/<section>.html`, `share/law/<CODE>/<chapter>.html` | Law share pages. A chapter page (`PE/46.html`) is titled "Penal Code Chapter 46: Weapons", lists the whole-chapter bills and the sections bills change, and uses `https://billatlas.org/#chapter?law=PE&ch=46` as canonical and app link. Chapter pages are not in the sitemap (the gateway serves `/law/<CODE>/<section>` only). Stale chapter pages are removed without touching section pages in the same folder | data run |
| `law/<CODE>/<chapter>.md`, `law/<CODE>/index.json`, `law/index.json` | `texas-bill-law-v1`, the current-law copy | law job |
| `law/search/<prefix>.json`, `law/search/index.json` | `texas-bill-law-search-v1`: `<prefix>.json` is a compact JSON list of `[key, heading]` (`["PE 46.02", "UNLAWFUL CARRYING WEAPONS"]`, `["PE 46", "WEAPONS"]`, official uppercase; the client title-cases) for every section and chapter of the 27 tracked codes. A prefix is the first 3 characters of a lowercased `[a-z0-9]+` word of 3 or more characters, not in the stop list (of and the for to in by or a an on with under from as at certain other); an entry is in each distinct prefix file once, entries sorted. `index.json` = `{format, generated_at, prefixes: {prefix: count}}`. Written only when changed, shards whose prefix vanished are removed. Rebuilt at the end of every law job and alone by `sync_law.py --out live/law --search-only` (no download) | law job |
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
  never free text (so "PM 2.5" stays a text search). This holds with other filters too: `{query: "PE 46.06",
  topic: "Guns"}` is that section's bills narrowed by topic, and its summary reads "Bills that change ...". The key
  is case-sensitive: "pe 46.06" is an ordinary search that also finds the section's bills. Any saved search whose
  query is exactly a key counts a bill as new when it has a dated action after the day it was last opened, or when
  the index's first-seen day for that bill and section is on or after it. Only the search with the key alone is the
  follow: Unfollowing removes every such search for the key (a narrowed one stays, as a saved search); an import
  skips a law already followed.
- Near you `texas-bill-atlas-near-you-v1`: district numbers, county and how they were found. Coordinates and
  addresses are never stored.
- Export file `texas-bill-atlas-profile-v1`: `{lists, follows, searches, theme}`. Import also reads older
  `texas-bill-atlas-watchlist-v1` files and plain lists of bill numbers.
- Addresses: every view has a path, listed in `src/core/routes.js` (`/today`, `/explorer?chamber=Senate`,
  `/about/method`, `/bill/<ID>`, `/law/<CODE>/<section>`, `/law/<CODE>/<chapter>`, `/member/<code>/<name>`); filters
  are the query string of `/explorer` and `/watchlist`. A shared list, an open bill and a view-only sync key stay in the
  fragment (`/explorer#list=HB5,SB12`), which never reaches the server. Copied links use paths too: a shared list is
  `/explorer#list=HB5,SB12`, a sync link `/watchlist#sync=<key>`. Old `#view?...` links, including share and sync links
  copied before paths, still open the same view and are rewritten to its path on arrival (in the browser: the server
  never sees a fragment); an edit key is never written back into the address. Personal and filterable views get canonical `/` and
  `noindex, follow`.

## Sync links

`scripts/sync_service.py` (client `src/sync.js`) stores `{watch, filters, follows, searches, theme}` per link in
SQLite, keyed by SHA-256 hashes of a random edit key and a derived view key; no email, name or IP. The edit key
travels only in the URL fragment and the `X-Sync-Key` header. Saves are versioned and a conflict replays the
device's unsaved changes onto the newer data. View-only links return `{watch, filters}` and serve a combined RSS at
`/api/sync/feed/<view key>.xml`.

Limits: 32 KB body, 500 bills, 200 follows, 20 saved searches, per-client rate limits (an IPv4 address or an IPv6
/64), 100,000 lists, deletion after a year unused. Operations: [deploy/sync/README.md](../deploy/sync/README.md).
