"""daily_check.py tells a quiet Legislature from a stopped data job. Cases are from the 2026-11-19 sweep: no bill was
posted between 08:00 and 15:00 UTC, every hourly run succeeded, and the old check failed the data at 7.8 h old."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import daily_check as dc  # noqa: E402
import sync_ftp  # noqa: E402

NOW = datetime(2026, 11, 19, 16, 7, tzinfo=timezone.utc)
QUIET_DATA = "2026-11-19T08:18:56Z"  # 7.8 h before NOW


def status(checked_at, **extra):
    return {"format": "texas-bill-sync-status-v1", "checked_at": checked_at, "failures": [], "incomplete": False, **extra}


def test_heartbeat_matches_the_sync_job():
    assert dc.SYNC_HEARTBEAT_HOURS == sync_ftp.HEARTBEAT.total_seconds() / 3600


def test_quiet_data_with_a_recent_run_passes():
    ok, detail = dc.data_verdict(QUIET_DATA, status("2026-11-19T15:18:20Z"), NOW)
    assert ok is True, detail
    assert "last run: 0.8 h old" in detail


def test_one_missed_run_passes_and_two_fail():
    assert dc.data_verdict(QUIET_DATA, status("2026-11-19T14:18:20Z"), NOW)[0] is True    # 1.8 h: the 15:18 run failed
    assert dc.data_verdict(QUIET_DATA, status("2026-11-19T13:18:20Z"), NOW)[0] is False   # 2.8 h: two runs missed


def test_data_older_than_the_heartbeat_allows_fails_even_with_a_recent_run():
    assert dc.data_verdict("2026-11-19T07:00:00Z", status("2026-11-19T15:18:20Z"), NOW)[0] is False  # 9.1 h


def test_a_run_that_published_with_failures_warns():
    ok, detail = dc.data_verdict(QUIET_DATA, status("2026-11-19T15:18:20Z", failures=["texts: timed out"]), NOW)
    assert ok is None and "texts: timed out" in detail
    ok, detail = dc.data_verdict(QUIET_DATA, status("2026-11-19T15:18:20Z", incomplete=True), NOW)
    assert ok is None and "incomplete read" in detail


def test_before_the_status_file_exists_only_the_heartbeat_bound_applies():
    ok, detail = dc.data_verdict(QUIET_DATA, None, NOW)
    assert ok is True and "no run status yet" in detail
    assert dc.data_verdict("2026-11-19T07:00:00Z", None, NOW)[0] is False


def test_a_bill_posted_since_the_last_run_waits_and_an_old_one_fails():
    posted = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)  # HB 1246, 09:00 CST
    assert dc.parity_verdict(1246, 1246, posted, NOW)[0] is True
    ok, detail = dc.parity_verdict(1246, 1245, posted, NOW)
    assert ok is None and "waiting for the next data run" in detail
    assert dc.parity_verdict(1246, 1245, datetime(2026, 11, 19, 13, 0, tzinfo=timezone.utc), NOW)[0] is False
    assert dc.parity_verdict(1246, 1245, None, NOW)[0] is False
    assert dc.parity_verdict(None, 1245, None, NOW)[0] is False


def test_agent_search_is_judged_against_the_current_snapshot():
    assert dc.agent_verdict(QUIET_DATA, QUIET_DATA, NOW)[0] is True  # quiet data, search built from it
    assert dc.agent_verdict(QUIET_DATA, "2026-11-19T15:30:00Z", NOW)[0] is None   # new data 0.6 h ago, rebuild pending
    assert dc.agent_verdict(QUIET_DATA, "2026-11-19T13:00:00Z", NOW)[0] is False  # new data 3.1 h ago, never rebuilt
    assert dc.agent_verdict(None, QUIET_DATA, NOW)[0] is False
