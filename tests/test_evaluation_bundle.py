from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chartagent.evaluation.bundle import EvaluationBundle, EvaluationBundleError
from chartagent.evaluation.manifest import load_manifest
from chartagent.evaluation.report import build_report, write_report


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "real_chart_diagnostic_manifest.json"


def _manifest():
    return load_manifest(MANIFEST, asset_root=ROOT)


def _history(sample_case: str, *, status: str = "completed") -> dict:
    return {
        "run": {
            "runId": f"run_{sample_case}",
            "sessionId": f"session_{sample_case}",
            "status": status,
            "provider": "qwen",
            "model": "qwen-test",
            "eventCount": 1,
        },
        "events": [{"runId": f"run_{sample_case}", "sequence": 1, "kind": "run_started", "payload": {}}],
        "historyGap": False,
    }


def test_evaluation_bundle_isolates_runs_and_writes_complete_layout(tmp_path):
    manifest = _manifest()
    first = EvaluationBundle.create(
        manifest=manifest,
        samples=[manifest.samples[0]],
        provider="qwen",
        data_dir=tmp_path / "data",
    )
    second = EvaluationBundle.create(
        manifest=manifest,
        samples=[manifest.samples[1]],
        provider="qwen",
        data_dir=tmp_path / "data",
    )

    assert first.root != second.root
    assert first.root.parent == tmp_path / "data" / "evaluations"
    assert {
        "evaluation.json",
        "manifest.json",
        "summary.json",
        "summary.md",
    }.issubset({path.name for path in first.root.iterdir() if path.is_file()})
    assert (first.root / "attachments").is_dir()
    assert (first.root / "run-artifacts").is_dir()
    assert (first.root / "diagnostics").is_dir()

    snapshot = json.loads((first.root / "manifest.json").read_text(encoding="utf-8"))
    assert snapshot["samples"][0]["case_id"] == manifest.samples[0].case_id
    assert str(ROOT) not in json.dumps(snapshot, ensure_ascii=False)


def test_evaluation_bundle_rejects_reusing_explicit_root(tmp_path):
    manifest = _manifest()
    explicit = tmp_path / "bundle"
    EvaluationBundle.create(
        manifest=manifest,
        samples=[manifest.samples[0]],
        provider="qwen",
        evaluation_root=explicit,
    )

    with pytest.raises(EvaluationBundleError, match="拒绝复用"):
        EvaluationBundle.create(
            manifest=manifest,
            samples=[manifest.samples[0]],
            provider="qwen",
            evaluation_root=explicit,
        )


def test_evaluation_bundle_records_reports_and_bounded_failure(tmp_path):
    manifest = _manifest()
    sample = manifest.samples[0]
    bundle = EvaluationBundle.create(
        manifest=manifest,
        samples=[sample],
        provider="qwen",
        evaluation_root=tmp_path / "bundle",
    )
    bundle.start_case(sample)
    history = _history(sample.case_id, status="failed")
    report = build_report(history, sample, requested_provider="qwen")
    paths = write_report(report, bundle.diagnostics_dir)
    run = SimpleNamespace(
        status="failed",
        session_id="session_eval",
        run_id="run_eval",
        model="qwen-test",
    )
    bundle.finish_case(sample, run=run, report=report.to_dict(), report_paths=paths)
    assert bundle.finalize() == "partial"

    index = json.loads(bundle.index_path.read_text(encoding="utf-8"))
    summary = json.loads(bundle.summary_json_path.read_text(encoding="utf-8"))
    case = index["cases"][sample.case_id]
    assert case["status"] == "failed"
    assert case["report"]["json"].startswith("diagnostics/")
    assert summary["status"] == "partial"
    assert summary["cases"][0]["run_id"] == "run_eval"


def test_evaluation_bundle_marks_all_unsubmitted_cases_blocked(tmp_path):
    manifest = _manifest()
    bundle = EvaluationBundle.create(
        manifest=manifest,
        samples=[manifest.samples[0]],
        provider="unsupported",
        evaluation_root=tmp_path / "bundle",
    )
    sample = manifest.samples[0]
    bundle.start_case(sample)
    bundle.record_case_error(
        sample,
        code="provider_unavailable",
        message="QWEN_API_KEY=secret-value is unavailable at /Users/private/chart.png",
    )

    assert bundle.finalize() == "blocked"
    summary = (bundle.root / "summary.json").read_text(encoding="utf-8")
    assert "secret-value" not in summary
    assert "/Users/private" not in summary
