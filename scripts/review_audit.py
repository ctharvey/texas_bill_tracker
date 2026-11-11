"""Spot-check audit: an independent Luna re-read of about 2% of settled reviews against the bill text.

The sample is deterministic (bill ID + review key), so the same reviews are checked until they change. The request
is built from the review's verified claims (what the site shows) and the exact text version the review is bound
to, so a repeat is a response-cache hit. Per-bill findings stay private in <cache>/audit/; only counts are
published (audit.json).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re

import classify_bill
import extract_bill as detailed

ROOT = detailed.ROOT
FORMAT = "texas-bill-luna-audit-v1"
RECORD_FORMAT = "texas-bill-audit-record-v2"  # v2: marked text; earlier verdicts never count
SAMPLE_PER_MILLE = 20
VERDICTS = ("agree", "minor_issues", "major_issues")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdict", "issues"],
          "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)},
                         "issues": {"type": "array", "maxItems": 6, "items": {
                             "type": "object", "additionalProperties": False,
                             "required": ["claim", "problem", "severity", "quote"],
                             "properties": {"claim": {"type": "string", "maxLength": 200},
                                            "problem": {"type": "string", "maxLength": 500},
                                            "severity": {"type": "string", "enum": ["minor", "major"]},
                                            "quote": {"type": "string", "maxLength": 600}}}}}}


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _squash(text: str) -> str:
    return " ".join(re.sub(r"</?(?:ins|del)>", "", text).split())


def sampled(bill_id: str, review_key: str | None) -> bool:
    digest = hashlib.sha256((bill_id + (review_key or "")).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 1000 < SAMPLE_PER_MILLE


def review_for_audit(bundle: dict) -> dict:
    """The review's verified claims, as published."""
    result = bundle["result"]
    verified = {c.get("claim") for c in (bundle.get("validation") or {}).get("verified_citations", [])
                if c.get("status") == "resolved"}

    def kept(field, keys):
        return [{k: item.get(k) for k in keys} for i, item in enumerate(result.get(field) or [])
                if f"{field}:{i}" in verified]
    return {"summary": (result.get("summary") or {}).get("text") if "summary" in verified else None,
            "topics": kept("policy_tags", ("tag", "explanation")),
            "major_effects": kept("major_effects", ("effect", "label", "explanation")),
            "affected_groups": kept("affected_groups", ("group", "explanation")),
            "locations": kept("locations", ("name", "kind", "explanation")),
            "agencies": kept("agencies", ("name", "impact", "explanation"))}


def review_hash(bundle: dict) -> str:
    return hashlib.sha256(_canonical(review_for_audit(bundle)).encode("utf-8")).hexdigest()


def bill_text(document: dict) -> str:
    """Plain text (markup removed): what auditor quotes are checked against."""
    return "\n\n".join(page for page in document["pages"] if page.strip())


def marked_text(document: dict) -> str:
    """The text as the review saw it: <ins>/<del> kept, so deleted language is not read as law. Spans are rejoined
    into their paragraphs; PDF documents have no markup and fall back to plain text."""
    spans = document.get("spans") or {}
    if not spans or not all("marked" in span for span in spans.values()):
        return bill_text(document)
    paragraphs: dict[int, list[str]] = {}
    for span in spans.values():
        paragraphs.setdefault(span["page"], []).append(span["marked"])
    return "\n\n".join(" ".join(parts) for _, parts in sorted(paragraphs.items()))


def build_request(bundle: dict, document: dict) -> dict:
    instructions = (ROOT / "scripts/review_audit_prompt.txt").read_text("utf-8")
    return {
        "model": classify_bill.MODEL, "service_tier": "flex", "store": False, "reasoning": {"effort": "medium"},
        "max_output_tokens": 8000, "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "text": {"format": {"type": "json_schema", "name": "texas_bill_review_audit_v1", "strict": True,
                            "schema": SCHEMA}},
        "input": [
            {"role": "developer", "content": [{"type": "input_text", "text": instructions,
                "prompt_cache_breakpoint": {"mode": "explicit", "ttl": "12h"}}]},
            {"role": "user", "content": [{"type": "input_text",
                "text": "REVIEW:\n" + _canonical(review_for_audit(bundle)) + "\n\nBILL TEXT:\n" + marked_text(document)}]},
        ],
    }


def validate(result: dict, document: dict) -> dict:
    import jsonschema
    jsonschema.Draft202012Validator(SCHEMA).validate(result)
    text = _squash(bill_text(document))
    issues = [{**item, "quote_found": bool(_squash(item["quote"])) and _squash(item["quote"]) in text}
              for item in result["issues"]]
    return {"errors": [], "status": "checked", "verdict": result["verdict"], "issues": issues}


def due(bundle: dict | None, record: dict | None, request_key: str) -> bool:
    return isinstance(bundle, dict) and (not isinstance(record, dict) or record.get("request_key") != request_key)


def audit(bundle: dict, document: dict, registry: list[dict], cache_root: Path, *, execute=False, sender=None,
          cache=None) -> dict:
    request = build_request(bundle, document)

    def validator(result, document, registry, schema, key, sources=None):
        return validate(result, document)

    return detailed.extract(document, registry, cache_root, execute=execute, sender=sender, request=request,
                            validator=validator, cost_estimator=classify_bill.response_cost, cache=cache)


def record_for(bundle: dict, report: dict) -> dict:
    return {"format": RECORD_FORMAT, "bill_id": bundle["bill_id"], "request_key": report["request_key"],
            "review_hash": review_hash(bundle), "text_sha256": (bundle.get("document") or {}).get("text_sha256"),
            "status": report.get("status"), "errors": report.get("errors", []),
            "verdict": report.get("verdict"), "issues": report.get("issues", [])}


def publish(reviews, cache_dir: Path, out: Path) -> int:
    """Counts only, for records that checked the bill's current review. Per-bill findings are never published."""
    counts = dict.fromkeys(VERDICTS, 0)
    for bill_id, bundle in reviews:
        try:
            record = json.loads((cache_dir / "audit" / (bill_id + ".json")).read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if (isinstance(record, dict) and record.get("format") == RECORD_FORMAT and record.get("status") == "checked"
                and record.get("verdict") in counts
                and record.get("review_hash") == review_hash(bundle)
                and record.get("text_sha256") == (bundle.get("document") or {}).get("text_sha256")):
            counts[record["verdict"]] += 1
    payload = {"format": FORMAT, "model": classify_bill.MODEL,
               "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
               "checked": sum(counts.values()), "agree": counts["agree"],
               "minor_issues": counts["minor_issues"], "major_issues": counts["major_issues"]}
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(out.name + ".tmp")
    temporary.write_text(json.dumps(payload) + "\n", "utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, out)
    return payload["checked"]
