"""Matching agency names that Luna writes to the agency list (src/taxonomy.js AGENCIES).

Luna names the bodies a bill affects without seeing the list; these functions give a name its list id. Used by the
classification validator, the review worker's follow-up questions and publishing.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

# Other names for listed agencies (the office's own title, its governing body, a common acronym), each sourced.
# Names on the list itself are matched without an entry.
AGENCY_NAME_ALIASES = Path(__file__).with_name("agency_name_aliases.json")
_name_tables: dict = {}

# A body named only by its kind ("the department", "Board", "state agency") needs its defining text to be identified.
_GENERIC_WORDS = (r"(?:state |local |governmental |law enforcement |licensing |regulatory |appropriate |"
                  r"participating |executive )*"
                  r"(?:department|commission|commissioner|agency|agencies|board|office|council|committee|"
                  r"authority|division|court|courts|entity|entities|institution|registrar|officer|director|"
                  r"governing body|executive commissioner)s?")
_GENERIC = re.compile(r"(?:(?:the|a|an|each|any|every|that|this|such|its)\s+)?" + _GENERIC_WORDS, re.I)


def agency_name_key(name: str) -> str:
    """Comparison form of an agency name: no accents, case or punctuation, "&" as "and", and a leading "the" or
    "Texas" and a trailing "of Texas" ignored ("Railroad Commission of Texas" = "railroad commission")."""
    s = re.sub("['‘’ʼ]", "", name or "")  # "Auditor's" = "Auditors", whichever apostrophe
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"^the ", "", s)
    s = re.sub(r"^(?:state of texas|texas) ", "", s)
    return re.sub(r" of (?:the state of )?texas$", "", s)


def _name_table(names: dict[str, str]) -> dict[str, str]:
    key = tuple(sorted(names.items()))
    if key not in _name_tables:
        seen: dict[str, set] = {}
        for registry_id, name in names.items():
            seen.setdefault(agency_name_key(name), set()).add(registry_id)
        for entry in json.loads(AGENCY_NAME_ALIASES.read_text("utf-8")):
            if entry["registry_id"] in names:
                seen.setdefault(agency_name_key(entry["alias"]), set()).add(entry["registry_id"])
        # A name that fits two agencies is ambiguous and maps to neither.
        _name_tables[key] = {k: next(iter(ids)) for k, ids in seen.items() if k and len(ids) == 1}
    return _name_tables[key]


def named_agency_id(agency: dict, names: dict[str, str]) -> str | None:
    """Registry ID whose name (or a listed alias) is the agency's name; None when no single agency has it."""
    return _name_table(names).get(agency_name_key(agency.get("name") or ""))


def is_generic_agency_name(name: str) -> bool:
    """True for a name that only says what kind of body it is ("the department", "Board", "state agency"),
    so the bill's defining text is needed to know which body it means."""
    return bool(_GENERIC.fullmatch((name or "").strip()))
