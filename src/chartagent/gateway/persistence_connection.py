"""SQLite connection and transaction boundary for Gateway persistence."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..storage import resolve_storage_paths


class SQLiteGatewayDatabase:
    """Own connection setup without owning Gateway domain queries."""

    def __init__(
        self,
        database: str | Path | None,
        *,
        data_dir: str | Path | None = None,
        artifact_root: str | Path | None = None,
    ) -> None:
        paths = resolve_storage_paths(
            data_dir=data_dir,
            database=database,
            artifact_root=artifact_root,
        )
        self.database = paths.database
        self.artifact_root = paths.run_artifacts
        self.database.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured connection whose context commits or rolls back."""

        with self.connect() as connection:
            yield connection


__all__ = ["SQLiteGatewayDatabase"]
