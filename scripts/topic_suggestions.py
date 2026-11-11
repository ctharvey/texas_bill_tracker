"""Second-pass topic suggestions: a cheap, cacheable Luna call per settled review, kept private.

The request is built only from the stored review and the current topic list, so a repeat is an exact
response-cache hit and a bill is re-asked only when its review or the topic list changes. Usage for the tally:
    python scripts/topic_suggestions.py --cache-dir <cache> [--min-bills 2]
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import re

import classify_bill
import extract_bill as detailed

ROOT = detailed.ROOT
FORMAT = "texas-bill-topic-suggestions-v1"
BILL_RE = re.compile(r"[A-Z]{2,4}\d{1,5}")


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _schema(topics: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["suggestions"],
            "properties": {"suggestions": {"type": "array", "maxItems": 3, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["topic", "reason", "closest_existing"],
                "properties": {"topic": {"type": "string", "minLength": 2, "maxLength": 40},
                               "reason": {"type": "string", "minLength": 1, "maxLength": 300},
                               "closest_existing": {"anyOf": [{"type": "string", "enum": topics},
                                                              {"type": "null"}]}}}}}}


def review_input(bundle: dict) -> dict:
    # No bill ID or version: identical companion reviews then send identical requests (one call, one cache hit).
    result = bundle["result"]
    return {"summary": (result.get("summary") or {}).get("text"),
            "topics": sorted(t.get("tag") for t in result.get("policy_tags") or [] if t.get("tag")),
            "major_effects": [{k: e.get(k) for k in ("effect", "label", "explanation")}
                              for e in result.get("major_effects") or []],
            "affected_groups": sorted(g.get("name") for g in result.get("affected_groups") or [] if g.get("name"))}


def build_request(bundle: dict, topics: list[str]) -> dict:
    topics = sorted(topics)
    instructions = ((ROOT / "scripts/topic_suggestions_prompt.txt").read_text("utf-8")
                    + "\nCURRENT TOPICS:\n" + _canonical(topics))
    return {
        "model": classify_bill.MODEL, "service_tier": "flex", "store": False, "reasoning": {"effort": "low"},
        "max_output_tokens": 3000, "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "text": {"format": {"type": "json_schema", "name": "texas_bill_topic_suggestions_v1", "strict": True,
                            "schema": _schema(topics)}},
        "input": [
            # Same developer text for every bill: one 12-hour prompt-cache prefix serves the whole pass.
            {"role": "developer", "content": [{"type": "input_text", "text": instructions,
                "prompt_cache_breakpoint": {"mode": "explicit", "ttl": "12h"}}]},
            {"role": "user", "content": [{"type": "input_text", "text": "REVIEW:\n" + _canonical(review_input(bundle))}]},
        ],
    }


def _norm(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9& ]+", " ", name.lower()).split())


def validate(result: dict, topics: list[str]) -> dict:
    import jsonschema
    jsonschema.Draft202012Validator(_schema(sorted(topics))).validate(result)
    existing = {_norm(t) for t in topics}
    kept, dropped = [], []
    for item in result["suggestions"]:
        (dropped if _norm(item["topic"]) in existing else kept).append(item)
    return {"errors": [], "kept": kept, "dropped": dropped, "status": "checked"}


def due(bundle: dict | None, record: dict | None, topics: list[str], retry: set[str], key_fn) -> bool:
    """A settled review (result, no queued follow-up questions) whose current request was not yet answered.

    `key_fn`: the key function of the response cache the call will go through (it differs by transport)."""
    if not isinstance(bundle, dict) or not isinstance(bundle.get("result"), dict):
        return False
    if bundle.get("bill_id") in retry:
        return False  # its review still changes when the questions run; ask once it settles
    try:
        key = key_fn(build_request(bundle, topics))
    except (KeyError, TypeError, AttributeError):
        return False
    return not isinstance(record, dict) or record.get("request_key") != key


def suggest(bundle: dict, topics: list[str], registry: list[dict], cache_root: Path, *, execute=False,
            sender=None, cache=None) -> dict:
    """One call (or cache hit). Returns the extract report; `result` is present only when it validated."""
    request = build_request(bundle, topics)

    def validator(result, document, registry, schema, key, sources=None):
        return validate(result, topics)

    return detailed.extract(bundle["document"], registry, cache_root, execute=execute, sender=sender,
                            request=request, validator=validator,
                            cost_estimator=classify_bill.response_cost, cache=cache)


def record_for(bundle: dict, report: dict) -> dict:
    return {"format": FORMAT, "bill_id": bundle["bill_id"], "request_key": report["request_key"],
            "review_key": bundle.get("first_pass_request_key"), "status": report.get("status"),
            "errors": report.get("errors", []), "suggestions": report.get("kept", []),
            "dropped": report.get("dropped", [])}


def tally(cache_dir: Path, min_bills: int = 1) -> list[dict]:
    groups: dict[str, dict] = {}
    for path in sorted((cache_dir / "suggestions").glob("*.json")):
        try:
            record = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        for item in record.get("suggestions") or []:
            key = _norm(item.get("topic", ""))
            if not key:
                continue
            group = groups.setdefault(key, {"topic": item["topic"], "bills": [], "closest": collections.Counter(),
                                            "reasons": []})
            if record["bill_id"] not in group["bills"]:
                group["bills"].append(record["bill_id"])
            group["closest"][item.get("closest_existing")] += 1
            if len(group["reasons"]) < 3:
                group["reasons"].append(f"{record['bill_id']}: {item.get('reason', '')}")
    rows = [{"topic": g["topic"], "bills": len(g["bills"]), "sample": g["bills"][:8],
             "closest": g["closest"].most_common(1)[0][0], "reasons": g["reasons"]}
            for g in groups.values() if len(g["bills"]) >= min_bills]
    return sorted(rows, key=lambda r: (-r["bills"], r["topic"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--min-bills", type=int, default=1)
    args = parser.parse_args()
    records = list((args.cache_dir / "suggestions").glob("*.json"))
    rows = tally(args.cache_dir, args.min_bills)
    print(f"{len(records)} bills checked; {len(rows)} suggested topics (min {args.min_bills} bills)")
    for row in rows:
        print(f"{row['bills']:4d}  {row['topic']}  (closest: {row['closest']})  e.g. {', '.join(row['sample'])}")
        for reason in row["reasons"]:
            print("        " + reason[:160])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
