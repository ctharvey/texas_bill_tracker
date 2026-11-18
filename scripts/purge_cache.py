"""Purge Cloudflare's copy of the data-run files that changed since the last successful purge.

texas-bill-data.service runs this from ExecStopPost, after every run (finished, failed or timed out). A Cloudflare cache
rule keeps PREFIXES at the edge for 30 days, so this purge is the only thing that makes changed files visible. luna/,
og/ and members.json have other writers and keep the 5-minute rule, so they are not purged here.

What changed is read from the files themselves: every file under PREFIXES is fingerprinted (mtime_ns and size) and
compared with the fingerprint stored at the last successful purge (live/purge-state.json). Added, rewritten and deleted
files are purged by exact path, up to MAX_OPS paths per request; a folder with too many changes is purged whole. The
fingerprint is taken before the purge is sent, so a write after it shows up next run. A failed purge keeps the old
fingerprint, so the next run purges this run's changes too, and records `pending_since` for daily_check.py.
Without a usable state (first run, unreadable file, PREFIXES changed) or without the live folder, every prefix is
purged, as before.

The token (Cache Purge on the billatlas.org zone only) is CF_PURGE_TOKEN from the unit's EnvironmentFile. Not
LoadCredential: under this unit's sandbox the credential is not readable from ExecStopPost (seen on the server).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ZONE_ID = "db785871c15127e883574d0bef17bce4"  # billatlas.org
ENDPOINT = f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/purge_cache"
HOST = "billatlas.org"
# Origin paths under live/ (after Cloudflare's rewrites of /openapi.json, /auth.md and /.well-known/api-catalog).
# A trailing slash marks a folder.
PATHS = ("bills.json", "feeds/", "share/", "sitemap.xml", "statutes/", "brackets/", "text/", "history/",
         "api-catalog.json", "openapi.json", "auth.md")
PREFIXES = [f"{HOST}/live/{path}" for path in PATHS]
LIVE = Path(os.environ.get("TBA_LIVE_DIR", "/var/www/html/texas-bill-atlas/live"))
STATE_NAME = "purge-state.json"  # beside ftp-history-state.json; the unit can write only inside live/
MAX_OPS = 100                    # Cloudflare's limit per purge request
TOKEN_VARIABLE = "CF_PURGE_TOKEN"


def read_token(environ=os.environ) -> str | None:
    return (environ.get(TOKEN_VARIABLE) or "").strip() or None


def fingerprint(live: Path) -> dict[str, str]:
    """{path relative to live/: "mtime_ns:size"} for every file under PATHS."""
    out: dict[str, str] = {}
    for path in PATHS:
        target = live / path.rstrip("/")
        files = [target] if not path.endswith("/") else [Path(d) / f for d, _, fs in os.walk(target) for f in fs]
        for file in files:
            try:
                st = file.stat()
            except OSError:
                continue  # gone between listing and stat, or never there: absent from the fingerprint
            if file.is_file():
                out[file.relative_to(live).as_posix()] = f"{st.st_mtime_ns}:{st.st_size}"
    return out


def changed(old: dict[str, str], new: dict[str, str]) -> list[str]:
    """Paths added, rewritten or deleted between two fingerprints."""
    return sorted(p for p in old.keys() | new.keys() if old.get(p) != new.get(p))


def plan(paths: list[str]) -> list[str]:
    """Purge prefixes for the changed paths, at most MAX_OPS: exact paths, with the busiest folders collapsed whole."""
    folders = [p for p in PATHS if p.endswith("/")]
    groups: dict[str, list[str]] = {}
    for p in paths:
        groups.setdefault(next((f for f in folders if p.startswith(f)), p), []).append(p)
    whole: set[str] = set()
    while sum(1 if g in whole else len(ps) for g, ps in groups.items()) > MAX_OPS:
        whole.add(max((g for g in groups if g in folders and g not in whole), key=lambda g: len(groups[g])))
    ops = sorted({g if g in whole else p for g, ps in groups.items() for p in ps})
    return [f"{HOST}/live/{op}" for op in ops]


def load_state(path: Path) -> dict | None:
    """The stored state, or None when missing, unreadable or made for a different PATHS."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("paths") != list(PATHS) or not isinstance(state.get("files"), dict):
        return None
    return state


def save_state(path: Path, state: dict) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(state, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def purge(token: str, prefixes: list[str], opener=None) -> tuple[bool, str]:
    """One prefix purge; returns (ok, status line). Never retries: the purge rate limit is shared by the account."""
    import urllib.error
    import urllib.request
    request = urllib.request.Request(ENDPOINT, data=json.dumps({"prefixes": prefixes}).encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                              "User-Agent": "texas-bill-atlas-purge"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=30) as response:
            body = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return False, f"HTTP {error.code}"
    except (urllib.error.URLError, OSError, ValueError) as error:
        return False, f"failed: {type(error).__name__}"
    if not body.get("success"):
        codes = ",".join(str(e.get("code")) for e in body.get("errors") or [] if isinstance(e, dict))
        return False, f"not accepted ({codes or 'no error code'})"
    return True, f"{len(prefixes)} prefixes purged"


def main(environ=os.environ, opener=None, live: Path | None = None, now=None) -> int:
    token = read_token(environ)
    if not token:
        print(f"Cache purge skipped: no {TOKEN_VARIABLE}", flush=True)
        return 0
    live = live or LIVE
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    if not live.is_dir():
        ok, status = purge(token, PREFIXES, opener)
        print(f"Cache purge (no {live}, everything): {status}", flush=True)
        return 0 if ok else 1

    state_path = live / STATE_NAME
    state = load_state(state_path)
    current = fingerprint(live)
    if state is None:
        prefixes, why = PREFIXES, "everything (no usable state)"
    else:
        paths = changed(state["files"], current)
        prefixes, why = plan(paths), f"{len(paths)} changed files"
    if not prefixes:
        print("Cache purge: nothing changed", flush=True)
        if state and state.get("pending_since"):
            save_state(state_path, {**state, "pending_since": None, "purged_at": stamp, "status": "nothing changed"})
        return 0

    ok, status = purge(token, prefixes, opener)
    print(f"Cache purge, {why}: {status}", flush=True)
    if ok:
        new_state = {"paths": list(PATHS), "files": current, "purged_at": stamp, "pending_since": None, "status": status}
    else:  # Keep the last good fingerprint so the next run purges these changes too.
        base = state or {"paths": list(PATHS), "files": {}, "purged_at": None}
        new_state = {**base, "pending_since": base.get("pending_since") or stamp, "status": status}
    try:
        save_state(state_path, new_state)
    except OSError as error:
        print(f"Cache purge state not saved: {type(error).__name__}", flush=True)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
