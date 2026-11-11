"""Concurrent batch runner with an input-pinned JSONL checkpoint, a reserved spend cap and clean stops.

Before each send an attempt marker goes to `<checkpoint>.attempts`; each result row carries its attempt id. On
resume an item is held (never resent) when it was sent without a recorded result, or its last row is `uncertain`
(maybe billed) or `refused` (billed, reply refused). Only `rerun=[...]` from the operator releases a held item.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable

from .cache import exclusive_lock, request_key
from .client import uncertain_attempts
from .cost import Rates, cost_usd, reservation_usd, usage_from_response
from .errors import outcome_of
from .exceptions import Deferred, ErrorInfo, Kind

_EPS = 1e-12


def _take_count(prior: int) -> int:
    """Read the maybe-billed attempts a client published during one call, and hand them on to outer layers."""
    n = uncertain_attempts.get()
    uncertain_attempts.set(prior + n)
    return n


def _plus(cost: float | None, extra: float) -> float | None:
    return cost if cost is None else cost + extra


class CheckpointBusy(RuntimeError):
    """Another process is running a batch on the same checkpoint."""


@dataclass
class BatchSummary:
    total: int = 0
    done: int = 0                       # ok items, including those finished in earlier runs
    ok: int = 0                         # ok items finished in this run
    errors: int = 0                     # not-sent errors in this run (rerun on resume)
    deferred: list[str] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)   # maybe billed: held until the operator reruns them
    refused: list[str] = field(default_factory=list)     # billed but refused (tier/status): held likewise
    skipped_budget: int = 0
    spent_usd: float = 0.0
    stopped_reason: str | None = None
    results: dict[str, dict] = field(default_factory=dict)


def _read_jsonl(path: Path) -> list[dict]:
    """Parseable rows in order. Unparseable lines (a crash mid-write) are ignored, and a truncated final line is
    terminated so the next appended row starts on its own line."""
    if not path.exists():
        return []
    with open(path, "rb") as fh:
        data = fh.read()
    rows = []
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(row, dict) and isinstance(row.get("custom_id"), str):
            rows.append(row)
    if data and not data.endswith(b"\n"):
        with open(path, "ab") as fh:
            fh.write(b"\n")
            fh.flush()
            os.fsync(fh.fileno())
    return rows


# 0.1.0 wrote every failure as `error` with no attempt id, maybe-billed ones included. Only these label kinds prove
# the item was not sent; any other 0.1.0 error row is held.
_LEGACY_NOT_SENT_KINDS = frozenset({"capacity", "rate_limit", "quota", "auth", "bad_request"})


def _held_state(row: dict) -> str | None:
    """'uncertain' or 'refused' when the last row for this request and pin must not be resent; None otherwise."""
    status = row.get("status")
    if status in ("uncertain", "refused"):
        return status
    if status == "ok":
        return "uncertain"  # ok without a dict reply (written by <= 0.1.2): billed, never resend
    if status == "error" and not isinstance(row.get("attempt_id"), str):
        label = row.get("label")
        kind = label.split(",", 1)[0].strip() if isinstance(label, str) else None
        return None if kind in _LEGACY_NOT_SENT_KINDS else "uncertain"
    return None


def _append(path: Path, line: str) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def run_batch(
    items: Iterable[tuple[str, dict]],
    client,
    checkpoint: Path | str,
    *,
    workers: int = 4,
    rates: Rates | None = None,
    max_usd: float | None = None,
    pin: str | None = None,
    on_progress: Callable[[BatchSummary], None] | None = None,
    default_output_tokens: int | None = None,
    extra_input_tokens: int | None = None,
    reserve_attempts: int = 1,
    rerun: Iterable[str] = (),
    max_defer_wait_s: float = 600,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> BatchSummary:
    """`sleep=None` waits for deferrals on an internal event that an interrupt or a halt cuts short. `cancel`, if
    given, is set on an interrupt (never on a halt) so a `FlexClient(cancel=...)` sharing it stops resending; use one
    event per run, since it stays set. `reserve_attempts` (the caller's choice, default 1): how many sends `max_usd`
    admission reserves per item; set it to the client's `server_attempts` under `retry_uncertain`."""
    if isinstance(reserve_attempts, bool) or not isinstance(reserve_attempts, int) or reserve_attempts < 1:
        raise ValueError(f"reserve_attempts must be an integer >= 1, got {reserve_attempts!r}")
    if isinstance(rerun, (str, bytes)):
        raise TypeError("rerun must be a collection of custom_ids, not a string")
    item_list = [(cid, req) for cid, req in items]
    seen: set[str] = set()
    for cid, _ in item_list:
        if cid in seen:
            raise ValueError(f"Duplicate custom_id: {cid!r}")
        seen.add(cid)
    if max_usd is not None and rates is None:
        raise ValueError("max_usd requires rates")
    path = Path(checkpoint)
    attempts_path = path.with_name(path.name + ".attempts")
    rerun_ids = set(rerun)
    reservations: dict[str, float] = {}
    if max_usd is not None:
        for cid, req in item_list:
            reservations[cid] = reservation_usd(req, rates, default_output_tokens,
                                                extra_input_tokens=extra_input_tokens)

    summary = BatchSummary(total=len(item_list))
    ready: deque[tuple[str, dict, str]] = deque()
    state = threading.Lock()
    write_lock = threading.Lock()
    delayed: list[tuple[float, tuple[str, dict, str]]] = []
    committed = 0.0
    inflight = 0.0
    active = 0
    stop = False
    blocked = False
    wake = threading.Event()  # set on interrupt or halt: cuts a deferral wait short
    pending_resolves: dict[str, list[str]] = {}

    def write(target: Path, row: dict) -> None:
        # ASCII-escaped: a lone surrogate in a reply can never fail the UTF-8 write (B-N13).
        line = json.dumps(row, ensure_ascii=True, allow_nan=False) + "\n"
        with write_lock:
            _append(target, line)

    def load_ready() -> None:
        rows = _read_jsonl(path)
        by_cid: dict[str, list[dict]] = {}
        finished: set[str] = set()
        for row in rows:
            by_cid.setdefault(row["custom_id"], []).append(row)
            if isinstance(row.get("attempt_id"), str):
                finished.add(row["attempt_id"])
        markers = _read_jsonl(attempts_path)
        for marker in markers:
            for resolved in marker.get("resolves") or ():
                finished.add(resolved)
        open_attempts: dict[str, list[dict]] = {}
        for marker in markers:
            if isinstance(marker.get("attempt_id"), str) and marker["attempt_id"] not in finished:
                open_attempts.setdefault(marker["custom_id"], []).append(marker)
        for cid, req in item_list:
            key = request_key(req)
            same = lambda r: r.get("request_hash") == key and r.get("pin") == pin  # noqa: E731
            # Only rows for this exact request and pin count: another version's rows never hide or release a hold.
            matching = [r for r in by_cid.get(cid, []) if same(r)]
            done = [r for r in matching if r.get("status") == "ok" and isinstance(r.get("response"), dict)]
            if done:
                summary.results[cid] = done[-1]["response"]
                summary.done += 1
                continue
            sent_unrecorded = [m for m in open_attempts.get(cid, []) if same(m)]
            held = _held_state(matching[-1]) if matching else None
            if cid in rerun_ids:
                if sent_unrecorded:
                    # Recorded inside the next attempt marker, only when that attempt actually starts.
                    pending_resolves[cid] = [m["attempt_id"] for m in sent_unrecorded]
            elif sent_unrecorded:
                summary.uncertain.append(cid)
                continue
            elif held == "uncertain":
                summary.uncertain.append(cid)
                continue
            elif held == "refused":
                summary.refused.append(cid)
                continue
            ready.append((cid, req, key))

    def settle_cost(resp: object, reserved: float) -> float | None:
        if rates is None:
            return None
        try:
            return cost_usd(usage_from_response(resp), rates)
        except Exception:
            return reserved if max_usd is not None else None

    def snapshot() -> BatchSummary:
        return replace(summary, deferred=list(summary.deferred), uncertain=list(summary.uncertain),
                       refused=list(summary.refused), results=dict(summary.results), spent_usd=committed)

    def _wait(seconds: float) -> None:
        """Deferral wait that an interrupt, a halt or the caller's cancel event ends early."""
        deadline = time.monotonic() + seconds
        while not wake.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0 or (cancel is not None and cancel.is_set()):
                return
            wake.wait(min(remaining, 0.1) if cancel is not None else remaining)

    def halt(reason: str) -> None:
        nonlocal stop
        stop = True
        wake.set()
        if summary.stopped_reason is None:
            summary.stopped_reason = reason

    def finish(item, reserved, attempt_id, *, status, response=None, cost=None, label=None, retry_at=None,
               charge=0.0, stop_reason=None, unconfirmed=0) -> None:
        """Record one attempt, then settle reservation and bookkeeping (always, even if the write fails)."""
        nonlocal committed, inflight, active
        cid, _req, key = item
        row = {"custom_id": cid, "request_hash": key, "pin": pin, "attempt_id": attempt_id, "status": status,
               "response": None, "cost_usd": cost, "label": label, "retry_at": retry_at}
        if unconfirmed:
            row["unconfirmed_attempts"] = unconfirmed
        if status == "ok":
            row["response"] = response
            if not isinstance(response, dict):
                # Billed, but only a dict counts as done on resume: hold it so resume never pays for it again.
                status = row["status"] = "uncertain"
                row["label"] = "non_dict_response"
            try:
                json.dumps(row, ensure_ascii=True, allow_nan=False)
            except (TypeError, ValueError):
                # Billed, but the reply cannot be persisted: hold it so resume never pays for it again.
                status = row["status"] = "uncertain"
                row["response"], row["label"] = None, "unserializable_response"
        elif status == "refused" and response is not None:
            try:
                json.dumps(response, ensure_ascii=True, allow_nan=False)
                row["response"] = response
            except (TypeError, ValueError):
                pass  # still held; the reply just is not kept
        write_failed = False
        try:
            write(path, row)
        except Exception:  # noqa: BLE001 - the attempt marker stays open, so resume holds this item
            write_failed = True
        with state:
            inflight -= reserved * reserve_attempts
            committed += charge if charge is not None else 0.0
            active -= 1
            if status == "ok":
                summary.ok += 1
                summary.done += 1
                summary.results[cid] = response
            elif status == "error":
                summary.errors += 1
            elif status == "deferred":
                delayed.append((retry_at, item))
            elif status == "uncertain":
                summary.uncertain.append(cid)
                if response is not None:
                    summary.results[cid] = response
            elif status == "refused":
                summary.refused.append(cid)
                if response is not None:
                    summary.results[cid] = response
            if write_failed:
                halt("checkpoint_write_failed")
            if stop_reason is not None:
                halt(stop_reason)
            if max_usd is not None and committed > max_usd + _EPS:
                halt("max_usd exceeded")
            snap = snapshot()
        if on_progress is not None and status != "deferred":
            try:
                on_progress(snap)
            except Exception:
                pass

    def run_item(item, reserved: float) -> None:
        cid, req, key = item
        attempt_id = uuid.uuid4().hex
        marker = {"custom_id": cid, "attempt_id": attempt_id, "request_hash": key, "pin": pin}
        resolves = pending_resolves.get(cid)
        if resolves:
            # One line: the operator's release of the earlier attempts and this attempt's own marker.
            marker["resolves"] = resolves
        try:
            write(attempts_path, marker)
        except Exception:  # noqa: BLE001 - cannot record the send, so do not send
            finish(item, reserved, attempt_id, status="error", label="attempt_write_failed",
                   stop_reason="checkpoint_write_failed")
            return
        pending_resolves.pop(cid, None)
        prior = uncertain_attempts.get()
        uncertain_attempts.set(0)
        try:
            resp = client.call(req)
        except Exception as e:  # noqa: BLE001 - every failure is classified by outcome
            n = _take_count(prior)
            info = getattr(e, "info", None)
            info = info if isinstance(info, ErrorInfo) else None
            label = info.label() if info is not None else type(e).__name__
            outcome = outcome_of(e)
            if isinstance(e, Deferred) and outcome == "not_sent":
                finish(item, reserved, attempt_id, status="deferred", retry_at=e.retry_at, label=label)
            elif outcome == "not_sent":
                hard = getattr(e, "halts_run", False) or (info is not None and info.kind in (Kind.QUOTA, Kind.AUTH))
                finish(item, reserved, attempt_id, status="error", label=label, stop_reason=label if hard else None)
            elif outcome == "billed":
                # Billed and refused: keep the reply (B-N3) and charge it, plus any maybe-billed earlier attempts.
                response = getattr(e, "response", None)
                cost = settle_cost(response, reserved)
                finish(item, reserved, attempt_id, status="refused", response=response, label=type(e).__name__,
                       cost=cost, charge=_plus(cost, n * reserved), unconfirmed=n)
            else:
                # Possibly billed, once per maybe-billed send: keep that many reservations and start no new work.
                finish(item, reserved, attempt_id, status="uncertain", label=label, charge=max(1, n) * reserved,
                       stop_reason=label, unconfirmed=n)
        except BaseException:
            _take_count(prior)
            raise
        else:
            n = _take_count(prior)
            cost = settle_cost(resp, reserved)
            finish(item, reserved, attempt_id, status="ok", response=resp, cost=cost,
                   charge=_plus(cost, n * reserved), unconfirmed=n)

    def worker() -> None:
        nonlocal inflight, active, blocked
        while True:
            sleep_for = 0.0
            item = None
            with state:
                if cancel is not None and cancel.is_set():
                    halt("cancelled")  # the caller cancelled: start nothing new
                if stop or blocked:
                    return
                now = clock()
                for entry in [d for d in delayed if d[0] <= now]:
                    delayed.remove(entry)
                    ready.append(entry[1])
                if ready:
                    cid = ready[0][0]
                    # Admission holds reserve_attempts sends (the caller's choice); charges stay per send.
                    res = reservations.get(cid, 0.0) * reserve_attempts
                    if max_usd is not None and committed + inflight + res > max_usd + _EPS:
                        if active == 0:
                            blocked = True  # does not fit even with nothing in flight
                        # Otherwise in-flight reservations may settle lower: the active workers re-check (B-N6).
                        return
                    item = ready.popleft()
                    inflight += res
                    active += 1
                elif delayed:
                    if active > 0:
                        return
                    wait_s = min(d[0] for d in delayed) - now
                    if wait_s > max_defer_wait_s:
                        return
                    sleep_for = max(wait_s, 0.0)
                else:
                    return
            if item is None:
                if sleep is None:
                    _wait(sleep_for)
                else:
                    sleep(sleep_for)
                continue
            try:
                run_item(item, reservations.get(item[0], 0.0))
            except BaseException:
                with state:  # e.g. SystemExit from a client: stop every worker, then propagate (B-N12)
                    halt("worker_aborted")
                raise

    # Two runners on one checkpoint would send (and pay for) the same items twice.
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(path.with_name(path.name + ".lock"), CheckpointBusy,
                        "Another run_batch is using this checkpoint"):
        load_ready()
        interrupted: BaseException | None = None
        pool = ThreadPoolExecutor(max_workers=max(1, workers))
        futures: list = []
        pending: set = set()
        # Never leave the checkpoint lock while a worker may still send: on an interrupt, stop new work and keep
        # waiting (through further interrupts) until every worker has returned.
        while True:
            try:
                if interrupted is not None:
                    stop = True
                while interrupted is None and len(futures) < max(1, workers):
                    fut = pool.submit(worker)
                    futures.append(fut)
                    pending.add(fut)
                if pending:
                    _done, pending = wait(pending, timeout=0.2)
                    continue
                pool.shutdown(wait=True)  # joins every thread, including one submitted but not yet recorded
                break
            except BaseException as exc:  # noqa: BLE001 - re-raised below once workers are drained
                wake.set()
                if cancel is not None:
                    cancel.set()
                if interrupted is None:
                    interrupted = exc
        if interrupted is not None:
            raise interrupted
        for fut in futures:
            fut.result()

    summary.deferred = [d[1][0] for d in delayed]
    if blocked:
        summary.skipped_budget = len(ready)
    summary.spent_usd = committed
    return summary
