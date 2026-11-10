import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import classify_bill as classification
import extract_bill as detailed
from extraction_cache import ResponseCache


def result():
    evidence = [{"span_id": "P001S001", "quote": "publish maps"}]
    return {"bill_id": "HB1", "summary": {"text": "Requires publication of maps.", "evidence": evidence},
            "policy_tags": [{"tag": "Government operations", "explanation": "Publication duty.",
                             "evidence": evidence}], "agencies": [],
            "all_state_agencies_scope": {"applies": False, "basis": "not_applicable",
                                         "explanation": "No agency-wide scope.", "evidence": []},
            "locations": [], "affected_groups": [], "major_effects": [], "uncertainties": []}


class RequestTests(unittest.TestCase):
    def test_luna_uses_full_source_shared_prefix_and_distinct_cache_key(self):
        registry = detailed.load_registry()
        a = detailed.document_from_pages("HB1", "90R", "introduced", ["First page", "Final page"])
        b = detailed.document_from_pages("HB2", "90R", "introduced", ["Another bill"])
        first, second = [classification.build_request(d, registry) for d in (a, b)]
        self.assertEqual(first["model"], "gpt-6-luna")
        self.assertEqual(first["service_tier"], "flex")
        self.assertEqual(first["input"][0], second["input"][0])
        self.assertIn("Final page", first["input"][1]["content"][0]["text"])
        self.assertIn("Data centers", classification.load_policy_tags())
        self.assertNotEqual(ResponseCache.key(first), ResponseCache.key(detailed.build_request(a, registry)))
        changed = classification.build_request({**a, "authors": ["Changed"], "status": "Filed"}, registry)
        self.assertEqual(ResponseCache.key(first), ResponseCache.key(changed))
        self.assertNotIn("obligations", first["text"]["format"]["schema"]["properties"])

    def test_policy_reader_fails_when_declaration_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "taxonomy.js"
            path.write_text("export const POLICY_AREAS = [\n{label:'New syntax'}\n];", encoding="utf-8")
            with self.assertRaises(ValueError): classification.load_policy_tags(path)


@unittest.skipUnless(importlib.util.find_spec("jsonschema"), "Optional schema dependency")
class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.doc = detailed.document_from_pages("HB1", "90R", "introduced", ["The commission shall publish maps."])
        self.registry = detailed.load_registry()
        self.schema = classification.build_request(self.doc, self.registry)["text"]["format"]["schema"]

    def validate(self, value):
        return classification.validate_result(value, self.doc, self.registry, self.schema, "f" * 64)

    def test_excerpts_and_canonical_tags_are_verified(self):
        import jsonschema
        self.assertEqual(self.validate(result())["errors"], [])
        value = result(); value["summary"]["evidence"][0]["quote"] = "invented sentence"
        self.assertTrue(self.validate(value)["errors"])
        value = result(); value["policy_tags"][0]["tag"] = "Invented policy"
        with self.assertRaises(jsonschema.ValidationError): self.validate(value)

    def test_scope_is_separate_and_inferences_stay_visible(self):
        value = result()
        value["agencies"] = [{"registry_id": "all-state-agencies", "name": "All state agencies",
                              "impact": "direct", "explanation": "General scope",
                              "evidence": value["summary"]["evidence"]}]
        self.assertTrue(self.validate(value)["errors"])
        value["agencies"][0].update(registry_id=None, name="Board", impact="inferred")
        checked = self.validate(value)
        self.assertEqual(checked["errors"], [])
        self.assertIn("Unresolved agency identity: Board", checked["review_reasons"])
        self.assertIn("Inferred agency impact: Board", checked["review_reasons"])
        value["all_state_agencies_scope"]["applies"] = True
        self.assertTrue(self.validate(value)["errors"])

    def test_distinct_effects_can_share_a_category(self):
        value = result()
        value["major_effects"] = [
            {"effect": "other", "label": label, "explanation": "Distinct organizing effect.",
             "evidence": value["summary"]["evidence"]} for label in ("Disclosure", "Participation")]
        self.assertEqual(self.validate(value)["errors"], [])
        value["major_effects"][1]["label"] = "Disclosure"
        self.assertTrue(self.validate(value)["errors"])

    def test_replay_cost_and_default_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            prepared = classification.classify(self.doc, self.registry, cache,
                                               sender=lambda _: self.fail("No authorization"))
            self.assertEqual(prepared["action"], "not_submitted")
            raw = {"model": classification.MODEL, "service_tier": "flex", "status": "completed",
                   "output": [{"type": "message", "content": [{"type": "output_text",
                                                               "text": json.dumps(result())}]}],
                   "usage": {"input_tokens": 1000, "output_tokens": 100, "input_tokens_details": {
                       "cached_tokens": 200, "cache_write_tokens": 300,
                       "cache_write_tokens_details": {"ttl_30m_tokens": 100, "ttl_12h_tokens": 200}}}}
            first = classification.classify(self.doc, self.registry, cache, execute=True, sender=lambda _: raw)
            self.assertEqual(first["errors"], [])
            expected = (500 * .05 + 200 * .005 + 100 * .0625 + 200 * .125 + 100 * .25) / 1e6
            self.assertAlmostEqual(first["new_api_cost_estimate"][0], expected)
            with patch.object(detailed, "send_request", side_effect=AssertionError("No provider call")):
                replay = classification.classify(self.doc, self.registry, cache, execute=True)
            self.assertTrue(replay["cache_hit"])
            self.assertEqual(replay["new_api_cost_estimate"], [0, 0])
            self.assertFalse(replay["publishable"])


if __name__ == "__main__":
    unittest.main()
