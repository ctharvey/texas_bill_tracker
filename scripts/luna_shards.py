"""Per-bill Luna maps split into content-addressed shards, so a browser re-downloads only the shards that changed.

<luna>/shards/<name>-<hash>.json holds the bills whose id hashes to shard n; its name is the hash of its bytes and
it is never rewritten, so any cache (Cloudflare keeps /live/* five minutes, the browser keeps shards with
force-cache) can only ever hold the right bytes for a name. <luna>/<name>-index.json lists the shard names in
order plus the map's other fields, and is written after every shard it names exists. Shards no index names are
removed only after PRUNE_AFTER_S, so an index an edge cache still serves keeps working. The single-file map stays
the source for every other reader (feeds, agent build, change log) and the site's fallback: on any failure the
caller removes the index (`withdraw`), and the site reads the single file.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time

INDEX_FORMAT = "texas-bill-luna-shards-v2"
SHARD_FORMAT = "texas-bill-luna-shard-v1"
PRUNE_AFTER_S = 24 * 3600  # well past the 5-minute edge cache of an old index


def shard_of(bill_id: str, shards: int) -> int:
    return int.from_bytes(hashlib.sha256(bill_id.encode("utf-8")).digest()[:4], "big") % shards


def _write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(data)
        os.chmod(temporary, 0o644)  # served publicly
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def index_path(luna_dir: Path, name: str) -> Path:
    return luna_dir / f"{name}-index.json"


def withdraw(luna_dir: Path, name: str) -> None:
    """Remove the index so the site reads the single file (used when shards could not be brought up to date)."""
    index_path(luna_dir, name).unlink(missing_ok=True)


def publish(luna_dir: Path, name: str, payload: dict, shards: int, *, now=time.time) -> int:
    """Shard payload["bills"]; the index carries every other field of payload (format becomes `of`). Returns the
    number of files written. Raises on any failure; the caller then withdraws the index."""
    folder = luna_dir / "shards"
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o755)  # the worker's UMask=0077 would create it 0700, unreadable to the web server
    parts: list[dict] = [{} for _ in range(shards)]
    for bill_id in sorted(payload["bills"]):
        parts[shard_of(bill_id, shards)][bill_id] = payload["bills"][bill_id]
    written, names = 0, []
    for n, bills in enumerate(parts):
        data = (json.dumps({"format": SHARD_FORMAT, "of": payload["format"], "shard": n, "bills": bills},
                           ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()[:20]
        path = folder / f"{name}-{digest}.json"
        if not path.is_file() or path.read_bytes() != data:
            _write(path, data)
            written += 1
        names.append(digest)
    # generated_at is kept: callers pass the single-file map as published, whose stamp moves only when it changes.
    index = {k: v for k, v in payload.items() if k not in ("bills", "format")}
    index.update({"format": INDEX_FORMAT, "of": payload["format"], "shards": names})
    data = (json.dumps(index, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    target = index_path(luna_dir, name)
    try:
        old = target.read_bytes()
    except OSError:
        old = b""
    try:
        before = json.loads(old).get("shards") if old else []
        before = [d for d in before if isinstance(d, str)] if isinstance(before, list) else []
    except (ValueError, AttributeError):
        before = []
    if old != data:
        _write(target, data)
        written += 1
    # The index just replaced may still be served from an edge cache for minutes: its shards stay too.
    keep = {f"{name}-{d}.json" for d in [*names, *before]}
    pattern = re.compile(re.escape(name) + r"-[0-9a-f]{20}\.json")
    for path in folder.iterdir():
        if pattern.fullmatch(path.name) and path.name not in keep:
            try:
                if now() - path.stat().st_mtime > PRUNE_AFTER_S:
                    path.unlink()
            except OSError:
                pass
    return written
