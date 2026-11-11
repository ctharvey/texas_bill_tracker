"""Flex client: send, classify, decide, sleep. Sync and async variants share one state machine."""
from __future__ import annotations

import asyncio
import contextvars
import inspect
import threading
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from .errors import classify, outcome_of
from .exceptions import (
    Cancelled,
    Deferred,
    ErrorInfo,
    IncompleteResponse,
    Kind,
    NotSent,
    Stopped,
    TierMismatch,
    UncertainOutcome,
    UnrecordedResponse,
)
from .policy import RetryPolicy, decide

#: Maybe-billed attempts behind the calls made in this context. Each FlexClient call adds its own count on every
#: exit (success or failure). A layer that settles spend (ledger, batch) saves the prior value, sets 0, calls, reads
#: n, then restores prior + n, so nested layers neither lose nor double-read it. Lost if the send runs in another
#: thread or task.
uncertain_attempts: contextvars.ContextVar[int] = contextvars.ContextVar("cth_flex_uncertain_attempts", default=0)

# Errors that are already a final decision by an inner layer; the client never retries or re-labels them.
_TERMINAL = (NotSent, Stopped, UncertainOutcome, TierMismatch, IncompleteResponse, UnrecordedResponse)


@dataclass(frozen=True)
class Event:
    kind: Literal["retry", "defer", "stop", "success"]
    attempt: int
    wait_s: float
    label: str
    elapsed_s: float


def flex_request(body: dict) -> dict:
    """Copy of `body` with service_tier set to flex."""
    request = dict(body)
    request["service_tier"] = "flex"
    return request


class _Run:
    """State of one `call`: attempt counters per Kind and the event trail."""

    def __init__(self, client: _Base, deadline: float | None, call_budget_s: float | None):
        self.c = client
        self.deadline = deadline
        self.call_budget_s = call_budget_s
        self.start = client._clock()
        self.counts: dict[object, int] = {}
        self.total = 0
        self.tainted = False
        self.maybe_billed = 0  # failures of this call that may have been billed

    def publish(self) -> None:
        uncertain_attempts.set(uncertain_attempts.get() + self.maybe_billed)

    def cancelled(self) -> BaseException:
        """The terminal error when the caller's cancel event stops a resend."""
        self._emit("stop", self.total, 0.0, "cancelled")
        if self.tainted:
            return UncertainOutcome("outcome unknown, not resent: cancelled after a maybe-billed attempt",
                                    ErrorInfo(Kind.OTHER, maybe_billed=True))
        return Cancelled("cancelled before resend; nothing pending was sent")

    def _emit(self, kind: str, attempt: int, wait_s: float, label: str) -> None:
        if self.c._on_event is None:
            return
        try:
            self.c._on_event(Event(kind, attempt, wait_s, label, self.c._clock() - self.start))  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - a broken observer must not change retry behaviour
            pass

    def on_error(self, exc: BaseException) -> float:
        """Return seconds to sleep before the next attempt, or raise the terminal error."""
        self.total += 1
        if isinstance(exc, _TERMINAL):
            # An inner layer (cache, ledger, another client) already decided: keep its type, retry_at, halts_run and
            # any billed response. Only an earlier maybe-billed attempt of this call can override a "not sent".
            label = exc.info.label() if isinstance(exc.info, ErrorInfo) else type(exc).__name__
            self._emit("stop", self.total, 0.0, label)
            if self.tainted and outcome_of(exc) == "not_sent":
                raise UncertainOutcome(f"outcome unknown, not resent: {label} after a maybe-billed attempt",
                                       ErrorInfo(Kind.OTHER, maybe_billed=True)) from exc
            raise exc
        info = classify(exc)
        self.tainted = self.tainted or info.maybe_billed
        if info.maybe_billed:
            self.maybe_billed += 1
        # Maybe-billed failures share one resend budget across kinds: each such resend may pay again.
        counter: object = "uncertain" if info.maybe_billed else info.kind
        attempt = self.counts.get(counter, 0) + 1
        self.counts[counter] = attempt
        now = self.c._clock()
        decision = decide(
            self.c._policy, info, attempt, now=now, deadline=self.deadline,
            call_budget_s=self.call_budget_s, rng=self.c._rng,
        )
        label = info.label()
        if decision.action == "retry":
            self._emit("retry", attempt, decision.wait_s, label)
            return decision.wait_s
        if self.tainted and not info.maybe_billed:
            # An earlier attempt of this call may have been billed (retry_uncertain resent it): the call as a whole
            # stays maybe-billed whatever the last attempt says, so it ends uncertain, never Stopped or Deferred.
            info = replace(info, maybe_billed=True)
        if decision.action == "defer" and not info.maybe_billed:
            self._emit("defer", attempt, decision.wait_s, label)
            raise Deferred(
                f"deferred: {label}; retry in {decision.wait_s:g}s",
                retry_at=now + decision.wait_s, info=info,
            ) from exc
        self._emit("stop", attempt, 0.0, label)
        if info.maybe_billed:
            raise UncertainOutcome(f"outcome unknown, not resent: {label} ({decision.reason})", info) from exc
        raise Stopped(f"stopped: {label} ({decision.reason})", info) from exc

    def on_response(self, response: Any) -> Any:
        tier = response.get("service_tier") if isinstance(response, dict) else getattr(response, "service_tier", None)
        status = response.get("status") if isinstance(response, dict) else getattr(response, "status", None)
        require_tier = self.c._require_tier
        # A missing tier is a mismatch too: billing at Flex rates cannot be confirmed (texas refused these).
        if require_tier and tier != require_tier:
            self._emit("stop", self.total + 1, 0.0, f"tier_mismatch, tier={tier}")
            raise TierMismatch(f"response served on tier {tier!r}, required {require_tier!r}", response)
        if self.c._require_completed and status is not None and status != "completed":
            self._emit("stop", self.total + 1, 0.0, f"incomplete, status={status}")
            raise IncompleteResponse(f"response status {status!r}, required 'completed'", response)
        self._emit("success", self.total + 1, 0.0, "ok")
        return response


class _Base:
    def __init__(
        self,
        send: Callable[[dict], Any],
        *,
        policy: RetryPolicy | None = None,
        require_tier: str | None = "flex",
        require_completed: bool = True,
        sleep: Callable[[float], Any] | None = None,
        clock: Callable[[], float] = time.time,
        on_event: Callable[[Event], Any] | None = None,
        rng: random.Random | None = None,
        cancel: threading.Event | None = None,
    ):
        self._cancel = cancel
        self._send = send
        self._policy = policy if policy is not None else RetryPolicy()
        self._require_tier = require_tier
        self._require_completed = require_completed
        self._sleep = sleep
        self._clock = clock
        self._on_event = on_event
        self._rng = rng


class FlexClient(_Base):
    """`cancel`: an event that, once set, stops further resends (`Cancelled`, or `UncertainOutcome` if an earlier
    attempt may have been billed). With the default sleep, a backoff wait ends early when it is set."""

    def __init__(self, send, *, policy=None, require_tier="flex", require_completed=True,
                 sleep=time.sleep, clock=time.time, on_event=None, rng=None, cancel=None):
        super().__init__(send, policy=policy, require_tier=require_tier, require_completed=require_completed,
                         sleep=sleep, clock=clock, on_event=on_event, rng=rng, cancel=cancel)

    def call(self, request: dict, *, deadline: float | None = None, call_budget_s: float | None = None) -> dict:
        run = _Run(self, deadline, call_budget_s)
        try:
            while True:
                try:
                    response = self._send(request)
                except Exception as exc:  # noqa: BLE001 - classified below
                    wait = run.on_error(exc)
                    cancel = self._cancel
                    if cancel is None:
                        self._sleep(wait)
                        continue
                    if cancel.is_set():
                        raise run.cancelled() from exc
                    if self._sleep is time.sleep:
                        cancel.wait(wait)
                    else:
                        self._sleep(wait)
                    if cancel.is_set():
                        raise run.cancelled() from exc
                    continue
                return run.on_response(response)
        finally:
            run.publish()


class AsyncFlexClient(_Base):
    """Async variant. `cancel` is checked before and after each backoff wait; it never blocks the event loop."""

    def __init__(self, send, *, policy=None, require_tier="flex", require_completed=True,
                 sleep=asyncio.sleep, clock=time.time, on_event=None, rng=None, cancel=None):
        super().__init__(send, policy=policy, require_tier=require_tier, require_completed=require_completed,
                         sleep=sleep, clock=clock, on_event=on_event, rng=rng, cancel=cancel)

    async def call(self, request: dict, *, deadline: float | None = None,
                   call_budget_s: float | None = None) -> dict:
        run = _Run(self, deadline, call_budget_s)
        try:
            while True:
                try:
                    response = self._send(request)
                    if inspect.isawaitable(response):
                        response = await response
                except Exception as exc:  # noqa: BLE001 - classified below
                    wait = run.on_error(exc)
                    if self._cancel is not None and self._cancel.is_set():
                        raise run.cancelled() from exc
                    result = self._sleep(wait)
                    if inspect.isawaitable(result):
                        await result
                    if self._cancel is not None and self._cancel.is_set():
                        raise run.cancelled() from exc
                    continue
                return run.on_response(response)
        finally:
            run.publish()
