"""Private, persistent response reuse with per-request duplicate protection.

Generalised from texas_bill_tracker `scripts/extraction_cache.py`. States: pending -> returned | not_submitted |
capacity_wait | refused | indeterminate. A pending, refused or indeterminate entry is never resent automatically.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .errors import outcome_of
from .exceptions import Deferred, ErrorInfo, NotSent, UnrecordedResponse

_FORMAT = 1


class CacheBusy(NotSent):
    """Another process or thread holds the lock for this request. Nothing was sent."""


class UnresolvedCall(NotSent):
    """An earlier attempt has an unknown outcome or a refused billed reply; an operator must reconcile it.
    Nothing was sent by this call."""


class CacheCoolingDown(Deferred):
    """A capacity wait is persisted for this request; do not call the provider before `retry_at`."""

    def __init__(self, retry_at: float):
        super().__init__("Capacity cooldown is active", retry_at)


@dataclass(frozen=True)
class CachedResponse:
    response: dict
    cache_hit: bool
    key: str


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def request_key(request: dict) -> str:
    # Transport credentials and changing metadata must not be part of the request object.
    return canonical_hash({"cache_format": _FORMAT, "request": request})


_REPLACE_DELAYS_S = (0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4)


def _replace(source: Path, target: Path) -> None:
    """os.replace, retried on PermissionError: on Windows a reader holding the target open fails the rename
    (B-N8, prior M5/F12). Gives up after about one second and raises."""
    for delay in _REPLACE_DELAYS_S:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            time.sleep(delay)
    os.replace(source, target)


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".cth-flex-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            # ASCII-escaped: a lone surrogate in a reply can never fail the write (B-N13). Hashing is unaffected.
            json.dump(value, handle, ensure_ascii=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def exclusive_lock(lock_path: Path, busy: type[Exception], message: str):
    """Non-blocking cross-process lock on `lock_path`; raises `busy(message)` if another holder has it."""
    # Do not unlink lock files: doing so can split ownership across different inodes.
    with Path(lock_path).open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise busy(message) from error
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise busy(message) from error
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ResponseCache:
    def __init__(self, directory: Path | str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(request: dict) -> str:
        return request_key(request)

    def _path(self, key: str) -> Path:
        return self.directory / (key + ".json")

    def _lock(self, key: str):
        return exclusive_lock(self.directory / (key + ".lock"), CacheBusy, "The same request is already running")

    def _read(self, key: str) -> dict | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text("utf-8"))
        except (ValueError, OSError) as error:
            raise UnresolvedCall("Corrupt cache entry; reconcile before resubmission") from error
        if not isinstance(entry, dict) or entry.get("request_key") != key or entry.get("cache_format") != _FORMAT:
            raise UnresolvedCall("Incompatible cache entry; reconcile before resubmission")
        return entry

    def execute(self, request: dict, send: Callable[[], dict]) -> CachedResponse:
        key = self.key(request)
        path = self._path(key)
        with self._lock(key):
            entry = self._read(key)
            if entry is not None:
                state = entry.get("state")
                if state == "returned" and isinstance(entry.get("response"), dict):
                    return CachedResponse(entry["response"], True, key)
                if state == "capacity_wait":
                    retry_at = entry.get("retry_not_before")
                    if not isinstance(retry_at, (int, float)):
                        raise UnresolvedCall("Corrupt capacity entry; reconcile before resubmission")
                    if time.time() < retry_at:
                        raise CacheCoolingDown(retry_at)
                elif state != "not_submitted":
                    raise UnresolvedCall("Earlier outcome is uncertain; reconcile before resubmission")
            pending = {"cache_format": _FORMAT, "request_key": key, "state": "pending", "started_at": time.time()}
            try:
                atomic_json(path, pending)
            except Exception as error:  # noqa: BLE001 - send() was never called
                raise NotSent(f"not sent: cache entry not written ({type(error).__name__})") from error
            try:
                response = send()
            except Exception as error:
                # Never store exception messages: SDK messages may contain request/credential details.
                meta = {"error_type": type(error).__name__, **_label(error)}
                outcome = outcome_of(error)
                refused = outcome == "billed" and isinstance(getattr(error, "response", None), dict)
                try:
                    if isinstance(error, Deferred) and outcome == "not_sent":
                        atomic_json(path, {**pending, "state": "capacity_wait", "retry_not_before": error.retry_at,
                                           **meta})
                    elif outcome == "not_sent":
                        atomic_json(path, {**pending, "state": "not_submitted", **meta})
                    elif refused:
                        # Billed but refused (tier/status): keep the reply so it is never paid for twice.
                        atomic_json(path, {**pending, "state": "refused", "response": error.response, **meta})
                    else:
                        atomic_json(path, {**pending, "state": "indeterminate", **meta})
                except Exception as record_error:  # noqa: BLE001 - the entry stays pending, which blocks a resend
                    if refused:
                        raise UnrecordedResponse("Billed reply not cached; entry left pending",
                                                 error.response) from record_error
                raise
            # send() returned, so the call was billed. Any failure from here on leaves the entry pending, which
            # blocks a resend, and raises UnrecordedResponse, never anything that reads as not sent.
            if not isinstance(response, dict):
                raise UnrecordedResponse("Expected a JSON response object; entry left pending", response)
            try:
                atomic_json(path, {**pending, "state": "returned", "response": response, "returned_at": time.time()})
            except Exception as error:  # noqa: BLE001
                raise UnrecordedResponse("Billed reply not cached; entry left pending", response) from error
            return CachedResponse(response, False, key)

    def forget(self, key: str, *, force: bool = False) -> bool:
        """Operator: drop a non-returned entry so the request may be sent again. Refuses a returned one, and a
        refused one (it holds a billed reply; read it with `stored_response`) unless `force=True`."""
        with self._lock(key):
            path = self._path(key)
            if not path.exists():
                return False
            try:
                entry = json.loads(path.read_text("utf-8"))
            except (ValueError, OSError):
                entry = None
            state = entry.get("state") if isinstance(entry, dict) else None
            if state == "returned":
                raise ValueError("Refusing to forget a returned entry")
            if state == "refused" and not force:
                raise ValueError("Refusing to forget a refused entry: it holds a billed reply (stored_response); "
                                 "pass force=True")
            path.unlink()
            return True

    def stored_response(self, key: str) -> dict | None:
        """The reply kept for a returned or refused entry, else None."""
        with self._lock(key):
            try:
                entry = json.loads(self._path(key).read_text("utf-8"))
            except (ValueError, OSError):
                return None
        if isinstance(entry, dict) and entry.get("state") in ("returned", "refused"):
            response = entry.get("response")
            return response if isinstance(response, dict) else None
        return None

    def resolve(self, key: str, response: dict) -> None:
        """Operator: record a response recovered out of band for an unresolved entry."""
        if not isinstance(response, dict):
            raise TypeError("Expected a JSON response object")
        with self._lock(key):
            atomic_json(self._path(key), {"cache_format": _FORMAT, "request_key": key, "state": "returned",
                                          "response": response, "returned_at": time.time(), "resolved": True})

    def entries(self) -> Iterator[tuple[str, str]]:
        """Yield (key, state) for every stored entry; unreadable files report state 'corrupt'."""
        for path in sorted(self.directory.glob("*.json")):
            try:
                state = json.loads(path.read_text("utf-8")).get("state", "corrupt")
            except (ValueError, OSError, AttributeError):
                state = "corrupt"
            yield path.stem, state


def _label(error: BaseException) -> dict:
    info = getattr(error, "info", None)
    return {"error_label": info.label()} if isinstance(info, ErrorInfo) else {}
