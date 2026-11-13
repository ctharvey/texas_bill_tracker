"""The --transport flex boundary (scripts/flex_boundary.py): cth_flex stack behind the pipeline's own exceptions.

No network and no paid calls: the OpenAI SDK is a fake (or the real SDK over httpx.MockTransport).
"""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import flex_boundary as fb  # noqa: E402 - also puts scripts/vendor on sys.path
import cth_flex  # noqa: E402
from cth_flex import cache as flex_cache  # noqa: E402
from cth_flex import exceptions as flex_exceptions  # noqa: E402
from cth_flex import ledger as flex_ledger  # noqa: E402
import classify_bill  # noqa: E402
import extract_bill as extraction  # noqa: E402
import extraction_cache as ec  # noqa: E402

HAS_OPENAI = importlib.util.find_spec("openai") is not None and importlib.util.find_spec("httpx") is not None

MODEL = classify_bill.MODEL
REQ = {"model": MODEL, "input": "hello", "max_output_tokens": 100, "service_tier": "flex",
       "prompt_cache_options": {"mode": "explicit"}}
REQ2 = {**REQ, "input": "a different request"}
OK = {"model": MODEL, "service_tier": "flex", "status": "completed",
      "usage": {"input_tokens": 10, "output_tokens": 5}, "output": []}


class Reply:
    def __init__(self, body):
        self.body = body

    def model_dump(self, mode="json"):
        return self.body


class Err(Exception):
    def __init__(self, status, code, headers=None):
        super().__init__("provider error")
        self.status_code = status
        self.code = code
        self.response = types.SimpleNamespace(status_code=status, headers=headers or {})
        self.body = {"error": {"code": code}}


class SDK:
    def __init__(self, script=(), on_create=None):
        self.script, self.calls, self.on_create = list(script), [], on_create
        self.responses = self

    def with_options(self, **kw):
        return self

    def create(self, **kw):
        self.calls.append(kw)
        if self.on_create:
            self.on_create(kw)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return Reply(item)


class BoundaryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.sleeps = []

    def boundary(self, script=(), factory=None, on_create=None, daily=None, run=None):
        self.sdk = SDK(script, on_create)
        return fb.FlexBoundary(self.dir, daily, run, openai_factory=factory or (lambda: self.sdk),
                               sleep=self.sleeps.append, log=lambda text: None)

    def run_once(self, b, request=REQ):
        return b.execute(request, lambda: b.send(request))

    def entry(self, request=REQ):
        path = self.dir / "responses" / (fb.FlexBoundary.key(request) + ".json")
        return json.loads(path.read_text("utf-8")) if path.exists() else {}

    def rows(self):
        path = self.dir / "budget.json"
        ledger = json.loads(path.read_text("utf-8")) if path.exists() else {}
        return [row for day in ledger.values() for row in day.values()]

    def states(self):
        return [row["state"] for row in self.rows()]


class OutcomeTests(BoundaryCase):
    def test_capacity_three_times_is_unavailable_with_two_sleeps(self):
        b = self.boundary([Err(429, "flex_unavailable")] * 3)
        with self.assertRaises(ec.CapacityUnavailable) as caught:
            self.run_once(b)
        self.assertEqual(len(self.sdk.calls), 3)
        self.assertEqual(self.sleeps, [30, 60])
        self.assertEqual(caught.exception.retry_after, 60)
        self.assertEqual(self.entry()["state"], "not_submitted")
        self.assertEqual(self.rows(), [])

    def test_long_retry_after_defers_without_sleeping_then_cools_down(self):
        b = self.boundary([Err(429, "flex_unavailable", {"retry-after": "3600"})])
        with self.assertRaises(ec.CapacityUnavailable) as caught:
            self.run_once(b)
        self.assertEqual(len(self.sdk.calls), 1)
        self.assertEqual(self.sleeps, [])
        self.assertAlmostEqual(caught.exception.retry_after, 3600, delta=30)
        self.assertEqual(self.entry()["state"], "capacity_wait")
        self.assertEqual(self.rows(), [])
        with self.assertRaises(ec.CacheCoolingDown):
            self.run_once(b)
        self.assertEqual(len(self.sdk.calls), 1)

    def test_timeout_is_uncertain_untranslated_and_held_without_blocking_other_requests(self):
        b = self.boundary([TimeoutError("t"), OK])
        with self.assertRaises(cth_flex.UncertainOutcome) as caught:
            self.run_once(b)
        self.assertIsInstance(caught.exception, cth_flex.UncertainOutcome)
        self.assertNotIsInstance(caught.exception, (ec.NotSubmitted, ec.CapacityUnavailable))
        self.assertIs(caught.exception.held, True)
        self.assertEqual(caught.exception.request_key, fb.FlexBoundary.key(REQ))
        self.assertEqual(len(self.sdk.calls), 1)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.entry()["state"], "indeterminate")
        legacy = (len(json.dumps(REQ, ensure_ascii=False).encode()) * .125 + REQ["max_output_tokens"] * .25) / 1e6
        [row] = self.rows()
        self.assertEqual((row["state"], row["held"], row["cost"], row["reserved"]), ("returned", True, legacy, 0))
        self.assertEqual(b.ledger, {"pending": {}})
        self.assertEqual(self.run_once(b, REQ2).response, OK)  # another request still goes out
        with self.assertRaises(ec.UnresolvedCall):  # the held one is never resent
            self.run_once(b)
        self.assertEqual(len(self.sdk.calls), 2)

    def test_quota_and_auth_stop_the_run_without_billing(self):
        for status, code in ((429, "insufficient_quota"), (401, "invalid_api_key")):
            with self.subTest(code=code):
                self.setUp()
                b = self.boundary([Err(status, code)])
                with self.assertRaises(ec.ApiStopped) as caught:
                    self.run_once(b)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(len(self.sdk.calls), 1)
                self.assertEqual(self.sleeps, [])
                self.assertEqual(self.entry()["state"], "not_submitted")
                self.assertEqual(self.rows(), [])

    def test_bad_request_is_rejected_not_pending(self):
        b = self.boundary([Err(400, "bad")])
        with self.assertRaises(ec.ApiRejected) as caught:
            self.run_once(b)
        self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual(len(self.sdk.calls), 1)
        self.assertEqual(b.ledger, {"pending": {}})
        self.assertNotIn("pending", self.states())
        self.assertEqual(self.entry()["state"], "not_submitted")

    def test_incomplete_flex_reply_is_kept_refused_and_never_resent(self):
        incomplete = {**OK, "status": "incomplete"}
        b = self.boundary([incomplete])
        first = self.run_once(b)
        self.assertFalse(first.cache_hit)
        self.assertEqual(first.response, incomplete)
        self.assertEqual(self.entry()["state"], "refused")
        rows = self.rows()
        self.assertEqual([r["state"] for r in rows], ["returned"])
        self.assertGreater(rows[0]["cost"], 0)
        second = self.run_once(b)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.response, incomplete)
        self.assertEqual(len(self.sdk.calls), 1)

    def test_unpriceable_replies_stay_pending_and_indeterminate(self):
        cases = {"other model": {**OK, "model": "gpt-6.1-terra"},
                 "wrong tier": {**OK, "service_tier": "default"},
                 "incomplete other model": {**OK, "model": "gpt-6.1-terra", "status": "incomplete"}}
        for name, reply in cases.items():
            with self.subTest(name):
                self.setUp()
                b = self.boundary([reply])
                with self.assertRaises(fb.UnpricedResponse):
                    self.run_once(b)
                self.assertEqual(len(self.sdk.calls), 1)
                self.assertEqual(self.entry()["state"], "indeterminate")
                self.assertEqual(self.states(), ["pending"])

    def test_dry_run_refusal_is_reraised_as_the_same_local_object_type(self):
        b = self.boundary([])

        def submit():
            raise ec.NotSubmitted("Prepared only")
        with self.assertRaises(ec.NotSubmitted) as caught:
            b.execute(REQ, submit)
        self.assertIs(type(caught.exception), ec.NotSubmitted)
        self.assertEqual(str(caught.exception), "Prepared only")
        self.assertEqual(self.sdk.calls, [])
        self.assertEqual(self.entry()["state"], "not_submitted")
        self.assertEqual(self.rows(), [])

    def test_missing_key_is_not_submitted_before_anything_is_reserved(self):
        def factory():
            raise cth_flex.NotSent("OPENAI_API_KEY is required")
        b = self.boundary([], factory=factory)
        with self.assertRaises(ec.NotSubmitted) as caught:
            self.run_once(b)
        self.assertIs(type(caught.exception), ec.NotSubmitted)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.entry()["state"], "not_submitted")

    def test_cache_replay_needs_no_factory_and_costs_nothing(self):
        first = self.run_once(self.boundary([OK]))
        self.assertFalse(first.cache_hit)

        def factory():
            raise AssertionError("A cache replay must not build a client")
        b = self.boundary([], factory=factory)
        replay = b.execute(REQ, lambda: self.fail("A cache replay must not send"))
        self.assertTrue(replay.cache_hit)
        self.assertEqual(replay.response, OK)
        self.assertEqual(b.run_spent, 0)

    def test_long_context_is_refused_before_sending(self):
        big = {**REQ, "input": "x" * 272001}
        b = self.boundary([OK])
        with self.assertRaises(ec.LongContext) as caught:
            self.run_once(b, big)
        self.assertIsInstance(caught.exception, ec.NotSubmitted)
        self.assertEqual(self.sdk.calls, [])
        self.assertEqual(self.entry(big)["state"], "not_submitted")
        self.assertEqual(self.rows(), [])


@unittest.skipUnless(HAS_OPENAI, "Install optional OpenAI SDK and httpx for the mock wire test")
class HeldCallTests(BoundaryCase):
    """An unknown outcome holds only its request; the cap, a failed hold and the operator release."""

    def held_rows(self):
        return [r for r in self.rows() if r.get("held") is True]

    def test_the_held_cap_refuses_new_calls_unsent(self):
        b = fb.FlexBoundary(self.dir, None, None, openai_factory=lambda: self.sdk, sleep=self.sleeps.append,
                            log=lambda text: None, max_held=2)
        self.sdk = SDK([TimeoutError("t"), TimeoutError("t"), OK])
        for request in (REQ, REQ2):
            with self.assertRaises(cth_flex.UncertainOutcome):
                self.run_once(b, request)
        third = {**REQ, "input": "a third request"}
        with self.assertRaises(ec.OutcomeUnresolved):
            self.run_once(b, third)
        self.assertEqual(len(self.sdk.calls), 2)
        self.assertEqual(self.entry(third)["state"], "not_submitted")  # provably unsent: sendable once released
        self.assertEqual(len(self.held_rows()), 2)

    def test_a_failed_hold_write_fails_closed(self):
        b = self.boundary([TimeoutError("t"), OK])
        save = b.spend._save

        def refuse_held(data):
            if any(row.get("held") for rows in data.values() for row in rows.values()):
                raise OSError("disk full")
            save(data)
        b.spend._save = refuse_held
        with self.assertRaises(cth_flex.UncertainOutcome) as caught:
            self.run_once(b)
        self.assertFalse(getattr(caught.exception, "held", False))  # the pipeline stops the run on it
        self.assertEqual(self.states(), ["pending"])
        with self.assertRaises(ec.OutcomeUnresolved):  # and the pending row blocks every new call
            self.run_once(b, REQ2)
        self.assertEqual(len(self.sdk.calls), 1)

    def test_hold_turns_a_leftover_pending_row_into_a_held_call_so_other_requests_go_on(self):
        b = self.boundary([TimeoutError("t"), OK])
        save = b.spend._save
        def refuse_held(data):
            if any(row.get("held") for rows in data.values() for row in rows.values()):
                raise OSError("disk full")
            save(data)
        b.spend._save = refuse_held
        with self.assertRaises(cth_flex.UncertainOutcome):
            self.run_once(b)
        b.spend._save = save
        key = fb.FlexBoundary.key(REQ)
        listing = io.StringIO()
        with contextlib.redirect_stdout(listing):
            self.assertEqual(fb.main(["--cache-dir", str(self.dir)]), 0)
        self.assertIn(key + " pending (no recorded outcome; settle with --hold " + key + ")", listing.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(fb.main(["--cache-dir", str(self.dir), "--hold", key]), 0)
        self.assertIn("Held " + key, out.getvalue())
        [(_, held_key, row)] = b.held()
        self.assertEqual((held_key, row["error_type"]), (key, "PendingAfterStop"))
        self.assertGreater(row["cost"], 0)  # booked at its reservation
        self.assertEqual(self.run_once(b, REQ2).response, OK)  # no longer blocks other calls
        with self.assertRaises(ec.UnresolvedCall):  # and is never resent by itself
            self.run_once(b)
        self.assertEqual(len(self.sdk.calls), 2)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fb.main(["--cache-dir", str(self.dir), "--hold", key]), 1)  # no longer pending


    def test_release_keeps_the_booked_bound_and_lets_the_request_be_sent_once_more(self):
        b = self.boundary([TimeoutError("t"), OK])
        with self.assertRaises(cth_flex.UncertainOutcome):
            self.run_once(b)
        key = fb.FlexBoundary.key(REQ)
        [(_, held_key, row)] = b.held()
        self.assertEqual(held_key, key)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(fb.main(["--cache-dir", str(self.dir), "--release", key]), 0)
        self.assertIn("Released " + key, out.getvalue())
        self.assertEqual(b.held(), [])
        released = [r for r in self.rows() if r.get("released_at")]
        self.assertEqual([(r["cost"], r["held"]) for r in released], [(row["cost"], False)])
        self.assertEqual(self.entry(), {})  # the indeterminate entry is gone
        self.assertEqual(self.run_once(b).response, OK)
        self.assertEqual(len(self.sdk.calls), 2)
        self.assertEqual(sorted(r["state"] for r in self.rows()), ["returned", "returned"])  # both costs booked

    def test_release_refuses_while_a_run_holds_the_worker_lock_and_unknown_keys(self):
        with ec.ResponseCache(self.dir / "worker-lock")._lock("worker"), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fb.main(["--cache-dir", str(self.dir)]), 1)
        with self.assertRaises(KeyError):
            self.boundary([]).release_held("0" * 64)


class WireTests(BoundaryCase):
    def test_posted_body_is_the_classification_request_with_cache_options_on_top(self):
        import httpx
        from openai import OpenAI
        captured = []

        def respond(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={
                "id": "offline", "object": "response", "created_at": 0, "model": MODEL, "status": "completed",
                "service_tier": "flex", "output": [],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 0}}})
        document = extraction.document_from_pages("HB1", "90R", "introduced", ["A full bill. Second clause."])
        request = classify_bill.build_request(document, extraction.load_registry())
        with httpx.Client(transport=httpx.MockTransport(respond)) as http:
            b = self.boundary(factory=lambda: OpenAI(api_key="test", base_url="https://api.openai.com/v1",
                                                     max_retries=0, http_client=http))
            result = self.run_once(b, request)
        self.assertFalse(result.cache_hit)
        self.assertEqual(captured, [request])
        self.assertIn("prompt_cache_options", captured[0])
        self.assertEqual(self.states(), ["returned"])


class ParityTests(BoundaryCase):
    def test_reservation_equals_the_legacy_budget_ceiling(self):
        request = {**REQ, "max_output_tokens": 12000, "input": "Bill text with a section sign § and a dash — " * 40}
        seen = []

        def peek(kw):
            seen.extend(row for rows in json.loads((self.dir / "budget.json").read_text("utf-8")).values()
                        for row in rows.values())
        b = self.boundary([OK], on_create=peek)
        self.run_once(b, request)
        legacy = (len(json.dumps(request, ensure_ascii=False).encode()) * .125 + request["max_output_tokens"] * .25) / 1e6
        self.assertEqual([r["state"] for r in seen], ["pending"])
        self.assertEqual(seen[0]["reserved"], legacy)

    def test_reservation_matches_legacy_for_a_real_classification_request(self):
        document = extraction.document_from_pages("HB1", "90R", "introduced", ["A full bill. Second clause."])
        request = classify_bill.build_request(document, extraction.load_registry())
        seen = []
        b = self.boundary([OK], on_create=lambda kw: seen.extend(
            row for rows in json.loads((self.dir / "budget.json").read_text("utf-8")).values()
            for row in rows.values()))
        self.run_once(b, request)
        legacy = (len(json.dumps(request, ensure_ascii=False).encode()) * .125 + request["max_output_tokens"] * .25) / 1e6
        self.assertEqual(seen[0]["reserved"], legacy)

    def vectors(self):
        def raw(usage):
            return {"model": MODEL, "service_tier": "flex", "status": "completed", "output": [], "usage": usage}
        return {
            "plain": raw({"input_tokens": 100, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                          "output_tokens": 50}),
            "details": raw({"input_tokens": 1000, "input_tokens_details": {
                "cached_tokens": 200, "cache_write_tokens": 300,
                "cache_write_tokens_details": {"ttl_30m_tokens": 100, "ttl_12h_tokens": 200}},
                "output_tokens": 100, "output_tokens_details": {"reasoning_tokens": 50}}),
            "writes without lifetimes": raw({"input_tokens": 900, "input_tokens_details": {
                "cached_tokens": 100, "cache_write_tokens": 300}, "output_tokens": 70}),
            "details only 30m": raw({"input_tokens": 500, "input_tokens_details": {
                "cached_tokens": 0, "cache_write_tokens": 400,
                "cache_write_tokens_details": {"ttl_30m_tokens": 400}}, "output_tokens": 10}),
        }

    def test_cost_matches_classify_response_cost(self):
        for name, raw in self.vectors().items():
            with self.subTest(name):
                flex = cth_flex.cost_usd(cth_flex.usage_from_response(raw), fb.LUNA_RATES)
                legacy = classify_bill.response_cost(raw)[1]
                self.assertAlmostEqual(flex, legacy, places=12)
                self.assertGreater(flex, 0)

    def test_inconsistent_cache_write_accounting_is_rejected_by_both(self):
        base = self.vectors()["details"]
        for name, lifetimes in (("unknown key", {"ttl_5m_tokens": 300}),
                                ("sum mismatch", {"ttl_30m_tokens": 100, "ttl_12h_tokens": 100})):
            with self.subTest(name):
                raw = json.loads(json.dumps(base))
                raw["usage"]["input_tokens_details"]["cache_write_tokens_details"] = lifetimes
                with self.assertRaises(ValueError):
                    cth_flex.usage_from_response(raw)
                with self.assertRaises(ValueError):
                    classify_bill.response_cost(raw)


class TranslationTests(unittest.TestCase):
    LOCAL = (ec.CacheCoolingDown, ec.CacheBusy, ec.UnresolvedCall, ec.CapacityUnavailable, ec.BudgetExceeded,
             ec.OutcomeUnresolved, ec.AlreadyBilled, ec.LongContext, ec.NotSubmitted, ec.ApiStopped, ec.ApiRejected)

    def instances(self):
        out = []
        classes = {}
        for module in (cth_flex, flex_cache, flex_ledger, flex_exceptions):
            for name, obj in vars(module).items():
                if isinstance(obj, type) and issubclass(obj, BaseException) and obj.__module__.startswith("cth_flex"):
                    classes[obj] = name
        later = time.time() + 10
        for cls in classes:
            if issubclass(cls, flex_cache.CacheCoolingDown):
                out.append(cls(later))
            elif issubclass(cls, cth_flex.Deferred):
                out.append(cls("m", later))
            elif issubclass(cls, (cth_flex.TierMismatch, cth_flex.IncompleteResponse, cth_flex.UnrecordedResponse)):
                out.append(cls("m", {}))
            elif issubclass(cls, cth_flex.AttemptFailed):
                for sent in ("not_sent", "maybe_sent"):
                    out.append(cls("m", cth_flex.ErrorInfo(cth_flex.Kind.OTHER), sent))
            else:
                try:
                    out.append(cls("m"))
                except TypeError:
                    continue
            if issubclass(cls, (cth_flex.Stopped, cth_flex.NotSent, cth_flex.UncertainOutcome)) and not issubclass(
                    cls, (flex_cache.CacheCoolingDown, cth_flex.Deferred)):
                for kind in cth_flex.Kind:
                    for billed in (False, True):
                        out.append(cls("m", cth_flex.ErrorInfo(kind, code="insufficient_quota", maybe_billed=billed)))
        return classes, out

    def test_no_not_sent_error_escapes_untranslated(self):
        classes, instances = self.instances()
        self.assertGreater(len(classes), 15)  # the walk really found the library's classes
        for error in instances:
            with self.subTest(type(error).__name__, info=getattr(error, "info", None)):
                translated = fb.translate(error)
                if translated is error:
                    self.assertNotEqual(cth_flex.outcome_of(error), "not_sent")
                else:
                    self.assertIsInstance(translated, self.LOCAL)
                    self.assertNotIsInstance(translated, cth_flex.FlexError)

    def test_every_exported_class_was_constructed(self):
        classes, instances = self.instances()
        built = {type(e) for e in instances}
        missing = [c.__name__ for c in classes if c not in built]
        self.assertEqual(missing, [])


class LedgerReadRaceTests(BoundaryCase):
    def test_a_send_starting_during_the_read_is_not_an_unknown_outcome(self):
        # Worker A reads the ledger after a failed question; worker B starts a send in that window.
        entered, release = threading.Event(), threading.Event()
        b = self.boundary([OK], on_create=lambda kw: (entered.set(), release.wait(10)))
        real, workers = b.spend.pending, []

        def pending_while_another_send_starts():
            worker = threading.Thread(target=self.run_once, args=(b,))
            workers.append(worker); worker.start()
            entered.wait(1)  # old code: B reserves and is sending by now; fixed: B waits for this read
            return real()

        b.spend.pending = pending_while_another_send_starts
        try:
            seen = b.ledger
        finally:
            release.set()
            for worker in workers:
                worker.join(10)
        self.assertEqual(seen, {"pending": {}})
        self.assertEqual(self.states(), ["returned"])

    def test_a_pending_row_no_send_owns_is_still_an_unknown_outcome(self):
        (self.dir / "budget.json").write_text(json.dumps(
            {"2026-11-12": {"deadbeef": {"state": "pending", "reserved": 0.01}}}), "utf-8")
        self.assertEqual(self.boundary().ledger, {"pending": {"deadbeef": {"state": "pending"}}})


class LegacyDiskCompatibilityTests(BoundaryCase):
    def write_entry(self, request, state, **extra):
        key = fb.FlexBoundary.key(request)
        directory = self.dir / "responses"
        directory.mkdir(parents=True, exist_ok=True)
        entry = {"cache_format": 1, "request_key": key, "state": state, "started_at": time.time(), **extra}
        (directory / (key + ".json")).write_text(json.dumps(entry), "utf-8")

    def test_legacy_pending_ledger_row_without_owner_blocks_sending(self):
        (self.dir / "budget.json").write_text(json.dumps(
            {"2026-11-09": {"deadbeef": {"state": "pending", "reserved": 0.01}}}), "utf-8")
        b = self.boundary([OK])
        with self.assertRaises(ec.OutcomeUnresolved):
            self.run_once(b)
        self.assertEqual(self.sdk.calls, [])

    def test_returned_entries_hit_without_sending_even_when_incomplete(self):
        for name, reply in (("complete", OK), ("incomplete", {**OK, "status": "incomplete"})):
            with self.subTest(name):
                self.setUp()
                self.write_entry(REQ, "returned", response=reply, returned_at=time.time())
                b = self.boundary([OK])
                result = self.run_once(b)
                self.assertTrue(result.cache_hit)
                self.assertEqual(result.response, reply)
                self.assertEqual(self.sdk.calls, [])

    def test_unresolved_legacy_states_raise_without_sending(self):
        for state, extra in (("indeterminate", {"error_type": "TimeoutError"}), ("pending", {})):
            with self.subTest(state):
                self.setUp()
                self.write_entry(REQ, state, **extra)
                b = self.boundary([OK])
                with self.assertRaises(ec.UnresolvedCall):
                    self.run_once(b)
                self.assertEqual(self.sdk.calls, [])

    def test_capacity_wait_in_the_future_cools_down_and_in_the_past_sends(self):
        self.write_entry(REQ, "capacity_wait", retry_not_before=time.time() + 600)
        b = self.boundary([OK])
        with self.assertRaises(ec.CacheCoolingDown):
            self.run_once(b)
        self.assertEqual(self.sdk.calls, [])
        self.write_entry(REQ, "capacity_wait", retry_not_before=time.time() - 5)
        result = self.run_once(b)
        self.assertFalse(result.cache_hit)
        self.assertEqual(len(self.sdk.calls), 1)
        self.assertEqual(self.entry()["state"], "returned")

    def test_not_submitted_entry_sends(self):
        self.write_entry(REQ, "not_submitted")
        b = self.boundary([OK])
        self.assertFalse(self.run_once(b).cache_hit)
        self.assertEqual(len(self.sdk.calls), 1)

    def test_lock_sibling_file_is_not_an_entry(self):
        legacy = ec.ResponseCache(self.dir / "responses")
        legacy.execute(REQ, lambda: OK)  # the legacy cache leaves <key>.lock next to <key>.json
        key = fb.FlexBoundary.key(REQ)
        self.assertTrue((self.dir / "responses" / (key + ".lock")).exists())
        b = self.boundary([])
        self.assertEqual(list(b.cache.entries()), [(key, "returned")])
        replay = b.execute(REQ, lambda: self.fail("legacy entry must replay"))
        self.assertTrue(replay.cache_hit)


class VendoredIntegrityTests(unittest.TestCase):
    def test_vendored_files_match_the_recorded_lf_hashes(self):
        directory = ROOT / "scripts" / "vendor" / "cth_flex"
        recorded = json.loads((directory / "VENDORED.json").read_text("utf-8"))["sha256_lf"]
        actual = {path.name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                  for path in directory.glob("*.py")}
        self.assertEqual(set(actual), set(recorded))
        self.assertEqual(actual, recorded)


if __name__ == "__main__":
    unittest.main()
