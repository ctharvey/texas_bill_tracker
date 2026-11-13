import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import classify_bill as classification
import extract_bill as detailed
import review_stages as stages
from extraction_cache import ResponseCache

OLD_MD = "# HB 1\n\nThe commission shall publish maps.\n\nThe department shall file a quarterly report.\n"
NEW_MD = "# HB 1\n\nThe commission shall publish maps.\n\nThe board shall audit each permit annually.\n"
PINNED_STAGE1_KEY = "f120ecc1d84920d994944b83220486e907c590f5e8fbce94bf3e9e7fcc7ad812"


def evidence(quote="The commission shall publish maps.", span="P002S001"):
    return [{"span_id": span, "quote": quote}]


def stage1_result():
    ev = evidence()
    return {"bill_id": "HB1", "summary": {"text": "Requires publication of maps.", "evidence": ev},
            "policy_tags": [{"tag": "Government operations", "explanation": "Publication duty.", "evidence": ev}],
            "agencies": [], "all_state_agencies_scope": {"applies": False, "basis": "not_applicable",
                                                          "explanation": "None.", "evidence": []},
            "locations": [], "affected_groups": [], "major_effects": [], "uncertainties": []}


def raw_for(value, model=classification.MODEL):
    return {"model": model, "service_tier": "flex", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}],
            "usage": {"input_tokens": 1000, "output_tokens": 100}}


def doc(markdown, version="introduced"):
    document = detailed.document_from_markdown("HB1", "90R", version, markdown)
    document["text_sha256"] = hashlib.sha256(markdown.encode()).hexdigest()
    return document


def bundle_for(document, key="k1"):
    return {"bill_id": "HB1", "document": document, "result": stage1_result(), "first_pass_request_key": key}


INDEX = {"versions": [{"code": "I", "sha256": "a"}, {"code": "H", "sha256": "b"}]}


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.doc = doc(OLD_MD)
        self.doc["text_sha256"] = "a"
        self.bundle = bundle_for(self.doc)

    def plan(self, bundle="default", index=INDEX, docs=None, record=None):
        return stages.stage_plan(self.bundle if bundle == "default" else bundle, index, docs, record)

    def test_table(self):
        plan = self.plan(bundle=None)
        self.assertEqual((plan["review"], plan["code"], plan["reason"]), ("first", "H", "new_bill"))
        self.assertEqual(self.plan(bundle=None, index=None)["code"], "I")
        plan = self.plan()
        self.assertEqual((plan["review"], plan["code"], plan["reason"], plan["from_code"]),
                         ("update", "H", "new_version", "I"))
        same = {"versions": [{"code": "I", "sha256": "a"}]}
        self.assertEqual(self.plan(index=same)["review"], "revisit")
        changed = {"versions": [{"code": "I", "sha256": "z"}]}
        plan = self.plan(index=changed)
        self.assertEqual((plan["review"], plan["code"], plan["reason"], plan["from_code"]),
                         ("update", "I", "text_revised", "I"))
        plan = self.plan(index=None)
        self.assertEqual((plan["review"], plan["code"]), ("revisit", "I"))

    def test_fiscal_due_and_staleness(self):
        same = {"versions": [{"code": "I", "sha256": "a"}]}
        docs_index = {"documents": [
            {"type": "fiscal_note", "code": "I", "name": "FN", "path": "fiscal_note-I.md", "sha256": "f1"},
            {"type": "fiscal_note", "code": "H", "name": "FN", "path": "fiscal_note-H.md", "sha256": "f2"}]}
        self.assertFalse(self.plan(index=same, docs={"documents": []})["fiscal_due"])
        self.assertTrue(self.plan(index=same, docs=docs_index)["fiscal_due"])
        docs = stages.fiscal_documents_for(docs_index, "I")
        record = {"binding": stages.fiscal_binding(self.bundle, docs)}
        self.assertFalse(self.plan(index=same, docs=docs_index, record=record)["fiscal_due"])
        self.bundle["first_pass_request_key"] = "k2"
        self.assertTrue(self.plan(index=same, docs=docs_index, record=record)["fiscal_due"])

    def test_latest_version(self):
        self.assertEqual(stages.latest_version(INDEX)["code"], "H")
        for bad in (None, {}, {"versions": []}, {"versions": "x"}, {"versions": [1]}, {"versions": [{}]}):
            self.assertIsNone(stages.latest_version(bad))

    def test_previous_for_update_is_canonical(self):
        self.bundle["result"]["uncertainties"] = ["x"]
        first = stages.previous_for_update(self.bundle)
        self.assertNotIn("span_id", json.dumps(first))
        self.assertNotIn("uncertainties", first["result"])
        self.assertNotIn("bill_id", first["result"])
        self.assertEqual(first["version"], "I")
        shuffled = copy.deepcopy(self.bundle)
        shuffled["result"] = {k: shuffled["result"][k] for k in reversed(list(shuffled["result"]))}
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(stages.previous_for_update(shuffled), sort_keys=True))
        self.assertEqual(first, stages.previous_for_update(self.bundle))


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.registry = detailed.load_registry()
        self.old, self.new = doc(OLD_MD), doc(NEW_MD, "H")

    def test_stage_one_request_key_is_pinned(self):
        key = ResponseCache.key(classification.build_request(doc(OLD_MD), self.registry))
        self.assertEqual(key, PINNED_STAGE1_KEY)

    def test_update_request_does_not_touch_stage_one(self):
        before = ResponseCache.key(classification.build_request(self.new, self.registry))
        previous = stages.previous_for_update(bundle_for(self.old))
        request = stages.build_version_update_request(self.new, self.registry, previous, "diff")
        after = ResponseCache.key(classification.build_request(self.new, self.registry))
        self.assertEqual(before, after)
        self.assertNotEqual(before, ResponseCache.key(request))
        self.assertIn("changes", request["text"]["format"]["schema"]["required"])
        self.assertEqual(request["text"]["format"]["name"], "texas_bill_version_update_v1")
        self.assertIn("PARAGRAPH DIFF", request["input"][1]["content"][0]["text"])
        self.assertNotIn("changes", classification.build_request(self.new, self.registry)["text"]["format"]["schema"]["properties"])

    def test_paragraph_diff_is_deterministic_and_capped(self):
        diff = stages.paragraph_diff(OLD_MD, NEW_MD)
        self.assertIn("-The department shall file a quarterly report.", diff)
        self.assertIn("+The board shall audit each permit annually.", diff)
        self.assertEqual(diff, stages.paragraph_diff(OLD_MD, NEW_MD))
        self.assertTrue(stages.paragraph_diff(OLD_MD, NEW_MD, 20).endswith("\n[diff truncated]"))


class VersionUpdateTests(unittest.TestCase):
    def setUp(self):
        self.registry = detailed.load_registry()
        self.old, self.new = doc(OLD_MD), doc(NEW_MD, "H")
        self.previous = stages.previous_for_update(bundle_for(self.old))

    def response(self):
        value = stage1_result()
        value["changes"] = [
            {"kind": "added", "label": "Audit duty", "explanation": "New audits.",
             "evidence": evidence("The board shall audit each permit annually.", "P003S001")},
            {"kind": "removed", "label": "Report", "explanation": "Report dropped.",
             "evidence": evidence("The department shall file a quarterly report.", "P003S001")},
            {"kind": "altered", "label": "Invented", "explanation": "Not real.",
             "evidence": evidence("Nothing like this exists.", "P003S001")}]
        return value

    def test_end_to_end_and_cache_hit(self):
        calls = []

        def sender(request):
            calls.append(request)
            return raw_for(self.response())

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            args = (self.new, self.old, self.previous, self.registry, cache)
            report = stages.version_update(*args, execute=True, sender=sender)
            self.assertNotIn("changes", report["result"])
            self.assertEqual([c["verified"] for c in report["changes"]], [True, True, False])
            self.assertEqual(report["errors"], ["Unresolved change excerpt: Invented"])
            self.assertEqual(report["status"], "needs_review")
            self.assertTrue(report["audit_recommended"])
            self.assertIn("verified_citations", report)
            self.assertTrue(report["verified_citations"])
            again = stages.version_update(*args, execute=True, sender=sender)
            self.assertTrue(again["cache_hit"])
            self.assertEqual(len(calls), 1)


class FiscalTests(unittest.TestCase):
    def setUp(self):
        self.registry = detailed.load_registry()
        self.agency = next(a for a in self.registry if a["id"] != "all-state-agencies")
        self.old = doc(OLD_MD)
        self.bundle = bundle_for(self.old)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.history = Path(self.tmp.name) / "history"
        (self.history / "HB1").mkdir(parents=True)
        self.fn = "### Fiscal Implications\n\nThe\nbill would cost the state $1 million.\n".encode()
        self.an = "Bill analysis text here.\n".encode()
        self.write({"fiscal_note-I.md": self.fn, "analysis-I.md": self.an})

    def write(self, files, tamper=None, path=None):
        entries = []
        for (name, data), kind in zip(files.items(), ("fiscal_note", "analysis")):
            (self.history / "HB1" / name).write_bytes(data)
            entries.append({"type": kind, "code": "I", "name": "Doc " + kind, "path": path or name,
                            "sha256": tamper or hashlib.sha256(data).hexdigest()})
        (self.history / "HB1" / "documents.json").write_text(
            json.dumps({"format": "texas-bill-documents-v1", "bill": "HB1", "documents": entries}), "utf-8")

    def test_load_documents(self):
        docs = stages.load_fiscal_documents("HB1", self.history, "I")
        self.assertEqual([d["id"] for d in docs], ["A1", "F1"])
        self.assertEqual(stages.load_fiscal_documents("HB1", self.history, "H"), [])
        self.write({"fiscal_note-I.md": self.fn, "analysis-I.md": self.an}, tamper="0" * 64)
        with self.assertRaises(ValueError):
            stages.load_fiscal_documents("HB1", self.history, "I")
        self.write({"fiscal_note-I.md": self.fn, "analysis-I.md": self.an}, path="../secret.md")
        with self.assertRaises(ValueError):
            stages.load_fiscal_documents("HB1", self.history, "I")
        with self.assertRaises(ValueError):
            stages.load_fiscal_documents("../HB1", self.history, "I")

    def test_fiscal_check(self):
        docs = stages.load_fiscal_documents("HB1", self.history, "I")
        fiscal_id = next(d["id"] for d in docs if d["type"] == "fiscal_note")
        good = [{"doc_id": fiscal_id, "quote": "The bill would cost the state $1 million."}]
        bad = [{"doc_id": fiscal_id, "quote": "The bill would cost $9 billion."}]
        value = {"bill_id": "HB1", "fiscal_summary": {"text": "Costs $1 million.", "evidence": good},
                 "agencies": [
                     {"name": self.agency["name"], "registry_id": self.agency["id"], "in_review": False,
                      "fiscal_effect": "Costs.", "evidence": good},
                     {"name": "Wrong Name", "registry_id": self.agency["id"], "in_review": False,
                      "fiscal_effect": "Costs.", "evidence": good},
                     {"name": "Unverified Agency", "registry_id": None, "in_review": False,
                      "fiscal_effect": "Costs.", "evidence": bad}],
                 "disagreements": [{"claim": "summary", "note": "Differs.", "evidence": good},
                                   {"claim": "agencies:0", "note": "Differs.", "evidence": bad}],
                 "no_fiscal_implication": False}
        with tempfile.TemporaryDirectory() as directory:
            report = stages.fiscal_check(self.bundle, docs, self.registry, Path(directory), execute=True,
                                         sender=lambda _: raw_for(value))
        self.assertEqual(report["verified"], {"fiscal_summary": True, "agencies": [True, False, False],
                                              "disagreements": [True, False]})
        self.assertEqual(report["status"], "needs_review")
        self.assertTrue(any("Noncanonical" in e for e in report["errors"]))
        self.assertEqual(report["binding"], stages.fiscal_binding(self.bundle, docs))
        record = {"bill_id": "HB1", "binding": report["binding"], "report": report, "documents": report["documents"]}
        public = stages.public_fiscal(record)
        self.assertEqual(public["format"], "texas-bill-luna-fiscal-v1")
        self.assertEqual(public["text_version"], "I")
        self.assertEqual(public["text_sha256"], self.old["text_sha256"])
        self.assertEqual([a["name"] for a in public["agencies"]], [self.agency["name"]])
        self.assertEqual(len(public["disagreements"]), 1)
        self.assertIn("summary", public)
        self.assertEqual([d["id"] for d in public["documents"]], ["A1", "F1"])
        self.assertIsNone(stages.public_fiscal({"bill_id": "HB1", "binding": report["binding"], "report": {}}))


if __name__ == "__main__":
    unittest.main()
