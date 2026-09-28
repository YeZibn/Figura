"""SQLite connection and transaction ownership for Figura runtime storage."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from figura.runtime.errors import RunError, RunErrorCode
from .schema import initialize_schema

_BUSY_TIMEOUT_MS = 5000
_DB_FILENAME = "figura.sqlite3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class SqliteDatabase:
    """Own the SQLite file, connections, and transaction contexts."""

    def __init__(self, data_root: str | os.PathLike[str]) -> None:
        self.data_root = Path(data_root).expanduser()
        self.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database_path = self.data_root / _DB_FILENAME
        existed = self.database_path.exists()
        self._initialize()
        if not existed:
            try:
                self.database_path.chmod(0o600)
            except OSError:
                raise RunError(RunErrorCode.STORAGE_ERROR) from None

    def _initialize(self) -> None:
        try:
            with self._connection() as connection:
                initialize_schema(connection)
        except RunError:
            raise
        except sqlite3.Error:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.database_path,
            timeout=_BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection() as connection:
                yield connection
        except RunError:
            raise
        except sqlite3.Error:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    @contextmanager
    def read_snapshot(self) -> Iterator[sqlite3.Connection]:
        """Read related rows from one consistent SQLite snapshot."""
        try:
            with self._connection() as connection:
                connection.execute("BEGIN")
                try:
                    yield connection
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except RunError:
            raise
        except sqlite3.Error:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except RunError:
            raise
        except sqlite3.IntegrityError:
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
        except sqlite3.Error:
            raise RunError(RunErrorCode.STORAGE_ERROR) from None
