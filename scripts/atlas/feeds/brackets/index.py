from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re

from atlas.feeds.brackets.parse import bill_brackets
from atlas.paths import REPO_ROOT, SCRIPTS_DIR
# Statute helpers still live in build_feeds.py; it imports this package lazily, so this import is not circular.
from build_feeds import _latest_text, write_if_changed

# Population brackets: "a county with a population of more than four million" resolved to the places that meet the
# population test under the 2020 census. Extra conditions ("adjacent to ...") are flagged, never resolved.
BRACKET_FORMAT = "texas-bill-brackets-v1"
POPULATION_FORMAT = "texas-population-2020-v1"
BRACKET_LIST_MAX = 40   # places listed by name; bigger sets are only counted
NEAR_SHARE = 0.02       # a place within 2% of a threshold is "close to the line"
BRACKET_BILL = re.compile(r"(HB|SB|HJR|SJR)[1-9]\d{0,4}")  # laws; resolutions are prose


def load_population(path: Path) -> dict | None:
    """The census table from scripts/census_places.py, or None when it is missing or not that format."""
    try:
        table = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(table, dict) or table.get("format") != POPULATION_FORMAT:
        return None
    counties, places = table.get("counties"), table.get("places")
    ok = lambda rows, width: isinstance(rows, dict) and rows and all(
        isinstance(v, list) and len(v) == width and isinstance(v[0], str) and isinstance(v[1], int) for v in rows.values())
    return table if ok(counties, 2) and ok(places, 3) else None


def _resolve(table: dict, kind: str, low: int | None, high: int | None) -> list[str]:
    rows = table["counties"] if kind == "county" else table["places"]
    hits = [g for g, v in rows.items() if (low is None or v[1] >= low) and (high is None or v[1] <= high)]
    return sorted(hits, key=lambda g: (-rows[g][1], g))


def _near(table: dict, kind: str, low: int | None, high: int | None) -> list[str]:
    rows = table["counties"] if kind == "county" else table["places"]
    near = []
    for t in (low, high):
        if t:
            near += [(abs(v[1] - t), g) for g, v in rows.items() if abs(v[1] - t) <= t * NEAR_SHARE]
    return [g for _, g in sorted(set(near))][:8]


def build_brackets(snapshot: dict, text_dir: Path, table: dict) -> dict:
    used: set[str] = set()
    bills: dict[str, dict] = {}

    def listed(geoids: list[str]) -> list[str] | None:
        if len(geoids) > BRACKET_LIST_MAX:
            return None
        used.update(geoids)
        return geoids

    for bill in snapshot.get("bills") or []:
        bill_id = str(bill.get("id", "")) if isinstance(bill, dict) else ""
        if not BRACKET_BILL.fullmatch(bill_id):
            continue
        found = _latest_text(text_dir, bill_id)
        if not found:
            continue
        version, markdown = found
        clauses, unparsed = bill_brackets(markdown)
        rows = []
        for c in clauses:
            low, high = c["bounds"]
            row = {"s": c["status"], "k": c["kind"], "t": c["text"], "lo": low, "hi": high, "sec": c["section"],
                   "cond": c["cond"]}
            if c["rel"]:
                row["rel"] = c["rel"]   # a neighbor, a place inside, the county a city is seat of, or the principal city
            if c["census"]:
                row["census"] = c["census"]       # tied to an older census: not resolved
            else:
                hits = _resolve(table, c["kind"], low, high)
                row["n"], row["p"] = len(hits), listed(hits)
                near = _near(table, c["kind"], low, high)
                if near:
                    used.update(near)
                    row["near"] = near
            was = c.get("was")
            if was:
                row["was"] = {"t": was["text"], "lo": was["bounds"][0], "hi": was["bounds"][1]}
                if not c["census"] and not was["census"]:
                    before = set(_resolve(table, was["kind"], *was["bounds"]))
                    after = set(row.get("p") or _resolve(table, c["kind"], low, high))
                    added = sorted(after - before, key=lambda g: (-table["counties" if c["kind"] == "county" else "places"][g][1], g))
                    dropped = sorted(before - after, key=lambda g: (-table["counties" if c["kind"] == "county" else "places"][g][1], g))
                    row["was"].update({"n": len(before), "added": len(added), "dropped": len(dropped),
                                       "added_p": listed(added), "dropped_p": listed(dropped)})
            rows.append(row)
        if rows or unparsed:
            bills[bill_id] = {"v": version["code"], "c": rows, "u": unparsed}
    counties, places = table["counties"], table["places"]
    shared = {n for n, k in Counter(v[0] for v in places.values()).items() if k > 1}  # e.g. two Renos
    names = {}
    for g in sorted(used):
        if g in counties:
            names[g] = counties[g]
        elif g in places:
            name, pop, county = places[g]
            names[g] = [name, pop, counties.get(county, [""])[0] if name in shared else ""]
    return {"format": BRACKET_FORMAT, "census": table.get("source", ""), "places": names, "bills": bills}


def write_brackets(snapshot: dict, text_dir: Path, census: Path, out_dir: Path) -> str:
    """Writes out_dir/index.json. Skips (and says why) without bill text or a valid census table."""
    if not text_dir.is_dir():
        return "skipped (no bill text)"
    table = load_population(census)
    if table is None:
        return f"skipped (no valid census table at {census})"
    index = build_brackets(snapshot, text_dir, table)
    out_dir.mkdir(parents=True, exist_ok=True)
    changed = write_if_changed(out_dir / "index.json", json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n")
    clauses = sum(len(b["c"]) for b in index["bills"].values())
    return f"{len(index['bills'])} bills, {clauses} clauses, {'written' if changed else 'unchanged'}"


def default_census() -> Path:
    """Beside build_feeds.py in scripts/ (an older data unit copied it there), else the repository's data/census copy."""
    beside = SCRIPTS_DIR / "tx_population_2020.json"
    return beside if beside.exists() else REPO_ROOT / "data" / "census" / "tx_population_2020.json"
