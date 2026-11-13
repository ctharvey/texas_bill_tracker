"""Related-entities pass: a supplemental Luna read of a bill's text listing every government body it involves.

Luna sees no agency list; names are matched to it in code (review_pipeline.agency_id_for). The request depends only
on the bill and its exact text, so it is a response-cache hit until the text changes. Records stay private in
<cache>/entities/; publishing adds only verified bodies that match a listed agency the review does not already have.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import classify_bill
import extract_bill as detailed
from review_audit import bill_text, marked_text

ROOT = detailed.ROOT
RECORD_FORMAT = "texas-bill-entities-record-v1"
IMPACTS = ("direct", "inferred")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["entities"],
          "properties": {"entities": {"type": "array", "maxItems": 40, "items": {
              "type": "object", "additionalProperties": False,
              "required": ["name", "impact", "explanation", "quote"],
              "properties": {"name": {"type": "string", "maxLength": 200},
                             "impact": {"type": "string", "enum": list(IMPACTS)},
                             "explanation": {"type": "string", "maxLength": 400},
                             "quote": {"type": "string", "maxLength": 600}}}}}}


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _squash(text: str) -> str:
    return " ".join(re.sub(r"</?(?:ins|del)>", "", text).split())


def build_request(bill_id: str, document: dict) -> dict:
    instructions = (ROOT / "scripts/related_entities_prompt.txt").read_text("utf-8")
    identity = {"bill_id": bill_id, "version": document.get("version")}
    return {
        "model": classify_bill.MODEL, "service_tier": "flex", "store": False, "reasoning": {"effort": "medium"},
        "max_output_tokens": 8000, "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "text": {"format": {"type": "json_schema", "name": "texas_bill_related_entities_v1", "strict": True,
                            "schema": SCHEMA}},
        "input": [
            {"role": "developer", "content": [{"type": "input_text", "text": instructions,
                "prompt_cache_breakpoint": {"mode": "explicit", "ttl": "12h"}}]},
            {"role": "user", "content": [{"type": "input_text",
                "text": _canonical(identity) + "\n\nBILL TEXT:\n" + marked_text(document)}]},
        ],
    }


def validate(result: dict, document: dict) -> dict:
    import jsonschema
    jsonschema.Draft202012Validator(SCHEMA).validate(result)
    text = _squash(bill_text(document))
    entities = [{**item, "quote_found": bool(_squash(item["quote"])) and _squash(item["quote"]) in text}
                for item in result["entities"]]
    return {"errors": [], "status": "checked", "entities": entities}


def due(bundle: dict | None, record: dict | None, request_key: str, text_sha256: str | None = None) -> bool:
    """Due when there is no record for this request, or the record is bound to other text (a re-render can keep the
    request identical; re-running it is then a response-cache hit that rebinds the record)."""
    if not isinstance(bundle, dict):
        return False
    return (not isinstance(record, dict) or record.get("request_key") != request_key
            or (text_sha256 is not None and record.get("text_sha256") != text_sha256))


def scan(bill_id: str, document: dict, registry: list[dict], cache_root: Path, *, execute=False, sender=None,
         cache=None) -> dict:
    request = build_request(bill_id, document)

    def validator(result, document, registry, schema, key, sources=None):
        return validate(result, document)

    return detailed.extract(document, registry, cache_root, execute=execute, sender=sender, request=request,
                            validator=validator, cost_estimator=classify_bill.response_cost, cache=cache)


def record_for(bill_id: str, document: dict, report: dict) -> dict:
    return {"format": RECORD_FORMAT, "bill_id": bill_id, "request_key": report["request_key"],
            "text_sha256": document.get("text_sha256"), "status": report.get("status"),
            "errors": report.get("errors", []), "entities": report.get("entities", [])}


def verified_entities(cache_dir: Path, bill_id: str, bundle: dict) -> list[dict]:
    """Entities whose quote is in the text, from a checked record of the exact text the review read; else []."""
    try:
        record = json.loads((cache_dir / "entities" / (bill_id + ".json")).read_text("utf-8"))
    except (OSError, ValueError):
        return []
    text_sha = (bundle.get("document") or {}).get("text_sha256") if isinstance(bundle, dict) else None
    if (not isinstance(record, dict) or record.get("format") != RECORD_FORMAT or record.get("bill_id") != bill_id
            or record.get("status") != "checked" or not text_sha or record.get("text_sha256") != text_sha):
        return []
    return [e for e in record.get("entities") or []
            if isinstance(e, dict) and e.get("quote_found") is True and isinstance(e.get("name"), str)
            and e.get("impact") in IMPACTS]
