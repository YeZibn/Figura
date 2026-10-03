"""Cross-process, fail-closed exclusive locks for durable Run execution."""

from __future__ import annotations

import hashlib
import os
import stat
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Iterator


_OWNED_LOCKS = ContextVar("figura_owned_execution_locks", default=frozenset())


class RunExecutionLockUnavailable(RuntimeError):
    """The current process cannot prove exclusive ownership of a Run."""


class PerRunExecutionLock:
    """Use an OS advisory lock whose lifetime is tied to an open file handle."""

    __slots__ = ("_lock_root",)

    def __init__(self, data_root: str | os.PathLike[str]) -> None:
        self._lock_root = Path(data_root).expanduser() / ".run-locks"

    def _identity(self, run_id: str):
        import threading
        return (str(self._lock_root.resolve()), run_id, os.getpid(), threading.get_ident())

    def owned_here(self, run_id: str) -> bool:
        return self._identity(run_id) in _OWNED_LOCKS.get()

    @contextmanager
    def acquire(self, run_id: str) -> Iterator[None]:
        if not isinstance(run_id, str) or not run_id:
            raise RunExecutionLockUnavailable("Run lock identity is invalid")
        try:
            lock_id = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        except UnicodeEncodeError:
            raise RunExecutionLockUnavailable("Run lock identity is invalid") from None

        try:
            import fcntl

            self._lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            root_stat = self._lock_root.stat()
            if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_mode & 0o077:
                raise RunExecutionLockUnavailable("Run lock storage is unavailable")
            if not hasattr(os, "O_NOFOLLOW"):
                raise RunExecutionLockUnavailable("No safe Run lock adapter is available")
            flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            descriptor = os.open(self._lock_root / f"{lock_id}.lock", flags, 0o600)
            try:
                lock_stat = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(lock_stat.st_mode)
                    or lock_stat.st_uid != os.geteuid()
                ):
                    raise RunExecutionLockUnavailable("Run lock storage is unavailable")
                os.fchmod(descriptor, 0o600)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (BlockingIOError, OSError):
                    raise RunExecutionLockUnavailable("Run lock is already held") from None
                token = _OWNED_LOCKS.set(_OWNED_LOCKS.get() | {self._identity(run_id)})
                try:
                    yield
                finally:
                    _OWNED_LOCKS.reset(token)
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        except RunExecutionLockUnavailable:
            raise
        except (ImportError, OSError, ValueError):
            raise RunExecutionLockUnavailable("Run lock storage is unavailable") from None


class RunExecutionOwnership(PerRunExecutionLock):
    """Exclusive owner of the complete execution task, separate from action locks."""

    def __init__(self, data_root: str | os.PathLike[str]) -> None:
        super().__init__(data_root)
        self._lock_root = Path(data_root).expanduser() / ".run-owner-locks"

    def is_held(self, run_id: str) -> bool:
        try:
            with self.acquire(run_id):
                return False
        except RunExecutionLockUnavailable:
            return True


def owned_claim(method):
    """Direct persistence claims must also prove owner and action exclusivity."""
    @wraps(method)
    def invoke(self, *args, **kwargs):
        run_id = kwargs["run_id"]
        owner = RunExecutionOwnership(self.data_root)
        action = PerRunExecutionLock(self.data_root)
        try:
            with nullcontext() if owner.owned_here(run_id) else owner.acquire(run_id):
                with nullcontext() if action.owned_here(run_id) else action.acquire(run_id):
                    return method(self, *args, **kwargs)
        except RunExecutionLockUnavailable:
            from .errors import RunError, RunErrorCode
            raise RunError(RunErrorCode.INVALID_TRANSITION) from None
    return invoke
