import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import extract_bill as extraction
from extraction_cache import ResponseCache, UnresolvedCall

HAS_SCHEMA = importlib.util.find_spec("jsonschema") is not None
HAS_OPENAI = importlib.util.find_spec("openai") is not None
SCHEMA = json.loads((ROOT / "scripts/extraction_schema.json").read_text("utf-8"))


def result():
    return {"bill_id": "HB1", "legal_state": "proposed_measure_not_verified_enacted", "entities": [],
            "authority_changes": [], "all_state_agencies_scope": False, "unresolved_identity_notes": [],
            "coverage_notes": [], "timing_rules": [], "unresolved_timing": [], "obligations": [],
            "coverage_limitations": []}


def obligation(**changes):
    value = {"obligation_id": "O1", "actor": {"name": "Commission", "basis": "explicit"},
             "modality": "must", "action": "Publish maps", "condition_or_trigger": None,
             "evidence": [{"span_ids": ["P001S001"]}]}
    return {**value, **changes}


def timing(temporal, constraint="on"):
    return {"rule_id": "T1", "actor": {"name": "Commission", "basis": "explicit"},
            "action": "Act", "constraint": constraint, "temporal": temporal,
            "condition": None, "exception": None, "evidence": [{"span_ids": ["P001S001"]}]}


def response(value, **changes):
    raw = {"model": extraction.MODEL, "service_tier": "flex", "status": "completed",
           "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}],
           "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                     "output_tokens": 50}}
    return {**raw, **changes}


class SourceAndKeyTests(unittest.TestCase):
    def setUp(self):
        self.registry = extraction.load_registry()
        self.doc = extraction.document_from_pages("HB1", "90R", "introduced", ["A full bill. Second clause."])

    def test_registry_uses_the_app_vocabulary_and_scope_stays_separate(self):
        self.assertIn("tsbpa", {a["id"] for a in self.registry})
        request = extraction.build_request(self.doc, self.registry)
        prefix = request["input"][0]["content"][0]["text"]
        vocabulary = json.loads(prefix.split("CANONICAL VOCABULARY (INCOMPLETE):\n")[1])
        self.assertNotIn("all-state-agencies", {a["id"] for a in vocabulary["agencies"]})
        self.assertEqual(vocabulary["scope_markers"][0]["id"], "all-state-agencies")

    def test_all_pages_and_characters_survive_span_generation(self):
        pages = ["An operative clause. " * 150, "A second page with an exception."]
        document = extraction.document_from_pages("HJR31", "90R", "introduced", pages)
        for number, text in enumerate(document["pages"], 1):
            pieces = [s["text"] for s in document["spans"].values() if s["page"] == number]
            self.assertEqual("".join("".join(pieces).split()), "".join(text.split()))
        with self.assertRaises(ValueError):
            extraction.document_from_pages("HB1", "90R", "introduced", ["Valid page", " "])

    def test_whitespace_and_history_metadata_do_not_trigger_calls(self):
        other = extraction.document_from_pages("HB1", "90R", "introduced", [" A full\n bill. Second clause. "])
        other.update(status="Referred", authors=["New author"], generated_at="later", pdf_sha256="new PDF metadata",
                     source_url="changed provenance URL")
        self.assertEqual(ResponseCache.key(extraction.build_request(self.doc, self.registry)),
                         ResponseCache.key(extraction.build_request(other, self.registry)))

    def test_text_version_model_prompt_schema_and_registry_changes_invalidate(self):
        original = extraction.build_request(self.doc, self.registry)
        variants = []
        for field, value in (("version", "committee-substitute"), ("bill_id", "HB2"), ("session", "91R")):
            variants.append(extraction.build_request({**self.doc, field: value}, self.registry))
        changed = extraction.document_from_pages("HB1", "90R", "introduced", ["A changed bill."])
        variants.append(extraction.build_request(changed, self.registry))
        variants.append(extraction.build_request(self.doc, self.registry, instructions="New instructions"))
        new_schema = copy.deepcopy(SCHEMA); new_schema["description"] = "New contract"
        variants.append(extraction.build_request(self.doc, self.registry, schema=new_schema))
        registry = copy.deepcopy(self.registry); registry[1]["name"] += " updated"
        variants.append(extraction.build_request(self.doc, registry))
        variants.append({**original, "model": "different-model"})
        for request in variants:
            self.assertNotEqual(ResponseCache.key(request), ResponseCache.key(original))

    def test_shared_prefix_is_identical_across_bills(self):
        other = extraction.document_from_pages("SB1", "90R", "introduced", ["Completely different text."])
        a, b = [extraction.build_request(d, self.registry) for d in (self.doc, other)]
        self.assertEqual(a["input"][0], b["input"][0])
        self.assertEqual(a["text"], b["text"])
        self.assertNotEqual(a["input"][1], b["input"][1])
        self.assertNotIn("prompt_cache_breakpoint", a["input"][1]["content"][0])

    def test_cache_cannot_be_inside_either_checkout(self):
        with self.assertRaises(ValueError):
            extraction.check_cache_location(ROOT / "data/cache")
        with self.assertRaises(ValueError):
            extraction.extract(self.doc, self.registry, ROOT / "private-cache")
        if (ROOT / ".git").is_file() and ROOT.parent.name == ".worktrees":
            with self.assertRaises(ValueError):
                extraction.check_cache_location(ROOT.parent.parent / "data/cache")


class CalendarTests(unittest.TestCase):
    def test_first_monday_third_year_after_census(self):
        point = {"kind": "ordinal_weekday_relative_to_event", "anchor_event": "census", "year_offset": 3,
                 "month": 6, "ordinal": 1, "weekday": "Monday"}
        self.assertEqual(extraction.resolve_calendar(point, dt.date(2020, 4, 1)), dt.date(2023, 6, 5))

    def test_same_year_date_uses_supplied_anchor_not_assumed_decade(self):
        point = {"kind": "calendar_relative_to_event", "anchor_event": "census", "year_offset": 3,
                 "month": 8, "day": 31}
        self.assertEqual(extraction.resolve_calendar(point, dt.date(2021, 1, 1)), dt.date(2024, 8, 31))

    def test_qualifying_year_and_qualifying_date_are_different(self):
        point = {"kind": "next_matching_calendar", "anchor_event": "appointment", "month": 6, "day": 14,
                 "year_modulus": 10, "year_remainder": 0, "selection": "next_matching_year_after_anchor"}
        anchor = dt.date(2020, 1, 1)
        self.assertEqual(extraction.resolve_calendar(point, anchor), dt.date(2030, 6, 14))
        point["selection"] = "next_matching_date_after_anchor"
        self.assertEqual(extraction.resolve_calendar(point, anchor), dt.date(2020, 6, 14))

    def test_nonexistent_ordinal_weekday_does_not_roll_into_next_month(self):
        point = {"kind": "ordinal_weekday_relative_to_event", "anchor_event": "event", "year_offset": 0,
                 "month": 2, "ordinal": 5, "weekday": "Monday"}
        with self.assertRaises(ValueError):
            extraction.resolve_calendar(point, dt.date(2021, 1, 1))


@unittest.skipUnless(HAS_SCHEMA, "Install optional requirements-extraction.txt for schema tests")
class SchemaAndExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bill-extraction-")
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name)
        self.doc = extraction.document_from_pages("HB1", "90R", "introduced", ["The commission shall publish maps."])
        self.registry = extraction.load_registry()

    def validate(self, value):
        return extraction.validate_result(value, self.doc, self.registry, SCHEMA, "f" * 64, sample_percent=0)

    def test_actor_basis_is_explicit_and_unknown_actor_uses_null(self):
        import jsonschema
        value = result(); value["obligations"] = [obligation(actor={"name": None, "basis": "unspecified"})]
        self.assertIn("Unknown or inferred actor: obligations:O1", self.validate(value)["review_reasons"])
        value["obligations"][0]["actor"] = {"name": "State election authorities", "basis": "unspecified"}
        with self.assertRaises(jsonschema.ValidationError): self.validate(value)

    def test_mixed_actor_modality_regression_is_flagged(self):
        value = result(); value["obligations"] = [obligation(
            actor={"name": "Member of public", "basis": "explicit"}, modality="may",
            action="Submit maps; each map must be publicly available")]
        self.assertTrue(any("mixed actor/modality" in x for x in self.validate(value)["review_reasons"]))
        value["obligations"] = [obligation(), obligation(obligation_id="O2", modality="may", action="Submit maps",
                               actor={"name": "Member of public", "basis": "explicit"})]
        self.assertFalse(any("mixed actor/modality" in x for x in self.validate(value)["review_reasons"]))

    def test_evidence_links_and_counts_are_derived_and_duplicate_ids_rejected(self):
        value = result(); value["obligations"] = [obligation()]
        checked = self.validate(value)
        self.assertEqual(checked["evidence_reverse_index"], {"P001S001": ["obligations:O1"]})
        self.assertEqual(checked["counts"]["obligations"], 1)
        value["obligations"].append(obligation())
        self.assertTrue(any("Duplicate record ID" in x for x in self.validate(value)["errors"]))

    def test_missing_evidence_and_scope_as_agency_are_rejected(self):
        value = result(); value["obligations"] = [obligation(evidence=[{"span_ids": ["P999S999"]}])]
        self.assertIn("Unknown evidence span: P999S999", self.validate(value)["errors"])
        value = result(); value["entities"] = [{
            "entity_ref": "scope", "registry_id": "all-state-agencies", "name": "All state agencies",
            "resolution": "registry_match", "entity_type": "agency", "roles": [], "mention_only": False,
            "basis": "explicit", "creation_options": {"establish_new": False, "designate_existing": False},
            "evidence": [{"span_ids": ["P001S001"]}]}]
        self.assertIn("Noncanonical entity identity: scope", self.validate(value)["errors"])

    def test_event_relative_types_and_unknown_inclusivity_validate(self):
        value = result()
        point = {"kind": "ordinal_weekday_relative_to_event", "anchor_event": "census", "year_offset": 3,
                 "month": 6, "ordinal": 1, "weekday": "Monday"}
        value["timing_rules"] = [timing({"kind": "point", "point": point}, "no_later_than")]
        self.assertEqual(self.validate(value)["errors"], [])
        value["timing_rules"] = [timing({"kind": "window", "start": point, "end": point,
                                         "start_inclusive": True, "end_inclusive": None}, "within_window")]
        self.assertIn("Unknown interval endpoint inclusivity", self.validate(value)["review_reasons"])

    def test_incompatible_deadline_duration_is_not_representable(self):
        import jsonschema
        value = result(); value["timing_rules"] = [timing(
            {"kind": "duration", "value": 90, "unit": "days", "comparison": "at_most",
             "anchor_event": "board deadline", "relation_to_anchor": "after"}, "no_later_than")]
        with self.assertRaises(jsonschema.ValidationError): self.validate(value)

    def test_default_preparation_never_calls_sender(self):
        report = extraction.extract(self.doc, self.registry, self.cache,
                                    sender=lambda _: self.fail("Preparation must not send"))
        self.assertEqual(report["action"], "not_submitted")
        self.assertEqual(report["new_api_cost_estimate"], [0, 0])

    def test_cache_replay_needs_no_client_or_credentials_and_cost_is_zero(self):
        first = extraction.extract(self.doc, self.registry, self.cache, execute=True,
                                   sender=lambda _: response(result()))
        with patch.object(extraction, "send_request", side_effect=AssertionError("No client or key access")):
            second = extraction.extract(self.doc, self.registry, self.cache)
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(second["usage_source"], "historical_response")
        self.assertEqual(second["new_api_cost_estimate"], [0, 0])
        self.assertFalse(second["publishable"])

    def test_invalid_and_incomplete_outputs_are_saved_without_automatic_retry(self):
        raw = response({}, status="incomplete")
        first = extraction.extract(self.doc, self.registry, self.cache, execute=True, sender=lambda _: raw)
        second = extraction.extract(self.doc, self.registry, self.cache, execute=True,
                                    sender=lambda _: self.fail("Do not resubmit an incomplete response"))
        self.assertTrue(first["errors"])
        self.assertTrue(second["cache_hit"])

    def test_response_is_revalidated_without_a_new_call(self):
        extraction.extract(self.doc, self.registry, self.cache, execute=True, sender=lambda _: response(result()))
        with patch.object(extraction, "validate_result", return_value={"errors": ["new validator finding"],
                                                                      "publishable": False}):
            report = extraction.extract(self.doc, self.registry, self.cache,
                                        sender=lambda _: self.fail("Revalidation is offline"))
        self.assertIn("new validator finding", report["errors"])

    def test_budget_and_cache_write_costs_do_not_double_count_reasoning(self):
        raw = response(result(), usage={"input_tokens": 1000, "input_tokens_details": {
            "cached_tokens": 200, "cache_write_tokens": 300,
            "cache_write_tokens_details": {"ttl_30m_tokens": 100, "ttl_12h_tokens": 200}},
            "output_tokens": 100, "output_tokens_details": {"reasoning_tokens": 50}})
        cost = (500 * .5 + 200 * .025 + 100 * .625 + 200 * 1.25 + 100 * 2.5) / 1e6
        for bound in extraction.response_cost(raw):
            self.assertAlmostEqual(bound, cost)

    def test_capacity_retry_is_bounded_and_unknown_timeout_not_retried(self):
        calls = []
        class Capacity(Exception):
            code = "flex_unavailable"
        def create(**kwargs):
            calls.append(kwargs)
            raise Capacity()
        client = types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
        fake_module = types.SimpleNamespace(OpenAI=lambda **_: client)
        with patch.dict(sys.modules, {"openai": fake_module}), patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), \
                patch.object(extraction.time, "sleep") as sleep:
            with self.assertRaises(extraction.CapacityUnavailable):
                extraction.send_request(extraction.build_request(self.doc, self.registry))
        self.assertEqual(len(calls), 3)
        self.assertEqual([x.args[0] for x in sleep.call_args_list], [30, 60])
        calls.clear()
        def timeout(**kwargs):
            calls.append(kwargs)
            raise TimeoutError("unknown submission outcome")
        client.responses.create = timeout
        with patch.dict(sys.modules, {"openai": fake_module}), patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), \
                patch.object(extraction.time, "sleep") as sleep:
            with self.assertRaises(TimeoutError):
                extraction.send_request(extraction.build_request(self.doc, self.registry))
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_long_retry_after_and_quota_errors_do_not_loop(self):
        calls = []
        class Capacity(Exception):
            code = "flex_unavailable"
            response = types.SimpleNamespace(headers={"retry-after": "3600"})
        def create(**kwargs):
            calls.append(kwargs)
            raise Capacity()
        client = types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
        fake_module = types.SimpleNamespace(OpenAI=lambda **_: client)
        with patch.dict(sys.modules, {"openai": fake_module}), patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), \
                patch.object(extraction.time, "sleep") as sleep:
            with self.assertRaises(extraction.CapacityUnavailable) as caught:
                extraction.send_request(extraction.build_request(self.doc, self.registry))
        self.assertEqual(caught.exception.retry_after, 3600)
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()
        calls.clear()
        Capacity.code = "insufficient_quota"
        with patch.dict(sys.modules, {"openai": fake_module}), patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            with self.assertRaises(Capacity):
                extraction.send_request(extraction.build_request(self.doc, self.registry))
        self.assertEqual(len(calls), 1)

    @unittest.skipUnless(HAS_OPENAI, "Install optional OpenAI SDK for mock wire test")
    def test_sdk_receives_cache_controls_and_complete_source_without_network(self):
        import httpx
        from openai import OpenAI
        captured = []
        def respond(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "offline", "object": "response", "created_at": 0,
                                            "model": extraction.MODEL, "status": "completed", "output": []})
        with httpx.Client(transport=httpx.MockTransport(respond)) as http:
            payload = extraction.build_request(self.doc, self.registry)
            args = copy.deepcopy(payload); options = args.pop("prompt_cache_options")
            OpenAI(api_key="offline-test", http_client=http).responses.create(
                **args, extra_body={"prompt_cache_options": options})
        self.assertEqual(captured, [payload])


if __name__ == "__main__":
    unittest.main()
