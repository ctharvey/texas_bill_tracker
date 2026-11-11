"""Retry policy: a pure decision function. No sleeping, no clock reads, no I/O."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from .exceptions import ErrorInfo, Kind


@dataclass(frozen=True)
class RetryPolicy:
    capacity_attempts: int = 8
    rate_limit_attempts: int = 6
    base_s: float = 15.0
    cap_s: float = 300.0
    jitter: bool = True
    max_hint_s: float = 900.0
    defer_over_s: float | None = None
    retry_server_errors: bool = False
    server_attempts: int = 3
    retry_uncertain: bool = False
    deadline_reserve_fraction: float = 1 / 3


@dataclass(frozen=True)
class Decision:
    action: Literal["retry", "defer", "stop"]
    wait_s: float
    reason: str


def attempts_allowed(policy: RetryPolicy, info: ErrorInfo) -> int | None:
    """Attempts budget for the error, or None when the error is not retryable under this policy."""
    kind = info.kind
    if info.maybe_billed:
        # A resend could pay twice: only on explicit opt-in, and only for transport-shaped failures.
        if policy.retry_uncertain and kind in (Kind.TIMEOUT, Kind.CONNECTION, Kind.SERVER):
            return policy.server_attempts
        return None
    if kind is Kind.CAPACITY:
        return policy.capacity_attempts
    if kind is Kind.RATE_LIMIT:
        return policy.rate_limit_attempts
    if kind is Kind.SERVER:
        return policy.server_attempts if policy.retry_server_errors else None
    if kind in (Kind.CONNECTION, Kind.TIMEOUT):  # proven not sent (never connected): safe to resend
        return policy.server_attempts
    return None


def backoff_s(policy: RetryPolicy, attempt: int, rng: random.Random | None = None) -> float:
    exponent = max(0, min(attempt - 1, 60))
    b = min(policy.cap_s, policy.base_s * (2 ** exponent))
    if policy.jitter:
        return (rng or random).uniform(b / 2, b)
    return b


def decide(
    policy: RetryPolicy,
    info: ErrorInfo,
    attempt: int,
    *,
    now: float,
    deadline: float | None = None,
    call_budget_s: float | None = None,
    rng: random.Random | None = None,
) -> Decision:
    allowed = attempts_allowed(policy, info)
    if allowed is None:
        return Decision("stop", 0.0, f"{info.kind.value} is not retryable")
    if attempt >= allowed:
        return Decision("stop", 0.0, f"{info.kind.value} attempts spent ({attempt}/{allowed})")
    wait = backoff_s(policy, attempt, rng)
    if info.retry_after_s is not None:
        wait = max(wait, min(info.retry_after_s, policy.max_hint_s))
    if policy.defer_over_s is not None and wait > policy.defer_over_s:
        return Decision("defer", wait, f"wait {wait:g}s exceeds defer threshold {policy.defer_over_s:g}s")
    if deadline is not None:
        reserve = policy.deadline_reserve_fraction * call_budget_s if call_budget_s else 0.0
        if now + wait + reserve > deadline:
            return Decision("stop", wait, "deadline would be missed")
    return Decision("retry", wait, f"{info.kind.value} retry {attempt}/{allowed}")
