"""Second pass: one cacheable Luna call per settled review for topic suggestions (private), reader extras (public
via extras.json: a plain-language headline, search terms, opposing-side terms) and the "all state agencies" scope
marker (public via tags.json), which is decided here from the bill text, not by the first pass.

The marker is a 2-of-3 vote: vote 1 is the call above; votes 2 and 3 repeat it as separate requests (a trailing
run line makes their cache keys differ), vote 3 only when the first two do not settle it. Each vote is bound to the
review and text it answered, and a vote made for an earlier review never counts.

The request is built from the review's verified claims, the bill text and the current topic list, so a repeat is an
exact response-cache hit and a bill is re-asked only when one of them changes. Extras are published only while the
record's input hash matches the bill's current verified review; the scope marker only while its quotes verified and
its binding matches the review and the text's content. Usage for the tally:
    python scripts/topic_suggestions.py --cache-dir <cache> [--min-bills 2]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re

import classify_bill
import extract_bill as detailed

ROOT = detailed.ROOT
FORMAT = "texas-bill-topic-suggestions-v2"
EXTRAS_FORMAT = "texas-bill-luna-extras-v1"
TERM = {"type": "string", "minLength": 2, "maxLength": 40}
BILL_RE = re.compile(r"[A-Z]{2,4}\d{1,5}")


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


SCOPE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["applies", "explanation", "quotes"],
                "properties": {"applies": {"type": "boolean"}, "explanation": {"type": "string", "maxLength": 300},
                               "quotes": {"type": "array", "maxItems": 3,
                                          "items": {"type": "string", "minLength": 12, "maxLength": 300}}}}
MIN_QUOTE_ALNUM = 30  # a bare "state agency" proves nothing; the quote must carry the operative clause


def _schema(topics: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False,
            "required": ["headline", "search_terms", "opposing_terms", "suggestions", "all_state_agencies"],
            "properties": {"all_state_agencies": SCOPE_SCHEMA,
                           "headline": {"type": "string", "maxLength": 160},
                           "search_terms": {"type": "array", "maxItems": 8, "items": TERM},
                           "opposing_terms": {"type": "array", "maxItems": 6, "items": TERM},
                           "suggestions": {"type": "array", "maxItems": 3, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["topic", "reason", "closest_existing"],
                "properties": {"topic": {"type": "string", "minLength": 2, "maxLength": 40},
                               "reason": {"type": "string", "minLength": 1, "maxLength": 300},
                               "closest_existing": {"anyOf": [{"type": "string", "enum": topics},
                                                              {"type": "null"}]}}}}}}


def review_input(bundle: dict) -> dict:
    """Verified claims only (as published): unverified text must not reach a public headline or search terms."""
    result = bundle["result"]
    verified = {c.get("claim") for c in (bundle.get("validation") or {}).get("verified_citations", [])
                if c.get("status") == "resolved"}

    def kept(field):
        return [item for i, item in enumerate(result.get(field) or []) if f"{field}:{i}" in verified]
    return {"summary": (result.get("summary") or {}).get("text") if "summary" in verified else None,
            "topics": sorted(t.get("tag") for t in kept("policy_tags") if t.get("tag")),
            "major_effects": [{k: e.get(k) for k in ("effect", "label", "explanation")} for e in kept("major_effects")],
            "affected_groups": sorted(g.get("group") for g in kept("affected_groups") if g.get("group"))}


def input_hash(bundle: dict) -> str:
    return hashlib.sha256(_canonical(review_input(bundle)).encode("utf-8")).hexdigest()


def bill_text(bundle: dict) -> str:
    """The text as the review saw it, <ins>/<del> kept (see review_audit.marked_text)."""
    import review_audit
    return review_audit.marked_text(bundle["document"])


def scope_hash(bundle: dict) -> str:
    """What the scope decision is bound to: the verified review and the text's content (text_hash, which an
    identical re-render keeps)."""
    return hashlib.sha256(_canonical({"review": review_input(bundle),
                                      "text_hash": bundle["document"].get("text_hash")}).encode("utf-8")).hexdigest()


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


def check_scope(scope: dict, document: dict) -> dict:
    """True only when every quote is current (not deleted) bill text long enough to carry a clause."""
    import review_audit
    current = re.sub(r"<del>.*?</del>", " ", review_audit.marked_text(document), flags=re.S)
    current = _alnum(re.sub(r"</?ins>", "", current))
    quotes = [" ".join(q.split()) for q in scope["quotes"]]
    found = [len(_alnum(q)) >= MIN_QUOTE_ALNUM and _alnum(q) in current for q in quotes]
    applies = bool(scope["applies"])
    return {"applies": applies, "explanation": " ".join(scope["explanation"].split()),
            "quotes": quotes if applies else [], "verified": not applies or (bool(quotes) and all(found))}


VOTES = (1, 2, 3)


def build_request(bundle: dict, topics: list[str], vote: int = 1) -> dict:
    """Vote 1 is the original request, byte for byte. Votes 2 and 3 add one trailing part after the bill text, so
    each is its own cache and ledger entry while the shared prompt prefix still caches."""
    if vote not in VOTES:
        raise ValueError(f"unknown vote {vote}")
    topics = sorted(topics)
    instructions = ((ROOT / "scripts/topic_suggestions_prompt.txt").read_text("utf-8")
                    + "\nCURRENT TOPICS:\n" + _canonical(topics))
    return {
        "model": classify_bill.MODEL, "service_tier": "flex", "store": False, "reasoning": {"effort": "low"},
        "max_output_tokens": 3000, "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "text": {"format": {"type": "json_schema", "name": "texas_bill_second_pass_v1", "strict": True,
                            "schema": _schema(topics)}},
        "input": [
            # Same developer text for every bill: one 12-hour prompt-cache prefix serves the whole pass.
            {"role": "developer", "content": [{"type": "input_text", "text": instructions,
                "prompt_cache_breakpoint": {"mode": "explicit", "ttl": "12h"}}]},
            {"role": "user", "content": [{"type": "input_text", "text": "REVIEW:\n" + _canonical(review_input(bundle))
                                          + "\n\nBILL TEXT:\n" + bill_text(bundle)}]
                                        + ([{"type": "input_text", "text": f"RUN: {vote}"}] if vote > 1 else [])},
        ],
    }


def _norm(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9& ]+", " ", name.lower()).split())


def validate(result: dict, topics: list[str], document: dict) -> dict:
    import jsonschema
    jsonschema.Draft202012Validator(_schema(sorted(topics))).validate(result)
    scope = check_scope(result["all_state_agencies"], document)
    existing = {_norm(t) for t in topics}
    kept, dropped = [], []
    for item in result["suggestions"]:
        (dropped if _norm(item["topic"]) in existing else kept).append(item)
    return {"errors": [], "kept": kept, "dropped": dropped, "status": "checked", "scope": scope,
            "headline": " ".join(result["headline"].split()) or None,
            "search_terms": _terms(result["search_terms"]), "opposing_terms": _terms(result["opposing_terms"])}


def _terms(items: list[str]) -> list[str]:
    out, seen = [], set()
    for item in items:
        term = " ".join(item.split())
        if term and term.lower() not in seen:
            seen.add(term.lower()); out.append(term)
    return out


def due(bundle: dict | None, record: dict | None, topics: list[str], retry: set[str], key_fn) -> bool:
    """A settled review (result, no queued follow-up questions) whose current request was not yet answered.

    `key_fn`: the key function of the response cache the call will go through (it differs by transport)."""
    if not isinstance(bundle, dict) or not isinstance(bundle.get("result"), dict):
        return False
    if bundle.get("bill_id") in retry:
        return False  # its review still changes when the questions run; ask once it settles
    try:
        if not any(review_input(bundle).values()):
            return False  # nothing verified to work from
        key = key_fn(build_request(bundle, topics))
    except (KeyError, TypeError, AttributeError):
        return False
    return not isinstance(record, dict) or record.get("request_key") != key


def suggest(bundle: dict, topics: list[str], registry: list[dict], cache_root: Path, *, execute=False,
            sender=None, cache=None, vote: int = 1) -> dict:
    """One call (or cache hit). Returns the extract report; `result` is present only when it validated."""
    request = build_request(bundle, topics, vote)

    def validator(result, document, registry, schema, key, sources=None):
        return validate(result, topics, document)

    return detailed.extract(bundle["document"], registry, cache_root, execute=execute, sender=sender,
                            request=request, validator=validator,
                            cost_estimator=classify_bill.response_cost, cache=cache)


def _vote_entry(bundle: dict, report: dict) -> dict:
    return {"request_key": report["request_key"], "status": report.get("status"),
            "scope": ({**report["scope"], "input_sha256": scope_hash(bundle)} if report.get("scope") else None)}


def _valid(entry, bundle: dict) -> bool:
    scope = entry.get("scope") if isinstance(entry, dict) and entry.get("status") == "checked" else None
    return isinstance(scope, dict) and scope.get("input_sha256") == scope_hash(bundle)


def votes(bundle: dict, record: dict | None) -> dict[int, dict]:
    """Scope votes made for this exact review and text, by vote number. A record from before voting counts its
    own scope as vote 1."""
    if not isinstance(record, dict):
        return {}
    raw = record.get("votes")
    if not isinstance(raw, dict):
        raw = {"1": {"request_key": record.get("request_key"), "status": record.get("status"),
                     "scope": record.get("scope")}}
    names = {str(v): v for v in VOTES}
    return {names[str(n)]: e["scope"] for n, e in raw.items() if str(n) in names and _valid(e, bundle)}


def decision(scopes: dict[int, dict]) -> dict | None:
    """2 of 3. A true vote needs verified quotes; a true vote whose quotes failed abstains (it is neither)."""
    trues = [n for n in sorted(scopes) if scopes[n].get("applies") and scopes[n].get("verified")]
    falses = [n for n in sorted(scopes) if not scopes[n].get("applies")]
    if len(trues) >= 2:
        first = scopes[trues[0]]
        return {"applies": True, "explanation": first.get("explanation") or "",
                "quotes": list(first.get("quotes") or [])}
    if len(falses) >= 2:
        return {"applies": False, "explanation": scopes[falses[0]].get("explanation") or "", "quotes": []}
    return None


def vote_due(bundle: dict | None, record: dict | None, retry: set[str]) -> int | None:
    """The next scope vote to ask (2 or 3), or None. Asked only after vote 1 answered this review and text."""
    if not isinstance(bundle, dict) or not isinstance(bundle.get("result"), dict) or bundle.get("bill_id") in retry:
        return None
    try:
        have = votes(bundle, record)
        if 1 not in have or decision(have) is not None:
            return None
    except (KeyError, TypeError, AttributeError):
        return None
    return next((v for v in VOTES if v not in have), None)


def with_vote(bundle: dict, record: dict, vote: int, report: dict) -> dict:
    """`record` with `vote` added; votes for any other review or text are dropped so they never pair up."""
    kept = {str(n): e for n, e in (record.get("votes") or {}).items() if _valid(e, bundle)}
    return {**record, "votes": {**kept, str(vote): _vote_entry(bundle, report)}}


def record_for(bundle: dict, report: dict, previous: dict | None = None) -> dict:
    """Vote 1's record: extras and suggestions come only from it. Earlier votes 2 and 3 for the same review and
    text are kept."""
    kept = {}
    if isinstance(previous, dict) and isinstance(previous.get("votes"), dict):
        kept = {str(n): e for n, e in previous["votes"].items() if str(n) != "1" and _valid(e, bundle)}
    return {"format": FORMAT, "bill_id": bundle["bill_id"], "request_key": report["request_key"],
            "review_key": bundle.get("first_pass_request_key"), "status": report.get("status"),
            "errors": report.get("errors", []), "suggestions": report.get("kept", []),
            "dropped": report.get("dropped", []), "input_sha256": input_hash(bundle),
            "headline": report.get("headline"), "search_terms": report.get("search_terms", []),
            "opposing_terms": report.get("opposing_terms", []),
            "scope": ({**report["scope"], "input_sha256": scope_hash(bundle)} if report.get("scope") else None),
            "votes": {**kept, "1": _vote_entry(bundle, report)}}


def scope_entry(bundle: dict, record: dict | None) -> dict | None:
    """The public all-state-agencies marker, or None until 2 of 3 votes for this exact review and text agree (the
    site then keeps its caption inference). Never the first pass's own marker."""
    if "result" not in bundle:
        return None
    return decision(votes(bundle, record))


def read_scope(cache_dir: Path, bill_id: str, bundle: dict) -> dict | None:
    try:
        record = json.loads((cache_dir / "suggestions" / (bill_id + ".json")).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return scope_entry(bundle, record)
    except (KeyError, TypeError, AttributeError):
        return None


def extras_entry(bundle: dict, record: dict | None) -> dict | None:
    """Public extras for a bill, or None unless the record answered this exact verified review."""
    if not isinstance(record, dict) or record.get("status") != "checked" or "result" not in bundle:
        return None
    if record.get("input_sha256") != input_hash(bundle):
        return None  # the review changed since; stale extras are not shown
    entry = {"search_terms": record.get("search_terms") or [], "opposing_terms": record.get("opposing_terms") or []}
    if record.get("headline") and review_input(bundle)["summary"]:
        entry["headline"] = record["headline"]
    return entry if entry.get("headline") or entry["search_terms"] or entry["opposing_terms"] else None


def publish_extras(reviews, cache_dir: Path, out: Path) -> int:
    """`reviews`: (bill_id, bundle) pairs of current reviews. Writes the world-readable extras file."""
    bills = {}
    for bill_id, bundle in reviews:
        try:
            record = json.loads((cache_dir / "suggestions" / (bill_id + ".json")).read_text("utf-8"))
        except (OSError, ValueError):
            continue
        entry = extras_entry(bundle, record)
        if entry:
            bills[bill_id] = entry
    payload = {"format": EXTRAS_FORMAT, "model": classify_bill.MODEL,
               "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
               "bills": bills}
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(out.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, out)
    return len(bills)


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
