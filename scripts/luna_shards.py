"""Per-bill Luna maps split into content-addressed shards, so a browser re-downloads only the shards that changed.

<luna>/shards/<name>-<n>.json holds the bills whose id hashes to shard n (no time stamp: identical content is
identical bytes). <luna>/<name>-index.json lists every shard's content hash plus the map's other fields; the site
fetches shards as <file>?v=<hash>, so an unchanged shard is a browser-cache hit with no request. Shards are written
before the index, and every file only when its bytes change. The single-file map stays the source for every other
reader (feeds, agent build, change log) and the site's fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

INDEX_FORMAT = "texas-bill-luna-shards-v1"
SHARD_FORMAT = "texas-bill-luna-shard-v1"


def shard_of(bill_id: str, shards: int) -> int:
    return int.from_bytes(hashlib.sha256(bill_id.encode("utf-8")).digest()[:4], "big") % shards


def _write_if_changed(path: Path, text: str) -> bool:
    data = text.encode("utf-8")
    try:
        if path.read_bytes() == data:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.chmod(temporary, 0o644)  # served publicly
    os.replace(temporary, path)
    return True


def publish(luna_dir: Path, name: str, payload: dict, shards: int) -> int:
    """Shard payload["bills"]; the index carries every other field of payload (format becomes `of`). Returns the
    number of files written."""
    parts: list[dict] = [{} for _ in range(shards)]
    for bill_id in sorted(payload["bills"]):
        parts[shard_of(bill_id, shards)][bill_id] = payload["bills"][bill_id]
    written, versions = 0, []
    for n, bills in enumerate(parts):
        text = json.dumps({"format": SHARD_FORMAT, "of": payload["format"], "shard": n, "bills": bills},
                          ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        written += _write_if_changed(luna_dir / "shards" / f"{name}-{n}.json", text)
        versions.append(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16])
    # generated_at is kept: callers pass the single-file map as published, whose stamp moves only when it changes.
    index = {k: v for k, v in payload.items() if k not in ("bills", "format")}
    index.update({"format": INDEX_FORMAT, "of": payload["format"], "shards": versions})
    written += _write_if_changed(luna_dir / f"{name}-index.json",
                                 json.dumps(index, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    return written
