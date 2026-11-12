"""Back up and check the sync links database (standard library only; run on the VPS as texas-bill-atlas).

The database stores only hashes of link keys, so the file is the backup: restoring it brings every link back.
Prints counts, sizes and paths only, never row contents.

  python3 sync_backup.py backup [--db PATH] [--dir PATH]
  python3 sync_backup.py check FILE
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

DB = Path("/var/lib/texas-bill-atlas/sync/sync.sqlite3")
BACKUP_DIR = Path("/var/lib/texas-bill-atlas/sync-backups")
# Columns of the lists table created by sync_service.Store; a backup without exactly these cannot be restored.
COLUMNS = ["edit_hash", "view_hash", "data", "version", "created_at", "updated_at", "seen_at"]


class BackupError(Exception):
    pass


def inspect(conn: sqlite3.Connection) -> dict:
    """Integrity, schema and row facts of an open database; raises BackupError if it could not be restored."""
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise BackupError(f"integrity_check: {integrity}")
    columns = [row[1] for row in conn.execute("PRAGMA table_info(lists)")]
    if columns != COLUMNS:
        raise BackupError(f"unexpected lists columns: {columns}")
    rows = bad = 0
    for (data,) in conn.execute("SELECT data FROM lists"):
        rows += 1
        try:
            if not isinstance(json.loads(data), dict):
                bad += 1
        except ValueError:
            bad += 1
    if bad:
        raise BackupError(f"{bad} of {rows} rows hold unreadable data")
    return {"integrity": integrity, "rows": rows}


def check(path: Path) -> dict:
    if not path.is_file():
        raise BackupError(f"no such file: {path}")
    # immutable=1: read the file as is, creating no journal or shm files next to it.
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        return inspect(conn)
    except sqlite3.DatabaseError as error:
        raise BackupError(f"not a readable database: {error}") from error
    finally:
        conn.close()


def backup(db: Path, out_dir: Path, now: float | None = None) -> tuple[Path, dict]:
    if not db.is_file():
        raise BackupError(f"no database at {db}")
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    final = out_dir / f"sync-{stamp}.sqlite3"
    if final.exists():
        raise BackupError(f"backup already exists: {final}")
    partial = out_dir / f".sync-{stamp}.partial"
    old_umask = os.umask(0o077)
    try:
        source = sqlite3.connect(str(db), isolation_level=None)
        target = sqlite3.connect(str(partial))
        try:
            # One read transaction: the row count and the copied pages come from the same snapshot, so a write
            # landing during the backup cannot make the counts disagree.
            source.execute("BEGIN")
            live_rows = source.execute("SELECT COUNT(*) FROM lists").fetchone()[0]
            source.backup(target)
            source.execute("COMMIT")
        finally:
            target.close()
            source.close()
        os.chmod(partial, 0o600)
        facts = check(partial)
        if facts["rows"] != live_rows:
            raise BackupError(f"row count mismatch: live {live_rows}, backup {facts['rows']}")
        os.replace(partial, final)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        os.umask(old_umask)
    return final, {**facts, "live_rows": live_rows, "bytes": final.stat().st_size}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("backup")
    make.add_argument("--db", type=Path, default=DB)
    make.add_argument("--dir", type=Path, default=BACKUP_DIR)
    verify = commands.add_parser("check")
    verify.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            path, facts = backup(args.db, args.dir)
            print(f"backup: {path} ({facts['bytes']} bytes) integrity={facts['integrity']} "
                  f"rows={facts['rows']} live_rows={facts['live_rows']}")
        else:
            facts = check(args.file)
            print(f"check: {args.file} integrity={facts['integrity']} rows={facts['rows']}")
    except BackupError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
