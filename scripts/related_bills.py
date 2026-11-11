"""Related bills from OpenAI embeddings of each bill's caption and verified Luna summary.

Vectors are cached by content (model, dimensions, text), so a run embeds only new or changed text. Spend is logged
from each reply's token count to <cache>/embeddings/usage.jsonl. Embeddings are not Flex calls: they never go
through the Luna ledger or response cache, and the SDK's own retries are off (a 429 ends the step for the run).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import heapq
import json
import math
from operator import mul
import os
from pathlib import Path
import struct

FORMAT = "texas-bill-related-v1"
MODEL = "text-embedding-3-small"
DIMENSIONS = 256
PRICE_PER_MILLION = 0.02  # USD per million input tokens, text-embedding-3-small
TOP = 5
MIN_SCORE = 0.5
BATCH = 256
MAX_TEXT = 4000


def bill_text(bill: dict, summary: str | None) -> str:
    caption = " ".join(str(bill.get("caption") or bill.get("title") or "").split())
    return (caption + ("\n" + " ".join(summary.split()) if summary else "")).strip()[:MAX_TEXT]


def text_key(text: str) -> str:
    return hashlib.sha256(f"{MODEL}|{DIMENSIONS}|{text}".encode("utf-8")).hexdigest()


def _pack(vector: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")


def _unpack(data: str) -> list[float]:
    raw = base64.b64decode(data)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def openai_embedder(texts: list[str]) -> tuple[list[list[float]], int]:
    from openai import OpenAI
    client = OpenAI(max_retries=0, timeout=60)
    reply = client.embeddings.create(model=MODEL, input=texts, dimensions=DIMENSIONS)
    if reply.model.split("-")[:4] != MODEL.split("-")[:4] or len(reply.data) != len(texts):
        raise ValueError("Unexpected embeddings reply")
    return [item.embedding for item in sorted(reply.data, key=lambda d: d.index)], reply.usage.total_tokens


def _atomic_write(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, "utf-8")
    if mode is not None:
        os.chmod(temporary, mode)
    os.replace(temporary, path)


def load_store(cache_dir: Path) -> dict[str, str]:
    path = cache_dir / "embeddings" / "vectors.json"
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("vectors", {}) if isinstance(data, dict) and data.get("model") == MODEL else {}


def embed_missing(texts: list[str], cache_dir: Path, embedder=openai_embedder) -> tuple[dict[str, list[float]], int]:
    """Unit vectors for every text (by key); only uncached texts are sent. Returns (vectors, tokens sent)."""
    store = load_store(cache_dir)
    missing, seen = [], set()
    for text in texts:
        key = text_key(text)
        if key not in store and key not in seen:
            seen.add(key); missing.append(text)
    tokens = 0
    for start in range(0, len(missing), BATCH):
        chunk = missing[start:start + BATCH]
        vectors, used = embedder(chunk)
        for text, vector in zip(chunk, vectors):
            if len(vector) != DIMENSIONS:
                raise ValueError("Unexpected embedding size")
            store[text_key(text)] = _pack(_unit(vector))
        tokens += used
        _atomic_write(cache_dir / "embeddings" / "vectors.json",
                      json.dumps({"model": MODEL, "dimensions": DIMENSIONS, "vectors": store}, separators=(",", ":")))
        with (cache_dir / "embeddings" / "usage.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                  "model": MODEL, "inputs": len(chunk), "tokens": used,
                                  "cost_usd": round(used * PRICE_PER_MILLION / 1e6, 8)}) + "\n")
    return {key: _unpack(store[key]) for key in (text_key(t) for t in texts)}, tokens


def companion_pairs(bills: list[dict]) -> set[frozenset]:
    pairs = set()
    for bill in bills:
        for other in bill.get("companions") or []:
            if isinstance(other, dict) and other.get("id"):
                pairs.add(frozenset((bill["id"], other["id"])))
    return pairs


def top_related(keys: dict[str, str], vectors: dict[str, list[float]], exclude: set[frozenset],
                top: int = TOP, min_score: float = MIN_SCORE) -> dict[str, list[dict]]:
    """Top cosine neighbours per bill. Bills with identical text (same key) and listed companions are skipped:
    the drawer already shows companions, and duplicates would crowd out genuinely related bills."""
    ids = sorted(keys)
    best: dict[str, list] = {i: [] for i in ids}
    for a in range(len(ids)):
        first, va = ids[a], vectors[keys[ids[a]]]
        for b in range(a + 1, len(ids)):
            second = ids[b]
            if keys[first] == keys[second] or frozenset((first, second)) in exclude:
                continue
            score = sum(map(mul, va, vectors[keys[second]]))
            if score < min_score:
                continue
            for mine, other in ((first, second), (second, first)):
                heap = best[mine]
                if len(heap) < top:
                    heapq.heappush(heap, (score, other))
                elif score > heap[0][0]:
                    heapq.heapreplace(heap, (score, other))
    return {i: [{"id": other, "score": round(score, 3)} for score, other in sorted(heap, reverse=True)]
            for i, heap in best.items() if heap}


def publish(snapshot_bills: list[dict], summaries: dict[str, str], cache_dir: Path, out: Path,
            embedder=openai_embedder) -> tuple[int, int]:
    """Embed what changed, then write `out` (world-readable). Returns (bills with related bills, tokens sent)."""
    bills = [b for b in snapshot_bills if isinstance(b, dict) and b.get("id")]
    texts = {b["id"]: bill_text(b, summaries.get(b["id"])) for b in bills}
    texts = {i: t for i, t in texts.items() if t}
    vectors, tokens = embed_missing(list(texts.values()), cache_dir, embedder)
    related = top_related({i: text_key(t) for i, t in texts.items()}, vectors, companion_pairs(bills))
    payload = {"format": FORMAT, "model": MODEL,
               "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
               "bills": related}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        previous = json.loads(out.read_text("utf-8"))
        unchanged = previous.get("bills") == related
    except (OSError, ValueError, AttributeError):
        unchanged = False
    if not unchanged:
        _atomic_write(out, text, 0o644)
    return len(related), tokens
