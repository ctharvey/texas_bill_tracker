# Sync service deployment

Runs `scripts/sync_service.py` (standard library only) in a locked-down container on the hosting network
`edge-bills`, which only the shared gateway and this container join. The gateway route and network belong to
cth.hosting (`gateway/sites.d/07-bills.ctharvey.me.caddy`, `docs/gateway-migration.md`).

Layout on the VPS (root-owned except the database directory):

- `/srv/sites/texas-bill-atlas/sync/compose.yaml` - this file's copy.
- `/srv/sites/texas-bill-atlas/sync/sync.env` - `PYTHON_IMAGE` (pinned digest), `SYNC_USER` (uid:gid of
  texas-bill-atlas), `SYNC_APP` (the extracted release below). No secrets.
- `/srv/sites/texas-bill-atlas/sync/app/<commit>/` - `sync_service.py`, `build_feeds.py` and `search_bills.py` from that main commit
  (`git --git-dir=/var/lib/texas-bill-atlas/repository.git show <commit>:scripts/<file>`).
- `/var/lib/texas-bill-atlas/sync/` - SQLite database, mode 0700, owned by texas-bill-atlas. It holds key hashes,
  watchlists and followed legislators' member codes only. No backup: people keep export files, and a lost list only unlinks devices.

Update: extract a new `app/<commit>`, point `SYNC_APP` at it, then
`docker compose --env-file sync.env -f compose.yaml up -d` and confirm
`https://bills.ctharvey.me/api/sync/health` returns 200. Roll back by pointing `SYNC_APP` at the previous commit.
Stopping the container is safe: the site reports sync as unavailable and keeps share links and files working.
