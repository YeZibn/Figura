"""Cross-process, fail-closed exclusive locks for durable Run execution."""

from __future__ import annotations

import hashlib
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class RunExecutionLockUnavailable(RuntimeError):
    """The current process cannot prove exclusive ownership of a Run."""


class PerRunExecutionLock:
    """Use an OS advisory lock whose lifetime is tied to an open file handle."""

    __slots__ = ("_lock_root",)

    def __init__(self, data_root: str | os.PathLike[str]) -> None:
        self._lock_root = Path(data_root).expanduser() / ".run-locks"

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
                try:
                    yield
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        except RunExecutionLockUnavailable:
            raise
        except (ImportError, OSError, ValueError):
            raise RunExecutionLockUnavailable("Run lock storage is unavailable") from None
