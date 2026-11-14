"""The one place the review pipeline meets cth.flex (--transport flex).

Stack, outermost first: response cache -> spend ledger -> FlexClient -> OpenAI SDK sender (cth.flex's supported order).
Inside the stack only cth.flex exceptions may be raised, because cth.flex decides "sent or not" from the exception type
(`outcome_of`); a pipeline exception raised inside would read as maybe billed. Out of the stack, every cth.flex error
is translated once, in `FlexBoundary.execute`, back to the pipeline's own classes, whose names drive queue state.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import threading
import time

_VENDOR = str(Path(__file__).resolve().parent / "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from cth_flex import (  # noqa: E402 - needs the vendor path
    AttemptFailed, Deferred, FlexClient, IncompleteResponse, Kind, NotSent, Rates, RetryPolicy, SpendLedger, Stopped, TierMismatch,
    UncertainOutcome, outcome_of,
)
from cth_flex import cache as flex_cache  # noqa: E402
from cth_flex import ledger as flex_ledger  # noqa: E402
from cth_flex.adapters import openai_responses_sender  # noqa: E402
from cth_flex.client import uncertain_attempts  # noqa: E402

from extraction_cache import (  # noqa: E402
    AlreadyBilled, ApiRejected, ApiStopped, BudgetExceeded, CacheBusy, CacheCoolingDown, CachedResponse,
    CapacityUnavailable, LongContext, NotSubmitted, OutcomeUnresolved, ResponseCache, UnresolvedCall,
)

# Luna Flex short-context rates per million tokens (classify_bill.response_cost; verified 2026-11-09). With these,
# the ledger's reservation (request bytes x the highest input-side rate + output cap x output rate) is exactly the
# legacy Budget's (bytes x .125 + max_output_tokens x .25).
LUNA_RATES = Rates(input=.05, cached_input=.005, output=.25, cache_write_30m=.0625, cache_write_12h=.125)
MAX_REQUEST_BYTES = 272000  # longer requests need long-context pricing review (legacy LongContext)
LEDGER_ZONE = "America/Chicago"
# Legacy send_request: three sends 30 s then 60 s apart; a wait over 60 s (including a provider hint, honoured in
# full) hands the bill back to the worker's cooling list instead of sleeping.
# A 5xx the provider proved it did not process (500-503, 505-519) is resent the same way, so a brief provider error
# no longer parks the bill for PARK_RETRY_S; a maybe-processed 5xx (504, 520-527) is never resent (retry_uncertain
# stays off) and is held as before.
TEXAS_POLICY = RetryPolicy(capacity_attempts=3, rate_limit_attempts=3, base_s=30, cap_s=60, jitter=False,
                           max_hint_s=7 * 24 * 3600, defer_over_s=60, retry_server_errors=True, server_attempts=3)

# Outage breaker. A held call (unknown outcome, booked at its upper bound) holds only its bill; HELD_LIMIT of them
# within HELD_WINDOW_S, or HELD_DAY_LIMIT within a day, refuse every new call. Holds age out of both windows, so
# the worker resumes without an operator, and a long outage still pays for at most HELD_DAY_LIMIT unknowns a day.
HELD_LIMIT = 3
HELD_WINDOW_S = 30 * 60
HELD_DAY_LIMIT = 10
DAY_S = 24 * 3600
# Pending rows a dead run left behind are booked and held automatically at the next run's start, at most this many
# a day (held or since released). Past it they stay pending, the ledger refuses every call, and an operator decides.
CRASH_HOLD_LIMIT = 6
STRANDED = "PendingAfterStop"

_SAME_NAME = {flex_ledger.BudgetExceeded: BudgetExceeded, flex_ledger.OutcomeUnresolved: OutcomeUnresolved,
              flex_ledger.AlreadyBilled: AlreadyBilled, flex_ledger.LongContext: LongContext}


class UnpricedResponse(UncertainOutcome):
    """A reply this boundary cannot price at Luna rates (another model, or long context). Raised inside the stack,
    with no reply attached, so the ledger keeps its reservation pending and the cache records indeterminate: an
    operator settles it, as with the legacy Budget."""


class _PrepareOnly(NotSent):
    """Carries the pipeline's own pre-send NotSubmitted (a dry run) through the cth.flex cache as not sent."""

    def __init__(self, original: NotSubmitted):
        super().__init__(str(original))
        self.original = original


def translate(error: BaseException) -> BaseException:
    """The pipeline exception for a cth.flex error leaving the stack. First match wins: CacheCoolingDown is a
    Deferred, and the cache and ledger refusals are NotSent. Maybe-billed errors pass through unchanged."""
    if isinstance(error, _PrepareOnly):
        return error.original
    if isinstance(error, flex_cache.CacheCoolingDown):
        return CacheCoolingDown("Capacity cooldown is active")
    if isinstance(error, flex_cache.CacheBusy):
        return CacheBusy("The same extraction is already running")
    if isinstance(error, flex_cache.UnresolvedCall):
        return UnresolvedCall(str(error))
    if isinstance(error, Deferred) and outcome_of(error) == "not_sent":
        return CapacityUnavailable(max(0.0, error.retry_at - time.time()))
    for flex_type, local_type in _SAME_NAME.items():
        if isinstance(error, flex_type):
            return local_type(str(error))
    if isinstance(error, NotSent) and outcome_of(error) == "not_sent":
        return NotSubmitted(f"{type(error).__name__}: {error}")
    if isinstance(error, (Stopped, AttemptFailed)) and outcome_of(error) == "not_sent":
        # AttemptFailed normally becomes Stopped inside FlexClient; mapped here too so nothing not-sent escapes.
        kind = error.info.kind if error.info is not None else Kind.OTHER
        if kind in (Kind.QUOTA, Kind.AUTH):
            return ApiStopped(error.info.code or kind.value)
        if kind in (Kind.CAPACITY, Kind.RATE_LIMIT):
            return CapacityUnavailable(60)  # attempts spent: as the legacy sender's last attempt
        return ApiRejected(error.info.label() if error.info is not None else "rejected")
    return error


class FlexBoundary:
    """Stands in for the legacy Budget (send, run_spent, ledger) and ResponseCache (key, execute) for one run.

    Build one per run: the ledger's run total and owner token are per instance."""

    def __init__(self, cache_dir: Path, daily_limit: float | None, run_limit: float | None, *,
                 openai_factory=None, sleep=time.sleep, log=None, max_held: int = HELD_LIMIT):
        if isinstance(max_held, bool) or not isinstance(max_held, int) or max_held < 1:
            raise ValueError("max_held must be an integer >= 1")
        self.max_held = max_held
        self.cache = flex_cache.ResponseCache(Path(cache_dir) / "responses")
        self.spend = SpendLedger(Path(cache_dir) / "budget.json", daily_limit_usd=daily_limit,
                                 run_limit_usd=run_limit, tz=LEDGER_ZONE, max_request_bytes=MAX_REQUEST_BYTES,
                                 reserve_attempts=1)
        self._openai_factory = openai_factory or _default_openai
        self._sleep = sleep
        self._log = log or (lambda text: print(text, file=sys.stderr, flush=True))
        self._client: FlexClient | None = None
        # Shared by the review workers (--workers): the ledger and cache lock themselves; these guard the rest.
        self._lock = threading.Lock()
        self._inflight: set[str] = set()
        self._local = threading.local()

    # ---- the legacy Budget's surface ----
    @property
    def response_cache(self) -> "FlexBoundary":
        return self

    @property
    def run_spent(self) -> float:
        return self.spend.run_spent

    @property
    def thread_calls(self) -> int:
        """Billed replies settled on this thread; run_document counts its own calls with it (run_spent is shared)."""
        return getattr(self._local, "calls", 0)

    @property
    def ledger(self) -> dict:
        """Unresolved rows, in the legacy shape {day: {key: row}}; run_document stops the run on any.

        A row another worker of this run still has in flight is not unresolved, so it is left out. Once its send
        returns, a row still pending is an unknown outcome and is included.

        The rows are read while holding the in-flight lock: `send` adds its key under it before reserving, so a send
        starting between a snapshot and the read would show as an unknown outcome and stop the run (00:36 13 Nov;
        test_a_send_starting_during_the_read_is_not_an_unknown_outcome)."""
        with self._lock:
            mine = set(self._inflight)
            pending = self.spend.pending()
        return {"pending": {key: {"state": "pending"} for key in pending if key not in mine}}

    def send(self, request: dict) -> dict:
        """Reserve, send and settle. Raises cth.flex errors; call it only inside `execute`."""
        self._flex_client()  # a missing SDK or key fails here, as NotSent, before anything is reserved
        self._check_held_limit()  # durable outage cap: N held calls stop every new one (overshoot < workers)
        key = self.key(request)
        with self._lock:
            self._inflight.add(key)
        try:
            response = self.spend.send(request, self._checked_send, LUNA_RATES)
        except IncompleteResponse:
            self._local.calls = self.thread_calls + 1  # billed and settled (kept as refused)
            raise
        finally:
            with self._lock:
                self._inflight.discard(key)
        self._local.calls = self.thread_calls + 1
        return response

    # ---- the legacy ResponseCache's surface ----
    @staticmethod
    def key(request: dict) -> str:
        return flex_cache.ResponseCache.key(request)

    def execute(self, request: dict, submit) -> CachedResponse:
        key = self.key(request)

        def send() -> dict:
            try:
                return submit()
            except NotSubmitted as error:  # the pipeline's dry-run refusal, raised before the ledger
                raise _PrepareOnly(error) from None

        try:
            cached = self.cache.execute(request, send)
            return CachedResponse(cached.response, cached.cache_hit, key)
        except IncompleteResponse as error:
            # Billed, settled and stored as refused: return it so the caller's validation records the failure.
            # (A wrong-tier reply never gets here: _checked_send turns it into UnpricedResponse.)
            return CachedResponse(error.response, False, key)
        except flex_cache.UnresolvedCall as error:
            try:
                stored = self.cache.stored_response(key)
            except Exception:  # noqa: BLE001 - unreadable or busy: report the unresolved call itself
                stored = None
            if stored is not None:  # a refused billed reply: never resent, revalidated offline like the legacy cache
                return CachedResponse(stored, True, key)
            translated = translate(error)
            translated.request_key = key  # the operator releases a held call by this key
            raise translated from error
        except Exception as error:  # noqa: BLE001 - translated once, here
            translated = translate(error)
            if translated is error:
                raise
            raise translated from error

    # ---- inside the stack ----
    def _flex_client(self) -> FlexClient:
        with self._lock:
            return self._build_client()

    def _build_client(self) -> FlexClient:
        if self._client is None:
            sdk = self._openai_factory()  # raises NotSent when the SDK or key is missing; nothing reserved yet

            def on_event(event) -> None:
                if event.kind == "retry":
                    self._log(f"Flex request not processed ({event.label}); retrying in {event.wait_s:g} seconds")

            self._client = FlexClient(openai_responses_sender(sdk), policy=TEXAS_POLICY, require_tier="flex",
                                      require_completed=True, sleep=self._sleep, on_event=on_event)
        return self._client

    def _checked_send(self, request: dict) -> dict:
        try:
            response = self._flex_client().call(request)
        except UncertainOutcome as error:
            self._hold(request, error)
            raise
        except TierMismatch:
            # Billed on another tier: Luna Flex rates would under-count it, so keep the reservation for an operator
            # (the legacy Budget could not price it either).
            raise UnpricedResponse("reply served on another tier; reservation kept for an operator") from None
        except IncompleteResponse as error:
            if error.response.get("model") != request.get("model"):
                raise UnpricedResponse("incomplete reply from an unexpected model") from None
            raise  # Flex tier, our model: priced correctly, kept as refused
        if not isinstance(response, dict):
            return response  # the ledger and cache treat a non-dict reply as billed and unrecorded
        usage = response.get("usage")
        if response.get("model") != request.get("model"):
            raise UnpricedResponse("reply from an unexpected model; reservation kept for an operator")
        if isinstance(usage, dict) and (usage.get("input_tokens") or 0) > MAX_REQUEST_BYTES:
            raise UnpricedResponse("long-context reply; reservation kept for an operator")
        return response

    def _hold(self, request: dict, error: UncertainOutcome) -> None:
        """Book a maybe-billed call at its upper bound and mark it held, so only its bill waits for an operator.

        Runs inside the ledger's send, while the row is still this instance's in-flight call: no other worker can
        see it as a pending row (which would stop the run). Fails closed: on any problem the row stays pending, the
        error carries no `held` mark, and the run stops as before. The key stays in the ledger (AlreadyBilled) and
        the cache records the call indeterminate (UnresolvedCall), so the request is never resent by itself."""
        if outcome_of(error) != "maybe_sent":
            return
        key = self.key(request)
        attempts = max(1, uncertain_attempts.get())  # each maybe-billed send of this call may have cost a ceiling
        try:
            with self.spend._locked() as data:
                for rows in data.values():
                    row = rows.get(key)
                    if (isinstance(row, dict) and row.get("state") == "pending"
                            and row.get("owner") == self.spend.owner):
                        bound = float(row.get("reserved", 0)) * attempts
                        rows[key] = {"state": "returned", "cost": bound, "reserved": 0, "held": True,
                                     "held_at": time.time(), "error_type": type(error).__name__}
                        self.spend._save(data)
                        self.spend.run_spent += bound
                        break
                else:
                    return
        except Exception:  # noqa: BLE001 - fail closed: the pending row stays and stops the run
            return
        error.held = True
        error.request_key = key

    def held(self) -> list[tuple[str, str, dict]]:
        """(day, request key, row) for every held call: unknown outcome, booked at its bound, not yet released."""
        with self.spend._locked() as data:
            return [(day, key, row) for day, rows in data.items() for key, row in rows.items()
                    if isinstance(row, dict) and row.get("held") is True]

    def _check_held_limit(self) -> None:
        try:
            held = [row for _day, _key, row in self.held() if row.get("error_type") != STRANDED]
        except NotSent:
            raise
        except Exception as error:  # noqa: BLE001 - nothing was sent; a NotSent, never a maybe-billed error
            raise flex_ledger.LedgerUnavailable(f"not sent: ledger unavailable ({type(error).__name__})") from error
        now = time.time()
        # A row without a usable held_at counts as just held (fails closed: it never ages out).
        ages = [now - (row["held_at"] if isinstance(row.get("held_at"), (int, float)) else now) for row in held]
        recent = sum(age < HELD_WINDOW_S for age in ages)
        day = sum(age < DAY_S for age in ages)
        if recent >= self.max_held:
            raise flex_ledger.OutcomeUnresolved(
                f"{recent} calls were held with unknown outcomes in the last {HELD_WINDOW_S // 60} minutes; new calls "
                "wait until they age out (likely a provider outage)")
        if day >= HELD_DAY_LIMIT:
            raise flex_ledger.OutcomeUnresolved(
                f"{day} calls were held with unknown outcomes in the last 24 hours; new calls wait until they age out "
                "or an operator releases them")

    def hold_stranded(self) -> tuple[list[tuple[str, float]], list[str]]:
        """Run start, under the worker lock: book and hold every pending row (a call a dead run left with no recorded
        outcome), so only its bill waits and other bills go on. Its cache entry stays pending, so the request is never
        resent by itself. Returns (held [(key, booking)], left pending): rows stay pending, refusing every new call,
        when holding them would pass CRASH_HOLD_LIMIT in a day (a crash loop)."""
        with self._lock:
            if self._inflight:
                raise RuntimeError("hold_stranded runs before any send")
        with self.spend._locked() as data:
            now = time.time()
            stranded = [(rows, key, row) for rows in data.values() for key, row in rows.items()
                        if isinstance(row, dict) and row.get("state") == "pending"]
            if not stranded:
                return [], []
            recent = sum(1 for rows in data.values() for row in rows.values()
                         if isinstance(row, dict) and row.get("error_type") == STRANDED
                         and isinstance(row.get("held_at"), (int, float)) and now - row["held_at"] < DAY_S)
            if recent + len(stranded) > CRASH_HOLD_LIMIT:
                return [], sorted(key for _rows, key, _row in stranded)
            held = []
            for rows, key, row in stranded:
                bound = float(row.get("reserved", 0))
                rows[key] = {"state": "returned", "cost": bound, "reserved": 0, "held": True, "held_at": now,
                             "error_type": STRANDED, "auto": True}
                held.append((key, bound))
            self.spend._save(data)
            return sorted(held), []

    def pending_rows(self) -> list[tuple[str, str, dict]]:
        """(day, request key, row) for every pending row: a call with no recorded outcome (e.g. a crash mid-send)."""
        with self.spend._locked() as data:
            return [(day, key, row) for day, rows in data.items() for key, row in rows.items()
                    if isinstance(row, dict) and row.get("state") == "pending"]

    def hold_pending(self, key: str) -> float:
        """Operator, with no run active: turn a leftover pending row into a held call booked at its reservation, so
        new calls may go again while only its bill waits (release it later with --release). Returns the booking."""
        with self.spend._locked() as data:
            for rows in data.values():
                row = rows.get(key)
                if isinstance(row, dict) and row.get("state") == "pending":
                    bound = float(row.get("reserved", 0))
                    rows[key] = {"state": "returned", "cost": bound, "reserved": 0, "held": True,
                                 "held_at": time.time(), "error_type": STRANDED}
                    self.spend._save(data)
                    return bound
        raise KeyError(key)

    def release_held(self, key: str) -> str:
        """Operator: let one held request be sent again (e.g. after checking the provider's usage log). Its booked
        bound stays in the ledger under a renamed key; the ledger row moves first, so a failure in between leaves the
        cache refusing the resend rather than a key the ledger would refuse as AlreadyBilled. Returns the new key."""
        with self.spend._locked() as data:
            for rows in data.values():
                row = rows.get(key)
                if isinstance(row, dict) and row.get("held") is True:
                    released = f"{key}:released-{int(time.time())}"
                    rows[released] = {**row, "held": False, "released_at": time.time()}
                    del rows[key]
                    self.spend._save(data)
                    break
            else:
                raise KeyError(key)
        self.cache.forget(key)
        return released


def main(argv=None) -> int:
    """Operator CLI: list held calls, or release one. Takes the review worker lock, so no run may be active."""
    import argparse
    parser = argparse.ArgumentParser(description="List or release held Luna calls (unknown outcome, booked at "
                                                 "their upper bound). Check the provider usage log before releasing.")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--release", metavar="REQUEST_KEY", help="let this held request be sent again")
    parser.add_argument("--hold", metavar="REQUEST_KEY",
                        help="book a leftover pending request at its reservation and hold it, so other bills go on")
    args = parser.parse_args(argv)
    try:
        lock = ResponseCache(args.cache_dir / "worker-lock")._lock("worker")
        lock.__enter__()
    except CacheBusy:
        print("A review run is active; try again when it ends", file=sys.stderr)
        return 1
    try:
        boundary = FlexBoundary(args.cache_dir, None, None)
        if args.hold:
            try:
                print("Held", args.hold, "(booked $%.6f; release it once reconciled)" % boundary.hold_pending(args.hold))
            except KeyError:
                print("No pending request", args.hold, file=sys.stderr)
                return 1
        if args.release:
            try:
                print("Released", args.release, "(booked cost kept as", boundary.release_held(args.release) + ")")
            except KeyError:
                print("No held request", args.release, "(the ledger has no held row for it)", file=sys.stderr)
                return 1
        for day, key, row in boundary.pending_rows():
            print(day, key, "pending (no recorded outcome; settle with --hold %s)" % key)
        for day, key, row in boundary.held():
            print(day, key, "booked $%.6f" % row.get("cost", 0), row.get("error_type", ""))
    finally:
        lock.__exit__(None, None, None)
    return 0


def _default_openai():
    try:
        from openai import OpenAI
    except ImportError:
        raise NotSent("Install requirements-extraction.txt before execution") from None
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise NotSent("OPENAI_API_KEY is required for execution on a cache miss")
    return OpenAI(api_key=key, base_url="https://api.openai.com/v1", timeout=900, max_retries=0)


# Last, so the CLI sees every module-level name (it once ran before _default_openai existed: NameError).
if __name__ == "__main__":
    raise SystemExit(main())
