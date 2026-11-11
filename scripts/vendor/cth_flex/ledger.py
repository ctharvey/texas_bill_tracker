"""Persistent spend ledger with reservations, generalised from texas_bill_tracker `review_pipeline.Budget`.

Layout: {day: {request_key: {"state": "pending", "reserved": usd, "owner": id} | {"state": "returned", "cost": usd,
"reserved": 0}}}. Every read-modify-write re-reads the file under a thread lock and a cross-process file lock.
A pending row blocks new calls unless it is one of this instance's own calls still in flight; crash leftovers and
other live instances' calls block until an operator resolves them.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from .cache import atomic_json, exclusive_lock, request_key
from .cost import Rates, cost_usd, reservation_usd, usage_from_response
from .client import uncertain_attempts
from .errors import outcome_of
from .exceptions import NotSent, UnrecordedResponse


class OutcomeUnresolved(NotSent):
    """A prior call has an unknown billing outcome; new calls are blocked. Nothing was sent."""

    halts_run = True


class AlreadyBilled(NotSent):
    """This request key is already in the ledger (billed, or in flight). Nothing was sent."""


class LongContext(NotSent):
    """The request is larger than `max_request_bytes`. Nothing was sent."""


class BudgetExceeded(NotSent):
    """The reservation would cross the daily or run limit. Nothing was sent."""

    halts_run = True


class LedgerBusy(NotSent):
    """The ledger file lock was not obtained within `lock_timeout_s`. Nothing was sent."""

    halts_run = True


class ReservationRefused(NotSent, ValueError):
    """The request cannot be priced (no output cap, unbounded hidden input, bad counts). Nothing was sent."""


class LedgerUnavailable(NotSent):
    """The ledger could not be read or written before the send. Nothing was sent."""

    halts_run = True


_HOST = socket.gethostname()
_LIVE_WINDOW_S = 3600.0


def _blocking_message(rows: list[dict]) -> str:
    """Informational only: never resolves anything. Says when a blocking row may be another instance's live call."""
    now = time.time()
    live = [r for r in rows if isinstance(r.get("started_at"), (int, float)) and now - r["started_at"] < _LIVE_WINDOW_S]
    message = "A prior billing outcome is unresolved; new calls are blocked"
    if live:
        where = ", ".join(sorted({f"{r.get('host')}:{r.get('pid')}" for r in live}))
        message += (f" ({len(live)} pending row(s) started in the last hour may still be in flight at {where}; "
                    "do not resolve a live call)")
    return message


def _reserve_attempts(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"reserve_attempts must be an integer >= 1, got {value!r}")
    return value


class SpendLedger:
    def __init__(self, path: Path | str, *, daily_limit_usd: float | None = None, run_limit_usd: float | None = None,
                 tz: str = "UTC", max_request_bytes: int | None = None, default_output_tokens: int | None = None,
                 extra_input_tokens: int | None = None, lock_timeout_s: float = 30.0,
                 reserve_attempts: int = 1):
        """`reserve_attempts`: how many sends to reserve per call before it starts (the caller's choice). Set it
        to the client's `server_attempts` under `retry_uncertain` so the limits hold before any resend is charged;
        the default 1 reserves one send and charges resends after the fact."""
        self.reserve_attempts = _reserve_attempts(reserve_attempts)
        for limit in (daily_limit_usd, run_limit_usd):
            if limit is not None and not limit > 0:
                raise ValueError("Limits must be positive or None")
        self.path = Path(path)
        self.daily_limit_usd, self.run_limit_usd = daily_limit_usd, run_limit_usd
        self.zone = ZoneInfo(tz)
        self.max_request_bytes = max_request_bytes
        self.default_output_tokens = default_output_tokens
        self.extra_input_tokens = extra_input_tokens
        self.lock_timeout_s = lock_timeout_s
        self.owner = uuid.uuid4().hex
        self.run_spent = 0.0
        self._inflight: dict[str, float] = {}  # this instance's calls in flight: key -> reservation
        self._mutex = threading.Lock()
        # Not read here: an unlocked read can break a concurrent writer's os.replace on Windows (B-N8). Every
        # decision re-reads the file under both locks; a corrupt file is reported on first use.
        self.ledger: dict = {}

    def day(self) -> str:
        # Recomputed per call so a run spanning midnight books spend to the correct day.
        return dt.datetime.now(self.zone).date().isoformat()

    def _load(self) -> dict:
        return json.loads(self.path.read_text("utf-8")) if self.path.exists() else {}

    @contextlib.contextmanager
    def _locked(self):
        """Hold both locks and yield the ledger freshly read from disk. Never trust an earlier in-memory copy."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_s
        # Bounded like the file lock (B-N21): in-process contention past lock_timeout_s is LedgerBusy, not a hang.
        if not self._mutex.acquire(timeout=max(0.0, self.lock_timeout_s)):
            raise LedgerBusy("Spend ledger is busy in this process")
        try:
            while True:
                lock = exclusive_lock(self.path.with_name(self.path.name + ".lock"), LedgerBusy,
                                      "Spend ledger is locked by another writer")
                try:
                    lock.__enter__()
                    break
                except LedgerBusy:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
            try:
                self.ledger = self._load()
                yield self.ledger
            finally:
                lock.__exit__(None, None, None)
        finally:
            self._mutex.release()

    def _save(self, data: dict) -> None:
        atomic_json(self.path, data)

    def pending(self) -> list[str]:
        with self._locked() as data:
            return [key for day in data.values() for key, row in day.items() if row.get("state") == "pending"]

    def resolve(self, key: str, cost_usd: float | None = None) -> None:
        """Operator: settle a pending row with its known cost, or drop it when the call is known not billed."""
        with self._locked() as data:
            for day in data.values():
                row = day.get(key)
                if row is not None and row.get("state") == "pending":
                    if cost_usd is None:
                        del day[key]
                    else:
                        day[key] = {"state": "returned", "cost": cost_usd, "reserved": 0}
                    self._save(data)
                    return
        raise KeyError(key)

    def send(self, request: dict, sender: Callable[[dict], dict], rates: Rates) -> dict:
        reserved_key = None
        try:
            try:
                day, key, ceiling = self._reserve(request, rates)
            except NotSent:
                raise
            except Exception as error:  # noqa: BLE001 - the sender was never called
                raise LedgerUnavailable(f"not sent: ledger unavailable ({type(error).__name__})") from error
            reserved_key = key
            prior = uncertain_attempts.get()
            uncertain_attempts.set(0)
            try:
                response = sender(request)
            except Exception as error:
                n = self._take_count(prior)
                outcome = outcome_of(error)
                if outcome == "not_sent":
                    self._release(day, key)
                elif outcome == "billed" and isinstance(getattr(error, "response", None), dict):
                    # Billed replies that the client refused: settle their real cost so later calls are not blocked.
                    self._settle(day, key, error.response, rates, n, ceiling)
                elif n > 1:
                    self._widen(day, key, n * ceiling)
                raise  # maybe sent: the pending row stays and blocks until resolved
            except BaseException:
                self._take_count(prior)
                raise
            n = self._take_count(prior)
            self._settle(day, key, response, rates, n, ceiling)
            return response
        finally:
            if reserved_key is not None:
                with self._mutex:
                    self._inflight.pop(reserved_key, None)

    @staticmethod
    def _take_count(prior: int) -> int:
        n = uncertain_attempts.get()
        uncertain_attempts.set(prior + n)
        return n

    def _widen(self, day: str, key: str, reserved: float) -> None:
        """Each maybe-billed send behind an uncertain outcome may have cost a full ceiling (A-N11)."""
        try:
            with self._locked() as data:
                row = data.get(day, {}).get(key)
                if isinstance(row, dict) and row.get("state") == "pending":
                    row["reserved"] = max(row.get("reserved", 0), reserved)
                    self._save(data)
        except Exception:  # noqa: BLE001 - the pending row still blocks; the original error is what matters
            pass

    def _reserve(self, request: dict, rates: Rates) -> tuple[str, str, float]:
        day = self.day()
        try:
            key = request_key(request)
            ceiling = reservation_usd(request, rates, self.default_output_tokens,
                                      extra_input_tokens=self.extra_input_tokens)
        except (TypeError, ValueError) as error:
            raise ReservationRefused(str(error)) from error
        saved = False
        try:
            with self._locked() as data:
                blocking = [row for rows in data.values() for k, row in rows.items()
                            if row.get("state") == "pending"
                            and not (row.get("owner") == self.owner and k in self._inflight)]
                if blocking:
                    raise OutcomeUnresolved(_blocking_message(blocking))
                if any(key in rows for rows in data.values()):
                    raise AlreadyBilled("This request was already billed or is in flight; restore its response cache "
                                        "before proceeding")
                size = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
                if self.max_request_bytes is not None and size > self.max_request_bytes:
                    raise LongContext("Long-context requests require separate pricing review")
                today = data.setdefault(day, {})
                committed = sum(row.get("cost", 0) + (row.get("reserved", 0) if row.get("state") == "pending" else 0)
                                for row in today.values())
                run_committed = self.run_spent + sum(self._inflight.values())
                hold = ceiling * self.reserve_attempts  # what admission reserves; charges stay per send
                if ((self.daily_limit_usd is not None and committed + hold > self.daily_limit_usd)
                        or (self.run_limit_usd is not None and run_committed + hold > self.run_limit_usd)):
                    raise BudgetExceeded("Spending ceiling reached; remaining work stays queued")
                today[key] = {"state": "pending", "reserved": hold, "owner": self.owner,
                              "started_at": time.time(), "pid": os.getpid(), "host": _HOST}
                self._save(data)
                saved = True
                self._inflight[key] = hold
        except BaseException:
            if saved:
                # B-N23: the row was written but the reservation did not complete (e.g. the lock release failed).
                # Nothing was sent: drop this instance's in-flight entry and, best effort, the row itself.
                with self._mutex:
                    self._inflight.pop(key, None)
                try:
                    self._release(day, key)
                except Exception:  # noqa: BLE001 - the row then blocks until an operator resolves it
                    pass
            raise
        return day, key, ceiling

    def _settle(self, day: str, key: str, response: dict, rates: Rates, unconfirmed: int = 0,
                ceiling: float = 0.0) -> None:
        # A reply arrived, so it was billed: no failure here may look "not sent". The pending row stays.
        try:
            cost = cost_usd(usage_from_response(response), rates)
        except Exception as error:  # noqa: BLE001
            raise UnrecordedResponse("Unknown billing outcome; reservation retained", response) from error
        # Maybe-billed sends behind this reply (retry_uncertain) may each have cost up to the ceiling (A-N11).
        extra = unconfirmed * ceiling
        cost += extra
        row = {"state": "returned", "cost": cost, "reserved": 0}
        if unconfirmed:
            row.update(unconfirmed_attempts=unconfirmed, unconfirmed_usd=extra)
        try:
            with self._locked() as data:
                data.setdefault(day, {})[key] = row
                self._save(data)
                self.run_spent += cost
        except Exception as error:  # noqa: BLE001
            raise UnrecordedResponse("Billed reply not recorded; reservation retained", response) from error

    def _release(self, day: str, key: str) -> None:
        with self._locked() as data:
            data.get(day, {}).pop(key, None)
            self._save(data)
