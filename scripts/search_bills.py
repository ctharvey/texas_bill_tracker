"""Search the agent edition's bill records (live/agent/data/bills.json) for agents and scripts.

Words match word forms (plural, -ing, -ed), quoted text matches as a phrase, and a few common synonyms widen a
word in both directions (gun <-> firearm). Every word must match unless none does, then any word counts and the page
says so. Filters: chamber, topic, agency, location, party, reviewed, filed_from, filed_to. Read-only; standard library only.
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlencode

AGENT = "https://agent.bills.ctharvey.me/"
SITE = "https://bills.ctharvey.me/"
WORD = re.compile(r"[a-z0-9]+")
BILL_REF = re.compile(r"\b(hb|sb|hjr|sjr|hcr|scr|hr|sr)\s*([1-9]\d{0,4})\b")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_QUERY, DEFAULT_LIMIT, MAX_LIMIT = 200, 50, 200
DISCLAIMER = ("Unofficial, independent open-source project; not a state website. Bill data comes from the Texas "
              "Legislative Council bulk files and can lag or contain errors. Topic, agency and impact tags are automated "
              "(caption rules or the Luna model reading the full text) and can be wrong. Not legal advice. Confirm on "
              "Texas Legislature Online before relying on anything here.")
STOP = {"a", "an", "and", "the", "of", "to", "for", "in", "on", "or", "by", "with", "at", "as", "is", "are", "be",
        "bill", "bills", "about", "relating", "that", "this", "which", "any", "all", "certain", "texas", "state"}
# Groups of close equivalents in Texas bill language: any member finds every other member, so "firearm" and "gun"
# return the same bills. Keep groups small and obvious; one-way widenings are listed in BROADER.
SYNONYM_GROUPS = (
    ("gun", "firearm", "handgun", "rifle", "shotgun", "weapon"),
    ("voucher", "education savings account", "school choice", "esa"),
    ("aquifer", "groundwater"), ("kid", "child", "minor"), ("car", "vehicle", "automobile"),
    ("police", "cop", "peace officer", "law enforcement"), ("teacher", "educator"),
    ("marijuana", "cannabis"), ("immigrant", "immigration", "alien"), ("tax", "taxation"),
    ("ai", "artificial intelligence"), ("power", "electric", "electricity"), ("vote", "voter", "ballot"),
)
BROADER = {"marijuana": ["hemp"], "cannabis": ["hemp"], "abortion": ["unborn child", "pregnancy"], "vote": ["election"]}


def _synonyms() -> dict[str, list[str]]:
    table: dict[str, list[str]] = {}
    for group in SYNONYM_GROUPS:
        for member in group:
            key = " ".join(stem(w) for w in words(member))
            table.setdefault(key, []).extend(m for m in group if m != member)
    for word, wider in BROADER.items():
        table.setdefault(stem(word), []).extend(wider)
    return {k: list(dict.fromkeys(v)) for k, v in table.items()}
FIELDS = (("title", 3), ("topics", 4), ("agencies", 4), ("people", 3), ("summary", 2), ("groups", 2),
          ("locations", 2), ("impacts", 1), ("actions", 1))
LABELS = {"title": "title/caption", "topics": "topics", "agencies": "agencies", "people": "members",
          "summary": "full-text summary", "groups": "affected groups", "locations": "locations",
          "impacts": "impacts", "actions": "actions"}


def stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 5 and word.endswith(("ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed") and not word.endswith("eed"):
        return word[:-2]
    return word


def words(text: str) -> list[str]:
    return WORD.findall(str(text or "").lower())


SYNONYMS = _synonyms()


def record_fields(r: dict) -> dict[str, str]:
    people = [p.get("full_name") or p.get("name") or "" for role in (r.get("people") or {}).values() if role for p in role]
    review = r.get("full_text_review") or {}
    return {
        "title": f"{r.get('title') or ''} {r.get('caption') or ''}",
        "topics": " ; ".join(r.get("topics") or []),
        "agencies": " ; ".join(f"{a.get('name') or ''} {a.get('id') or ''}" for a in r.get("agencies") or []),
        "people": " ; ".join(people),
        "summary": review.get("summary") or "",
        "groups": " ; ".join(r.get("affected_groups") or []),
        "locations": " ; ".join(l.get("name") or "" for l in r.get("locations") or []),
        "impacts": " ; ".join(r.get("impacts") or []),
        "actions": " ; ".join(r.get("actions") or []),
    }


class Index:
    """Bill records plus per-field stemmed tokens; reloads when the file changes and keeps the last good copy."""

    def __init__(self, path: Path):
        self.path, self.mtime, self.lock = path, None, threading.Lock()
        self.meta, self.docs, self.vocab = {}, [], []

    def get(self):
        with self.lock:
            try:
                mtime = self.path.stat().st_mtime
            except OSError:
                return self
            if mtime != self.mtime:
                try:
                    data = json.loads(self.path.read_text("utf-8"))
                    self.load(data)
                    self.mtime = mtime
                except (OSError, ValueError, TypeError, AttributeError):
                    pass
            return self

    def load(self, data: dict) -> None:
        docs, vocab = [], set()
        for r in data.get("bills") or []:
            if not isinstance(r, dict) or not r.get("id"):
                continue
            fields = record_fields(r)
            tokens = {name: {stem(w) for w in words(text)} for name, text in fields.items()}
            lowered = {name: " ".join(words(text)) for name, text in fields.items()}
            vocab.update(w for w in words(fields["title"] + " " + fields["topics"] + " " + fields["summary"]) if len(w) > 3)
            docs.append((r, tokens, lowered))
        self.docs, self.vocab = docs, sorted(vocab)
        self.meta = {k: data.get(k) for k in ("bill_data_as_of", "tags_as_of", "roster_as_of", "count", "coverage")}


def parse_query(q: str) -> tuple[list[str], list[list[str]], list[str]]:
    """Phrases (quoted), word terms (each a list of alternatives, stemmed) and bill ids named in the query."""
    lowered = q.lower()
    ids = [f"{m[1].upper()}{m[2]}" for m in BILL_REF.finditer(lowered)]
    rest = BILL_REF.sub(" ", lowered)
    phrases, terms = [], []
    for p in re.findall(r'"([^"]+)"', rest):
        key = " ".join(stem(w) for w in words(p))
        if key in SYNONYMS:  # A quoted synonym phrase ("school choice") widens like a word.
            terms.append(list(dict.fromkeys([" ".join(words(p))] + SYNONYMS[key])))
        elif words(p):
            phrases.append(" ".join(words(p)))
    rest = re.sub(r'"[^"]*"', " ", rest)
    for w in words(rest):
        if w in STOP or len(w) < 2:
            continue
        alternatives = [w] + SYNONYMS.get(stem(w), [])
        terms.append(list(dict.fromkeys(alternatives)))
    return phrases, terms, ids


def term_hit(alternatives: list[str], tokens: dict, lowered: dict) -> tuple[int, set]:
    best, where = 0, set()
    for alt in alternatives:
        parts = words(alt)
        for name, weight in FIELDS:
            hit = (" ".join(parts) in lowered[name]) if len(parts) > 1 else stem(parts[0]) in tokens[name]
            if hit:
                where.add(name)
                best = max(best, weight if alt == alternatives[0] else weight - 1)
    return best, where


def matches_filters(r: dict, f: dict) -> bool:
    if f.get("chamber") and (r.get("chamber") or "").lower() != f["chamber"].lower():
        return False
    if f.get("topic") and not any(f["topic"].lower() in t.lower() for t in r.get("topics") or []):
        return False
    if f.get("agency") and not any(f["agency"].lower() in f"{a.get('id') or ''} {a.get('name') or ''}".lower()
                                   for a in r.get("agencies") or []):
        return False
    if f.get("location"):
        place = " ".join(words(f["location"]))
        named = [l.get("name") or "" for l in r.get("locations") or []] + [f"{r.get('title') or ''} {r.get('caption') or ''}"]
        if not place or not any(re.search(rf"\b{re.escape(place)}\b", " ".join(words(text))) for text in named):
            return False
    if f.get("party") and f["party"].lower() not in ((r.get("authorship_party") or {}).get("label") or "").lower():
        return False
    if f.get("reviewed") in ("yes", "true", "1") and not r.get("full_text_review"):
        return False
    if f.get("reviewed") in ("no", "false", "0") and r.get("full_text_review"):
        return False
    filed = r.get("filed_at") or ""
    if f.get("filed_from") and (not filed or filed < f["filed_from"]):
        return False
    if f.get("filed_to") and (not filed or filed > f["filed_to"]):
        return False
    return True


FILTERS = ("chamber", "topic", "agency", "location", "party", "reviewed", "filed_from", "filed_to")


class BadQuery(ValueError):
    pass


def parse_params(query_string: str) -> dict:
    raw = {k: v[-1].strip() for k, v in parse_qs(query_string, keep_blank_values=False).items()}
    q = raw.get("q", "")
    if len(q) > MAX_QUERY or any(len(raw.get(k, "")) > 100 for k in FILTERS):
        raise BadQuery(f"q is limited to {MAX_QUERY} characters and filters to 100")
    for k in ("filed_from", "filed_to"):
        if raw.get(k) and not DATE.fullmatch(raw[k]):
            raise BadQuery(f"{k} must be YYYY-MM-DD")
    try:
        limit = min(MAX_LIMIT, max(1, int(raw.get("limit") or DEFAULT_LIMIT)))
        offset = max(0, int(raw.get("offset") or 0))
    except ValueError:
        raise BadQuery("limit and offset must be whole numbers") from None
    return {"q": q, "filters": {k: raw[k] for k in FILTERS if raw.get(k)}, "limit": limit, "offset": offset,
            "format": "json" if raw.get("format") == "json" else "md"}


def search(index: Index, params: dict) -> dict:
    phrases, terms, ids = parse_query(params["q"])
    filters, results, mode = params["filters"], [], "all"
    pool = [d for d in index.docs if matches_filters(d[0], filters)]

    def scored(require_all: bool) -> list:
        found = []
        for r, tokens, lowered in pool:
            named = r["id"] in ids
            if not named and not terms and not phrases:
                continue  # Only bill numbers were asked for.
            score, hits, where = (100, 0, {"bill number"}) if named else (0, 0, set())
            missing_phrase = False
            for phrase in phrases:
                fields = [name for name, _ in FIELDS if phrase in lowered[name]]
                if fields:
                    score += 5
                    where.update(fields)
                else:
                    missing_phrase = True
            if missing_phrase and not named:
                continue
            for alternatives in terms:
                weight, fields = term_hit(alternatives, tokens, lowered)
                if weight:
                    hits, score = hits + 1, score + weight
                    where.update(fields)
            if not named and terms and (hits < len(terms) if require_all else hits == 0):
                continue
            found.append((hits, score, r, where))
        return found

    if not phrases and not terms and not ids:
        results = [(0, 0, r, set()) for r, _, _ in pool] if filters else []
        mode = "filters"
    else:
        results = scored(True)
        if not results and len(terms) > 1:
            results, mode = scored(False), "any"
    # Most recent action first, then (stable) best match first.
    results.sort(key=lambda x: ((x[2].get("last_action") or {}).get("date") or "", x[2]["id"]), reverse=True)
    results.sort(key=lambda x: (x[0], x[1]), reverse=True)
    page = results[params["offset"]:params["offset"] + params["limit"]]
    suggestions = []
    if not results and (terms or phrases):
        seen = set(index.vocab)
        for w in [w for t in terms for w in words(t[0])] + [w for p in phrases for w in p.split()]:
            if w not in seen:
                suggestions += difflib.get_close_matches(w, index.vocab, n=3, cutoff=0.8)
        suggestions = list(dict.fromkeys(suggestions))[:6]
    known = {d[0]["id"] for d in index.docs}
    return {"missing_ids": [i for i in dict.fromkeys(ids) if i not in known],
            "query": params["q"], "mode": mode, "filters": filters, "total": len(results), "offset": params["offset"],
            "limit": params["limit"], "results": page, "suggestions": suggestions, "meta": index.meta,
            "terms": [t[0] for t in terms], "phrases": phrases, "ids": ids}


def link(params: dict, **changes) -> str:
    values = {"q": params["q"], **params["filters"], "limit": params["limit"], "offset": params["offset"], **changes}
    values = {k: v for k, v in values.items() if v not in ("", None) and not (k == "offset" and not v)
              and not (k == "limit" and v == DEFAULT_LIMIT)}
    return f"{AGENT}search?{urlencode(values)}"


def cell(value) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()


def as_json(found: dict, params: dict) -> dict:
    nxt = found["offset"] + found["limit"]
    return {"format": "texas-bill-atlas-search-v1", "query": found["query"], "mode": found["mode"],
            "filters": found["filters"], "total": found["total"], "offset": found["offset"], "limit": found["limit"],
            "data_as_of": found["meta"].get("bill_data_as_of"), "tags_as_of": found["meta"].get("tags_as_of"),
            "coverage": found["meta"].get("coverage"), "suggestions": found["suggestions"],
            "not_in_data": found["missing_ids"],
            "next": link(params, offset=nxt, format="json") if nxt < found["total"] else None,
            "results": [{"id": r["id"], "number": r.get("number"), "title": r.get("title"), "status": r.get("status"),
                         "filed_at": r.get("filed_at"), "chamber": r.get("chamber"), "topics": r.get("topics") or [],
                         "agencies": [a.get("name") for a in r.get("agencies") or []],
                         "locations": [l.get("name") for l in r.get("locations") or []],
                         "full_text_reviewed": bool(r.get("full_text_review")),
                         "last_action": r.get("last_action"), "matched_in": sorted(LABELS.get(w, w) for w in where),
                         "markdown": f"{AGENT}bills/{r['id']}.md", "json": f"{AGENT}bills/{r['id']}.json"}
                        for *_, r, where in found["results"]]}


def usage(meta: dict) -> str:
    return f"""# Search Texas Bill Atlas

`GET {AGENT}search?q=<words>` returns matching bills as Markdown; add `&format=json` for JSON.

- Words match their forms (firearm, firearms; school, schools). Quote a phrase: `q="water rights"`.
- Common synonyms find each other: gun, firearm, handgun, rifle and weapon return the same bills; voucher, "school
  choice" and "education savings account" do too; aquifer and groundwater; marijuana and cannabis.
- Every word must match. If no bill matches every word, bills matching any word are shown, and the page says so.
- Bill numbers work: `q=HB 5` or `q=sb12`.
- Filters (with or without q): `chamber=House|Senate`, `topic=<part of a topic name>`, `agency=<id or part of a name>`,
  `location=<part of a place name, e.g. Harris>`, `party=democratic|republican|bipartisan`, `reviewed=yes|no`,
  `filed_from=YYYY-MM-DD`, `filed_to=YYYY-MM-DD`. A location matches a place the full-text review names, or the place
  named in the title or caption; unreviewed bills that affect a place without naming it are not found.
- Bills filed in the last few days: `filed_from=<date>` with no q (all of them, most recent action first).
- Paging: `limit` (default {DEFAULT_LIMIT}, at most {MAX_LIMIT}) and `offset`.

Searched: titles and captions, topics, agencies, Luna full-text summaries, member names, affected groups, locations,
impacts and recorded actions. Only {(meta.get('coverage') or {}).get('full_text_reviewed', 'some')} bills have a full-text review so far; for
the rest only the caption and caption-based tags are searchable.

Examples: [{AGENT}search?q=groundwater]({AGENT}search?q=groundwater) ·
[{AGENT}search?q=gun]({AGENT}search?q=gun) ·
[{AGENT}search?q=data+center&agency=puc]({AGENT}search?q=data+center&agency=puc) ·
[{AGENT}search?filed_from=2026-11-10]({AGENT}search?filed_from=2026-11-10)
"""


def as_markdown(found: dict, params: dict, disclaimer: str = "") -> str:
    meta, total = found["meta"], found["total"]
    described = " ".join([f'"{p}"' for p in found["phrases"]] + found["terms"] + found["ids"]) or "(filters only)"
    filters = ", ".join(f"{k}={v}" for k, v in found["filters"].items())
    as_of = f"Bill data as of {meta.get('bill_data_as_of') or 'unknown'}; full-text tags as of {meta.get('tags_as_of') or 'not available yet'}."
    lines = [f"# Search: {cell(params['q']) or '(no words)'}", ""]
    if found["mode"] == "any":
        lines += ["No bill matches every word, so these bills match at least one word (most words matched first).", ""]
    lines += [f"{total} {'bill' if total == 1 else 'bills'} matched {described}{f' with {filters}' if filters else ''}. {as_of}", ""]
    if found["missing_ids"]:
        lines += [f"Not in the current data: {', '.join(found['missing_ids'])}. A bill appears here once it is filed and "
                  "published in the Texas Legislative Council bulk files (checked hourly); until then it has no page.", ""]
    if not total:
        coverage = meta.get("coverage") or {}
        lines += ["No bill in the current data matches. This does not mean no bill concerns it: only "
                  f"{coverage.get('full_text_reviewed', 'some')} of {coverage.get('bills', 'the')} bills have a full-text review so far, "
                  "and the rest are searchable by caption only. Try a broader or different word, or browse "
                  f"[topics]({AGENT}topics/index.md) and [agencies]({AGENT}agencies/index.md).", ""]
        if found["suggestions"]:
            lines += ["Similar words in the data: " + ", ".join(f"[{w}]({link(params, q=w, offset=0)})" for w in found["suggestions"]), ""]
    else:
        start = found["offset"] + 1
        end = found["offset"] + len(found["results"])
        lines += [f"Showing {start}-{end}." if found["results"] else "No results on this page.", "",
                  "| Bill | Title | Topics | Agencies | Review | Last action | Date | Matched in |",
                  "|---|---|---|---|---|---|---|---|"]
        for *_, r, where in found["results"]:
            last = r.get("last_action") or {}
            lines.append(f"| [{cell(r.get('number') or r['id'])}]({AGENT}bills/{r['id']}.md) | {cell(r.get('title'))} | "
                         f"{cell('; '.join(r.get('topics') or []))} | {cell('; '.join(a.get('name') or '' for a in r.get('agencies') or [])) or 'none tagged'} | "
                         f"{'full text' if r.get('full_text_review') else 'caption'} | {cell(last.get('category'))} | {last.get('date') or ''} | "
                         f"{cell(', '.join(sorted(LABELS.get(w, w) for w in where)))} |")
        lines.append("")
        nxt = found["offset"] + found["limit"]
        if nxt < total:
            lines += [f"Next page: {link(params, offset=nxt)}", ""]
    lines += [f"As JSON: {link(params, format='json', offset=found['offset'])}",
              f"Same words in the tracker: {SITE}#all?{urlencode({'query': params['q']})}" if params["q"] else "",
              f"How search works: {AGENT}search", ""]
    if disclaimer:
        lines += ["---", disclaimer, ""]
    return "\n".join(line for line in lines if line is not None)
