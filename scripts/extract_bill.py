#!/usr/bin/env python3
"""Optional Terra Flex extraction into a private review cache. Never writes the shared bill dataset."""
from __future__ import annotations

import argparse
import ast
import datetime as dt
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from extraction_cache import (
    CacheBusy, CacheCoolingDown, CapacityUnavailable, NotSubmitted, ResponseCache, UnresolvedCall,
    atomic_json, canonical_hash,
)

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gpt-6.1-terra"
VALIDATOR_REVISION = 1
SOURCE_REVISION = "normalized-pages-v1"
SAMPLE_PERCENT = 5
SOURCE_SIGNALS = re.compile(r"\b(?:shall|must|may\s+not|before|after|deadline|expire\w*|days?|years?)\b", re.I)
NESTED_MODAL = re.compile(r"\b(?:shall|must|may)\b", re.I)


def check_cache_location(path: Path) -> None:
    roots = [ROOT.resolve()]
    git_file = ROOT / ".git"
    if git_file.is_file():
        declaration = git_file.read_text("utf-8").strip()
        if declaration.startswith("gitdir: "):
            git_dir = (ROOT / declaration[8:]).resolve()
            common_file = git_dir / "commondir"
            if common_file.is_file():
                common = (git_dir / common_file.read_text("utf-8").strip()).resolve()
                roots.append(common.parent)
    if any(path.resolve().is_relative_to(root) for root in roots):
        raise ValueError("The extraction cache must be outside the checkout/web root")


def load_registry(path: Path = ROOT / "src/taxonomy.js") -> list[dict]:
    """Read the app's literal agency pairs without adding Node or a duplicate registry."""
    source = path.read_text("utf-8")
    try:
        pairs = source.split("export const AGENCIES = ", 1)[1].split("].filter", 1)[0] + "]"
        pairs = ast.literal_eval(re.sub(r"(?m)^\s*//[^\n]*", "", pairs))
    except (IndexError, SyntaxError, ValueError) as error:
        raise ValueError("Agency declaration changed; update the registry reader") from error
    registry = {}
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(x, str) and x for x in pair):
            raise ValueError("Invalid agency pair")
        registry.setdefault(pair[0], {"id": pair[0], "name": pair[1]})
    if "all-state-agencies" not in registry or len(registry) < 2:
        raise ValueError("Registry is missing scope or agency entries")
    return list(registry.values())


def document_from_pages(bill_id: str, session: str, version: str, pages: list[str]) -> dict:
    if not re.fullmatch(r"(?:HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9]\d{0,4}", bill_id):
        raise ValueError("Invalid bill ID")
    if not re.fullmatch(r"\d{2,3}[RS]\d?", session) or not version.strip():
        raise ValueError("Invalid session or missing text version")
    normalized = [" ".join(page.split()) for page in pages]
    if not normalized or any(not page for page in normalized):
        raise ValueError("Every PDF page must contain extractable text; OCR is required for image-only pages")
    spans = {}
    for number, text in enumerate(normalized, 1):
        start, ordinal = 0, 1
        while start < len(text):
            end = len(text)
            if end - start > 600:
                split = text.rfind(" ", start + 1, start + 600)
                end = split if split > start else start + 600
            spans[f"P{number:03d}S{ordinal:03d}"] = {
                "page": number, "start": start, "end": end, "text": text[start:end],
            }
            start, ordinal = end, ordinal + 1
            while start < len(text) and text[start].isspace():
                start += 1
    return {"bill_id": bill_id, "session": session, "version": version.strip(), "pages": normalized,
            "spans": spans, "text_hash": canonical_hash(normalized), "source_revision": SOURCE_REVISION}


MARKDOWN_SOURCE_REVISION = "markdown-paragraphs-v1"
_MD_TAG = re.compile(r"</?(?:ins|del)>")


def plain_paragraphs(markdown: str) -> list[str]:
    """Plain projection of a bill-text Markdown file; paragraph 0 is the title line."""
    paragraphs = []
    for raw in markdown.split("\n\n"):
        text = raw.rstrip("\n")
        if not text.strip():
            continue
        for prefix in ("### ", "# "):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        for tag in ("<ins>", "</ins>", "<del>", "</del>"):
            text = text.replace(tag, "")
        paragraphs.append(re.sub(r"\\(.)", r"\1", text))
    return paragraphs


def marked_paragraphs(markdown: str) -> list[tuple[str, list[int]]]:
    """Per paragraph (same order as plain_paragraphs): marked text and, for each plain offset, the offset
    of that character in the marked text. The marked text keeps <ins>/<del> and is otherwise unescaped
    exactly like the plain text, so stripping the tags from it gives the plain paragraph."""
    result = []
    for raw in markdown.split("\n\n"):
        text = raw.rstrip("\n")
        if not text.strip():
            continue
        for prefix in ("### ", "# "):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        pieces, position = [], 0  # (is_tag, content)
        for match in _MD_TAG.finditer(text):
            pieces.extend((False, ch) for ch in text[position:match.start()])
            pieces.append((True, match[0]))
            position = match.end()
        pieces.extend((False, ch) for ch in text[position:])
        chars = "".join(ch for tag, ch in pieces if not tag)
        escapes = {m.start() for m in re.finditer(r"\\(.)", chars)}
        marked, offsets, index, length = [], [], 0, 0
        for is_tag, content in pieces:
            if is_tag:
                marked.append(content)
                length += len(content)
                continue
            here, index = index, index + 1
            if here in escapes:
                continue  # The backslash itself is dropped; the next character is literal.
            offsets.append(length)
            marked.append(content)
            length += 1
        result.append(("".join(marked), offsets))
    return result


def document_from_markdown(bill_id: str, session: str, version_code: str, markdown: str) -> dict:
    if not re.fullmatch(r"(?:HB|SB|HJR|SJR|HCR|SCR|HR|SR)[1-9]\d{0,4}", bill_id):
        raise ValueError("Invalid bill ID")
    if not re.fullmatch(r"\d{2,3}[RS]\d?", session) or not version_code.strip():
        raise ValueError("Invalid session or missing text version")
    pages = plain_paragraphs(markdown)
    marked_rows = marked_paragraphs(markdown)
    if not pages or not any(page.strip() for page in pages) or len(marked_rows) != len(pages):
        raise ValueError("Bill text Markdown has no text")
    # Ids widen past 999 paragraphs (P1000S001); the classification schema puts no pattern on span_id.
    spans, marked_texts = {}, []
    for number, (text, (marked, offsets)) in enumerate(zip(pages, marked_rows), 1):
        marked_texts.append(marked)
        if not text.strip():
            continue
        if len(offsets) != len(text):
            raise ValueError("Markdown plain/marked projections disagree")
        start, ordinal = 0, 1
        while start < len(text):
            end = len(text)
            if end - start > 600:
                split = text.rfind(" ", start + 1, start + 600)
                end = split if split > start else start + 600
            low = offsets[start]
            while marked[:low].endswith(("<ins>", "<del>")):
                low -= 5
            high = offsets[end - 1] + 1
            while True:
                closing = next((t for t in ("</ins>", "</del>") if marked.startswith(t, high)), None)
                if closing is None:
                    break
                high += len(closing)
            spans[f"P{number:03d}S{ordinal:03d}"] = {
                "page": number, "start": start, "end": end, "text": text[start:end], "marked": marked[low:high],
            }
            start, ordinal = end, ordinal + 1
            while start < len(text) and text[start].isspace():
                start += 1
    if not spans:
        raise ValueError("Bill text Markdown has no text")
    return {"bill_id": bill_id, "session": session, "version": version_code.strip(), "pages": pages,
            "spans": spans, "text_hash": canonical_hash({"pages": pages, "marked": marked_texts}),
            "source_revision": MARKDOWN_SOURCE_REVISION, "input_format": "markdown"}


def read_pdf(path: Path, bill_id: str, session: str, version: str) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise NotSubmitted("Install requirements-extraction.txt to read PDFs") from error
    document = document_from_pages(bill_id, session, version, [page.extract_text() for page in PdfReader(path).pages])
    # Byte-level provenance does not invalidate extraction when the actual extracted text is unchanged.
    document["pdf_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return document


def build_request(document: dict, registry: list[dict], *, schema: dict | None = None,
                  instructions: str | None = None) -> dict:
    if schema is None:
        schema = json.loads((ROOT / "scripts/extraction_schema.json").read_text("utf-8"))
    if instructions is None:
        instructions = (ROOT / "scripts/extraction_prompt.txt").read_text("utf-8")
    agencies = [a for a in registry if a["id"] != "all-state-agencies"]
    scope = [a for a in registry if a["id"] == "all-state-agencies"]
    vocabulary = json.dumps({"agencies": agencies, "scope_markers": scope}, ensure_ascii=False,
                            sort_keys=True, separators=(",", ":"))
    source = "\n\n".join(
        f"[{key}; paragraph {span['page']}]\n{span['marked']}" if "marked" in span
        else f"[{key}; PDF page {span['page']}]\n{span['text']}"
        for key, span in document["spans"].items())
    # Only semantic identity enters the model request. URLs, timestamps, PDF metadata, authors and
    # legislative-history/status updates stay out, so hourly history refreshes cannot change this key.
    identity = {k: document[k] for k in ("bill_id", "session", "version", "source_revision", "text_hash")}
    return {
        "model": MODEL, "service_tier": "flex", "store": False, "reasoning": {"effort": "high"},
        "max_output_tokens": 48000, "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "text": {"format": {"type": "json_schema", "name": "texas_bill_extraction_v1",
                            "strict": True, "schema": schema}},
        "input": [
            {"role": "developer", "content": [{"type": "input_text",
                "text": instructions + "\nCANONICAL VOCABULARY (INCOMPLETE):\n" + vocabulary,
                "prompt_cache_breakpoint": {"mode": "explicit", "ttl": "12h"}}]},
            {"role": "user", "content": [{"type": "input_text",
                "text": json.dumps(identity, sort_keys=True) + "\nCOMPLETE BILL SOURCE:\n" + source}]},
        ],
    }


def resolve_calendar(point: dict, anchor: dt.date) -> dt.date:
    """Resolve only the new exact calendar relationships, using a supplied verified event date."""
    kind = point["kind"]
    if kind == "calendar_relative_to_event":
        return dt.date(anchor.year + point["year_offset"], point["month"], point["day"])
    if kind == "ordinal_weekday_relative_to_event":
        year, month = anchor.year + point["year_offset"], point["month"]
        weekday = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday").index(point["weekday"])
        first = dt.date(year, month, 1)
        day = 1 + (weekday - first.weekday()) % 7 + 7 * (point["ordinal"] - 1)
        return dt.date(year, month, day)  # Reject a nonexistent fifth weekday instead of rolling months.
    if kind == "next_matching_calendar":
        modulus, remainder = point["year_modulus"], point["year_remainder"]
        if modulus <= 0 or not 0 <= remainder < modulus:
            raise ValueError("Invalid qualifying year")
        if point["selection"] not in ("next_matching_year_after_anchor", "next_matching_date_after_anchor"):
            raise ValueError("Unknown qualifying-year selection")
        year = anchor.year + (point["selection"] == "next_matching_year_after_anchor")
        year += (remainder - year % modulus) % modulus
        candidate = dt.date(year, point["month"], point["day"])
        if candidate <= anchor:
            candidate = dt.date(year + modulus, point["month"], point["day"])
        return candidate
    raise ValueError("Not a supported event-relative calendar type")


def validate_result(result: dict, document: dict, registry: list[dict], schema: dict,
                    key: str, sample_percent: int = SAMPLE_PERCENT) -> dict:
    import jsonschema
    jsonschema.Draft202012Validator(schema).validate(result)
    errors, reasons, reverse = [], [], {}
    if result["bill_id"] != document["bill_id"]:
        errors.append("Output bill ID differs from source")
    names = {a["id"]: a["name"] for a in registry if a["id"] != "all-state-agencies"}
    if result["unresolved_identity_notes"] or result["coverage_limitations"]:
        reasons.append("Model reports identity or coverage limitations")
    entity_ids = {e["entity_ref"] for e in result["entities"]}
    for change in result["authority_changes"]:
        for field in ("from_entity_refs", "to_entity_refs", "affected_entity_refs", "trigger_entity_refs"):
            if set(change[field]) - entity_ids:
                errors.append("Unknown authority entity reference: " + change["change_id"])
    for entity in result["entities"]:
        if entity["registry_id"] is not None and names.get(entity["registry_id"]) != entity["name"]:
            errors.append("Noncanonical entity identity: " + entity["entity_ref"])

    def time_points(value):
        if isinstance(value, dict):
            kind = value.get("kind")
            if kind == "unresolved":
                reasons.append("Unresolved time relationship")
            if kind == "fixed_date":
                dt.date.fromisoformat(value["date_iso"])
            if kind in ("recurring_calendar", "next_matching_calendar"):
                dt.date(2000, value["month"], value["day"])
                modulus, remainder = value["year_modulus"], value["year_remainder"]
                if (modulus is None) != (remainder is None) or (modulus is not None
                        and (modulus <= 0 or not 0 <= remainder < modulus)):
                    raise ValueError("Invalid qualifying year")
            if kind == "calendar_relative_to_event":
                dt.date(2000, value["month"], value["day"])
            if kind == "window" and (value["start_inclusive"] is None or value["end_inclusive"] is None):
                reasons.append("Unknown interval endpoint inclusivity")
            for child in value.values():
                time_points(child)
        elif isinstance(value, list):
            for child in value:
                time_points(child)

    for field, id_field in (("entities", "entity_ref"), ("authority_changes", "change_id"),
                           ("timing_rules", "rule_id"), ("obligations", "obligation_id")):
        seen = set()
        for claim in result[field]:
            identifier = claim[id_field]
            label = field + ":" + identifier
            if identifier in seen:
                errors.append("Duplicate record ID: " + label)
            seen.add(identifier)
            for evidence in claim["evidence"]:
                for span_id in evidence["span_ids"]:
                    span = document["spans"].get(span_id)
                    if span is None:
                        errors.append("Unknown evidence span: " + span_id)
                    elif document["pages"][span["page"] - 1][span["start"]:span["end"]] != span["text"]:
                        errors.append("Evidence offset mismatch: " + span_id)
                    else:
                        reverse.setdefault(span_id, set()).add(label)
            if "actor" in claim and claim["actor"]["basis"] != "explicit":
                reasons.append("Unknown or inferred actor: " + label)
            if field == "obligations" and NESTED_MODAL.search(claim["action"]):
                reasons.append("Check mixed actor/modality inside action: " + label)
            if field == "timing_rules":
                try:
                    time_points(claim["temporal"])
                except ValueError:
                    errors.append("Invalid calendar value: " + label)
    uncited = [span_id for span_id, span in document["spans"].items()
               if SOURCE_SIGNALS.search(span["text"]) and span_id not in reverse]
    if uncited:
        reasons.append("Potentially operative source spans have no linked claim")
    sampled = int(key[:8], 16) % 100 < sample_percent
    if sampled:
        reasons.append("Deterministic quality-review sample")
    return {
        "validator_revision": VALIDATOR_REVISION, "errors": sorted(set(errors)),
        "review_reasons": sorted(set(reasons)), "audit_recommended": bool(errors or reasons),
        "sampled": sampled, "status": "needs_review" if errors or reasons else "pending_review",
        "publishable": False, "evidence_reverse_index": {k: sorted(v) for k, v in sorted(reverse.items())},
        "uncited_candidate_spans": uncited,
        "counts": {k: len(result[k]) for k in ("entities", "authority_changes", "timing_rules", "obligations")},
    }


def response_cost(raw: dict, *, model: str = MODEL,
                  rates: tuple = (.5, .025, 2.5, .625, 1.25)) -> list[float] | None:
    if raw.get("service_tier") != "flex" or raw.get("model") != model or not raw.get("usage"):
        return None
    usage = raw["usage"]
    details = usage.get("input_tokens_details") or {}
    reads, writes = details.get("cached_tokens", 0), details.get("cache_write_tokens", 0)
    ordinary = usage["input_tokens"] - reads - writes
    if min(ordinary, reads, writes, usage["output_tokens"]) < 0:
        raise ValueError("Inconsistent provider token usage")
    input_rate, read_rate, output_rate, short_write, long_write = rates
    fixed = (ordinary * input_rate + reads * read_rate + usage["output_tokens"] * output_rate) / 1e6
    lifetimes = details.get("cache_write_tokens_details")
    if lifetimes is not None:
        if set(lifetimes) - {"ttl_30m_tokens", "ttl_12h_tokens"} or sum(lifetimes.values()) != writes:
            raise ValueError("Unrecognized provider cache-write accounting")
        total = fixed + (lifetimes.get("ttl_30m_tokens", 0) * short_write
                         + lifetimes.get("ttl_12h_tokens", 0) * long_write) / 1e6
        return [total, total]
    return [fixed + writes * short_write / 1e6, fixed + writes * long_write / 1e6]


def send_request(request: dict) -> dict:
    # This function runs only after explicit execution and a response-cache miss, under its lock.
    try:
        from openai import OpenAI
    except ImportError as error:
        raise NotSubmitted("Install requirements-extraction.txt before execution") from error
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise NotSubmitted("OPENAI_API_KEY is required for execution on a cache miss")
    client = OpenAI(api_key=key, base_url="https://api.openai.com/v1", timeout=900, max_retries=0)
    for attempt in range(3):
        try:
            arguments = dict(request)
            options = arguments.pop("prompt_cache_options")
            response = client.responses.create(**arguments, extra_body={"prompt_cache_options": options})
            return response.model_dump(mode="json")
        except Exception as error:
            if getattr(error, "code", None) not in ("flex_unavailable", "resource_unavailable", "rate_limit_exceeded"):
                raise
            delay = (30, 60, 60)[attempt]
            retry_after = getattr(getattr(error, "response", None), "headers", {}).get("retry-after")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    try:
                        until = parsedate_to_datetime(retry_after)
                        if until.tzinfo is None:
                            until = until.replace(tzinfo=dt.timezone.utc)
                        delay = max(delay, (until - dt.datetime.now(dt.timezone.utc)).total_seconds())
                    except (TypeError, ValueError, OverflowError):
                        raise CapacityUnavailable(60) from None
            if attempt == 2 or delay > 60:
                raise CapacityUnavailable(delay) from None
            print(f"Flex capacity unavailable; retrying in {delay:g} seconds", file=sys.stderr, flush=True)
            time.sleep(delay)
    raise AssertionError("Unreachable retry state")


def extract(document: dict, registry: list[dict], cache_root: Path, *, execute: bool = False,
            sender=None, request: dict | None = None, validator=None, cost_estimator=None, cache=None) -> dict:
    check_cache_location(cache_root)
    request = request if request is not None else build_request(document, registry)
    import jsonschema
    jsonschema.Draft202012Validator.check_schema(request["text"]["format"]["schema"])
    # `cache`: anything with key/execute, e.g. a FlexBoundary (--transport flex); default is the built-in cache.
    cache = cache if cache is not None else ResponseCache(cache_root / "responses")
    key = cache.key(request)
    atomic_json(cache_root / "requests" / (key + ".json"), request)

    def submit():
        if not execute:
            raise NotSubmitted("Prepared only; use --execute to authorize a new provider call")
        return (sender or send_request)(request)

    try:
        cached = cache.execute(request, submit)
    except NotSubmitted as error:
        return {"action": "not_submitted", "request_key": key, "message": str(error),
                "reason_type": type(error).__name__, "new_api_cost_estimate": [0, 0], "publishable": False}
    raw = cached.response
    estimate = (cost_estimator or response_cost)(raw)
    report = {"request_key": key, "text_hash": document["text_hash"], "cache_hit": cached.cache_hit,
              "usage_source": "historical_response" if cached.cache_hit else "new_response",
              "original_response_cost_estimate": estimate,
              "new_api_cost_estimate": [0, 0] if cached.cache_hit else estimate,
              "source_provenance": {k: document.get(k) for k in ("pdf_sha256", "source_url")},
              "status": "needs_review", "publishable": False}
    try:
        if (raw.get("status") != "completed" or raw.get("service_tier") != "flex"
                or raw.get("model") != request["model"]):
            raise ValueError("Incomplete response or unexpected model/service tier; not retried")
        output = "".join(part["text"] for item in raw.get("output", []) if item.get("type") == "message"
                         for part in item.get("content", []) if part.get("type") == "output_text")
        result = json.loads(output)
        report.update((validator or validate_result)(
            result, document, registry, request["text"]["format"]["schema"], key))
        report["result"] = result
    except (ValueError, KeyError, TypeError, jsonschema.ValidationError) as error:
        report["errors"] = ["Response failed validation: " + type(error).__name__]
        report["audit_recommended"] = True
    atomic_json(cache_root / "results" / (key + ".json"), report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True, help="Local official TLC full-bill PDF")
    parser.add_argument("--bill-id", required=True)
    parser.add_argument("--session", default="90R")
    parser.add_argument("--version", required=True, help="Official text version, e.g. introduced")
    parser.add_argument("--source-url", required=True, help="Official TLC FTP provenance URL")
    default_cache = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    parser.add_argument("--cache-dir", type=Path, default=default_cache / "texas-bill-atlas" / "extraction")
    parser.add_argument("--execute", action="store_true", help="Allow a paid call only on a cache miss")
    args = parser.parse_args()
    if not args.source_url.startswith("ftp://ftp.legis.state.tx.us/bills/"):
        parser.error("Use the official TLC bulk FTP source URL")
    try:
        check_cache_location(args.cache_dir)
    except ValueError as error:
        parser.error(str(error))
    document = read_pdf(args.pdf, args.bill_id, args.session, args.version)
    document["source_url"] = args.source_url
    report = extract(document, load_registry(), args.cache_dir, execute=args.execute)
    summary = {k: v for k, v in report.items() if k not in ("result", "evidence_reverse_index")}
    print(json.dumps(summary, indent=2))
    return 2 if report.get("errors") or (args.execute and report.get("action") == "not_submitted") else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Avoid leaking SDK exception contents or credentials into scheduled logs.
        detail = ""
        if isinstance(error, (CacheBusy, CacheCoolingDown, CapacityUnavailable, NotSubmitted, UnresolvedCall)):
            detail = ": " + str(error)
        else:
            code = getattr(error, "code", None)
            if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,80}", code):
                detail = ": " + code
        print("Extraction stopped: " + type(error).__name__ + detail, file=sys.stderr)
        raise SystemExit(2)
