"""Token usage and cost. Rates are USD per 1M tokens; cached and cache-write tokens are subsets of input tokens."""
from __future__ import annotations

import json
from dataclasses import dataclass

_WRITE_LIFETIMES = {"ttl_30m_tokens", "ttl_12h_tokens"}


@dataclass(frozen=True)
class Usage:
    input_tokens: int            # total prompt tokens, including cached reads and cache writes
    cached_tokens: int = 0       # subset of input_tokens billed at the cached rate
    cache_write_30m: int = 0     # subset of input_tokens billed at the 30-minute cache-write rate
    cache_write_12h: int = 0     # subset of input_tokens billed at the 12-hour cache-write rate
    output_tokens: int = 0
    reasoning_tokens: int = 0    # subset of output_tokens (already billed as output)

    def __post_init__(self):
        values = (self.input_tokens, self.cached_tokens, self.cache_write_30m, self.cache_write_12h,
                  self.output_tokens, self.reasoning_tokens)
        if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
            raise ValueError("Token counts must be integers")
        if min(values) < 0:
            raise ValueError("Negative token count")
        if self.cached_tokens + self.cache_write_30m + self.cache_write_12h > self.input_tokens:
            raise ValueError("Cached and cache-write tokens exceed input tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("Reasoning tokens exceed output tokens")


@dataclass(frozen=True)
class Rates:
    input: float
    cached_input: float
    output: float
    cache_write_30m: float | None = None
    cache_write_12h: float | None = None


def _num(mapping: dict, name: str, default: int | None = 0) -> int:
    value = mapping.get(name, default)
    if value is None:
        value = 0
    return value


def usage_from_response(resp: dict) -> Usage:
    """Read usage from a Responses or Chat Completions body. Raises ValueError when absent or inconsistent."""
    usage = resp.get("usage") if isinstance(resp, dict) else None
    if not isinstance(usage, dict):
        raise ValueError("Response has no usage")
    if "input_tokens" in usage:
        total, output = usage["input_tokens"], usage.get("output_tokens", 0)
        details = usage.get("input_tokens_details") or {}
        out_details = usage.get("output_tokens_details") or {}
    elif "prompt_tokens" in usage:
        total, output = usage["prompt_tokens"], usage.get("completion_tokens", 0)
        details = usage.get("prompt_tokens_details") or {}
        out_details = usage.get("completion_tokens_details") or {}
    else:
        raise ValueError("Unrecognized usage shape")
    cached = _num(details, "cached_tokens")
    writes = _num(details, "cache_write_tokens")
    lifetimes = details.get("cache_write_tokens_details")
    short = long = 0
    if lifetimes is not None:
        if (not isinstance(lifetimes, dict) or set(lifetimes) - _WRITE_LIFETIMES
                or sum(lifetimes.values()) != writes):
            raise ValueError("Unrecognized provider cache-write accounting")
        short, long = lifetimes.get("ttl_30m_tokens", 0), lifetimes.get("ttl_12h_tokens", 0)
    else:
        # Lifetime not reported: bill at the 12-hour rate, the higher one, so the estimate is an upper bound.
        long = writes
    return Usage(total, cached, short, long, output, _num(out_details, "reasoning_tokens"))


def _write_rate(rate: float | None, name: str, tokens: int) -> float:
    if tokens and rate is None:
        raise ValueError(f"Rates.{name} is required for cache-write tokens")
    return rate or 0.0


def cost_usd(usage: Usage, rates: Rates) -> float:
    ordinary = usage.input_tokens - usage.cached_tokens - usage.cache_write_30m - usage.cache_write_12h
    total = (ordinary * rates.input + usage.cached_tokens * rates.cached_input
             + usage.output_tokens * rates.output
             + usage.cache_write_30m * _write_rate(rates.cache_write_30m, "cache_write_30m", usage.cache_write_30m)
             + usage.cache_write_12h * _write_rate(rates.cache_write_12h, "cache_write_12h", usage.cache_write_12h))
    return total / 1e6


# Hidden input is detected by a whitelist at known input positions only: anything not known to be carried in the
# request bytes counts as hidden. Schemas, metadata and tool parameter definitions are never walked.
_SERVER_CONTEXT_KEYS = ("previous_response_id", "conversation", "web_search_options")
_LOCAL_TOOL_TYPES = frozenset({"function", "custom"})
_LOCAL_ITEM_TYPES = frozenset({"message", "function_call", "function_call_output", "custom_tool_call",
                               "custom_tool_call_output"})
_LOCAL_PART_TYPES = frozenset({"input_text", "output_text", "text", "refusal"})
_LOCAL_CHAT_PART_TYPES = frozenset({"text", "refusal"})


def _content_hidden(content: object, local_types: frozenset) -> bool:
    if content is None or isinstance(content, str):
        return False
    if not isinstance(content, list):
        return True
    return any(not isinstance(p, dict) or p.get("type") not in local_types for p in content)


def _item_hidden(item: object) -> bool:
    if not isinstance(item, dict):
        return True
    kind = item.get("type", "message" if "role" in item else None)
    if kind == "reasoning":
        return not item.get("encrypted_content")  # a reasoning item given by id alone is loaded server-side
    if kind not in _LOCAL_ITEM_TYPES:
        return True  # item_reference, hosted tool calls, unknown items
    return kind == "message" and _content_hidden(item.get("content"), _LOCAL_PART_TYPES)


def _hidden_input(request: dict) -> bool:
    """True when the bill includes input the request bytes do not bound: server-side state, hosted tools, media."""
    if any(request.get(key) is not None for key in _SERVER_CONTEXT_KEYS):
        return True
    if isinstance(request.get("prompt"), dict):  # a stored prompt reference; a string prompt is in the bytes
        return True
    tools = request.get("tools")
    if tools is not None and (not isinstance(tools, list) or any(
            not isinstance(t, dict) or t.get("type") not in _LOCAL_TOOL_TYPES for t in tools)):
        return True
    inputs = request.get("input")
    if isinstance(inputs, list):
        if any(_item_hidden(item) for item in inputs):
            return True
    elif inputs is not None and not isinstance(inputs, str):
        return True
    messages = request.get("messages")
    if messages is not None:
        if not isinstance(messages, list):
            return True
        for message in messages:
            if not isinstance(message, dict) or _content_hidden(message.get("content"), _LOCAL_CHAT_PART_TYPES):
                return True
    return False


def _count(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return value


def reservation_usd(request: dict, rates: Rates, default_output_tokens: int | None = None, *,
                    extra_input_tokens: int | None = None) -> float:
    """Upper bound before send: UTF-8 request bytes bound the input tokens (one token per byte at the highest
    input-side rate), plus `extra_input_tokens` (always added when given), plus the output cap times `n`.
    Raises ValueError when the request has input the bytes cannot bound and `extra_input_tokens` is missing."""
    if extra_input_tokens is not None:
        _count(extra_input_tokens, "extra_input_tokens", 0)
    size = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    cap = None
    for name in ("max_output_tokens", "max_completion_tokens", "max_tokens"):
        if request.get(name) is not None:
            cap = _count(request[name], name, 0)
            break
    if cap is None and default_output_tokens is not None:
        cap = _count(default_output_tokens, "default_output_tokens", 0)
    if cap is None:
        raise ValueError("Request has no output token cap; pass default_output_tokens")
    if _hidden_input(request) and extra_input_tokens is None:
        raise ValueError("Request uses server-side or media input; pass extra_input_tokens")
    size += extra_input_tokens or 0
    n = request.get("n")
    choices = 1 if n is None else _count(n, "n", 1)
    input_rate = max(r for r in (rates.input, rates.cached_input, rates.cache_write_30m, rates.cache_write_12h)
                     if r is not None)
    return (size * input_rate + cap * choices * rates.output) / 1e6
