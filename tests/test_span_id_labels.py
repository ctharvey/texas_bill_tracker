"""Span IDs the model writes with their source label ("[P002S001; paragraph 2]") are read as the bare ID."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import classify_bill as classification  # noqa: E402
import extract_bill as detailed  # noqa: E402

MARKDOWN = ("# H.B. No. 1 - Introduced\n\n### SECTION 1.\n\n"
            "<ins>The commission shall publish maps.</ins>\n\n<ins>The board shall report yearly.</ins>\n")


def response(result: dict) -> dict:
    return {"model": classification.MODEL, "service_tier": "flex", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(result)}]}],
            "usage": {"input_tokens": 1000, "output_tokens": 100}}


def labelled_result(span: str) -> dict:
    evidence = [{"span_id": span, "quote": "The commission shall publish maps."}]
    return {"bill_id": "HB1", "summary": {"text": "Requires maps.", "evidence": evidence},
            "policy_tags": [], "agencies": [],
            "all_state_agencies_scope": {"applies": False, "basis": "not_applicable",
                                         "explanation": "None.", "evidence": []},
            "locations": [], "affected_groups": [],
            "major_effects": [{"effect": "reporting", "label": "Maps", "explanation": "Maps.",
                               "evidence": evidence}],
            "uncertainties": [{"question": "Which commission?", "affected_claims": ["summary"],
                               "span_ids": [span, "[P003S001; paragraph 3]"], "needed_source": None}]}


class SpanLabelTests(unittest.TestCase):
    def setUp(self):
        self.doc = detailed.document_from_markdown("HB1", "90R", "introduced", MARKDOWN)
        self.target = next(k for k, s in self.doc["spans"].items() if "publish maps" in s["text"])

    def test_labelled_forms_become_the_bare_id(self):
        page = self.doc["spans"][self.target]["page"]
        for written in (f"[{self.target}; paragraph {page}]", f"[{self.target}; paragraph", f"[{self.target}]",
                        f"[{self.target}; PDF page 1]", f" [{self.target}] "):
            with self.subTest(written=written):
                out = detailed.normalize_span_ids({"evidence": [{"span_id": written}], "span_ids": [written]},
                                                  self.doc)
                self.assertEqual(out, {"evidence": [{"span_id": self.target}], "span_ids": [self.target]})

    def test_unknown_or_other_ids_are_left_for_validation(self):
        for written in ("[P999S001; paragraph 999]", "D_WA16_BOARD", "P999S001", "paragraph 2", "",
                        f"x[{self.target}]"):
            with self.subTest(written=written):
                out = detailed.normalize_span_ids({"span_id": written, "span_ids": [written]}, self.doc)
                self.assertEqual(out, {"span_id": written, "span_ids": [written]})

    def test_labelled_response_validates_like_a_clean_one(self):
        page = self.doc["spans"][self.target]["page"]
        registry = detailed.load_registry()
        with tempfile.TemporaryDirectory() as directory:
            report = classification.classify(
                self.doc, registry, Path(directory), execute=True,
                sender=lambda _: response(labelled_result(f"[{self.target}; paragraph {page}")))
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["citation_counts"]["relocated"], 0)
        self.assertEqual(report["result"]["summary"]["evidence"][0]["span_id"], self.target)
        self.assertEqual(report["result"]["uncertainties"][0]["span_ids"][0], self.target)

    def test_a_still_unknown_span_is_reported(self):
        result = labelled_result(self.target)
        result["uncertainties"][0]["span_ids"] = ["[P999S001; paragraph 999]"]
        with tempfile.TemporaryDirectory() as directory:
            report = classification.classify(self.doc, detailed.load_registry(), Path(directory), execute=True,
                                             sender=lambda _: response(result))
        self.assertIn("Question cites an unknown bill span", report["errors"])

    def test_markdown_label_is_the_bare_id(self):
        user = classification.build_request(self.doc, detailed.load_registry())["input"][1]["content"][0]["text"]
        self.assertIn(f"[{self.target}]\n<ins>The commission shall publish maps.</ins>", user)
        self.assertNotIn("; paragraph", user)


if __name__ == "__main__":
    unittest.main()
