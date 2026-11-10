#!/usr/bin/env python3
"""Focused Luna Flex classification of a complete TLC bill into a private review cache."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

import extract_bill as detailed

ROOT = detailed.ROOT
MODEL = "gpt-6-luna"


def load_policy_tags(path: Path = ROOT / "src/taxonomy.js") -> list[str]:
    source = path.read_text("utf-8")
    try:
        declaration = source.split("export const POLICY_AREAS = [", 1)[1].split("\n];", 1)[0]
    except IndexError as error:
        raise ValueError("Policy declaration changed; update the vocabulary reader") from error
    lines = [line.strip() for line in declaration.splitlines() if line.strip()]
    tags = []
    for line in lines:
        match = re.fullmatch(r"\{name:'([^']+)', pattern:/.*/i\},?", line)
        if match is None:
            raise ValueError("Policy declaration changed; update the vocabulary reader")
        tags.append(match[1])
    if not tags or len(set(tags)) != len(tags):
        raise ValueError("Missing or duplicate policy tags")
    return tags


def build_request(document: dict, registry: list[dict]) -> dict:
    schema = json.loads((ROOT / "scripts/classification_schema.json").read_text("utf-8"))
    tags = load_policy_tags()
    schema["properties"]["policy_tags"]["items"]["properties"]["tag"]["enum"] = tags
    instructions = (ROOT / "scripts/classification_prompt.txt").read_text("utf-8")
    instructions += "\nCANONICAL POLICY TAGS:\n" + json.dumps(tags, ensure_ascii=False)
    request = detailed.build_request(document, registry, schema=schema, instructions=instructions)
    request.update(model=MODEL, max_output_tokens=12000)
    request["text"]["format"]["name"] = "texas_bill_classification_v1"
    return request


def resolve_quote(quote: str, hint: str, document: dict) -> dict:
    """Locate an exact excerpt; offsets are into normalized page text, end exclusive."""
    pages = document["pages"]
    source = " ".join(pages)
    page_starts, cursor = [], 0
    for page in pages:
        page_starts.append(cursor)
        cursor += len(page) + 1
    matches, cursor = [], 0
    while quote.strip() and (start := source.find(quote, cursor)) >= 0:
        matches.append((start, start + len(quote)))
        cursor = start + 1
    count = len(matches)
    method = "unique_quote"
    if count > 1:
        # Only a source-verified overlap with the hinted span can disambiguate repeats.
        span = document["spans"].get(hint)
        contextual = []
        if span is not None:
            offset = page_starts[span["page"] - 1]
            contextual = [(start, end) for start, end in matches
                          if start < offset + span["end"] and end > offset + span["start"]]
        matches = contextual if len(contextual) == 1 else []
        method = "hinted_source_context"
    if not matches:
        return {"status": "ambiguous" if count else "not_found", "candidate_count": count}
    start, end = matches[0]
    parts = []
    for number, (page, offset) in enumerate(zip(pages, page_starts), 1):
        local_start, local_end = max(start - offset, 0), min(end - offset, len(page))
        if local_start >= local_end:
            continue
        spans = [sid for sid, span in document["spans"].items()
                 if span["page"] == number and span["start"] < local_end and span["end"] > local_start]
        parts.append({"page": number, "start": local_start, "end": local_end, "span_ids": spans,
                      "quote": page[local_start:local_end]})
    span_ids = [sid for part in parts for sid in part["span_ids"]]
    return {"status": "resolved", "method": method, "candidate_count": count,
            "quote": source[start:end], "parts": parts,
            "location_changed": span_ids != [hint]}


def validate_result(result: dict, document: dict, registry: list[dict], schema: dict, key: str) -> dict:
    import jsonschema
    jsonschema.Draft202012Validator(schema).validate(result)
    errors, reasons, reverse, citations = [], [], {}, []
    if result["bill_id"] != document["bill_id"]:
        errors.append("Output bill ID differs from source")
    names = {a["id"]: a["name"] for a in registry if a["id"] != "all-state-agencies"}
    for agency in result["agencies"]:
        if agency["registry_id"] is None:
            reasons.append("Unresolved agency identity: " + agency["name"])
        elif names.get(agency["registry_id"]) != agency["name"]:
            errors.append("Noncanonical agency identity: " + agency["name"])
        if agency["impact"] == "inferred":
            reasons.append("Inferred agency impact: " + agency["name"])
    scope = result["all_state_agencies_scope"]
    if scope["applies"]:
        if scope["basis"] == "not_applicable" or not scope["evidence"]:
            errors.append("Applicable agency-wide scope requires basis and evidence")
        if scope["basis"] == "inferred":
            reasons.append("Inferred all-state-agencies scope")
    elif scope["basis"] != "not_applicable" or scope["evidence"]:
        errors.append("Non-applicable agency-wide scope must have empty evidence")
    claims = [("summary", result["summary"]), ("all_state_agencies_scope", scope)]
    for field, identity in (("policy_tags", "tag"), ("agencies", "name"), ("locations", "name"),
                            ("affected_groups", "group"), ("major_effects", "label")):
        seen = set()
        for i, claim in enumerate(result[field]):
            if claim[identity] in seen:
                errors.append("Duplicate classification: " + field + ":" + claim[identity])
            seen.add(claim[identity])
            claims.append((f"{field}:{i}", claim))
    for label, claim in claims:
        for index, evidence in enumerate(claim["evidence"]):
            span_id, quote = evidence["span_id"], evidence["quote"]
            citation = {"claim": label, "evidence_index": index, "requested_span_id": span_id,
                        **resolve_quote(quote, span_id, document)}
            citations.append(citation)
            if citation["status"] != "resolved":
                errors.append("Unresolved excerpt (" + citation["status"] + "): " + label + ":" + span_id)
            else:
                for part in citation["parts"]:
                    for resolved_span in part["span_ids"]:
                        reverse.setdefault(resolved_span, set()).add(label)
    if result["uncertainties"]:
        reasons.append("Model reports uncertainty")
    return {"validator_revision": 2, "errors": sorted(set(errors)), "review_reasons": sorted(set(reasons)),
            "status": "needs_review" if errors or reasons else "pending_review", "publishable": False,
            "audit_recommended": bool(errors or reasons),
            "evidence_reverse_index": {k: sorted(v) for k, v in sorted(reverse.items())},
            "verified_citations": citations,
            "citation_counts": {"resolved": sum(c["status"] == "resolved" for c in citations),
                                "relocated": sum(c.get("location_changed", False) for c in citations),
                                "ambiguous": sum(c["status"] == "ambiguous" for c in citations),
                                "not_found": sum(c["status"] == "not_found" for c in citations)},
            "counts": {k: len(result[k]) for k in
                       ("policy_tags", "agencies", "locations", "affected_groups", "major_effects")}}


def response_cost(raw: dict) -> list[float] | None:
    # Official Luna Flex short-context rates per million tokens, verified 2026-11-09.
    if (raw.get("usage") or {}).get("input_tokens", 0) > 272000:
        return None  # Long-context pricing is outside this evaluator's estimates.
    return detailed.response_cost(raw, model=MODEL, rates=(.05, .005, .25, .0625, .125))


def classify(document: dict, registry: list[dict], cache_root: Path, *, execute=False, sender=None) -> dict:
    return detailed.extract(document, registry, cache_root, execute=execute, sender=sender,
                            request=build_request(document, registry), validator=validate_result,
                            cost_estimator=response_cost)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--bill-id", required=True)
    parser.add_argument("--session", default="90R")
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-url", required=True)
    default_cache = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    parser.add_argument("--cache-dir", type=Path, default=default_cache / "texas-bill-atlas" / "extraction")
    parser.add_argument("--execute", action="store_true", help="Allow one paid call on a cache miss")
    args = parser.parse_args()
    if not args.source_url.startswith("ftp://ftp.legis.state.tx.us/bills/"):
        parser.error("Use the official TLC bulk FTP source URL")
    detailed.check_cache_location(args.cache_dir)
    document = detailed.read_pdf(args.pdf, args.bill_id, args.session, args.version)
    document["source_url"] = args.source_url
    report = classify(document, detailed.load_registry(), args.cache_dir, execute=args.execute)
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("result", "evidence_reverse_index", "verified_citations")}, indent=2))
    return 2 if report.get("errors") or (args.execute and report.get("action") == "not_submitted") else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Keep provider exception bodies and credentials out of logs.
        print("Classification stopped: " + type(error).__name__, flush=True)
        raise SystemExit(2)
