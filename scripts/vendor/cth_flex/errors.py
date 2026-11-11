"""Classify provider and transport failures into `ErrorInfo`. Never raises, never returns provider message text."""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Literal

from .exceptions import (AttemptFailed, ErrorInfo, FlexError, IncompleteResponse, Kind, NotSent, Stopped,
                         TierMismatch, UncertainOutcome, UnrecordedResponse)
from .retry_after import parse_retry_after

_MAX_DEPTH = 8
_SAFE_TOKEN = re.compile(r"[a-z0-9_.-]+")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]+")
_TOKEN_MAX = 80

_BILLING_CODES = frozenset({"insufficient_quota", "billing_hard_limit_reached", "provider_quota_exhausted"})
_BILLING_PREFIXES = ("credit_balance_",)
_BILLING_MESSAGE_MARKERS = ("exceeded your current quota",)
_CAPACITY_CODES = frozenset({"flex_unavailable", "resource_unavailable"})
_CAPACITY_MESSAGE_MARKERS = ("does not have sufficient resources", "resource unavailable")
_TRANSIENT_402_REASONS = frozenset({"in_flight_budget_exhausted"})


class FlexHTTPError(Exception):
    """A non-2xx HTTP response from a raw-HTTP sender. Carries no message text beyond the status."""

    def __init__(self, status: int, headers: Any = None, body: Any = None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.headers = headers if headers is not None else {}
        self.body = body


def _token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()[:_TOKEN_MAX]
    return text if _SAFE_TOKEN.fullmatch(text) else None


def _id_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()[:_TOKEN_MAX]
    return text if _SAFE_ID.fullmatch(text) else None


def _is_billing(code: str | None, type_: str | None, message: str) -> bool:
    for value in (code, type_):
        if value and (value in _BILLING_CODES or value.startswith(_BILLING_PREFIXES)):
            return True
    return any(marker in message for marker in _BILLING_MESSAGE_MARKERS)


def _error_dict(body: Any) -> dict:
    if isinstance(body, dict):
        inner = body.get("error")
        if isinstance(inner, dict):
            return inner
        return body
    return {}


def _int_status(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 999:
        return value
    return None


def _mro_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def _transport_info(exc: BaseException) -> ErrorInfo | None:
    names = _mro_names(exc)
    request_id = _id_token(getattr(exc, "request_id", None))
    if "ConnectTimeout" in names or "ConnectError" in names or isinstance(exc, ConnectionRefusedError):
        return ErrorInfo(Kind.CONNECTION, request_id=request_id, maybe_billed=False)
    if (
        "APITimeoutError" in names
        or "TimeoutException" in names
        or isinstance(exc, TimeoutError)
        or any(n.endswith("Timeout") for n in names)
    ):
        return ErrorInfo(Kind.TIMEOUT, request_id=request_id, maybe_billed=True)
    if "APIConnectionError" in names or "TransportError" in names or isinstance(exc, ConnectionError):
        return ErrorInfo(Kind.CONNECTION, request_id=request_id, maybe_billed=True)
    return None


def _from_status(status: int, headers: Any, body: Any, code: str | None, type_: str | None,
                 message: str, request_id: str | None) -> ErrorInfo:
    hint = parse_retry_after(headers, body)

    def info(kind: Kind, maybe_billed: bool = False) -> ErrorInfo:
        return ErrorInfo(kind, status=status, code=code, type=type_, request_id=request_id,
                         retry_after_s=hint, maybe_billed=maybe_billed)

    if 200 <= status < 300:
        return info(Kind.OTHER, True)  # received after a success status: billed
    if status == 401:
        return info(Kind.AUTH)
    if 400 <= status < 500 and _is_billing(code, type_, message):
        return info(Kind.QUOTA)
    if status == 403:
        return info(Kind.AUTH)
    if status == 402:
        metadata = _error_dict(body).get("metadata")
        reason = metadata.get("reason") if isinstance(metadata, dict) else None
        if hint is not None or reason in _TRANSIENT_402_REASONS:
            return info(Kind.RATE_LIMIT)
        return info(Kind.QUOTA)
    if status == 429:
        if code in _CAPACITY_CODES or type_ in _CAPACITY_CODES or any(
            marker in message for marker in _CAPACITY_MESSAGE_MARKERS
        ):
            return info(Kind.CAPACITY)
        return info(Kind.RATE_LIMIT)
    if status == 408:
        return info(Kind.TIMEOUT, True)
    if status == 504 or 520 <= status <= 527:
        return info(Kind.SERVER, True)  # a gateway timed out waiting on the origin: it may have processed it
    if 500 <= status < 600:
        return info(Kind.SERVER)
    if status in (400, 404, 409, 422):
        return info(Kind.BAD_REQUEST)
    return info(Kind.OTHER)


def _classify_one(exc: BaseException) -> ErrorInfo | None:
    status = _int_status(getattr(exc, "status_code", None))
    if status is None:
        status = _int_status(getattr(exc, "status", None))
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = _int_status(getattr(response, "status_code", None))
    if status is None:
        return _transport_info(exc)
    headers = getattr(exc, "headers", None) or getattr(response, "headers", None)
    body = getattr(exc, "body", None)
    if body is None and response is not None and callable(getattr(response, "json", None)):
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - unread or non-JSON body
            body = None
    err = _error_dict(body)
    raw_code = getattr(exc, "code", None)
    raw_type = getattr(exc, "type", None)
    code = _token(raw_code if isinstance(raw_code, str) else err.get("code"))
    type_ = _token(raw_type if isinstance(raw_type, str) else err.get("type"))
    raw_message = getattr(exc, "message", None)
    if not isinstance(raw_message, str):
        raw_message = err.get("message")
    message = raw_message.lower() if isinstance(raw_message, str) else ""
    request_id = _id_token(getattr(exc, "request_id", None))
    return _from_status(status, headers, body, code, type_, message, request_id)


def _own_status(exc: BaseException) -> int | None:
    """The HTTP status carried by this exception itself (never its chain)."""
    status = _int_status(getattr(exc, "status_code", None))
    if status is None:
        status = _int_status(getattr(exc, "status", None))
    if status is None:
        status = _int_status(getattr(getattr(exc, "response", None), "status_code", None))
    return status


def _status_not_sent(status: int) -> bool:
    """True when a response with this status proves the provider did not process (bill) the request."""
    if 400 <= status <= 499:
        return status not in (408, 499)
    return 500 <= status <= 503 or 505 <= status <= 519


_NOT_CONNECTED = frozenset({"ConnectError", "ConnectTimeout", "PoolTimeout"})


def _never_connected(exc: BaseException) -> bool:
    return bool(_NOT_CONNECTED & _mro_names(exc)) or isinstance(exc, ConnectionRefusedError)


def _sdk_retried(exc: BaseException) -> bool:
    """True when the exception's own request says the OpenAI SDK had already retried (x-stainless-retry-count > 0).
    A missing header proves nothing either way; the adapters are what guarantee a single attempt."""
    try:  # httpx raises RuntimeError, not AttributeError, for an unset .request
        request = getattr(exc, "request", None)
        if request is None:
            request = getattr(getattr(exc, "response", None), "request", None)
        headers = getattr(request, "headers", None)
    except Exception:  # noqa: BLE001 - no readable request: no retry evidence
        return False
    if headers is None or not callable(getattr(headers, "get", None)):
        return False
    value = headers.get("x-stainless-retry-count")
    if not isinstance(value, str):
        return False
    try:
        return int(value.strip()) > 0
    except ValueError:
        return True  # malformed: cannot rule out a retry


Outcome = Literal["not_sent", "maybe_sent", "billed"]


def outcome_of(exc: BaseException) -> Outcome:
    """Whether a failed call reached the provider: the one authority every module branches on.

    Reads only the raised exception's own type and attributes, never its __cause__/__context__ chain: a chain records
    how errors were handled, not whether bytes reached the provider. Without direct evidence of not sent, maybe sent.
    """
    try:
        if isinstance(exc, (TierMismatch, IncompleteResponse, UnrecordedResponse)):
            return "billed"
        if isinstance(exc, AttemptFailed):
            return "not_sent" if exc.sent == "not_sent" else "maybe_sent"
        if isinstance(exc, UncertainOutcome):  # before NotSent: a type claiming both is unknown, so maybe sent
            return "maybe_sent"
        if isinstance(exc, NotSent):
            return "maybe_sent" if exc.info is not None and exc.info.maybe_billed else "not_sent"
        if isinstance(exc, Stopped):  # a client decision: not sent unless its info says otherwise
            return "maybe_sent" if exc.info is not None and exc.info.maybe_billed else "not_sent"
        if isinstance(exc, FlexError):  # any other library error: not sent only with info saying so
            return "not_sent" if isinstance(exc.info, ErrorInfo) and not exc.info.maybe_billed else "maybe_sent"
        if _sdk_retried(exc):  # an earlier attempt hidden inside the SDK may have been billed
            return "maybe_sent"
        status = _own_status(exc)
        if status is not None:
            return "not_sent" if _status_not_sent(status) else "maybe_sent"
        return "not_sent" if _never_connected(exc) else "maybe_sent"
    except Exception:  # noqa: BLE001 - a hostile exception is unknown, and unknown is maybe sent
        return "maybe_sent"


def _describe(exc: BaseException) -> ErrorInfo | None:
    if isinstance(exc, FlexError):
        return exc.info if isinstance(exc.info, ErrorInfo) else ErrorInfo(Kind.OTHER)
    return _classify_one(exc)


def classify(exc: BaseException) -> ErrorInfo:
    """Describe a failure (kind, status, code, retry hint) for retry decisions and labels.

    The description comes from the raised exception when it describes itself, otherwise from the first exception in
    its chain that does. The chain can only push towards stopping: a QUOTA or AUTH error anywhere in it wins.
    `maybe_billed` never comes from the chain: it is `outcome_of(exc) != "not_sent"`.
    """
    try:
        maybe_billed = outcome_of(exc) != "not_sent"
        infos: list[ErrorInfo] = []
        seen: set[int] = set()
        current: BaseException | None = exc
        depth = 0
        while current is not None and id(current) not in seen and depth <= _MAX_DEPTH:
            seen.add(id(current))
            found = _describe(current)
            infos.append(found)  # None keeps position 0 for the raised exception itself
            # An explicit cause is a wrapped error. An implicit context is a handled earlier error: only describe
            # through it from a plain wrapper, so a stale 401 cannot turn a fresh capacity 429 into a stop.
            if current.__cause__ is not None:
                current = current.__cause__
            elif found is None and not current.__suppress_context__:
                current = current.__context__
            else:
                current = None
            depth += 1
        described = [info for info in infos if info is not None]
        if not described:
            return ErrorInfo(Kind.OTHER, maybe_billed=maybe_billed)
        stops = [info for info in described if info.kind in (Kind.QUOTA, Kind.AUTH)]
        chosen = stops[0] if stops else (infos[0] if infos[0] is not None else described[0])
        return replace(chosen, maybe_billed=maybe_billed)
    except Exception:  # noqa: BLE001 - classification must never fail the failure path
        return ErrorInfo(Kind.OTHER, maybe_billed=True)


def classify_response(status: int, headers: Any = None, body: Any = None) -> ErrorInfo:
    try:
        return classify(FlexHTTPError(status, headers, body))
    except Exception:  # noqa: BLE001
        return ErrorInfo(Kind.OTHER)
