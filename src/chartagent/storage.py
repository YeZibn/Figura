"""Canonical paths for Figura's durable local application data."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DATA_DIR_ENV = "CHARTAGENT_DATA_DIR"
ATTACHMENT_DIR_ENV = "CHARTAGENT_ATTACHMENT_DIR"
PROJECT_ROOT_ENV = "CHARTAGENT_PROJECT_ROOT"
DEFAULT_DATA_DIR_NAME = ".chartagent"
LEGACY_DATA_DIR_NAME = ".chartagent"


class StorageRootConflict(ValueError):
    """Raised when legacy and project-local durable data are ambiguous."""


@dataclass(frozen=True)
class StoragePaths:
    """Normalized durable paths selected for one application run."""

    root: Path
    database: Path
    attachments: Path
    run_artifacts: Path
    diagnostics: Path


def project_root() -> Path:
    """Return the repository root for the source-tree package."""

    return Path(__file__).resolve().parents[2]


def _configured_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_path(value: str | os.PathLike[str], *, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=False)


def _contains_durable_state(root: Path) -> bool:
    """Detect known durable entries without scanning arbitrary user files."""

    for name in ("sessions.db", "attachments", "run-artifacts", "diagnostics"):
        candidate = root / name
        if candidate.is_file():
            return True
        if candidate.is_dir():
            try:
                next(candidate.iterdir())
            except (OSError, StopIteration):
                continue
            return True
    return False


def _legacy_conflict(
    *,
    selected_root: Path,
    explicit_selection: bool,
    home_dir: Path,
) -> StorageRootConflict | None:
    if explicit_selection:
        return None
    legacy_root = (home_dir / LEGACY_DATA_DIR_NAME).resolve(strict=False)
    if legacy_root == selected_root or not _contains_durable_state(legacy_root):
        return None
    return StorageRootConflict(
        "Legacy ChartAgent data exists at "
        f"{legacy_root}; choose it explicitly with {DATA_DIR_ENV} or --data-dir "
        f"before using the project-local store at {selected_root}."
    )


def resolve_storage_paths(
    *,
    data_dir: str | os.PathLike[str] | None = None,
    database: str | os.PathLike[str] | None = None,
    attachment_root: str | os.PathLike[str] | None = None,
    artifact_root: str | os.PathLike[str] | None = None,
    diagnostics_root: str | os.PathLike[str] | None = None,
    project_root_path: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    home_dir: str | os.PathLike[str] | None = None,
    check_legacy: bool = True,
) -> StoragePaths:
    """Resolve all durable paths using one deterministic precedence rule.

    Explicit ``database`` remains a compatibility escape hatch. When it is
    the only storage override, its parent is used as the derived root so
    direct ``GatewayHistoryStore(database=...)`` callers do not split their
    artifacts and attachments into the old home directory.
    """

    environment = env if env is not None else os.environ
    package_project_root = project_root()
    configured_project_root = _configured_value(environment.get(PROJECT_ROOT_ENV))
    project_root_path = (
        Path(project_root_path).expanduser().resolve(strict=False)
        if project_root_path is not None
        else (
            _normalize_path(configured_project_root, base=package_project_root)
            if configured_project_root is not None
            else package_project_root
        )
    )
    configured_data_dir = _configured_value(environment.get(DATA_DIR_ENV))
    explicit_data_dir = _configured_value(data_dir)
    database_path = (
        _normalize_path(database, base=project_root_path)
        if database is not None
        else None
    )

    if explicit_data_dir is not None:
        root = _normalize_path(explicit_data_dir, base=project_root_path)
        explicit_selection = True
    elif configured_data_dir is not None:
        root = _normalize_path(configured_data_dir, base=project_root_path)
        explicit_selection = True
    elif database_path is not None:
        root = database_path.parent
        explicit_selection = True
    else:
        root = (project_root_path / DEFAULT_DATA_DIR_NAME).resolve(strict=False)
        explicit_selection = False

    if check_legacy and not explicit_selection:
        home = (
            Path(home_dir).expanduser().resolve(strict=False)
            if home_dir is not None
            else Path.home().resolve(strict=False)
        )
        conflict = _legacy_conflict(
            selected_root=root,
            explicit_selection=explicit_selection,
            home_dir=home,
        )
        if conflict is not None:
            raise conflict

    database_path = database_path or (root / "sessions.db")
    configured_attachment_root = _configured_value(environment.get(ATTACHMENT_DIR_ENV))
    attachments = (
        _normalize_path(attachment_root, base=project_root_path)
        if attachment_root is not None
        else (
            _normalize_path(configured_attachment_root, base=project_root_path)
            if configured_attachment_root is not None
            else root / "attachments"
        )
    )
    artifacts = (
        _normalize_path(artifact_root, base=project_root_path)
        if artifact_root is not None
        else root / "run-artifacts"
    )
    diagnostics = (
        _normalize_path(diagnostics_root, base=project_root_path)
        if diagnostics_root is not None
        else root / "diagnostics"
    )
    return StoragePaths(
        root=root,
        database=database_path,
        attachments=attachments,
        run_artifacts=artifacts,
        diagnostics=diagnostics,
    )


__all__ = [
    "ATTACHMENT_DIR_ENV",
    "DATA_DIR_ENV",
    "DEFAULT_DATA_DIR_NAME",
    "PROJECT_ROOT_ENV",
    "StoragePaths",
    "StorageRootConflict",
    "project_root",
    "resolve_storage_paths",
]
