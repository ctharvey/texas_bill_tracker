import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_feeds  # noqa: E402
import classify_bill as classification  # noqa: E402
import extract_bill as detailed  # noqa: E402
import law_context  # noqa: E402

# Shapes taken from real 89R/90R bills: HB1094 (repealer list, unqualified chapters in an amended section),
# HB829 (subchapter repeal citing a session-law chapter), HB1093 (subchapter named after the chapter),
# SB309 (several subchapters), HB126 (a mixed repealer list naming each code).
BILL = """### SECTION 1.

Section 403.606, Government Code, is amended to read as follows:

Sec. 403.606. CERTAIN PERSONS INELIGIBLE. A company listed under Chapter 808, 809, 2270, <del>2271,</del> or 2275 is not eligible.

### SECTION 2.

The following chapters of the Government Code are repealed:

(1) Chapter 2271;

(2) Chapter 2274; and

(3) Chapter 2276.

### SECTION 3.

Subchapter T, Chapter 403, Government Code, as added by Chapter 377 (H.B. 5), Acts of the 88th Legislature, Regular Session, 2023, is repealed.

### SECTION 4.

Texas Education Code, Chapter 29, Subchapter J, is repealed.

### SECTION 5.

The following provisions are repealed:

(1) Subchapters C and D, Chapter 559, Insurance Code;

(2) Chapter 802, Occupations Code;

(3) Section 2271.002, Government Code.
"""


class BillChapterTests(unittest.TestCase):
    def test_whole_chapter_repeals_parts_and_references(self):
        found = build_feeds.bill_chapters(BILL)
        self.assertEqual({k: v for k, v in found.items() if v == "repeal"},
                         {"GV 2271": "repeal", "GV 2274": "repeal", "GV 2276": "repeal", "OC 802": "repeal"})
        self.assertEqual(found["GV 808"], "cited")   # unqualified chapter in a Government Code section
        self.assertEqual(found["GV 2275"], "cited")
        self.assertEqual(found["GV 403"], "amend")   # only Subchapter T goes
        self.assertEqual(found["ED 29"], "amend")    # only Subchapter J goes
        self.assertEqual(found["IN 559"], "amend")   # Subchapters C and D
        self.assertNotIn("GV 377", found)            # a session-law chapter, not a code chapter

    def test_section_index_is_unchanged_by_chapter_parsing(self):
        sections, _ = build_feeds.bill_statutes(BILL)
        self.assertEqual({k: v["kind"] for k, v in sections.items()}, {"GV 403.606": "amend", "GV 2271.002": "repeal"})


def write_law(root: Path) -> Path:
    law = root / "law"
    (law / "GV").mkdir(parents=True)
    chapters = {
        "2271": ("CHAPTER 2271. PROHIBITION ON CONTRACTS WITH COMPANIES BOYCOTTING ISRAEL",
                 [("2271.001", "DEFINITIONS.", 'In this chapter: (1) "Boycott Israel" has the meaning assigned by '
                   "Section 808.001."),
                  ("2271.002", "PROVISION REQUIRED IN CONTRACT.", "A governmental entity may not enter into a "
                   "contract with a company for goods or services unless the contract contains a written "
                   "verification from the company that it does not boycott Israel. " + "More words. " * 300)]),
        "403": ("CHAPTER 403. COMPTROLLER OF PUBLIC ACCOUNTS",
                [("403.606", "CERTAIN PERSONS INELIGIBLE.", "A person is not eligible to submit an application.")]),
    }
    entries = {}
    for number, (heading, sections) in chapters.items():
        body = f"# Government Code, {heading}\n\n{heading}\n\n" + "".join(
            f"## Sec. {sid}. {title} {text}\n\n" for sid, title, text in sections)
        (law / "GV" / f"{number}.md").write_text(body, "utf-8")
        entries[number] = {"heading": heading, "file": f"GV/{number}.md", "sha256": "a" * 64,
                           "sections": [[sid, f"Sec. {sid}. {title}"] for sid, title, _ in sections]}
    (law / "GV" / "index.json").write_text(json.dumps({"code": "GV", "chapters": entries}), "utf-8")
    (law / "index.json").write_text(json.dumps({"codes": {"GV": {"name": "Government Code"}}}), "utf-8")
    return law


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.law = write_law(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_headings_then_section_text_with_ids(self):
        items = law_context.build(BILL, self.law)
        self.assertEqual([i["id"] for i in items], [f"L_{n}" for n in range(1, len(items) + 1)])
        repealed = next(i for i in items if i["kind"] == "chapter" and i["chapter"] == "2271")
        self.assertEqual(repealed["action"], "repeal")
        self.assertIn("BOYCOTTING ISRAEL", repealed["text"])
        self.assertIn("Sec. 2271.002. PROVISION REQUIRED IN CONTRACT.", repealed["text"])
        self.assertEqual(repealed["source_url"], "https://statutes.capitol.texas.gov/Docs/GV/htm/GV.2271.htm")
        texts = {i["section"]: i for i in items if i["kind"] == "section"}
        self.assertEqual(texts["Government Code Section 403.606"]["action"], "amend")
        self.assertEqual(texts["Government Code Section 2271.002"]["action"], "repeal")  # named, so not "with_chapter"
        self.assertTrue(texts["Government Code Section 2271.002"]["trimmed"])
        self.assertLessEqual(len(texts["Government Code Section 2271.002"]["text"]), law_context.SECTION_TEXT_MAX)
        self.assertEqual(texts["Government Code Section 2271.001"]["action"], "repeal_with_chapter")
        self.assertFalse(any(i["kind"] == "chapter" and i["chapter"] in ("2274", "2276") for i in items))  # not in copy
        self.assertLess(items.index(repealed), items.index(texts["Government Code Section 403.606"]))

    def test_text_budget_drops_sections_but_keeps_headings(self):
        with patch.object(law_context, "BILL_TEXT_MAX", 100):
            items = law_context.build(BILL, self.law)
        self.assertTrue(any(i["kind"] == "chapter" for i in items))
        self.assertLessEqual(sum(len(i["text"]) for i in items if i["kind"] == "section"), 100)


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.doc = detailed.document_from_pages("HB1", "90R", "introduced", ["The commission shall publish maps."])
        self.registry = detailed.load_registry()

    def test_no_law_context_leaves_the_request_unchanged(self):
        plain = classification.build_request(self.doc, self.registry)
        empty = classification.build_request({**self.doc, "law_context": []}, self.registry)
        self.assertEqual(plain, empty)
        self.assertNotIn("CURRENT TEXAS LAW", json.dumps(plain))

    def test_law_items_follow_the_shared_prefix_and_change_the_key(self):
        items = [{"id": "L_1", "section": "Government Code, Chapter 2271", "action": "repeal",
                  "text": "CHAPTER 2271. PROHIBITION ON CONTRACTS", "law_sha256": "a" * 64, "source_url": "u"}]
        plain = classification.build_request(self.doc, self.registry, 1)
        law = classification.build_request({**self.doc, "law_context": items}, self.registry, 1)
        self.assertEqual(plain["input"][0], law["input"][0])  # shared prompt-cache prefix untouched
        text = law["input"][1]["content"][0]["text"]
        self.assertIn("CHAPTER 2271. PROHIBITION ON CONTRACTS", text)
        self.assertNotIn("law_sha256", text)
        self.assertLess(text.index("CURRENT TEXAS LAW"), text.index("RETRY 1"))
        self.assertTrue(text.startswith(plain["input"][1]["content"][0]["text"].split("\nRETRY 1")[0]))


@unittest.skipUnless(importlib.util.find_spec("jsonschema"), "Optional schema dependency")
class ValidationTests(unittest.TestCase):
    def test_law_quotes_must_be_verbatim(self):
        doc = detailed.document_from_pages("HB1", "90R", "introduced", ["The commission shall publish maps."])
        doc["law_context"] = [{"id": "L_1", "section": "Government Code, Chapter 2271", "action": "repeal",
                               "text": "CHAPTER 2271. PROHIBITION ON CONTRACTS WITH COMPANIES BOYCOTTING ISRAEL",
                               "source_url": "https://statutes.capitol.texas.gov/Docs/GV/htm/GV.2271.htm"}]
        registry = detailed.load_registry()
        schema = classification.build_request(doc, registry)["text"]["format"]["schema"]
        evidence = [{"span_id": "P001S001", "quote": "publish maps"},
                    {"span_id": "L_1", "quote": "PROHIBITION ON CONTRACTS WITH COMPANIES BOYCOTTING ISRAEL"}]
        value = {"bill_id": "HB1", "summary": {"text": "Ends the contract rule.", "evidence": evidence},
                 "policy_tags": [], "agencies": [], "locations": [], "affected_groups": [], "major_effects": [],
                 "all_state_agencies_scope": {"applies": False, "basis": "not_applicable",
                                              "explanation": "None.", "evidence": []}, "uncertainties": []}
        checked = classification.validate_result(value, doc, registry, schema, "f" * 64)
        self.assertEqual(checked["errors"], [])
        law = [c for c in checked["verified_citations"] if c["requested_span_id"] == "L_1"][0]
        self.assertEqual((law["status"], law["source_type"]), ("resolved", "current_law"))
        bad = copy.deepcopy(value)
        bad["summary"]["evidence"][1]["quote"] = "PROHIBITION ON ALL CONTRACTS"
        self.assertTrue(classification.validate_result(bad, doc, registry, schema, "f" * 64)["errors"])
        del doc["law_context"]  # the same citation without the item sent is never accepted
        self.assertTrue(classification.validate_result(value, doc, registry, schema, "f" * 64)["errors"])


class PipelineAttachTests(unittest.TestCase):
    def setUp(self):
        import review_pipeline
        self.rp = review_pipeline
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.law = write_law(root)
        self.md = root / "I.md"
        self.md.write_text(BILL, "utf-8")
        self.doc = detailed.document_from_pages("HB1", "90R", "introduced", ["text"])

    def tearDown(self):
        self.tmp.cleanup()

    def stored(self, text_hash, items=None):
        document = {"text_hash": text_hash, **({"law_context": items} if items else {})}
        return {"document": document, "result": {}}

    def test_new_text_with_flag_gets_fresh_items(self):
        self.rp.attach_law_context(self.doc, None, self.md, self.law)
        self.assertTrue(self.doc["law_context"])
        other = detailed.document_from_pages("HB1", "90R", "introduced", ["text"])
        self.rp.attach_law_context(other, self.stored("old-text"), self.md, self.law)
        self.assertEqual(other["law_context"], self.doc["law_context"])

    def test_without_flag_nothing_is_attached(self):
        self.rp.attach_law_context(self.doc, None, self.md, None)
        self.assertNotIn("law_context", self.doc)

    def test_reviewed_text_keeps_exactly_what_it_was_sent(self):
        sent = [{"id": "L_1", "section": "s", "action": "repeal", "text": "law as it was", "source_url": "u"}]
        missing = Path(self.tmp.name) / "no-law-here"  # a changed or missing law copy is never read
        self.rp.attach_law_context(self.doc, self.stored(self.doc["text_hash"], sent), self.md, missing)
        self.assertEqual(self.doc["law_context"], sent)
        plain = detailed.document_from_pages("HB1", "90R", "introduced", ["text"])
        self.rp.attach_law_context(plain, self.stored(plain["text_hash"]), self.md, self.law)
        self.assertNotIn("law_context", plain)  # reviewed without law: its cached request stays as answered

    def test_quiet_and_progress_checks_rebuild_the_answered_request(self):
        sent = [{"id": "L_1", "section": "s", "action": "repeal", "text": "law as it was", "source_url": "u"}]
        registry = detailed.load_registry()
        answered = classification.build_request({**self.doc, "law_context": sent}, registry)
        fresh = detailed.document_from_pages("HB1", "90R", "introduced", ["text"])
        self.assertTrue(self.rp.reuse_law_context(fresh, self.stored(fresh["text_hash"], sent)))
        self.assertEqual(classification.build_request(fresh, registry), answered)

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "Optional schema dependency")
    def test_identical_companion_reuses_a_review_that_cites_law(self):
        registry = detailed.load_registry()
        law = [{"id": "L_1", "section": "Government Code, Chapter 2271", "action": "repeal",
                "text": "CHAPTER 2271. PROHIBITION ON CONTRACTS WITH COMPANIES BOYCOTTING ISRAEL", "source_url": "u"}]
        body = "The commission shall publish maps. " + "Each map shows every district line in the state. " * 6
        donor_doc = detailed.document_from_pages("HB1", "90R", "introduced", ["H.B. No. 1 " + body])
        donor_doc["law_context"] = law
        mine = detailed.document_from_pages("HB2", "90R", "introduced", ["H.B. No. 2 " + body])
        evidence = [{"span_id": "P001S001", "quote": "publish maps"},
                    {"span_id": "L_1", "quote": "BOYCOTTING ISRAEL"}]
        result = {"bill_id": "HB1", "summary": {"text": "Ends a rule.", "evidence": evidence}, "policy_tags": [],
                  "agencies": [], "locations": [], "affected_groups": [], "major_effects": [], "uncertainties": [],
                  "all_state_agencies_scope": {"applies": False, "basis": "not_applicable", "explanation": "None.",
                                               "evidence": []}}
        schema = classification.build_request(donor_doc, registry)["text"]["format"]["schema"]
        validation = classification.validate_result(result, donor_doc, registry, schema, "f" * 64)
        self.assertEqual(validation["errors"], [])
        cache = Path(self.tmp.name) / "cache"
        (cache / "reviews").mkdir(parents=True)
        (cache / "reviews" / "HB1.json").write_text(json.dumps({
            "bill_id": "HB1", "document": donor_doc, "result": result, "validation": validation,
            "first_pass_request_key": "f" * 64, "status": "ready_for_review"}), "utf-8")
        reused = self.rp.reuse_companion_review("HB2", mine, [{"id": "HB1", "relation": "Identical"}], cache, registry)
        self.assertIsNotNone(reused)
        self.assertEqual(reused["document"]["law_context"], law)
        self.assertNotIn("law_context", mine)  # the caller's document is not changed

    def test_unreadable_law_copy_reviews_without_context(self):
        self.rp.attach_law_context(self.doc, None, self.md, Path(self.tmp.name) / "absent")
        self.assertNotIn("law_context", self.doc)


if __name__ == "__main__":
    unittest.main()
