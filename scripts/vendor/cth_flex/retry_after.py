"""Parse a server retry hint into seconds."""
from __future__ import annotations

import datetime as dt
import math
import time
from email.utils import parsedate_to_datetime
from typing import Any


def _lookup(headers: Any, name: str) -> Any:
    if not headers:
        return None
    try:
        items = list(headers.items())
    except Exception:  # noqa: BLE001 - odd header objects must not break classification
        return None
    for key, value in items:
        if isinstance(key, str) and key.lower() == name:
            return value
    return None


def _number(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _http_date(raw: Any, now: float) -> float | None:
    if not isinstance(raw, str):
        return None
    try:
        until = parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if until is None:
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=dt.timezone.utc)
    return until.timestamp() - now


def parse_retry_after(headers: Any, body: Any = None, now: float | None = None) -> float | None:
    """Seconds to wait, or None. `retry-after-ms`, then `retry-after` (seconds or HTTP date), then the
    OpenRouter body `error.metadata.headers["retry-after"]` (also accepts `metadata` at the top level)."""
    if now is None:
        now = time.time()
    raw_ms = _lookup(headers, "retry-after-ms")
    if raw_ms is not None:
        value = _number(raw_ms)
        if value is not None and value >= 0:
            return value / 1000.0
    raw = _lookup(headers, "retry-after")
    if raw is not None:
        value = _number(raw)
        if value is None:
            value = _http_date(raw, now)
        if value is not None and value >= 0:
            return value
    if isinstance(body, dict):
        error = body.get("error")
        containers = [error] if isinstance(error, dict) else []
        containers.append(body)
        for container in containers:
            metadata = container.get("metadata")
            if not isinstance(metadata, dict):
                continue
            value = _number(_lookup(metadata.get("headers"), "retry-after"))
            if value is not None and value >= 0:
                return value
    return None
