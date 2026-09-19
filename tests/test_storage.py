from __future__ import annotations

from pathlib import Path

import pytest

from chartagent.storage import StorageRootConflict, resolve_storage_paths
from chartagent.gateway.service import GatewayService
from chartagent.memory.sqlite import default_database_path


def test_storage_defaults_to_project_local_layout(tmp_path):
    project = tmp_path / "project"
    paths = resolve_storage_paths(project_root_path=project, home_dir=tmp_path / "home", env={})

    assert paths.root == project / ".chartagent"
    assert paths.database == project / ".chartagent" / "sessions.db"
    assert paths.attachments == project / ".chartagent" / "attachments"
    assert paths.run_artifacts == project / ".chartagent" / "run-artifacts"
    assert paths.diagnostics == project / ".chartagent" / "diagnostics"


def test_default_database_path_uses_environment_root(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARTAGENT_DATA_DIR", str(tmp_path / "configured"))

    assert default_database_path() == tmp_path / "configured" / "sessions.db"


def test_gateway_service_derives_attachment_and_artifact_roots_together(tmp_path):
    root = tmp_path / "data"
    service = GatewayService(data_dir=root, readiness_probe=lambda: {"status": "ready"})

    try:
        assert service.database == root / "sessions.db"
        assert service._attachment_store.root == root / "attachments"
        assert service._history.artifact_root == root / "run-artifacts"
    finally:
        service.close()


def test_storage_precedence_prefers_explicit_root_and_normalizes_relative_paths(tmp_path):
    project = tmp_path / "project"
    env = {"CHARTAGENT_DATA_DIR": "from-env"}

    paths = resolve_storage_paths(
        data_dir="explicit",
        project_root_path=project,
        env=env,
        home_dir=tmp_path / "home",
    )

    assert paths.root == project / "explicit"
    assert paths.database == project / "explicit" / "sessions.db"


def test_storage_environment_relative_path_is_independent_of_current_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    paths = resolve_storage_paths(
        project_root_path=project,
        env={"CHARTAGENT_DATA_DIR": "configured"},
        home_dir=tmp_path / "home",
    )

    assert paths.root == project / "configured"


def test_project_root_environment_is_used_by_wrapped_launchers(tmp_path):
    project = tmp_path / "wrapped-project"

    paths = resolve_storage_paths(
        env={"CHARTAGENT_PROJECT_ROOT": str(project)},
        home_dir=tmp_path / "home",
    )

    assert paths.root == project / ".chartagent"


def test_explicit_database_uses_its_parent_for_derived_paths(tmp_path):
    database = tmp_path / "isolated" / "sessions.db"
    paths = resolve_storage_paths(
        database=database,
        env={},
        project_root_path=tmp_path / "project",
        home_dir=tmp_path / "home",
    )

    assert paths.root == database.parent
    assert paths.database == database
    assert paths.attachments == database.parent / "attachments"
    assert paths.run_artifacts == database.parent / "run-artifacts"


def test_attachment_environment_override_is_still_supported(tmp_path):
    project = tmp_path / "project"
    paths = resolve_storage_paths(
        project_root_path=project,
        env={"CHARTAGENT_ATTACHMENT_DIR": "custom-attachments"},
        home_dir=tmp_path / "home",
    )

    assert paths.attachments == project / "custom-attachments"
    assert paths.root == project / ".chartagent"


def test_legacy_home_data_requires_an_explicit_choice(tmp_path):
    project = tmp_path / "project"
    legacy = tmp_path / "home" / ".chartagent"
    legacy.mkdir(parents=True)
    (legacy / "sessions.db").write_bytes(b"legacy")

    with pytest.raises(StorageRootConflict, match="CHARTAGENT_DATA_DIR"):
        resolve_storage_paths(
            project_root_path=project,
            env={},
            home_dir=tmp_path / "home",
        )

    selected = resolve_storage_paths(
        data_dir="selected",
        project_root_path=project,
        env={},
        home_dir=tmp_path / "home",
    )
    assert selected.root == project / "selected"
