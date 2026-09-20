from __future__ import annotations

import json
from pathlib import Path

import pytest

from chartagent.evaluation.gateway import DiagnosticGatewayError, DiagnosticRun
from chartagent.evaluation import __main__ as evaluation_main


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "real_chart_diagnostic_manifest.json"


def _history(case_id: str) -> dict:
    return {
        "run": {
            "runId": f"run_{case_id}",
            "sessionId": f"session_{case_id}",
            "status": "completed",
            "provider": "qwen",
            "model": "qwen-test",
            "eventCount": 1,
        },
        "events": [{"runId": f"run_{case_id}", "sequence": 1, "kind": "run_started", "payload": {}}],
        "historyGap": False,
    }


class FakeManagedGateway:
    def __init__(self, data_dir, **kwargs):
        self.root = Path(data_dir)
        self.process = None
        self.closed = False

    def start(self):
        (self.root / "sessions.db").write_bytes(b"fake-db")
        return "http://127.0.0.1:8765/api/v1"

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, base_url, **kwargs):
        self.base_url = base_url

    def run_sample(self, sample, *, provider, session_name, timeout):
        if sample.case_id == "shareholders_and_adjusted_price":
            raise DiagnosticGatewayError("provider_unavailable", "provider unavailable")
        return DiagnosticRun(
            session_id=f"session_{sample.case_id}",
            run_id=f"run_{sample.case_id}",
            requested_provider=provider,
            provider=provider,
            model="qwen-test",
            status="completed",
            history=_history(sample.case_id),
        )


@pytest.fixture
def fake_runtime(monkeypatch):
    monkeypatch.setattr(evaluation_main, "load_environment", lambda: None)
    monkeypatch.delenv("CHARTAGENT_GATEWAY_URL", raising=False)
    monkeypatch.setattr(evaluation_main, "ManagedGateway", FakeManagedGateway)
    monkeypatch.setattr(evaluation_main, "GatewayDiagnosticClient", FakeClient)


def test_managed_cli_persists_batch_and_partial_case_results(tmp_path, fake_runtime):
    bundle_root = tmp_path / "bundle"
    result = evaluation_main.main(
        [
            "--manifest",
            str(MANIFEST),
            "--asset-root",
            str(ROOT),
            "--execute",
            "--provider",
            "qwen",
            "--evaluation-root",
            str(bundle_root),
        ]
    )

    assert result == 1
    index = json.loads((bundle_root / "evaluation.json").read_text(encoding="utf-8"))
    assert index["status"] == "partial"
    assert index["cases"]["dashboard_text_two_bars_pie"]["status"] == "completed"
    assert index["cases"]["shareholders_and_adjusted_price"]["status"] == "blocked"
    assert (bundle_root / "diagnostics" / "dashboard_text_two_bars_pie.json").is_file()
    assert (bundle_root / "summary.json").is_file()
    assert (bundle_root / "sessions.db").is_file()


def test_external_cli_keeps_legacy_report_only_mode(tmp_path, fake_runtime):
    output_dir = tmp_path / "diagnostics"
    result = evaluation_main.main(
        [
            "--manifest",
            str(MANIFEST),
            "--asset-root",
            str(ROOT),
            "--case-id",
            "dashboard_text_two_bars_pie",
            "--execute",
            "--provider",
            "qwen",
            "--base-url",
            "http://127.0.0.1:8765/api/v1",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert result == 0
    assert (output_dir / "dashboard_text_two_bars_pie.json").is_file()
    assert not (output_dir / "evaluation.json").exists()


def test_cli_requires_provider_before_creating_bundle(tmp_path, fake_runtime):
    result = evaluation_main.main(
        [
            "--manifest",
            str(MANIFEST),
            "--asset-root",
            str(ROOT),
            "--execute",
            "--evaluation-root",
            str(tmp_path / "bundle"),
        ]
    )

    assert result == 2
    assert not (tmp_path / "bundle").exists()
