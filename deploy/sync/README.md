# Sync service deployment

Runs `scripts/sync_service.py` (standard library only) in a locked-down container on the hosting network
`edge-bills`, which only the shared gateway and this container join. The gateway route and network belong to
cth.hosting (`gateway/sites.d/07-bills.ctharvey.me.caddy`, `docs/gateway-migration.md`).

Layout on the VPS (root-owned except the database directory):

- `/srv/sites/texas-bill-atlas/sync/compose.yaml` - this file's copy.
- `/srv/sites/texas-bill-atlas/sync/sync.env` - `PYTHON_IMAGE` (pinned digest), `SYNC_USER` (uid:gid of
  texas-bill-atlas), `SYNC_APP` (the extracted release below). No secrets.
- `/srv/sites/texas-bill-atlas/sync/app/<commit>/scripts/` - the whole `scripts/` folder of that main commit, so moving
  code between files needs no change here. Extract it with
  `git --git-dir=/var/lib/texas-bill-atlas/repository.git archive --format=tar -o /tmp/sync-app.tar <commit> scripts`, then
  `mkdir app/<commit> && tar -xf /tmp/sync-app.tar -C app/<commit>`. Releases extracted before this layout (flat files
  directly in `app/<commit>/`) only work with the previous compose command, `/app/sync_service.py`.
- `/var/lib/texas-bill-atlas/sync/` - SQLite database, mode 0700, owned by texas-bill-atlas. It holds key hashes,
  watchlists, followed legislators' member codes and saved searches only. There is no scheduled backup. A one-off
  backup is taken before each deploy that touches sync (below); people also keep their lists on each device.

Backup (before any sync deploy): copy `scripts/sync_backup.py` from the reviewed commit, then
`sudo -u texas-bill-atlas python3 sync_backup.py backup`. It writes `/var/lib/texas-bill-atlas/sync-backups/sync-<UTC>.sqlite3`
(directory 0700, file 0600) from one consistent snapshot of the live database, refuses to finish unless the copy passes
`integrity_check`, has the expected `lists` columns, holds readable data in every row, and has the same row count as the
live database had at that moment. It prints only the path, size and counts. `sync_backup.py check <file>` re-checks a
file without changing it. Backups hold lists that were deleted after they were taken, so they are removed once the
change they protect is settled.

Restore (only after a failed release has damaged lists): `docker compose --env-file sync.env -f compose.yaml stop sync`;
as texas-bill-atlas, move `sync.sqlite3` and any `sync.sqlite3-wal`/`-shm` aside (keep them), copy the checked backup to
`sync.sqlite3` (mode 0600); `docker compose ... up -d`; confirm health returns 200. Links are stored as fingerprints, so
every link that existed at backup time opens its list again; changes made after the backup are lost.

Update: extract a new `app/<commit>`, point `SYNC_APP` at it, then
`docker compose --env-file sync.env -f compose.yaml up -d` and confirm
`https://bills.ctharvey.me/api/sync/health` returns 200. Roll back by pointing `SYNC_APP` at the previous commit, as long
as both use the same layout. The compose command and the app folder layout are coupled: switching from flat releases to
`scripts/` releases means replacing `compose.yaml` and `SYNC_APP` together in one `up -d` (keep the old `compose.yaml`),
and rolling back across that change means restoring both.
Stopping the container is safe: the site reports sync as unavailable and keeps share links and files working.
