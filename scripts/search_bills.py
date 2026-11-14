"""Search the agent edition's bill records (live/agent/data/bills.json) for agents and scripts.

Words match word forms (plural, -ing, -ed), quoted text matches as a phrase, and a few common synonyms widen a
word in both directions (gun <-> firearm). Every word must match unless none does, then any word counts and the page
says so. Filters: chamber, topic, agency, location, party, reviewed, filed_from, filed_to. Read-only; standard library only.
"""
from __future__ import annotations

import difflib
import functools
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
# CPU bounds per request: each alternative is a full scan, and each fuzzy word runs difflib over the whole
# vocabulary. Without them one 200-character query cost about half a second of the sync service's single CPU.
MAX_ALTERNATIVES, MAX_FUZZY_WORDS = 8, 3
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
    ("marijuana", "cannabis", "thc", "hemp"), ("immigrant", "immigration", "alien"), ("tax", "taxation"),
    ("ai", "artificial intelligence"), ("power", "electric", "electricity"), ("vote", "voter", "ballot"),
)
BROADER = {"abortion": ["unborn child", "pregnancy"], "vote": ["election"]}


def _synonyms() -> dict[str, list[str]]:
    table: dict[str, list[str]] = {}
    for group in SYNONYM_GROUPS:
        for member in group:
            key = " ".join(stem(w) for w in words(member))
            table.setdefault(key, []).extend(m for m in group if m != member)
    for word, wider in BROADER.items():
        table.setdefault(stem(word), []).extend(wider)
    return {k: list(dict.fromkeys(v)) for k, v in table.items()}
FIELDS = (("title", 3), ("subjects", 4), ("topics", 4), ("agencies", 4), ("people", 3), ("summary", 2), ("groups", 2),
          ("locations", 2), ("impacts", 1), ("actions", 1))
LABELS = {"title": "title/caption", "subjects": "official subjects", "topics": "topics", "agencies": "agencies", "people": "members",
          "summary": "full-text summary", "groups": "affected groups", "locations": "locations",
          "impacts": "impacts", "actions": "actions"}


@functools.lru_cache(maxsize=65536)  # pure; search calls it per field per bill per term
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
        "subjects": " ; ".join(r.get("subjects") or []),
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
        self.meta, self.docs, self.vocab, self.members, self.topics, self.agency_ids = {}, [], [], {}, set(), set()
        self.topic_names = []

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
        docs, vocab, members = [], set(), {}
        for r in data.get("bills") or []:
            if not isinstance(r, dict) or not r.get("id"):
                continue
            fields = record_fields(r)
            tokens = {name: {stem(w) for w in words(text)} for name, text in fields.items()}
            lowered = {name: " ".join(words(text)) for name, text in fields.items()}
            vocab.update(w for w in words(fields["title"] + " " + fields["topics"] + " " + fields["summary"]) if len(w) > 3)
            for role in (r.get("people") or {}).values():
                for p in role or []:
                    full = p.get("full_name") or p.get("name") or ""
                    label = f"{full} ({p['chamber']}{' district ' + str(p['district']) if p.get('district') else ''})" \
                        if p.get("chamber") else full
                    for w in words(full):
                        if len(w) > 2:
                            members.setdefault(w, set()).add(label)
            docs.append((r, tokens, lowered))
        self.docs, self.vocab = docs, sorted(vocab)
        # Member-name words -> the members they name, for "did you mean" on misspelled names.
        self.members = {w: sorted(names) for w, names in members.items()}
        self.topic_names = sorted({t for r, _, _ in docs for t in r.get("topics") or []})
        self.topics = {t.lower() for t in self.topic_names}
        self.agency_ids = {(a.get("id") or "").lower() for r, _, _ in docs for a in r.get("agencies") or []} - {""}
        self.meta = {k: data.get(k) for k in ("bill_data_as_of", "tags_as_of", "roster_as_of", "count", "coverage")}


def parse_query(q: str) -> tuple[list[str], list[list[str]], list[str], list[str]]:
    """Bill ids named in the query, and its alternatives: the query split on a standalone OR outside quotes. Each
    alternative has quoted phrases, word terms (each a list of synonyms) and the words as typed (labels)."""
    lowered = q.lower()
    ids = [f"{m[1].upper()}{m[2]}" for m in BILL_REF.finditer(lowered)]
    rest = BILL_REF.sub(" ", lowered)
    # Quoted text keeps its own "or" ("65 or older"); only a bare "or" separates alternatives.
    pieces = re.split(r'("[^"]*")', rest)
    parts, current = [], ""
    for piece in pieces:
        if piece.startswith('"'):
            current += f" {piece} "
            continue
        chunks = re.split(r"\bor\b", piece)
        current += chunks[0]
        for chunk in chunks[1:]:
            parts.append(current)
            current = chunk
    parts.append(current)
    return ids, [a for a in (parse_alternative(p) for p in parts) if a["phrases"] or a["terms"]]


def parse_alternative(text: str) -> dict:
    phrases, terms, labels = [], [], []
    for p in re.findall(r'"([^"]+)"', text):
        key = " ".join(stem(w) for w in words(p))
        if key in SYNONYMS:  # A quoted synonym phrase ("school choice") widens like a word.
            terms.append(list(dict.fromkeys([" ".join(words(p))] + SYNONYMS[key])))
            labels.append(f'"{" ".join(words(p))}"')
        elif words(p):
            phrases.append(" ".join(words(p)))
    for w in words(re.sub(r'"[^"]*"', " ", text)):
        if w in STOP or len(w) < 2:
            continue
        terms.append(list(dict.fromkeys([w] + SYNONYMS.get(stem(w), []))))
        labels.append(w)
    shown = " ".join([f'"{p}"' for p in phrases] + labels)
    return {"phrases": phrases, "terms": terms, "labels": labels, "text": shown}


def term_hit(alternatives: list[str], tokens: dict, lowered: dict) -> tuple[int, set]:
    best, where = 0, set()
    for alt in alternatives:
        parts = words(alt)
        phrase, single = (" ".join(parts), None) if len(parts) > 1 else (None, stem(parts[0]))
        for name, weight in FIELDS:
            hit = (phrase in lowered[name]) if phrase is not None else single in tokens[name]
            if hit:
                where.add(name)
                best = max(best, weight if alt == alternatives[0] else weight - 1)
    return best, where


def matches_filters(r: dict, f: dict) -> bool:
    if f.get("chamber") and (r.get("chamber") or "").lower() != f["chamber"].lower():
        return False
    # A known topic name or agency id matches exactly, as the tracker's filters do; anything else matches part of a
    # topic name, or whole words of an agency name ("tea" must not match "Teacher Retirement System").
    if f.get("topic"):
        want = f["topic"].lower()
        if not any(t.lower() == want if f.get("_topic_exact") else want in t.lower() for t in r.get("topics") or []):
            return False
    if f.get("agency"):
        want = " ".join(words(f["agency"]))
        if not want or not any((a.get("id") or "").lower() == f["agency"].lower() if f.get("_agency_exact") else
                               re.search(rf"\b{re.escape(want)}\b", " ".join(words(f"{a.get('id') or ''} {a.get('name') or ''}")))
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
    if len(parse_query(q)[1]) > MAX_ALTERNATIVES:
        raise BadQuery(f"q is limited to {MAX_ALTERNATIVES} alternatives joined with OR")
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


def bill_order(bill_id: str) -> tuple[str, int]:
    """Sort key that compares bill numbers as numbers: 'HB99' < 'HB100'."""
    match = re.fullmatch(r"([A-Z]+)(\d+)", bill_id or "")
    return (match.group(1), int(match.group(2))) if match else (bill_id or "", 0)


def group_companions(results: list) -> list:
    """Move companion bills that are both in the results next to each other, at the first one's position.

    Mirrors companionGroups in src/taxonomy.js; record companions already run in both directions."""
    pos = {x[2]["id"]: i for i, x in enumerate(results)}
    placed, out = set(), []
    for x in results:
        if x[2]["id"] in placed:
            continue
        placed.add(x[2]["id"])
        queue, group = [x], []
        while queue:
            y = queue.pop(0)
            group.append(y)
            for c in y[2].get("companions") or []:
                cid = c.get("id") if isinstance(c, dict) else None
                if cid in pos and cid not in placed:
                    placed.add(cid)
                    queue.append(results[pos[cid]])
        out += sorted(group, key=lambda y: pos[y[2]["id"]])
    return out


def companions_of(r: dict, result_ids) -> list[dict]:
    return [{"id": c["id"], "number": c.get("number") or c["id"], "relation": c.get("relation"),
             "in_results": c["id"] in result_ids}
            for c in r.get("companions") or [] if isinstance(c, dict) and c.get("id")]


def companion_cell(r: dict, result_ids) -> str:
    parts = []
    for c in companions_of(r, result_ids):
        text = c["number"] + (" (" + c["relation"].lower() + ")" if c["relation"] else "")
        parts.append(text + (", also in these results" if c["in_results"] else ""))
    return cell("; ".join(parts))


def search(index: Index, params: dict) -> dict:
    ids, alternatives = parse_query(params["q"])
    filters, results, mode = params["filters"], [], "all"
    exact = {"_topic_exact": (filters.get("topic") or "").lower() in index.topics,
             "_agency_exact": (filters.get("agency") or "").lower() in index.agency_ids}
    pool = [d for d in index.docs if matches_filters(d[0], {**filters, **exact})]
    filter_labels = {f"{k}={v}" for k, v in filters.items()}

    def match(alt: dict, tokens: dict, lowered: dict) -> tuple[int, int, set] | None:
        """(words matched, score, fields) when every quoted phrase matches; None otherwise."""
        score, hits, where = 0, 0, set()
        for phrase in alt["phrases"]:
            fields = [name for name, _ in FIELDS if phrase in lowered[name]]
            if not fields:
                return None
            score, where = score + 5, where | set(fields)
        for synonyms in alt["terms"]:
            weight, fields = term_hit(synonyms, tokens, lowered)
            if weight:
                hits, score, where = hits + 1, score + weight, where | fields
        return hits, score, where

    def scored(require_all: bool) -> list:
        found = []
        for r, tokens, lowered in pool:
            named = r["id"] in ids
            best = (100, 0, {"bill number"}) if named else None
            for alt in alternatives:
                m = match(alt, tokens, lowered)
                if m is None or (m[0] < len(alt["terms"]) if require_all else (alt["terms"] and not m[0])):
                    continue
                # Rank by the share of an alternative's words matched, then score.
                m = (m[0] / max(1, len(alt["terms"])), m[1], m[2])
                if best is None or (not named and m[:2] > best[:2]):
                    best = m
            if best is not None:
                found.append((best[0], best[1], r, best[2]))
        return found

    if not alternatives and not ids:
        results = [(0, 0, r, set(filter_labels)) for r, _, _ in pool] if filters else []
        mode = "filters"
    else:
        results = scored(True)
        if not results and len(alternatives) == 1 and len(alternatives[0]["terms"]) > 1:
            # Only the bills matching the most words; a long tail of one-word matches buries the answer.
            results, mode = scored(False), "any"
            best = max((x[0] for x in results), default=0)
            results = [x for x in results if x[0] == best]
    # Most recent action first, then (stable) best match first.
    # Best match first, then most recent action, then bill number as a number (HB 99 before HB 100); stable sorts.
    results.sort(key=lambda x: bill_order(x[2]["id"]))
    results.sort(key=lambda x: (x[2].get("last_action") or {}).get("date") or "", reverse=True)
    results.sort(key=lambda x: (x[0], x[1]), reverse=True)
    results = group_companions(results)
    page = results[params["offset"]:params["offset"] + params["limit"]]
    # Counts for each word (one alternative) or each alternative (OR), so a query can be narrowed or widened.
    if len(alternatives) > 1:
        per_term = [{"term": alt["text"], "total": sum(1 for _, tokens, lowered in pool
                     if (m := match(alt, tokens, lowered)) is not None and m[0] == len(alt["terms"]))}
                    for alt in alternatives]
    elif alternatives and (len(alternatives[0]["terms"]) > 1 or not results):
        per_term = [{"term": label, "total": sum(1 for _, tokens, lowered in pool if term_hit(t, tokens, lowered)[0])}
                    for label, t in zip(alternatives[0]["labels"], alternatives[0]["terms"])]
    else:
        per_term = []
    terms = [t for alt in alternatives for t in alt["terms"]]
    phrases = [p for alt in alternatives for p in alt["phrases"]]
    suggestions, members = [], []
    counted = {t["term"]: t["total"] for t in per_term}
    unmatched = [w for alt in alternatives for label, t in zip(alt["labels"], alt["terms"])
                 if counted.get(label, counted.get(alt["text"], 1)) == 0 for w in words(t[0])]
    if not results:
        unmatched += [w for p in phrases for w in p.split()]
    seen = set(index.vocab)
    for w in list(dict.fromkeys(unmatched))[:MAX_FUZZY_WORDS]:
        if w in index.members:
            continue
        for name in difflib.get_close_matches(w, list(index.members), n=2, cutoff=0.8):
            members += index.members[name]
        if w not in seen:
            suggestions += difflib.get_close_matches(w, index.vocab, n=3, cutoff=0.8)
    known = {d[0]["id"] for d in index.docs}
    return {"missing_ids": [i for i in dict.fromkeys(ids) if i not in known],
            "query": params["q"], "mode": mode, "filters": filters, "total": len(results), "offset": params["offset"],
            "limit": params["limit"], "results": page, "suggestions": list(dict.fromkeys(suggestions))[:6],
            "members": list(dict.fromkeys(members))[:6], "per_term": per_term, "meta": index.meta,
            "alternatives": [a["text"] for a in alternatives], "ids": ids,
            "member_count": len({n for names in index.members.values() for n in names}),
            "result_ids": frozenset(x[2]["id"] for x in results),
            "caption_only": bool(terms or phrases or filters.get("location"))}


def link(params: dict, **changes) -> str:
    values = {"q": params["q"], **params["filters"], "limit": params["limit"], "offset": params["offset"], **changes}
    values = {k: v for k, v in values.items() if v not in ("", None) and not (k == "offset" and not v)
              and not (k == "limit" and v == DEFAULT_LIMIT)}
    return f"{AGENT}search?{urlencode(values)}"


def cell(value) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()


def coverage_note(meta: dict) -> str:
    coverage = meta.get("coverage") or {}
    reviewed, bills = coverage.get("full_text_reviewed"), coverage.get("bills")
    if not isinstance(reviewed, int) or not isinstance(bills, int):
        return "Bills without a full-text review are searched by caption, official subjects, caption-based tags and members only."
    return (f"Only {reviewed} of {bills} bills have a full-text review so far; the other {bills - reviewed} are searched by "
            "caption, official subjects, caption-based tags and members only, so bills that only their full text ties to this can be missing.")


def authors_of(r: dict) -> list[str]:
    return [p.get("full_name") or p.get("name") or "" for p in ((r.get("people") or {}).get("authors") or [])]


def as_json(found: dict, params: dict) -> dict:
    nxt = found["offset"] + found["limit"]
    return {"format": "texas-bill-atlas-search-v1", "query": found["query"], "mode": found["mode"],
            "read_as_alternatives": found["alternatives"],
            "no_matching_member": bool(not found["total"] and found["alternatives"] and not found["members"]),
            "filters": found["filters"], "total": found["total"], "offset": found["offset"], "limit": found["limit"],
            "data_as_of": found["meta"].get("bill_data_as_of"), "tags_as_of": found["meta"].get("tags_as_of"),
            "coverage": found["meta"].get("coverage"), "suggestions": found["suggestions"],
            "did_you_mean_members": found["members"],
            "each_word": [{**t, "search": link(params, q=t["term"], offset=0, format="json")} for t in found["per_term"]],
            "searched_note": coverage_note(found["meta"]) if found["caption_only"] else None,
            "not_in_data": found["missing_ids"],
            "next": link(params, offset=nxt, format="json") if nxt < found["total"] else None,
            "results": [{"id": r["id"], "number": r.get("number"), "title": r.get("title"), "status": r.get("status"),
                         "filed_at": r.get("filed_at"), "chamber": r.get("chamber"), "authors": authors_of(r),
                         "authorship_party": (r.get("authorship_party") or {}).get("label"), "topics": r.get("topics") or [],
                         "agencies": [a.get("name") for a in r.get("agencies") or []],
                         "locations": [l.get("name") for l in r.get("locations") or []],
                         "full_text_reviewed": bool(r.get("full_text_review")),
                         "companions": companions_of(r, found.get("result_ids", ())),
                         "last_action": r.get("last_action"), "matched_in": sorted(LABELS.get(w, w) for w in where),
                         "markdown": f"{AGENT}bills/{r['id']}.md", "json": f"{AGENT}bills/{r['id']}.json"}
                        for *_, r, where in found["results"]]}


def usage(meta: dict, topics: list[str] = ()) -> str:
    topic_line = (f"\nTopic names (exact values; anything else matches part of a name): {', '.join(f'`{t}`' for t in topics)}.\n"
                  if topics else "")
    return f"""# Search Texas Bill Atlas

`GET {AGENT}search?q=<words>` returns matching bills as Markdown; add `&format=json` for JSON.

- Words match their forms (firearm, firearms; school, schools). Quote a phrase: `q="water rights"`.
- Common synonyms find each other: gun, firearm, handgun, rifle and weapon return the same bills; voucher, "school
  choice" and "education savings account" do too; aquifer and groundwater; marijuana, cannabis, THC and hemp.
- Every word must match. OR separates alternatives, each matched on its own: `q=lottery OR casino OR sports betting`
  finds bills about lotteries, casinos, or sports betting (both words); `q=school safety OR "school police"` works
  too. To keep a word in every alternative, repeat it: `q=property tax senior OR property tax elderly`. The results
  page shows how the query was read. If no bill matches every word of a query without OR, the bills matching the
  most words are shown, with a count for each word on its own, and the page says which words matched nothing.
- Misspelled member names get a "did you mean" (`q=jonson` suggests Ann Johnson). A name with no bills says so.
- Bill numbers work: `q=HB 5` or `q=sb12`.
- Filters (with or without q): `chamber=House|Senate`, `topic=<topic name, or part of one>`, `agency=<id, or words of its name>`,
  `location=<part of a place name, e.g. Harris>`, `party=democratic|republican|bipartisan`, `reviewed=yes|no`,
  `filed_from=YYYY-MM-DD`, `filed_to=YYYY-MM-DD`. A location matches a place the full-text review names, or the place
  named in the title or caption; unreviewed bills that affect a place without naming it are not found.
- Bills filed in the last few days: `filed_from=<date>` with no q (all of them, most recent action first).
- Paging: `limit` (default {DEFAULT_LIMIT}, at most {MAX_LIMIT}) and `offset`.
- Tracker links: the tracker keeps its filters after `#`, which never reaches a server. `{SITE}#all?topic=Education&agency=tea`
  is the same view as `{AGENT}search?topic=Education&agency=tea`; the topic, agency and chamber values carry over.
  `query=` becomes `q=`.
{topic_line}
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
    described = " OR ".join(found["alternatives"])
    described = " ".join(x for x in (described, " ".join(found["ids"])) if x) or "(filters only)"
    filters = ", ".join(f"{k}={v}" for k, v in found["filters"].items())
    as_of = f"Bill data as of {meta.get('bill_data_as_of') or 'unknown'}; full-text tags as of {meta.get('tags_as_of') or 'not available yet'}."
    lines = [f"# Search: {cell(params['q']) or f'filters only ({filters})'}", ""]
    if len(found["alternatives"]) > 1:
        lines += ["Read as alternatives (each side of OR is matched on its own, all its words required): "
                  + " · ".join(f"`{a}`" for a in found["alternatives"]), ""]
    if found["mode"] == "any":
        matched = [t["term"] for t in found["per_term"] if t["total"]]
        lines += [f"No bill matches every word of {described}{f' with {filters}' if filters else ''}. Showing the {total} "
                  f"{'bill' if total == 1 else 'bills'} matching the most of them ({', '.join(matched) or 'none'}); "
                  f"{', '.join(t['term'] for t in found['per_term'] if not t['total']) or 'no word'} matched nothing. "
                  "Search fewer words, or join alternatives with OR (`q=hemp OR marijuana`). " + as_of, ""]
    else:
        lines += [f"{total} {'bill' if total == 1 else 'bills'} matched {described}{f' with {filters}' if filters else ''}. {as_of}", ""]
    if found["per_term"]:
        lines += [("Each alternative on its own: " if len(found["alternatives"]) > 1 else "Each word on its own: ")
                  + " · ".join(f"[{cell(t['term'])}]({link(params, q=t['term'], offset=0)}) ({t['total']})"
                               for t in found["per_term"]), ""]
    if found["members"]:
        lines += ["Did you mean a member? " + "; ".join(f"[{cell(m)}]({link(params, q=m.split(' (')[0], offset=0)})"
                                                         for m in found["members"]), ""]
    elif not total and found["alternatives"]:
        lines += [f"No member by that name is in the data either: the {found['member_count']} members who have authored or "
                  f"sponsored a bill are listed at {AGENT}authors/index.md. A member who has filed nothing yet has no page.", ""]
    if found["caption_only"] and total:
        lines += [coverage_note(meta), ""]
    if found["missing_ids"]:
        lines += [f"Not in the current data: {', '.join(found['missing_ids'])}. A bill appears here once it is filed and "
                  "published in the Texas Legislative Council bulk files (checked hourly); until then it has no page.", ""]
    if not total:
        coverage = meta.get("coverage") or {}
        lines += ["No bill in the current data matches. This does not mean no bill concerns it: only "
                  f"{coverage.get('full_text_reviewed', 'some')} of {coverage.get('bills', 'the')} bills have a full-text review so far, "
                  "and the rest are searchable by caption and official subjects only. Try a broader or different word, or browse "
                  f"[topics]({AGENT}topics/index.md) and [agencies]({AGENT}agencies/index.md).", ""]
        if found["suggestions"]:
            lines += ["Similar words in the data: " + ", ".join(f"[{w}]({link(params, q=w, offset=0)})" for w in found["suggestions"]), ""]
    else:
        start = found["offset"] + 1
        end = found["offset"] + len(found["results"])
        ids = found.get("result_ids", ())
        linked = any(c["in_results"] for *_, r, _ in found["results"] for c in companions_of(r, ids))
        lines += [f"Showing {start}-{end}." if found["results"] else "No results on this page.", "",
                  *(["Companion bills that both match are listed next to each other; the Companions column marks them "
                     "\"also in these results\".", ""] if linked else []),
                  "| Bill | Title | Authors | Party | Topics | Agencies | Review | Last action | Date | Companions | Matched in |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for *_, r, where in found["results"]:
            last = r.get("last_action") or {}
            lines.append(f"| [{cell(r.get('number') or r['id'])}]({AGENT}bills/{r['id']}.md) | {cell(r.get('title'))} | "
                         f"{cell(', '.join(authors_of(r)))} | {cell((r.get('authorship_party') or {}).get('label'))} | "
                         f"{cell('; '.join(r.get('topics') or []))} | {cell('; '.join(a.get('name') or '' for a in r.get('agencies') or [])) or 'none tagged'} | "
                         f"{'full text' if r.get('full_text_review') else 'caption'} | {cell(last.get('category'))} | {last.get('date') or ''} | "
                         f"{companion_cell(r, ids)} | {cell(', '.join(sorted(LABELS.get(w, w) for w in where)))} |")
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
