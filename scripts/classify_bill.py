"""Focused Luna Flex classification of a complete TLC bill into a private review cache (the first pass)."""
from __future__ import annotations

import json
from pathlib import Path
import re

import extract_bill as detailed

ROOT = detailed.ROOT
MODEL = "gpt-6-luna"
VALIDATOR_REVISION = 3  # bump when validate_result changes: every reviewed bill is then revisited under it
FIRST_PASS_TOKENS = 12000
# A first pass that was cut off or whose summary excerpt could not be verified is sent again, changed, at most this
# many times per text. Each retry is a different request (more output room, a retry note), so the response cache can
# never replay the failed answer.
MAX_FIRST_PASS_RETRIES = 2
RETRY_NOTE = ("\nRETRY {attempt}: an earlier review of this bill was cut off or quoted an excerpt that does not appear "
              "verbatim in the cited span. Keep every explanation brief, and copy each quote exactly, character for "
              "character, from the span it cites.")


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


def load_statutory_context(document: dict, path: Path = ROOT / "scripts/statutory_definitions.json") -> list[dict]:
    """Select reviewed chapter definitions from explicit amendment clauses, never topic similarity."""
    source = " ".join(document["pages"])
    context = []
    for chapter in json.loads(path.read_text("utf-8")):
        number = str(chapter["chapter"])
        code = r"\s+".join(re.escape(word) for word in chapter["code"].split())
        pattern = (r"\b(?:Chapter\s+" + number + r"|Section\s+" + number
                   + r"\.\d+(?:\([a-z0-9]+\))*)\s*,\s*" + code
                   + r"\s*,?\s+is\s+(?:amended|added)\b")
        amendment = re.search(pattern, source, re.I)
        if amendment is None:
            continue
        for definition in chapter["definitions"]:
            # A narrower/revised in-bill definition can override the chapter definition.
            override = r'["\u201c]' + re.escape(definition["term"]) + r'["\u201d]\s+(?:means|has the meaning)\b'
            if re.search(override, source, re.I):
                continue
            context.append({**{k: v for k, v in chapter.items() if k != "definitions"},
                            **definition, "amendment_quote": amendment[0]})
    return context


def build_request(document: dict, registry: list[dict], attempt: int = 0) -> dict:
    """`attempt` 0 is the normal first pass; 1..MAX_FIRST_PASS_RETRIES are retries (see RETRY_NOTE)."""
    schema = json.loads((ROOT / "scripts/classification_schema.json").read_text("utf-8"))
    tags = load_policy_tags()
    schema["properties"]["policy_tags"]["items"]["properties"]["tag"]["enum"] = tags
    instructions = (ROOT / "scripts/classification_prompt.txt").read_text("utf-8")
    instructions += "\nCANONICAL POLICY TAGS:\n" + json.dumps(tags, ensure_ascii=False)
    if document.get("input_format") == "markdown":
        instructions += "\n" + (ROOT / "scripts/markdown_input_note.txt").read_text("utf-8")
    request = detailed.build_request(document, registry, schema=schema, instructions=instructions)
    request.update(model=MODEL, max_output_tokens=FIRST_PASS_TOKENS * (1 + attempt))
    request["text"]["format"]["name"] = "texas_bill_classification_v1"
    # Bill-dependent definitions stay after the shared prompt-cache breakpoint.
    request["input"][1]["content"][0]["text"] += (
        "\nREVIEWED STATUTORY DEFINITIONS (PARTIAL COVERAGE):\n"
        + json.dumps([{k: v for k, v in definition.items() if k != "verified_on"}
                      for definition in load_statutory_context(document)], sort_keys=True, ensure_ascii=False))
    if attempt:
        request["input"][1]["content"][0]["text"] += RETRY_NOTE.format(attempt=attempt)
    return request


def resolve_quote(quote: str, hint: str, document: dict) -> dict:
    """Locate an exact excerpt; offsets are into normalized page text, end exclusive."""
    if document.get("input_format") == "markdown":
        quote = re.sub(r"</?(?:ins|del)>", "", quote)
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


def validate_result(result: dict, document: dict, registry: list[dict], schema: dict, key: str,
                    sources: list[dict] | None = None) -> dict:
    import jsonschema
    jsonschema.Draft202012Validator(schema).validate(result)
    errors, reasons, reverse, citations = [], [], {}, []
    definitions = {definition["id"]: definition for definition in load_statutory_context(document)}
    external = {s["id"]: s for s in sources or []}
    if result["bill_id"] != document["bill_id"]:
        errors.append("Output bill ID differs from source")
    names = {a["id"]: a["name"] for a in registry if a["id"] != "all-state-agencies"}
    for agency in result["agencies"]:
        if not any(not e["span_id"].startswith("D_") for e in agency["evidence"]):
            errors.append("Agency impact requires bill evidence: " + agency["name"])
        if agency["registry_id"] is None:
            reasons.append("Unresolved agency identity: " + agency["name"])
        elif names.get(agency["registry_id"]) != agency["name"]:
            errors.append("Noncanonical agency identity: " + agency["name"])
        for definition in definitions.values():
            if (agency["registry_id"] == definition["registry_id"]
                    and agency["name"].casefold() not in " ".join(document["pages"]).casefold()
                    and not any(e["span_id"] == definition["id"] for e in agency["evidence"])):
                errors.append("Agency identity requires statutory definition citation: " + agency["name"])
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
            definition = definitions.get(span_id)
            if definition is not None:
                resolved = {"status": "resolved" if quote.strip() and quote in definition["quote"] else "not_found",
                            "source_type": "statutory_definition", "source_url": definition["source_url"],
                            "section": definition["section"], "verified_on": definition["verified_on"],
                            "quote": definition["quote"], "parts": []}
            elif span_id in external:
                source = external[span_id]
                resolved = {"status": "resolved" if quote.strip() and quote in source["text"] else "not_found",
                            "source_type": "statutory_context", "source_url": source["source_url"],
                            "section": source["section"], "quote": quote, "parts": []}
            elif span_id.startswith(("D_", "S_")):
                resolved = {"status": "not_found", "source_type": "statutory_definition"}
            else:
                resolved = {"source_type": "bill", **resolve_quote(quote, span_id, document)}
            citation = {"claim": label, "evidence_index": index, "requested_span_id": span_id, **resolved}
            citations.append(citation)
            if citation["status"] != "resolved":
                errors.append("Unresolved excerpt (" + citation["status"] + "): " + label + ":" + span_id)
            else:
                if definition is not None or span_id in external:
                    reverse.setdefault(span_id, set()).add(label)
                for part in citation["parts"]:
                    for resolved_span in part["span_ids"]:
                        reverse.setdefault(resolved_span, set()).add(label)
    if result["uncertainties"]:
        reasons.append("Model reports uncertainty")
        labels = {label for label, _ in claims}
        for question in result["uncertainties"]:
            if isinstance(question, dict):
                if set(question["affected_claims"]) - labels:
                    errors.append("Question targets an unknown claim")
                if set(question["span_ids"]) - document["spans"].keys():
                    errors.append("Question cites an unknown bill span")
    return {"validator_revision": VALIDATOR_REVISION, "errors": sorted(set(errors)), "review_reasons": sorted(set(reasons)),
            "status": "needs_review" if errors or reasons else "pending_review", "publishable": False,
            "audit_recommended": bool(errors or reasons),
            "evidence_reverse_index": {k: sorted(v) for k, v in sorted(reverse.items())},
            "verified_citations": citations,
            "statutory_context": list(definitions.values()),
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


def classify(document: dict, registry: list[dict], cache_root: Path, *, execute=False, sender=None,
             cache=None, attempt: int = 0) -> dict:
    return detailed.extract(document, registry, cache_root, execute=execute, sender=sender,
                            request=build_request(document, registry, attempt), validator=validate_result,
                            cost_estimator=response_cost, cache=cache)
