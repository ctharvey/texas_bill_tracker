import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import daily_check as dc  # noqa: E402

NOW = datetime(2026, 11, 16, 22, 0, tzinfo=timezone.utc)


def test_freshness_flags_stale_and_unreadable_stamps():
    assert dc.freshness("bills", "2026-11-16T20:17:00Z", NOW, 3)[0] is True
    assert dc.freshness("bills", "2026-11-16T18:00:00.123456Z", NOW, 3)[0] is False
    assert dc.freshness("bills", "2026-11-16T21:00:00", NOW, 3)[0] is True  # No zone reads as UTC.
    assert dc.freshness("bills", None, NOW, 3)[0] is False
    assert dc.freshness("bills", "yesterday", NOW, 3)[0] is False


def test_asset_digest_reads_the_bundle_path():
    assert dc.asset_digest('<script type="module" src="./assets/7ace0c0ad67129a7/app.js"></script>') == "7ace0c0ad67129a7"
    assert dc.asset_digest('<script src="./src/app.js"></script>') is None


def test_highest_bill_numbers_from_ftp_and_snapshot():
    assert dc.highest_bill(["HB 1177.xml", "HB 1178.xml", "HB 999.xml", "notes.txt"]) == 1178
    assert dc.highest_bill([]) is None
    bills = [{"id": "HB1178"}, {"id": "HB99"}, {"id": "SB400"}, {"id": "HJR5"}, {}]
    assert dc.snapshot_highest(bills) == 1178


def test_ci_verdict_uses_the_newest_main_run_of_each_event():
    runs = [
        {"event": "schedule", "headBranch": "main", "headSha": "a" * 40, "status": "completed", "conclusion": "failure",
         "createdAt": "2026-11-15T08:00:00Z"},
        {"event": "schedule", "headBranch": "main", "headSha": "b" * 40, "status": "completed", "conclusion": "success",
         "createdAt": "2026-11-16T08:00:00Z"},
        {"event": "workflow_dispatch", "headBranch": "domain-move", "headSha": "c" * 40, "status": "completed",
         "conclusion": "failure", "createdAt": "2026-11-16T21:00:00Z"},
        {"event": "push", "headBranch": "main", "headSha": "d" * 40, "status": "in_progress", "conclusion": "",
         "createdAt": "2026-11-16T21:30:00Z"},
    ]
    assert dc.ci_verdict(runs, "schedule", NOW)[0] is True
    assert dc.ci_verdict(runs, "push", NOW)[0] is True  # Still running is not a failure.
    late = datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc)
    assert dc.ci_verdict(runs, "schedule", late)[0] is False  # No nightly run for 40 h.
    assert dc.ci_verdict([r for r in runs if r["event"] != "schedule"], "schedule", NOW)[0] is False
    runs[1]["conclusion"] = "failure"
    assert dc.ci_verdict(runs, "schedule", NOW)[0] is False
