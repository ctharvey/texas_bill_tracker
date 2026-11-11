"""Shared error types. Every module raises these; nothing stores provider messages (they can echo prompts)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(str, Enum):
    CAPACITY = "capacity"        # 429 flex_unavailable / resource_unavailable: not billed, wait it out
    RATE_LIMIT = "rate_limit"    # 429 rate_limit_exceeded (or a 402 with a retry hint): not billed, back off
    QUOTA = "quota"              # insufficient_quota, billing_hard_limit_reached, credit_balance_*: stop
    AUTH = "auth"                # 401/403: stop
    TIMEOUT = "timeout"          # read timeout or 408: the request may have been billed
    CONNECTION = "connection"    # transport failure; billed only if the request may have been sent
    SERVER = "server"            # 5xx response
    BAD_REQUEST = "bad_request"  # 400/404/409/422: fix the request
    OTHER = "other"


@dataclass(frozen=True)
class ErrorInfo:
    kind: Kind
    status: int | None = None
    code: str | None = None
    type: str | None = None
    request_id: str | None = None
    retry_after_s: float | None = None
    maybe_billed: bool = False   # True when the provider may have processed (and charged) the request

    def label(self) -> str:
        """Log-safe description: identifiers only, never the provider's message."""
        parts = [self.kind.value]
        for name in ("status", "code", "type", "request_id"):
            value = getattr(self, name)
            if value is not None:
                parts.append(f"{name}={value}")
        if self.retry_after_s is not None:
            parts.append(f"retry_after={self.retry_after_s:g}s")
        return ", ".join(parts)


class FlexError(RuntimeError):
    """Base class. `info` is set when the failure came from a provider response or transport error."""

    def __init__(self, message: str, info: ErrorInfo | None = None):
        super().__init__(message)
        self.info = info


class NotSent(FlexError):
    """The request certainly did not reach the provider (a pre-send refusal or a wait). Safe to send later.

    `halts_run` tells a batch runner whether the refusal blocks all further work (True) or only this item."""

    halts_run: bool = False


class Cancelled(NotSent):
    """The caller's cancel event stopped a resend. Nothing pending was sent; stop the run."""

    halts_run = True


class Stopped(FlexError):
    """Not retryable (quota, auth, bad request, attempts or deadline exhausted). Not billed unless info says so."""


class Deferred(NotSent):
    """Capacity or rate-limit wait too long to sleep through; retry at `retry_at` (epoch seconds). Not billed."""

    def __init__(self, message: str, retry_at: float, info: ErrorInfo | None = None):
        super().__init__(message, info)
        self.retry_at = retry_at


class UncertainOutcome(FlexError):
    """The request may have been processed and billed (timeout, connection drop after send). Never resend blindly."""


class TierMismatch(FlexError):
    """The provider answered on a different service tier (billed at that tier). Carries the raw response."""

    def __init__(self, message: str, response: dict):
        super().__init__(message)
        self.response = response


class AttemptFailed(FlexError):
    """One send attempt failed. `sent` records whether it reached the provider, decided by the adapter at the point
    where that was known ("not_sent" or "maybe_sent"). `info` describes the failure for retry decisions."""

    def __init__(self, message: str, info: ErrorInfo, sent: str):
        if sent not in ("not_sent", "maybe_sent"):
            raise ValueError("sent must be 'not_sent' or 'maybe_sent'")
        super().__init__(message, info)
        self.sent = sent


class UnrecordedResponse(FlexError):
    """A reply arrived (billed) but a layer failed to record it. Carries the raw response; never resend."""

    def __init__(self, message: str, response: object):
        super().__init__(message)
        self.response = response


class IncompleteResponse(FlexError):
    """A Responses API reply whose status is not 'completed' (billed). Carries the raw response."""

    def __init__(self, message: str, response: dict):
        super().__init__(message)
        self.response = response
