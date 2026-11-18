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


XML = ('<billhistory bill="90(R) HB 1160"><lastaction>11/16/2026 H Filed</lastaction>'
       '<caption version="Introduced">Relating to roads &amp; bridges.</caption><authors>Plesa | Bhojani</authors>'
       '<coauthors /></billhistory>')
BILL = {"id": "HB1160", "number": "HB 1160", "caption": "Relating to roads & bridges.", "authors": ["Plesa", "Bhojani"],
        "last_action": "11/16/2026 H Filed", "subjects": ["Roads (I0001)"]}
MEMBERS = {"house|Plesa": {}, "house|Bhojani": {}}
TAG = {"summary": "Adds a rule.", "policy_tags": ["Transportation"]}


def findings(**over):
    args = dict(bill=BILL, official=dc.official_record(XML), members=MEMBERS, tag=TAG, luna_failed=None,
                text_state="ok", agent_ok=True, search_ok=True)
    args.update(over)
    return dc.bill_findings(**args)


def levels(found):
    return sorted({level for level, _ in found})


def test_official_record_reads_the_history_file():
    assert dc.official_record(XML) == {"caption": "Relating to roads & bridges.", "authors": ["Plesa", "Bhojani"],
                                       "last_action": "11/16/2026 H Filed"}


def test_a_bill_with_everything_passes():
    assert findings() == []
    assert dc.verdict(findings())[0] is True


def test_waiting_for_text_or_review_is_a_warning_not_a_failure():
    assert levels(findings(text_state="none", tag=None)) == ["warn"]
    assert levels(findings(text_state="placeholder", tag=None)) == ["warn"]
    assert levels(findings(tag=None)) == ["warn"]  # Text posted, Luna not there yet.
    assert levels(findings(bill={**BILL, "subjects": []})) == ["warn"]
    assert dc.verdict(findings(tag=None))[0] is None


def test_each_missing_part_fails():
    assert levels(findings(official=None)) == ["fail"]
    assert levels(findings(bill={**BILL, "caption": "Relating to roads."})) == ["fail"]
    assert levels(findings(bill={**BILL, "authors": ["Plesa"]})) == ["fail"]
    assert levels(findings(members={"house|Plesa": {}})) == ["fail"]  # An author the roster does not know.
    assert levels(findings(members={"senate|Plesa": {}, "senate|Bhojani": {}})) == ["fail"]  # Wrong chamber.
    assert levels(findings(tag={"summary": "", "policy_tags": []})) == ["fail"]
    assert levels(findings(tag=None, luna_failed="download")) == ["fail"]  # Readable text, but Luna failed it.
    assert levels(findings(agent_ok=False)) == ["fail"]
    assert levels(findings(search_ok=False)) == ["fail"]
    assert dc.verdict(findings(agent_ok=False, text_state="none"))[0] is False


def test_a_bill_newer_than_the_agent_build_only_warns_about_the_agent_edition():
    assert levels(findings(agent_ok=False, search_ok=False, agent_behind=True)) == ["warn"]
    assert levels(findings(agent_ok=False, search_ok=False)) == ["fail"]


def test_text_posted_after_the_data_run_is_a_wait_not_a_luna_failure():
    assert levels(findings(tag=None, luna_failed="download", text_is_new=True)) == ["warn"]
    assert levels(findings(tag=None, luna_failed="download")) == ["fail"]


def test_ftp_listing_times_read_as_texas_time():
    assert dc.ftp_time("11-16-26  03:32PM                13580 HB01184I.htm") == datetime(2026, 11, 16, 21, 32, tzinfo=timezone.utc)
    assert dc.ftp_time("not a listing") is None


def test_purge_state_passes_warns_while_pending_and_fails_when_stuck():
    ok = {"files": {}, "purged_at": "2026-11-16T21:17:30Z", "pending_since": None, "status": "3 prefixes purged"}
    assert dc.purge_verdict(ok, NOW)[0] is True
    assert dc.purge_verdict({**ok, "pending_since": "2026-11-16T21:17:30Z"}, NOW)[0] is None
    stuck = dc.purge_verdict({**ok, "pending_since": "2026-11-16T18:17:30Z"}, NOW)
    assert stuck[0] is False and "pending 3.7 h" in stuck[1]
    assert dc.purge_verdict(None, NOW)[0] is None
