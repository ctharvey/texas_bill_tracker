"""Senders that plug SDK or HTTP clients into `FlexClient`. openai and httpx are imported lazily, only here.

Sender contract: one `send()` call makes at most one HTTP attempt. The adapters enforce it: SDK clients are rebuilt
with `max_retries=0` (or refused), so a possibly billed request is never resent behind the Flex client's back.
Adapters record whether a failed attempt reached the provider (`AttemptFailed.sent`) where that is known.
"""
from __future__ import annotations

import inspect
import os
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any

from .errors import FlexHTTPError, _mro_names, _never_connected, classify
from .exceptions import AttemptFailed, ErrorInfo, Kind

#: Request keys the OpenAI SDK signatures do not accept; they travel in `extra_body`.
DEFAULT_EXTRA_BODY_KEYS = frozenset({"prompt_cache_options"})

_SDK_TRANSPORT = frozenset({"APIConnectionError", "APITimeoutError"})


def _without_sdk_retries(client: Any) -> tuple[Any, bool]:
    """The client to call, and whether SDK retries are provably off (only then may an SDK error be read as not
    sent). A client without `with_options` is accepted when it does not claim retries, but its errors are never
    translated: it may be a wrapper over a retrying client."""
    with_options = getattr(client, "with_options", None)
    if callable(with_options):
        return with_options(max_retries=0), True
    retries = getattr(client, "max_retries", 0)
    if isinstance(retries, bool) or not isinstance(retries, int) or retries != 0:
        raise ValueError(
            f"OpenAI client has max_retries={retries!r} and no with_options(); build it with max_retries=0 so a "
            "possibly billed request is never resent by the SDK"
        )
    return client, False


def _split_request(request: dict, extra_body_keys: Iterable[str]) -> dict:
    arguments = dict(request)
    extra = dict(arguments.pop("extra_body", None) or {})
    for key in extra_body_keys:
        if key in arguments:
            extra[key] = arguments.pop(key)
    if extra:
        arguments["extra_body"] = extra
    return arguments


def _translate(exc: Exception) -> Exception:
    """The SDK wraps transport errors one level deep. With SDK retries off, a wrapped never-connected error proves the
    single attempt never reached the provider. Everything else is left for `outcome_of` to judge."""
    if _SDK_TRANSPORT & _mro_names(exc) and exc.__cause__ is not None and _never_connected(exc.__cause__):
        info = replace(classify(exc), maybe_billed=False)
        return AttemptFailed(f"not sent: {info.label()}", info, sent="not_sent")
    return exc


def _dump(response: Any) -> Any:
    try:
        return response.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - the call succeeded, so it was billed
        raise AttemptFailed("reply received but could not be decoded", ErrorInfo(Kind.OTHER, maybe_billed=True),
                            sent="maybe_sent") from exc


def _sender(method: Callable[..., Any], extra_body_keys: Iterable[str], no_retries: bool) -> Callable[[dict], Any]:
    keys = tuple(extra_body_keys)
    translate = _translate if no_retries else (lambda exc: exc)

    def send(request: dict) -> Any:
        try:
            result = method(**_split_request(request, keys))
        except Exception as exc:  # noqa: BLE001 - translated or re-raised unchanged
            translated = translate(exc)
            if translated is exc:
                raise
            raise translated from exc
        if inspect.isawaitable(result):
            async def finish() -> Any:
                try:
                    reply = await result
                except Exception as exc:  # noqa: BLE001
                    translated = translate(exc)
                    if translated is exc:
                        raise
                    raise translated from exc
                return _dump(reply)
            return finish()
        return _dump(result)

    return send


def openai_responses_sender(client: Any, *, extra_body_keys: Iterable[str] = DEFAULT_EXTRA_BODY_KEYS):
    """Sender calling `client.responses.create(**request)` with SDK retries off; returns the response as a dict."""
    client, no_retries = _without_sdk_retries(client)
    return _sender(client.responses.create, extra_body_keys, no_retries)


def openai_chat_sender(client: Any, *, extra_body_keys: Iterable[str] = DEFAULT_EXTRA_BODY_KEYS):
    """Sender calling `client.chat.completions.create(**request)` with SDK retries off; returns a dict."""
    client, no_retries = _without_sdk_retries(client)
    return _sender(client.chat.completions.create, extra_body_keys, no_retries)


def _json_or_none(response: Any) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001 - error bodies are not always JSON
        return None


def httpx_sender(
    *,
    base_url: str = "https://api.openai.com",
    endpoint: str = "/v1/responses",
    api_key: str | None = None,
    timeout_s: float = 900,
    client: Any = None,
) -> Callable[[dict], dict]:
    """Sender posting the request as JSON. Raises `FlexHTTPError` on a non-2xx status.

    The API key is resolved here, so nothing pre-send can fail inside `send()`."""
    key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY is required (or pass api_key=)")
    url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def send(request: dict) -> dict:
        http = client
        owned = False
        if http is None:
            import httpx

            http = httpx.Client(timeout=timeout_s)
            owned = True
        try:
            response = http.post(url, json=request, headers=headers, timeout=timeout_s)
            status = response.status_code
            if not 200 <= status < 300:
                raise FlexHTTPError(status, response.headers, _json_or_none(response))
            try:
                return response.json()
            except Exception as exc:  # noqa: BLE001 - a 2xx arrived: billed
                raise AttemptFailed("reply received but could not be decoded",
                                    ErrorInfo(Kind.OTHER, status=status, maybe_billed=True),
                                    sent="maybe_sent") from exc
        finally:
            if owned:
                http.close()

    return send
