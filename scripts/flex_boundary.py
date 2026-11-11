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

from extraction_cache import (  # noqa: E402
    AlreadyBilled, ApiRejected, ApiStopped, BudgetExceeded, CacheBusy, CacheCoolingDown, CachedResponse,
    CapacityUnavailable, LongContext, NotSubmitted, OutcomeUnresolved, UnresolvedCall,
)

# Luna Flex short-context rates per million tokens (classify_bill.response_cost; verified 2026-11-09). With these,
# the ledger's reservation (request bytes x the highest input-side rate + output cap x output rate) is exactly the
# legacy Budget's (bytes x .125 + max_output_tokens x .25).
LUNA_RATES = Rates(input=.05, cached_input=.005, output=.25, cache_write_30m=.0625, cache_write_12h=.125)
MAX_REQUEST_BYTES = 272000  # longer requests need long-context pricing review (legacy LongContext)
LEDGER_ZONE = "America/Chicago"
# Legacy send_request: three sends 30 s then 60 s apart; a wait over 60 s (including a provider hint, honoured in
# full) hands the bill back to the worker's cooling list instead of sleeping.
TEXAS_POLICY = RetryPolicy(capacity_attempts=3, rate_limit_attempts=3, base_s=30, cap_s=60, jitter=False,
                           max_hint_s=7 * 24 * 3600, defer_over_s=60)

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
                 openai_factory=None, sleep=time.sleep, log=None):
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
        returns, a row still pending is an unknown outcome and is included."""
        with self._lock:
            mine = set(self._inflight)
        return {"pending": {key: {"state": "pending"} for key in self.spend.pending() if key not in mine}}

    def send(self, request: dict) -> dict:
        """Reserve, send and settle. Raises cth.flex errors; call it only inside `execute`."""
        self._flex_client()  # a missing SDK or key fails here, as NotSent, before anything is reserved
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
            raise translate(error) from error
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
                    self._log(f"Flex capacity unavailable; retrying in {event.wait_s:g} seconds")

            self._client = FlexClient(openai_responses_sender(sdk), policy=TEXAS_POLICY, require_tier="flex",
                                      require_completed=True, sleep=self._sleep, on_event=on_event)
        return self._client

    def _checked_send(self, request: dict) -> dict:
        try:
            response = self._flex_client().call(request)
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


def _default_openai():
    try:
        from openai import OpenAI
    except ImportError:
        raise NotSent("Install requirements-extraction.txt before execution") from None
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise NotSent("OPENAI_API_KEY is required for execution on a cache miss")
    return OpenAI(api_key=key, base_url="https://api.openai.com/v1", timeout=900, max_retries=0)
