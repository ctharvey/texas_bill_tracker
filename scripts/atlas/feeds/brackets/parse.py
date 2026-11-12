from __future__ import annotations

import re

# Statute helpers still live in build_feeds.py; it imports this package lazily, so this import is not circular.
from build_feeds import parse_clause, plain_text

_WORD_NUMBER = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_POP_NUM = (r"(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?: million)?"
            r"|(?:one|two|three|four|five|six|seven|eight|nine|ten) million)")
_OP_BEFORE = (r"(?:not more than|not less than|not greater than|at least|more than|greater than|less than|fewer than|"
              r"in excess of|exceeding|that exceeds|over|under)")
_OP_AFTER = r"(?:or more|or greater|or less|or fewer)"
_ONE = rf"(?:{_OP_BEFORE} )?{_POP_NUM}(?: {_OP_AFTER})?"
_RANGE = rf"(?P<range>between {_POP_NUM} and {_POP_NUM}|{_ONE}(?:,? (?:and|but) {_ONE})?)"
_ENTITY = (r"(?P<entity>county or municipality|municipality or county|municipality|municipalities|city|cities|county|"
           r"counties)")
_HAS = r"(?:,? (?:that|which) (?:has|had)|,? having|,? with|,? of|,? has)"
_POPULATION = r"(?:a (?:total )?population|populations)"
_BRACKET = re.compile(rf"\b{_ENTITY}{_HAS} {_POPULATION} (?:of |that is )?{_RANGE}", re.I)
_ITEM = re.compile(rf"^\([0-9A-Za-z-]+\) (?:(?:that|which) (?:has|had) |having |with |has ){_POPULATION} "
                   rf"(?:of |that is )?{_RANGE}", re.I)
_LEAD_ENTITY = re.compile(rf"\b{_ENTITY}\b", re.I)
# Any "population ... <number>" phrase, for counting the ones no clause covers.
_POP_PHRASE = re.compile(r"populations?(?:(?!population)[^.;:]){0,60}?(?=\d|(?:one|two|three|four|five|six|seven|eight|"
                         r"nine|ten) million)", re.I)
# A test on a related place, not on the place the provision covers; the last such word before the bracket wins.
_RELATED = re.compile(r".*\b(adjacent to|adjoining|bordering|borders|border|neighboring|contains|contain|containing|"
                      r"includes|include|including|seat of|principal)\b[^.;:]{0,30}$", re.I)
_RELATION = {"adjacent to": "near", "adjoining": "near", "bordering": "near", "borders": "near", "border": "near",
             "neighboring": "near", "contains": "inside", "contain": "inside", "containing": "inside",
             "includes": "inside", "include": "inside", "including": "inside", "seat of": "seat", "principal": "principal"}
_CENSUS_YEAR = re.compile(r"\b(1[89]\d0|20\d0) (?:federal )?(?:decennial )?census", re.I)
_CENSUS_TAIL = re.compile(r"^,? ?(?:as determined by|according to|under) (?:the )?(?:most recent )?(?:federal )?"
                          r"(?:decennial )?census,?", re.I)
_CONDITION = re.compile(r"^,? ?(?:and |or )?(?:that|which|located|is located|bordering|that borders|adjacent|containing|"
                        r"in which|where|bisected|through which|within|having|in a county|on the|along)\b", re.I)


def _population_number(text: str) -> int:
    m = re.fullmatch(r"([\d,]+(?:\.\d+)?|[a-z]+)( million)?", text.lower())
    base = float(m.group(1).replace(",", "")) if m.group(1)[0].isdigit() else _WORD_NUMBER[m.group(1)]
    return int(round(base * (1_000_000 if m.group(2) else 1)))


def bracket_bounds(text: str) -> tuple[int | None, int | None] | None:
    """Inclusive (low, high) for a range such as "more than 2.1 million" or "50,000 or more but less than 250,000".
    None when a part has no comparison word (a bare number) or the range is empty."""
    between = re.fullmatch(rf"between ({_POP_NUM}) and ({_POP_NUM})", text.strip(), re.I)
    if between:  # read as inclusive at both ends
        low, high = _population_number(between.group(1)), _population_number(between.group(2))
        return (low, high) if low <= high else None
    low = high = None
    for part in re.split(r",? (?:and|but) ", text.strip()):
        m = re.fullmatch(rf"(?:({_OP_BEFORE}) )?({_POP_NUM})(?: ({_OP_AFTER}))?", part, re.I)
        op = ((m.group(1) or m.group(3) or "").lower()) if m else ""
        if not op:
            return None
        n = _population_number(m.group(2))
        if op in ("at least", "not less than", "or more", "or greater"):
            low = n
        elif op in ("more than", "greater than", "in excess of", "exceeding", "that exceeds", "over"):
            low = n + 1
        elif op in ("not more than", "not greater than", "or less", "or fewer"):
            high = n
        else:
            high = n - 1
    if low is not None and high is not None and low > high:
        return None
    return low, high


def _wording(line: str, keep: str) -> str:
    """One paragraph as current law (keep="del") or as proposed (keep="ins"), in plain text."""
    drop = "ins" if keep == "del" else "del"
    text = re.sub(rf"\\?\[?<{drop}>.*?</{drop}>\\?\]?", "", line)
    text = re.sub(rf"\\?\[<{keep}>(.*?)</{keep}>\\?\]", r"\1", text)
    return re.sub(r"\s{2,}", " ", plain_text(text)).strip()


def _paragraph_brackets(text: str, lead: tuple[str, bool] | None) -> list[dict]:
    """Brackets in one plain paragraph. `lead` is (entity, joint) from a lead-in line ending in ":" for list items such
    as "(1) has a population of ..."; joint means the items are conditions together ("a county that:")."""
    found = [(m, m.group("entity"), False) for m in _BRACKET.finditer(text)]
    item = _ITEM.match(text)
    if item and lead:
        found.append((item, lead[0], lead[1] or bool(re.search(r"\band$", text))))
    out = []
    for m, entity, joint in found:
        tail = re.split(r"(?<=[.;:])(?:\s|$)", text[m.end():m.end() + 240])[0]
        year = _CENSUS_YEAR.search(tail)
        related = _RELATED.match(text[max(0, m.start() - 60):m.start()]) if m is not item else None
        entity = entity.lower()
        kinds = ["county", "city"] if " or " in entity else ["county" if entity.startswith("count") else "city"]
        for kind in kinds:
            out.append({"kind": kind, "text": m.group(0)[:200], "bounds": bracket_bounds(m.group("range")),
                        "census": int(year.group(1)) if year and year.group(1) != "2020" else None,
                        "cond": joint or bool(_CONDITION.match(_CENSUS_TAIL.sub("", tail.strip()).strip())),
                        "rel": _RELATION[related.group(1).lower()] if related else None})
    return out


def _unread(wordings: list[str], clauses: list[dict]) -> int:
    """Population phrases with a number that no readable clause covers (bare numbers, "either ... or", nested wording)."""
    covered = [c["text"] for c in clauses if c["bounds"] is not None]
    missing = set()
    for wording in wordings:
        for m in _POP_PHRASE.finditer(wording):
            number = re.match(r"\d+(?:[,.]\d+)*|\w+ million", wording[m.end():])
            if number and re.match(r"\s*(?:percent|%)", wording[m.end() + len(number.group(0)):]):
                continue
            phrase = m.group(0) + (number.group(0) if number else "")
            if not any(phrase in t for t in covered):
                missing.add(phrase)
    return len(missing)


def bill_brackets(markdown: str) -> tuple[list[dict], int]:
    """(clauses, unparsed) from a bill's text. A clause is new, changed (with "was"), existing or removed: unmarked
    wording is existing law inside a SECTION that amends a code and new law in any other SECTION."""
    clauses: list[dict] = []
    unparsed = 0
    section, codified, lead, expect_clause, last_entity = "", False, None, False, None
    for line in markdown.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("### "):
            section, expect_clause, lead, last_entity = line[4:].strip().rstrip("."), True, None, None
            continue
        if expect_clause:
            codified, expect_clause = parse_clause(plain_text(line))["kind"] != "none", False
        cur, new = _wording(line, "del"), _wording(line, "ins")
        if "population" in line.lower():
            marked = "<ins>" in line or "<del>" in line
            now = _paragraph_brackets(new, lead)
            before = _paragraph_brackets(cur, lead) if marked else []
            before_texts = {b["text"] for b in before}
            gone = [b for b in before if b["text"] not in {n["text"] for n in now}]
            for c in now:
                if not marked:
                    c["status"] = "existing" if codified else "new"
                elif c["text"] in before_texts:
                    c["status"] = "existing"
                else:
                    # "(1) has a population of 25,000 [(A) ... 10,000]": list labels may be renumbered too.
                    stem = lambda t: re.sub(r"^\([0-9A-Za-z-]+\) ", "", t).split(" population")[0]
                    was = next((g for g in gone if g["kind"] == c["kind"] and stem(g["text"]) == stem(c["text"])), None)
                    c["status"] = "changed" if was else "new"
                    if was:
                        gone.remove(was)
                        c["was"] = was
                c["section"] = section
                clauses.append(c)
            for g in gone:
                clauses.append({**g, "status": "removed", "section": section})
            unparsed += _unread([new, cur] if marked else [new], now + before)
        entities = _LEAD_ENTITY.findall(new)
        if new.endswith(":"):
            # "a municipality[:] / [(1)] that:" - a lead-in naming no place keeps the place named just before it.
            entity = entities[-1] if entities else (lead[0] if lead else last_entity)
            lead = (entity, bool(re.search(r"\b(?:that|which)\s*:$", new))) if entity else None
        elif not re.match(r"^\([0-9A-Za-z-]+\) ", new):
            lead = None
        if entities:
            last_entity = entities[-1]
    seen, out = set(), []
    for c in clauses:
        if c["bounds"] is None:
            continue
        key = (c["kind"], c["text"], c["status"], c.get("was", {}).get("text"))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out, unparsed
