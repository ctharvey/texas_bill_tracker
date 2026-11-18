"""The pipeline's exception classes, the response-cache key, atomic JSON writes and the worker file lock.

Responses are cached by the vendored cth_flex cache behind flex_boundary.FlexBoundary, which uses the same key."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile


class CacheBusy(RuntimeError):
    pass


class UnresolvedCall(RuntimeError):
    pass


class CacheCoolingDown(RuntimeError):
    pass


class NotSubmitted(RuntimeError):
    """Failure known to have happened before submission; safe to retry later."""


class CapacityUnavailable(RuntimeError):
    def __init__(self, retry_after: float = 60):
        self.retry_after = retry_after
        super().__init__("Provider capacity unavailable")


class BudgetExceeded(NotSubmitted):
    pass


class OutcomeUnresolved(NotSubmitted):
    """An earlier billing outcome is unknown; no further calls until reconciled."""


class AlreadyBilled(NotSubmitted):
    """This exact request was billed before; its response cache must be restored."""


class LongContext(NotSubmitted):
    """The request exceeds the reviewed pricing range."""


class ApiStopped(RuntimeError):
    """The provider refused the account (quota, billing or auth); nothing was billed. Ends the run."""

    def __init__(self, code: str):
        self.code = code
        super().__init__("Provider refused the request: " + code)


class ApiRejected(ValueError):
    """The provider rejected this request without processing it (bad request or a proven-unbilled server error)."""


@dataclass(frozen=True)
class CachedResponse:
    response: dict
    cache_hit: bool
    key: str


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: object, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".extraction-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            # ASCII-escaped, as in the vendored cache: a lone surrogate in a reply can never fail the write.
            json.dump(value, handle, ensure_ascii=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)  # before the rename, so readers never see the file unreadable
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class ResponseCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(request: dict) -> str:
        # Transport credentials and changing source URLs/status metadata are never part of this object.
        return canonical_hash({"cache_format": 1, "request": request})

    @contextlib.contextmanager
    def _lock(self, key: str):
        # Do not unlink lock files: doing so can split ownership across different inodes.
        with (self.directory / (key + ".lock")).open("a+b") as handle:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    raise CacheBusy("The same extraction is already running") from error
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
                    raise CacheBusy("The same extraction is already running") from error
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
