"""updates.json: what each tags.json publish changed, overall and per bill."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import luna_updates as lu  # noqa: E402

BASE = {"reviewed_at": "2026-11-14T10:00:00Z", "status": "ready_for_review", "text_version": "I", "summary": "Old.",
        "policy_tags": [{"tag": "Education"}], "agencies": [{"id": "tea", "name": "Texas Education Agency"}]}
AGENCY_WIDE = {"applies": True, "explanation": "Every state agency must."}


def kinds(changes):
    return [c["kind"] for c in changes]


class BillChanges(unittest.TestCase):
    def test_a_new_review_and_its_marker(self):
        self.assertEqual(kinds(lu.bill_changes(None, BASE)), ["reviewed"])
        self.assertEqual(kinds(lu.bill_changes(None, {**BASE, "all_state_agencies": AGENCY_WIDE})),
                         ["reviewed", "all_agencies"])

    def test_the_marker_gained_and_lost_and_a_false_marker_is_not_news(self):
        self.assertEqual(kinds(lu.bill_changes(BASE, {**BASE, "all_state_agencies": AGENCY_WIDE})), ["all_agencies"])
        self.assertEqual(kinds(lu.bill_changes({**BASE, "all_state_agencies": AGENCY_WIDE}, BASE)), ["not_all_agencies"])
        self.assertEqual(lu.bill_changes(BASE, {**BASE, "all_state_agencies": {"applies": False}}), [])

    def test_agencies_and_topics_list_what_was_added_and_removed(self):
        new = {**BASE, "agencies": [{"id": "dot", "name": "Texas Department of Transportation"}],
               "policy_tags": [{"tag": "Education"}, {"tag": "Transportation"}]}
        self.assertEqual(lu.bill_changes(BASE, new), [
            {"kind": "agencies", "added": ["Texas Department of Transportation"], "removed": ["Texas Education Agency"]},
            {"kind": "topics", "added": ["Transportation"], "removed": []}])

    def test_a_new_version_covers_its_new_summary_and_a_withdrawn_review_says_so(self):
        self.assertEqual(lu.bill_changes(BASE, {**BASE, "text_version": "E", "summary": "New."}),
                         [{"kind": "new_version", "from": "I", "to": "E"}])
        self.assertEqual(kinds(lu.bill_changes(BASE, {**BASE, "summary": "New."})), ["summary"])
        self.assertEqual(kinds(lu.bill_changes(BASE, None)), ["withdrawn"])

    def test_a_revisit_that_only_moves_the_review_time_is_no_change(self):
        self.assertEqual(lu.bill_changes(BASE, {**BASE, "reviewed_at": "2026-11-14T11:00:00Z"}), [])


class Record(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.out = self.dir / "tags.json"
        self.log = self.dir / "updates.json"

    def tags(self, bills, at="2026-11-14T10:00:00Z"):
        return {"generated_at": at, "bills": bills}

    def test_no_earlier_file_and_no_change_log_nothing(self):
        self.assertEqual(lu.record(self.out, None, self.tags({"HB1": BASE}), "t"), 0)
        self.assertEqual(lu.record(self.out, self.tags({"HB1": BASE}), self.tags({"HB1": BASE}), "t"), 0)
        self.assertFalse(self.log.exists())

    def test_each_publish_adds_its_counts_and_bills_newest_first(self):
        first = self.tags({"HB1": BASE})
        second = self.tags({"HB1": {**BASE, "all_state_agencies": AGENCY_WIDE}, "HB2": BASE}, "2026-11-14T11:00:00Z")
        self.assertEqual(lu.record(self.out, first, second, "2026-11-14T11:00:00Z"), 2)
        third = self.tags({**second["bills"], "HB3": {**BASE, "all_state_agencies": AGENCY_WIDE}})
        lu.record(self.out, second, third, "2026-11-14T12:00:00Z")
        log = json.loads(self.log.read_text("utf-8"))
        self.assertEqual(log["format"], lu.FORMAT)
        self.assertEqual([u["at"] for u in log["updates"]], ["2026-11-14T12:00:00Z", "2026-11-14T11:00:00Z"])
        self.assertEqual(log["updates"][1]["counts"], {"reviewed": 1, "all_agencies": 1})
        self.assertEqual(log["updates"][1]["since"], "2026-11-14T10:00:00Z")
        self.assertEqual(sorted(log["updates"][1]["bills"]), ["HB1", "HB2"])
        self.assertEqual(log["updates"][0]["counts"], {"reviewed": 1, "all_agencies": 1})

    def test_the_log_keeps_only_the_newest_entries(self):
        prev = self.tags({})
        for i in range(lu.KEEP + 5):
            cur = self.tags({f"HB{i}": BASE})
            lu.record(self.out, prev, cur, f"t{i}")
            prev = cur
        updates = json.loads(self.log.read_text("utf-8"))["updates"]
        self.assertEqual(len(updates), lu.KEEP)
        self.assertEqual(updates[0]["at"], f"t{lu.KEEP + 4}")


if __name__ == "__main__":
    unittest.main()
