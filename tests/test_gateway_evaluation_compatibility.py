from __future__ import annotations

import inspect
import json
from pathlib import Path

from chartagent.evaluation import EvaluationBundle as PublicEvaluationBundle
from chartagent.evaluation import build_timeline as PublicBuildTimeline
from chartagent.evaluation.bundle import EvaluationBundle
from chartagent.evaluation.manifest import load_manifest
from chartagent.evaluation.reader import EvaluationReader
from chartagent.evaluation.reader_projection import EvaluationReader as CanonicalEvaluationReader
from chartagent.evaluation.timeline import build_timeline
from chartagent.evaluation.timeline import DiagnosticTimeline, StageEvidence
from chartagent.evaluation.timeline_model import (
    DiagnosticTimeline as CanonicalDiagnosticTimeline,
    StageEvidence as CanonicalStageEvidence,
)
from chartagent.gateway import GatewayService as PublicGatewayService
from chartagent.gateway.evaluation_adapter import EvaluationReaderAdapter
from chartagent.gateway.history import GatewayHistoryStore
from chartagent.gateway.persistence import GatewayHistoryStore as CanonicalGatewayHistoryStore
from chartagent.gateway.persistence_connection import SQLiteGatewayDatabase
from chartagent.gateway.run_persistence import RunPersistenceMixin
from chartagent.gateway.run_lifecycle import HistoricalRun, ManagedRun
from chartagent.gateway.run_manager import RunManager as CanonicalRunManager
from chartagent.gateway.run_observations import ObservationStore as CanonicalObservationStore
from chartagent.gateway.runs import ObservationStore, RunManager
from chartagent.gateway.service_evaluation import EvaluationWorkbenchMixin
from chartagent.gateway.protocol import (
    ContinuationKind,
    RunAccepted,
    RunEvent,
    RunLineage,
    RunStatus,
)
from chartagent.gateway.runs import ObservationStore, RunManager
from chartagent.gateway.service import GatewayService


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "real_chart_diagnostic_manifest.json"


def test_gateway_public_facade_and_constructor_signatures_are_stable() -> None:
    assert PublicGatewayService is GatewayService
    assert GatewayHistoryStore is CanonicalGatewayHistoryStore
    assert RunPersistenceMixin in GatewayHistoryStore.__mro__
    assert "transaction" in dir(SQLiteGatewayDatabase)
    assert "..evaluation.reader" not in (ROOT / "src/chartagent/gateway/service.py").read_text(encoding="utf-8")
    assert EvaluationReaderAdapter.__module__ == "chartagent.gateway.evaluation_adapter"
    assert ObservationStore is CanonicalObservationStore
    assert RunManager is CanonicalRunManager
    assert ManagedRun.__module__ == "chartagent.gateway.run_lifecycle"
    assert HistoricalRun.__module__ == "chartagent.gateway.run_lifecycle"
    assert EvaluationWorkbenchMixin in GatewayService.__mro__
    assert set(inspect.signature(GatewayService).parameters) == {
        "data_dir",
        "database",
        "model",
        "memory_factory",
        "runtime_factory",
        "attachment_store",
        "attachment_root",
        "artifact_root",
        "run_manager",
        "history_store",
        "readiness_probe",
    }
    assert set(inspect.signature(GatewayHistoryStore).parameters) == {
        "database",
        "data_dir",
        "artifact_root",
        "max_events",
        "max_runs",
        "retention_seconds",
        "max_artifact_bytes",
        "max_artifacts",
    }
    assert set(inspect.signature(RunManager).parameters) == {
        "max_runs",
        "max_events",
        "retention_seconds",
        "observation_store",
        "history_store",
    }
    assert set(inspect.signature(ObservationStore).parameters) == {
        "max_bytes",
        "max_images",
        "retention_seconds",
    }


def test_gateway_protocol_json_shapes_round_trip_without_private_fields() -> None:
    lineage = RunLineage(
        parent_run_id="run_parent",
        root_run_id="run_root",
        continuation_kind=ContinuationKind.RETRY,
    )
    accepted = RunAccepted(
        run_id="run_child",
        session_id="session_1",
        status=RunStatus.RUNNING,
        provider="qwen",
        model="qwen-test",
        parent_run_id=lineage.parent_run_id,
        root_run_id=lineage.root_run_id,
        continuation_kind=lineage.continuation_kind,
    )
    event = RunEvent(
        "run_child",
        1,
        "tool_result",
        {"tool_name": "measure_bars", "result": {"bars": 2}},
    )

    accepted_payload = accepted.to_dict()
    event_payload = json.loads(event.to_json())

    assert json.loads(json.dumps(accepted_payload, ensure_ascii=False)) == accepted_payload
    assert json.loads(json.dumps(event_payload, ensure_ascii=False)) == event_payload
    assert event_payload == event.to_dict()
    assert "detail_payload" not in event_payload


def test_evaluation_public_facade_and_bundle_layout_are_stable(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST, asset_root=ROOT)
    sample = manifest.samples[0]
    bundle = EvaluationBundle.create(
        manifest=manifest,
        samples=[sample],
        provider="qwen",
        evaluation_root=tmp_path / "evaluation",
    )

    assert PublicEvaluationBundle is EvaluationBundle
    assert PublicBuildTimeline is build_timeline
    assert EvaluationReader is CanonicalEvaluationReader
    assert DiagnosticTimeline is CanonicalDiagnosticTimeline
    assert StageEvidence is CanonicalStageEvidence
    assert set(inspect.signature(EvaluationReader).parameters) == {"data_root"}
    assert bundle.root == tmp_path / "evaluation"
    assert {
        "evaluation.json",
        "manifest.json",
        "summary.json",
        "summary.md",
    }.issubset({path.name for path in bundle.root.iterdir() if path.is_file()})
    assert (bundle.root / "diagnostics").is_dir()
    assert (bundle.root / "attachments").is_dir()
    assert (bundle.root / "run-artifacts").is_dir()


def test_evaluation_timeline_projection_is_json_stable() -> None:
    timeline = build_timeline(
        {
            "events": [
                {
                    "sequence": 1,
                    "kind": "run_started",
                    "payload": {},
                }
            ],
            "historyGap": False,
        }
    )
    payload = timeline.to_dict()
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
    assert payload["stages"]
