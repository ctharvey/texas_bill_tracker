"""Pure stage logic for the staged Luna review: detector, version update, and fiscal check."""
from __future__ import annotations

import copy
import difflib
import functools
import hashlib
import json
from pathlib import Path
import re

import classify_bill
import extract_bill as detailed

ROOT = detailed.ROOT
DOCUMENTS_FORMAT = "texas-bill-documents-v1"
FISCAL_TYPES = ("fiscal_note", "analysis")
FISCAL_FORMAT = "texas-bill-luna-fiscal-v1"


def version_code(document: dict) -> str:
    version = document["version"]
    return "I" if version == "introduced" else version


def latest_version(index: dict | None) -> dict | None:
    if not isinstance(index, dict) or not isinstance(index.get("versions"), list) or not index["versions"]:
        return None
    last = index["versions"][-1]
    if not isinstance(last, dict) or not isinstance(last.get("code"), str) or not last["code"]:
        return None
    return last


def _with_ids(docs: list[dict]) -> list[dict]:
    counters, result = {}, []
    for doc in docs:
        counters[doc["type"]] = counters.get(doc["type"], 0) + 1
        prefix = "F" if doc["type"] == "fiscal_note" else "A"
        result.append({**doc, "id": doc.get("id") or f"{prefix}{counters[doc['type']]}"})
    return result


def fiscal_documents_for(docs_index: dict | None, code: str) -> list[dict]:
    if not isinstance(docs_index, dict) or not isinstance(docs_index.get("documents"), list):
        return []
    entries = [d for d in docs_index["documents"]
               if isinstance(d, dict) and d.get("type") in FISCAL_TYPES and d.get("code") == code]
    return sorted(entries, key=lambda d: (d["type"], d["code"]))


def fiscal_binding(bundle: dict, docs: list[dict]) -> dict:
    return {"review_key": bundle.get("first_pass_request_key"),
            "text_sha256": bundle["document"].get("text_sha256"),
            "version": version_code(bundle["document"]),
            "documents": {d["id"]: d["sha256"] for d in _with_ids(docs)}}


def stage_plan(bundle: dict | None, index: dict | None, docs_index: dict | None,
               fiscal_record: dict | None) -> dict:
    latest = latest_version(index)
    if (not isinstance(bundle, dict) or not isinstance(bundle.get("result"), dict)
            or not isinstance(bundle.get("document"), dict)):
        return {"review": "first", "code": latest["code"] if latest else "I", "reason": "new_bill",
                "from_code": None, "fiscal_due": False}
    reviewed = version_code(bundle["document"])
    reviewed_sha = bundle["document"].get("text_sha256")
    if latest is None:
        review, code, reason, from_code = "revisit", reviewed, "reviewed_version", None
    elif latest["code"] != reviewed:
        review, code, reason, from_code = "update", latest["code"], "new_version", reviewed
    elif reviewed_sha and latest.get("sha256") and reviewed_sha != latest["sha256"]:
        review, code, reason, from_code = "update", reviewed, "text_revised", reviewed
    else:
        review, code, reason, from_code = "revisit", reviewed, "reviewed_version", None
    due = False
    if review == "revisit":
        docs = fiscal_documents_for(docs_index, reviewed)
        due = bool(docs) and (fiscal_record is None
                              or fiscal_record.get("binding") != fiscal_binding(bundle, docs))
    return {"review": review, "code": code, "reason": reason, "from_code": from_code, "fiscal_due": due}


def load_fiscal_documents(bill_id: str, history_dir: Path, code: str) -> list[dict]:
    if not re.fullmatch(r"[A-Z]{2,4}\d{1,5}", bill_id):
        raise ValueError("Invalid bill ID")
    folder = history_dir / bill_id
    index = json.loads((folder / "documents.json").read_text("utf-8"))
    if not isinstance(index, dict) or index.get("format") != DOCUMENTS_FORMAT:
        raise ValueError("Malformed documents index")
    docs = []
    for entry in _with_ids(fiscal_documents_for(index, code)):
        name = entry.get("path")
        if (not isinstance(name, str) or not name or "/" in name or "\\" in name or ".." in name
                or name != Path(name).name):
            raise ValueError("Invalid document path")
        data = (folder / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            raise ValueError("Document does not match its index checksum")
        docs.append({"id": entry["id"], "type": entry["type"], "code": entry["code"],
                     "name": entry.get("name", ""), "sha256": entry["sha256"], "text": data.decode("utf-8")})
    return docs


def previous_for_update(bundle: dict) -> dict:
    result = copy.deepcopy(bundle["result"])
    result.pop("uncertainties", None)
    result.pop("bill_id", None)

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "evidence" and isinstance(value, list):
                    node[key] = [{"quote": e["quote"]} for e in value if isinstance(e, dict) and "quote" in e]
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(result)
    return {"version": version_code(bundle["document"]), "result": result}


def _diff(old: list[str], new: list[str], limit_chars: int) -> str:
    text = "\n".join(difflib.unified_diff(old, new, fromfile="previous", tofile="current", lineterm="", n=1))
    if len(text) > limit_chars:
        text = text[:limit_chars] + "\n[diff truncated]"
    return text


def paragraph_diff(old_markdown: str, new_markdown: str, limit_chars: int = 20000) -> str:
    return _diff(detailed.plain_paragraphs(old_markdown), detailed.plain_paragraphs(new_markdown), limit_chars)


def build_version_update_request(document: dict, registry: list[dict], previous: dict, diff: str) -> dict:
    request = copy.deepcopy(classify_bill.build_request(document, registry))
    request["input"][0]["content"][0]["text"] += (
        "\n" + (ROOT / "scripts/version_update_prompt.txt").read_text("utf-8"))
    schema = request["text"]["format"]["schema"]
    evidence = copy.deepcopy(schema["properties"]["summary"]["properties"]["evidence"]["items"])
    schema["properties"]["changes"] = {
        "type": "array", "maxItems": 12,
        "items": {"type": "object",
                  "properties": {"kind": {"type": "string", "enum": ["added", "removed", "altered"]},
                                 "label": {"type": "string"}, "explanation": {"type": "string"},
                                 "evidence": {"type": "array", "items": evidence, "minItems": 1, "maxItems": 3}},
                  "required": ["kind", "label", "explanation", "evidence"], "additionalProperties": False}}
    schema["required"] = [*schema["required"], "changes"]
    request["text"]["format"]["name"] = "texas_bill_version_update_v1"
    request["input"][1]["content"][0]["text"] += (
        "\nPREVIOUS VERSION REVIEW (" + previous["version"] + "; evidence quotes refer to that text):\n"
        + json.dumps(previous["result"], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\nPARAGRAPH DIFF FROM THE PREVIOUS VERSION:\n" + diff)
    return request


def validate_version_update(result, document, registry, schema, key, sources=None, *, old_document) -> dict:
    import jsonschema
    jsonschema.Draft202012Validator(schema).validate(result)
    changes = result.pop("changes")
    if not isinstance(changes, list):
        raise ValueError("changes must be a list")
    validation = classify_bill.validate_result(
        result, document, registry, classify_bill.build_request(document, registry)["text"]["format"]["schema"],
        key, sources)
    errors = list(validation["errors"])
    checked = []
    for change in changes:
        against = old_document if change["kind"] == "removed" else document
        citations = [classify_bill.resolve_quote(e["quote"], e["span_id"], against) for e in change["evidence"]]
        verified = all(c["status"] == "resolved" for c in citations)
        if not verified:
            errors.append("Unresolved change excerpt: " + change["label"])
        checked.append({"kind": change["kind"], "label": change["label"], "explanation": change["explanation"],
                        "evidence": change["evidence"], "verified": verified, "citations": citations})
    reasons = validation["review_reasons"]
    validation.update(errors=sorted(set(errors)), changes=checked,
                      status="needs_review" if errors or reasons else "pending_review",
                      audit_recommended=bool(errors or reasons))
    return validation


def page_diff(old_document: dict, document: dict) -> str:
    return _diff(old_document["pages"], document["pages"], 20000)


def version_update(document, old_document, previous, registry, cache_root, *, execute=False, sender=None,
                   cache=None, diff: str | None = None) -> dict:
    # `diff`: the one stored with the review, so a revisit rebuilds the identical request (a cache hit) even if
    # the previous version's file was re-converted since.
    request = build_version_update_request(
        document, registry, previous, page_diff(old_document, document) if diff is None else diff)
    return detailed.extract(document, registry, cache_root, execute=execute, sender=sender, request=request,
                            validator=functools.partial(validate_version_update, old_document=old_document),
                            cost_estimator=classify_bill.response_cost, cache=cache)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def build_fiscal_request(bundle: dict, docs: list[dict], registry: list[dict]) -> dict:
    schema = json.loads((ROOT / "scripts/fiscal_check_schema.json").read_text("utf-8"))
    instructions = ((ROOT / "scripts/fiscal_check_prompt.txt").read_text("utf-8")
                    + "\nCANONICAL AGENCIES:\n"
                    + _canonical([a for a in sorted(registry, key=lambda a: a["id"])
                                  if a["id"] != "all-state-agencies"]))
    result = bundle["result"]
    review = {"agencies": [{k: a.get(k) for k in ("registry_id", "name", "impact", "explanation")}
                           for a in result.get("agencies", [])],
              "major_effects": [{k: e.get(k) for k in ("effect", "label", "explanation")}
                                for e in result.get("major_effects", [])],
              "summary": result["summary"]["text"]}
    identity = {"bill_id": bundle["bill_id"] if "bill_id" in bundle else result.get("bill_id"),
                "version": version_code(bundle["document"])}
    sources = "\n\n".join(f"[{d['id']}; {d['type']} {d['code']}: {d['name']}]\n{d['text']}"
                          for d in _with_ids(docs))
    return {
        "model": classify_bill.MODEL, "service_tier": "flex", "store": False, "reasoning": {"effort": "high"},
        "max_output_tokens": 8000, "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "text": {"format": {"type": "json_schema", "name": "texas_bill_fiscal_check_v1",
                            "strict": True, "schema": schema}},
        "input": [
            {"role": "developer", "content": [{"type": "input_text", "text": instructions,
                "prompt_cache_breakpoint": {"mode": "explicit", "ttl": "12h"}}]},
            {"role": "user", "content": [{"type": "input_text",
                "text": _canonical(identity) + "\nCURRENT REVIEW (verified claims):\n" + _canonical(review)
                        + "\nDOCUMENTS:\n" + sources}]},
        ],
    }


def _squash(text: str) -> str:
    return " ".join(text.split())


def validate_fiscal(result: dict, docs: list[dict], registry: list[dict]) -> dict:
    import jsonschema
    schema = json.loads((ROOT / "scripts/fiscal_check_schema.json").read_text("utf-8"))
    jsonschema.Draft202012Validator(schema).validate(result)
    texts = {d["id"]: _squash(d["text"]) for d in docs}
    errors = []

    def quotes_ok(evidence, label):
        ok = True
        for item in evidence:
            quote = _squash(item["quote"])
            if not quote or item["doc_id"] not in texts or quote not in texts[item["doc_id"]]:
                ok = False
        if not ok:
            errors.append("Unresolved fiscal excerpt: " + label)
        return ok

    names = {a["id"]: a["name"] for a in registry if a["id"] != "all-state-agencies"}
    summary = quotes_ok(result["fiscal_summary"]["evidence"], "fiscal_summary")
    agencies = []
    for i, agency in enumerate(result["agencies"]):
        ok = quotes_ok(agency["evidence"], f"agencies:{i}")
        if agency["registry_id"] is not None and names.get(agency["registry_id"]) != agency["name"]:
            errors.append("Noncanonical agency identity: " + agency["name"])
            ok = False
        agencies.append(ok)
    disagreements = [quotes_ok(d["evidence"], f"disagreements:{i}") for i, d in enumerate(result["disagreements"])]
    return {"errors": sorted(set(errors)),
            "verified": {"fiscal_summary": summary, "agencies": agencies, "disagreements": disagreements},
            "status": "needs_review" if errors else "checked"}


def fiscal_check(bundle, docs, registry, cache_root, *, execute=False, sender=None, cache=None) -> dict:
    request = build_fiscal_request(bundle, docs, registry)

    def validator(result, document, registry, schema, key, sources=None):
        return validate_fiscal(result, docs, registry)

    report = detailed.extract(bundle["document"], registry, cache_root, execute=execute, sender=sender,
                              request=request, validator=validator,
                              cost_estimator=classify_bill.response_cost, cache=cache)
    return {**report, "binding": fiscal_binding(bundle, docs),
            "documents": [{k: d[k] for k in ("id", "type", "code", "sha256")} for d in _with_ids(docs)]}


def public_fiscal(record: dict) -> dict | None:
    report = (record or {}).get("report")
    if not isinstance(report, dict) or not isinstance(report.get("result"), dict):
        return None
    result, verified, binding = report["result"], report.get("verified") or {}, record["binding"]
    documents = record.get("documents") or report.get("documents")
    if documents is None:
        documents = [{"id": i, "sha256": sha} for i, sha in binding["documents"].items()]

    def quotes(evidence):
        return [e["quote"] for e in evidence]  # the site renders quote strings

    def flags(name, count):
        value = verified.get(name) or []
        return [bool(value[i]) if i < len(value) else False for i in range(count)]

    output = {"format": FISCAL_FORMAT, "bill_id": record.get("bill_id", result.get("bill_id")),
              "text_version": binding["version"], "text_sha256": binding["text_sha256"],
              "documents": documents, "no_fiscal_implication": result["no_fiscal_implication"]}
    if verified.get("fiscal_summary"):
        output["summary"] = {"text": result["fiscal_summary"]["text"],
                             "quotes": quotes(result["fiscal_summary"]["evidence"])}
    output["agencies"] = [
        {"name": a["name"], "registry_id": a["registry_id"], "in_review": a["in_review"],
         "fiscal_effect": a["fiscal_effect"], "quotes": quotes(a["evidence"])}
        for a, ok in zip(result["agencies"], flags("agencies", len(result["agencies"]))) if ok]
    output["disagreements"] = [
        {"claim": d["claim"], "note": d["note"], "quotes": quotes(d["evidence"])}
        for d, ok in zip(result["disagreements"], flags("disagreements", len(result["disagreements"]))) if ok]
    return output
