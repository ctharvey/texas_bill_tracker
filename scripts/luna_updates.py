"""What each tags.json publish changed, kept as a short public log (updates.json beside tags.json).

One entry per publish that changed anything: when, the counts by kind (the overall change) and each bill's changes.
Compares the published files only, so it says what readers saw change, never anything withheld. No calls."""
from __future__ import annotations

import json
import os
from pathlib import Path

FORMAT = "texas-bill-luna-updates-v1"
KEEP = 40  # publishes with changes; mid-run publishes make several per run

# Kinds in display order; the page names them.
KINDS = ("reviewed", "new_version", "all_agencies", "not_all_agencies", "agencies", "topics", "summary", "withdrawn")


def _scope(entry: dict) -> bool | None:
    scope = entry.get("all_state_agencies")
    return bool(scope.get("applies")) if isinstance(scope, dict) else None


def _names(entry: dict, field: str, key: str) -> set[str]:
    return {item[key] for item in entry.get(field) or [] if isinstance(item, dict) and isinstance(item.get(key), str)}


def bill_changes(old: dict | None, new: dict | None) -> list[dict]:
    """[{kind, ...}] for one bill: what a reader would see change between two published entries."""
    if not isinstance(old, dict) and not isinstance(new, dict):
        return []
    if not isinstance(old, dict):
        out = [{"kind": "reviewed"}]
        if _scope(new):
            out.append({"kind": "all_agencies"})
        return out
    if not isinstance(new, dict):
        return [{"kind": "withdrawn"}]
    out = []
    if old.get("text_version") != new.get("text_version"):
        out.append({"kind": "new_version", "from": old.get("text_version"), "to": new.get("text_version")})
    was, now = _scope(old), _scope(new)
    if now and not was:
        out.append({"kind": "all_agencies"})
    elif was and not now:
        out.append({"kind": "not_all_agencies"})
    for kind, field, key in (("agencies", "agencies", "name"), ("topics", "policy_tags", "tag")):
        before, after = _names(old, field, key), _names(new, field, key)
        if before != after:
            out.append({"kind": kind, "added": sorted(after - before), "removed": sorted(before - after)})
    if old.get("summary") != new.get("summary") and not any(c["kind"] == "new_version" for c in out):
        out.append({"kind": "summary"})
    return out


def diff(old_bills: dict, new_bills: dict) -> dict:
    """{"counts": {kind: bills}, "bills": {bill: [changes]}} between two tags.json `bills` maps."""
    bills = {}
    for bill in sorted(set(old_bills) | set(new_bills)):
        changes = bill_changes(old_bills.get(bill), new_bills.get(bill))
        if changes:
            bills[bill] = changes
    counts = {k: sum(1 for cs in bills.values() if any(c["kind"] == k for c in cs)) for k in KINDS}
    return {"counts": {k: n for k, n in counts.items() if n}, "bills": bills}


def _read(path: Path):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def record(out: Path, previous: dict | None, current: dict, now: str) -> int:
    """Append what `current` (the tags.json payload just written) changed against `previous` (the file it replaced)
    to updates.json beside it. No previous file: nothing to compare, nothing logged. Returns bills changed."""
    if not isinstance(previous, dict) or not isinstance(previous.get("bills"), dict):
        return 0
    change = diff(previous["bills"], current.get("bills") or {})
    if not change["bills"]:
        return 0
    path = out.with_name("updates.json")
    log = _read(path)
    entries = log.get("updates") if isinstance(log, dict) and isinstance(log.get("updates"), list) else []
    entries = ([{"at": now, "since": previous.get("generated_at"), **change}] + entries)[:KEEP]
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps({"format": FORMAT, "updates": entries}, ensure_ascii=False,
                                    separators=(",", ":")) + "\n", "utf-8")
    os.chmod(temporary, 0o644)  # served publicly
    os.replace(temporary, path)
    return len(change["bills"])
