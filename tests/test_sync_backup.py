import os
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sync_backup  # noqa: E402
import sync_service as svc  # noqa: E402

SAVE_A = {"watch": ["HB1", "SB2"], "follows": ["A1234"],
          "searches": [{"id": "abcd1234", "name": "Water bills", "filters": {"query": "water"}}]}
SAVE_B = {"watch": ["HB717"]}


def people(db: Path):
    store = svc.Store(db)
    a = store.create(SAVE_A, 1000.0)
    b = store.create(SAVE_B, 1000.0)
    version, _ = store.update(a, 1, {**SAVE_A, "watch": ["HB1", "SB2", "HB110"]}, 1001.0)
    return store, a, b, version


def test_restored_backup_opens_every_existing_link_with_the_saves_it_had(tmp_path):
    db = tmp_path / "live" / "sync.sqlite3"
    db.parent.mkdir()
    store, a, b, version = people(db)
    path, facts = sync_backup.backup(db, tmp_path / "backups", now=0)
    assert facts["rows"] == facts["live_rows"] == 2 and facts["integrity"] == "ok"
    # After the backup someone edits a list and someone deletes theirs.
    store.update(a, version, {"watch": []}, 1002.0)
    store.delete(b)
    store.close()
    shutil.copyfile(path, db)  # The restore runbook: container stopped, backup copied over the database.
    for suffix in ("-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    restored = svc.Store(db)
    kind, data, got_version = restored.lookup(a, 1003.0)
    assert (kind, got_version, data["watch"], data["follows"], data["searches"]) == (
        "edit", version, ["HB1", "SB2", "HB110"], SAVE_A["follows"], SAVE_A["searches"])
    assert restored.lookup(svc.view_key_for(a), 1003.0)[0] == "view"
    assert restored.lookup(b, 1003.0)[1] == SAVE_B
    # The restored list keeps working: the next write continues from the backed-up version.
    assert restored.update(a, version, {"watch": ["HB1"]}, 1004.0)[0] == version + 1


def test_backup_is_private_and_reports_no_saved_content(tmp_path, capsys):
    db = tmp_path / "sync.sqlite3"
    people(db)[0].close()
    assert sync_backup.main(["backup", "--db", str(db), "--dir", str(tmp_path / "backups")]) == 0
    out = capsys.readouterr().out
    assert "rows=2" in out and "Water bills" not in out and "HB1" not in out
    [made] = (tmp_path / "backups").iterdir()
    assert made.name.startswith("sync-") and made.suffix == ".sqlite3"
    if os.name != "nt":
        assert made.stat().st_mode & 0o777 == 0o600
        assert (tmp_path / "backups").stat().st_mode & 0o777 == 0o700


def test_existing_backup_is_never_overwritten(tmp_path):
    db = tmp_path / "sync.sqlite3"
    people(db)[0].close()
    first, _ = sync_backup.backup(db, tmp_path / "b", now=0)
    before = first.read_bytes()
    with pytest.raises(sync_backup.BackupError, match="already exists"):
        sync_backup.backup(db, tmp_path / "b", now=0)
    assert first.read_bytes() == before and [p.name for p in (tmp_path / "b").iterdir()] == [first.name]


def test_missing_database_leaves_nothing_behind(tmp_path):
    with pytest.raises(sync_backup.BackupError, match="no database"):
        sync_backup.backup(tmp_path / "missing.sqlite3", tmp_path / "b", now=0)
    assert not (tmp_path / "b").exists()


def broken(tmp_path, kind):
    path = tmp_path / f"{kind}.sqlite3"
    if kind == "garbage":
        path.write_bytes(b"not a database" * 100)
        return path
    conn = sqlite3.connect(path)
    if kind == "schema":
        conn.execute("CREATE TABLE lists (edit_hash TEXT, data TEXT)")
    else:
        conn.execute("CREATE TABLE lists (edit_hash TEXT PRIMARY KEY, view_hash TEXT UNIQUE NOT NULL, data TEXT NOT NULL,"
                     " version INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,"
                     " seen_at INTEGER NOT NULL)")
        conn.execute("INSERT INTO lists VALUES ('e', 'v', '{not json', 1, 0, 0, 0)")
    conn.commit()
    conn.close()
    return path


@pytest.mark.parametrize("kind,message", [("garbage", "not a readable database"), ("schema", "unexpected lists columns"),
                                          ("data", "unreadable data")])
def test_check_refuses_a_file_that_could_not_be_restored(tmp_path, kind, message, capsys):
    path = broken(tmp_path, kind)
    with pytest.raises(sync_backup.BackupError, match=message):
        sync_backup.check(path)
    assert sync_backup.main(["check", str(path)]) == 1
    assert "FAILED" in capsys.readouterr().err


def test_check_passes_on_a_real_backup_and_creates_no_side_files(tmp_path):
    db = tmp_path / "sync.sqlite3"
    people(db)[0].close()
    path, _ = sync_backup.backup(db, tmp_path / "b", now=0)
    assert sync_backup.check(path) == {"integrity": "ok", "rows": 2}
    assert sorted(p.name for p in (tmp_path / "b").iterdir()) == [path.name]


def test_a_copy_that_fails_its_check_is_removed_and_reported(tmp_path, monkeypatch):
    db = tmp_path / "sync.sqlite3"
    people(db)[0].close()

    def failing(path):
        assert path.name.endswith(".partial")  # The copy is checked before it gets its final name.
        raise sync_backup.BackupError("integrity_check: page 3 corrupt")

    monkeypatch.setattr(sync_backup, "check", failing)
    with pytest.raises(sync_backup.BackupError, match="corrupt"):
        sync_backup.backup(db, tmp_path / "b", now=0)
    assert list((tmp_path / "b").iterdir()) == []


def test_integrity_problems_are_refused():
    class Corrupt:
        def execute(self, sql):
            class Row:
                def fetchone(self):
                    return ("*** in database main ***\nPage 3: btreeInitPage() returns error code 11",)
            return Row()

    with pytest.raises(sync_backup.BackupError, match="integrity_check"):
        sync_backup.inspect(Corrupt())


def test_columns_match_the_service_schema(tmp_path):
    db = tmp_path / "sync.sqlite3"
    svc.Store(db).close()
    conn = sqlite3.connect(db)
    assert [row[1] for row in conn.execute("PRAGMA table_info(lists)")] == sync_backup.COLUMNS
    conn.close()
