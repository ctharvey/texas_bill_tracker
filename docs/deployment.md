# Deployment

Production is https://billatlas.org (agent edition https://agent.billatlas.org) on the shared VPS. The gateway
(Caddy, owned by the `ctharvey/cth.hosting` repo, `gateway/sites.d/09-billatlas.org.caddy` and
`10-agent.billatlas.org.caddy`) serves `/srv/static/texas-bill-atlas/current` and handles HTTPS. The old names
bills.ctharvey.me and agent.bills.ctharvey.me serve the same release with no redirect, because watchlists, filters
and sync keys live in browser storage tied to the address they were saved under.

## How code ships

- **Site**: `texas-bill-atlas.timer` runs the deployer every two minutes. `deploy_static.py` fetches public GitHub
  `main`, takes `index.html`, everything under `src/` and `public/`, and six data files, requires an official-FTP
  snapshot of at least 1,000 bills, writes an immutable release, and switches `current` atomically. `src/` is also
  copied to `assets/<digest>/` so browsers can cache scripts for a year. Each release gets a `live -> ../../live`
  symlink. The ten newest releases (plus the live one) are kept. A failed fetch or check leaves the last release up.
- **Server jobs**: after a publish, the deployer leaves a marker in `/var/lib/texas-bill-atlas/refresh` for each job
  whose code or inputs changed (`JOB_INPUTS`). `texas-bill-refresh.path` starts `refresh_jobs.sh`, which reruns
  members, law, data, agent and share cards in that order. The review unit is never started this way. By hand:
  `sudo -u texas-bill-atlas touch /var/lib/texas-bill-atlas/refresh/{data,agent,og}`.
- **Units and the deployer itself** are installed by hand as root and do not update on push. The deployer runs from
  `/usr/local/lib/texas-bill-atlas/deploy_static.py`: reinstall it *before* pushing a deployer change, or the new
  commit deploys with the old deployer. If that happens, reinstall it and push any new commit: the deployer skips a
  commit that is already published, so it rebuilds the release only for a new one (happened 2026-11-19 with the
  `app.css`, `boot.js` and `shell.html` release files).

## Installing on a new server

As root, from a reviewed archive of this repository:

```sh
useradd --system --home-dir /var/lib/texas-bill-atlas --shell /usr/sbin/nologin texas-bill-atlas
install -d -m 755 -o texas-bill-atlas -g texas-bill-atlas /var/www/html/texas-bill-atlas /var/lib/texas-bill-atlas/refresh
install -d -m 755 /usr/local/lib/texas-bill-atlas
install -m 644 scripts/deploy_static.py scripts/refresh_jobs.sh /usr/local/lib/texas-bill-atlas/
install -m 644 scripts/texas-bill-*.service scripts/texas-bill-*.timer scripts/texas-bill-refresh.path /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now texas-bill-atlas.timer texas-bill-refresh.path
systemctl enable --now texas-bill-data.timer texas-bill-members.timer texas-bill-og.timer texas-bill-agent.timer
systemctl enable --now texas-bill-law.timer
```

Before enabling the jobs:

- `texas-bill-data` needs root-only `/etc/texas-bill-atlas/cf-purge.env` with `CF_PURGE_TOKEN=<token>` (a Cloudflare
  token with Cache Purge on the billatlas.org zone only); the unit does not start without it.
- `texas-bill-og` needs its npm packages: `sudo sh scripts/install_og_deps.sh`.
- `texas-bill-alert@.service` (started on any unit failure) reads optional `/etc/texas-bill-alert.env`.
- The review worker has its own setup; see [review-pipeline.md](review-pipeline.md#server-setup).
- The sync service runs in a container; see [deploy/sync/README.md](../deploy/sync/README.md).

Check with `systemctl list-timers 'texas-bill-*'` and `journalctl -u <unit>`.

## Cloudflare

The billatlas.org zone (Free plan) proxies the site; agent.billatlas.org is DNS-only. Smart Tiered Cache is on.
Minimum TLS version 1.2 (raised from 1.0 on 2026-11-23).
Cache rules:

| Path | Edge | Browser |
|---|---|---|
| `/assets/*` | 1 year | 1 year |
| `/live/luna/shards/*` (content-addressed) | 1 year | 1 year |
| Files only the data run writes (see [data-pipeline.md](data-pipeline.md#data-run-texas-bill-data)) | 30 days, 404s 1 day; added, changed and deleted files purged after each run | origin (`no-cache`) |
| Other `/live/*` and `/data/*` | 5 minutes | origin |
| `/live/luna/status.json` | 15 seconds | origin |
| `/api/sync/health` | 30 seconds | origin |
| `/favicon.ico`, `/icon.png`, `/apple-touch-icon.png` | 1 week | 1 week |
| `/law` and `/law/*` (section, chapter and code pages, static or rendered on request) | 1 hour; 3xx, 4xx and 5xx (including the sync service's 429s) not cached | origin (`no-cache`) |
| Other `*.js` and `*.css` (the stable `/app.css` and `/boot.js`, `src/`) | origin (`no-cache`, revalidated) | origin (`no-cache`) |

The page itself is not cached. `/bill/<ID>` is the same page for every visitor: a URL rewrite serves
`live/share/<ID>.html` (IDs with a bill prefix, case-sensitive), so it shares that file's cache entry and purge, and
the page sends people on to the app. A redirect rule sends `/bill/<ID>` with `Accept: text/markdown` to
`agent.billatlas.org/bills/<ID>.md`; agents otherwise find that record from the page's `rel="alternate"` link. The
gateway's own user-agent rules for `/bill/<ID>` now apply only to bills.ctharvey.me. `/law/<CODE>/<section>` is
cached at the edge for an hour (table above), with no rewrite or purge: the gateway (cth.hosting `09-billatlas.org.caddy`) gives everyone
`live/share/law/<CODE>/<key>.html` when it exists, else the sync service's page rendered on request
(`scripts/law_on_demand.py`, noindex; 404 for keys not in the law copy), else, when the sync service is down, the app. Transform rules also serve `/.well-known/api-catalog`, `/openapi.json` and `/auth.md` from `live/`. A WAF rule
blocks `/wp-*`, `.php`, `/.env` and `/.git` probes.

## Daily check

`python -X utf8 scripts/daily_check.py` sweeps the public systems. Run it once a day, and after a push once the Tests run
has finished. It needs no server access and writes nothing; the GitHub Actions checks use the `gh` CLI.

- Options: `--no-ci` skips the GitHub Actions checks; `--sample N` sets how many of the newest filing day's bills are
  spot-checked (default 8, 0 for all).
- It checks both sites and that they run the same build, bill data age and edge purges, the Legislature's FTP against the
  site, the roster, Luna's status, the sync API, the agent edition and search, newly filed bills, TLS certificates, the
  nightly tests (E2E) and the tests on the last push to `main`.
- Output is one PASS, WARN or FAIL line per check, then totals. It exits 1 if anything failed; warnings alone exit 0.
- WARN "waiting for the next data run" on the FTP line is normal soon after a bill is posted. Check again after the
  hourly :17 run.
- FAIL "tests on the last push": `gh run list --workflow Tests -L 5`, then `gh run view <id> --log-failed`.
- The limits are the constants at the top of the script; its tests are `tests/test_daily_check*.py`.

## Rollback

Stop `texas-bill-atlas.timer`, point a temporary relative symlink at a kept `releases/<commit>`, and rename it over
`current` with `mv -Tf`. Fix or revert `main` before starting the timer again. This affects only the site, not
`live/` data.
