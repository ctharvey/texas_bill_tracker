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
  members, data, agent and share cards in that order. The review unit is never started this way. By hand:
  `sudo -u texas-bill-atlas touch /var/lib/texas-bill-atlas/refresh/{data,agent,og}`.
- **Units and the deployer itself** are installed by hand as root and do not update on push. The deployer runs from
  `/usr/local/lib/texas-bill-atlas/deploy_static.py`: reinstall it *before* pushing a deployer change, or the new
  commit deploys with the old deployer.

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
Cache rules:

| Path | Edge | Browser |
|---|---|---|
| `/assets/*` | 1 year | 1 year |
| `/live/luna/shards/*` (content-addressed) | 1 year | 1 year |
| Files only the data run writes (see [data-pipeline.md](data-pipeline.md#data-run-texas-bill-data)) | 1 hour, purged after each run | origin (`no-cache`) |
| Other `/live/*` and `/data/*` | 5 minutes | origin |
| `/live/luna/status.json` | 15 seconds | origin |
| `/api/sync/health` | 30 seconds | origin |
| `/favicon.ico`, `/icon.png`, `/apple-touch-icon.png` | 1 week | 1 week |

The page itself and `/bill/<ID>` are not cached, because the gateway answers crawlers and people differently by user
agent. Transform rules serve `/.well-known/api-catalog`, `/openapi.json` and `/auth.md` from `live/`. A WAF rule
blocks `/wp-*`, `.php`, `/.env` and `/.git` probes.

## Rollback

Stop `texas-bill-atlas.timer`, point a temporary relative symlink at a kept `releases/<commit>`, and rename it over
`current` with `mv -Tf`. Fix or revert `main` before starting the timer again. This affects only the site, not
`live/` data.
