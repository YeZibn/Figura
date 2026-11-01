"""SQLite connection and transaction ownership for Figura runtime storage."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from figura.runtime.errors import RunError, RunErrorCode
from .schema import initialize_schema
from figura.shared.payloads import ExecutionPayloadLimits, use_payload_limits, use_payload_read_limits

_BUSY_TIMEOUT_MS = 5000
_DB_FILENAME = "figura.sqlite3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class SqliteDatabase:
    """Own the SQLite file, connections, and transaction contexts."""

    def __init__(self, data_root: str | os.PathLike[str], *, payload_limits: ExecutionPayloadLimits | None = None) -> None:
        self.payload_limits = payload_limits or ExecutionPayloadLimits.from_env()
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
        deadline = time.monotonic() + _BUSY_TIMEOUT_MS / 1000
        while True:
            try:
                with self._connection() as connection:
                    initialize_schema(connection)
                return
            except RunError:
                raise
            except sqlite3.OperationalError as error:
                # Concurrent first opens can briefly race journal_mode=WAL,
                # before BEGIN IMMEDIATE's normal busy timeout applies.
                if str(error) not in {"database is locked", "database is busy"} or time.monotonic() >= deadline:
                    raise RunError(RunErrorCode.STORAGE_ERROR) from None
                time.sleep(.025)
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
                with self._payload_context(connection):
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
                    with self._payload_context(connection):
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
                    connection.execute("UPDATE execution_payload_metadata SET read_ceiling = MAX(read_ceiling, ?) WHERE singleton = 1", (self.payload_limits.max_json_bytes,))
                    with self._payload_context(connection):
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

    @contextmanager
    def _payload_context(self, connection: sqlite3.Connection):
        row = connection.execute("SELECT read_ceiling FROM execution_payload_metadata WHERE singleton = 1").fetchone()
        ceiling = max(row[0], self.payload_limits.max_json_bytes)
        with use_payload_limits(self.payload_limits), use_payload_read_limits(ExecutionPayloadLimits(ceiling)):
            yield
