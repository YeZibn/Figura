from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from chartagent.evaluation.gateway import DiagnosticGatewayError, GatewayDiagnosticClient
from chartagent.evaluation.manifest import DiagnosticManifestError, load_manifest
from chartagent.evaluation.report import build_report
from chartagent.evaluation.timeline import build_timeline
from chartagent.decision_timeline import enrich_event_payload


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "real_chart_diagnostic_manifest.json"


def _event(sequence: int, kind: str, payload: dict | None = None) -> dict:
    event_payload = dict(payload or {})
    unit_type, phase, actor, role = "observation", "action", "tool", "action"
    strict_kinds = {
        "chart_staged", "chart_verification_result", "chart_promotion_result",
        "tool_call", "tool_result", "tool_skipped", "visual_observation", "assembly_validation_failure",
    }
    if kind in strict_kinds:
        tool_name = event_payload.get("tool_name")
        if kind == "chart_verification_result":
            unit_type, phase, actor, role = "verification", "verify", "system", "verification"
        elif kind == "chart_promotion_result":
            unit_type, phase, actor, role = "artifact", "publish", "system", "artifact"
        elif kind == "chart_staged":
            unit_type, phase, actor, role = "generation", "render", "tool", "action"
            event_payload.setdefault("call_id", f"call_{sequence}")
        elif kind == "assembly_validation_failure":
            unit_type, phase, actor, role = "generation", "assemble", "agent", "decision"
        elif kind == "visual_observation":
            unit_type, phase, role = "observation", "observe", "observation"
        else:
            unit_type = "measurement" if tool_name in {
                "extract_text", "measure_bars", "extract_line_series", "extract_pie_slices", "extract_scatter_points",
            } else "generation" if tool_name in {"assemble_spec", "render_chart"} else "observation"
            event_payload.setdefault("call_id", f"call_{sequence}")
        state_field = "status" if kind == "tool_result" else "state"
        event_payload.setdefault("unit_type", unit_type)
        event_payload.setdefault("phase", phase)
        event_payload.setdefault("actor", actor)
        event_payload.setdefault("role", role)
        event_payload.setdefault("transition_id", f"{kind}:{sequence}")
        unit_identity = event_payload.get("call_id") or f"event_{sequence}"
        event_payload.setdefault("unit_id", f"{unit_type}:{unit_identity}")
        default_state = "success" if kind == "tool_result" else "failed" if kind == "assembly_validation_failure" else "pass" if kind == "chart_verification_result" else "published" if kind == "chart_promotion_result" else "staged" if kind == "chart_staged" else "completed"
        event_payload.setdefault(state_field, default_state)
        event_payload = enrich_event_payload(kind, event_payload, run_id="run_eval", sequence=sequence)
    return {"runId": "run_eval", "sequence": sequence, "kind": kind, "payload": event_payload}


def _tool_result(sequence: int, tool_name: str, *, status: str = "success", **payload: object) -> dict:
    return _event(
        sequence,
        "tool_result",
        {"tool_name": tool_name, "status": status, **payload},
    )


def _history(events: list[dict], *, status: str = "completed", provider: str = "qwen") -> dict:
    return {
        "run": {
            "runId": "run_eval",
            "sessionId": "session_eval",
            "status": status,
            "provider": provider,
            "model": "qwen-test",
            "eventCount": len(events),
        },
        "events": events,
        "historyGap": False,
    }


def test_real_diagnostic_manifest_validates_relative_assets_and_fingerprints():
    manifest = load_manifest(MANIFEST, asset_root=ROOT)

    assert [sample.case_id for sample in manifest.samples] == [
        "dashboard_text_two_bars_pie",
        "shareholders_and_adjusted_price",
    ]
    assert manifest.samples[0].expected_panel_count == 4
    assert manifest.samples[0].asset_path == ROOT / "photo" / "dashboard_text_two_bars_pie.png"
    assert all(not Path(sample.asset).is_absolute() for sample in manifest.samples)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("asset", "/private/chart.png", "绝对路径"),
        ("sha256", "0" * 64, "指纹不匹配"),
    ],
)
def test_real_diagnostic_manifest_rejects_invalid_asset_identity(tmp_path, field, value, message):
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["samples"][0][field] = value
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(DiagnosticManifestError, match=message):
        load_manifest(path, asset_root=ROOT)


def test_real_diagnostic_manifest_rejects_sensitive_fields(tmp_path):
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["api_key"] = "do-not-keep"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(DiagnosticManifestError, match="敏感字段"):
        load_manifest(path, asset_root=ROOT)


def test_timeline_projects_complete_multi_panel_chain_without_false_repeated_split():
    manifest = load_manifest(MANIFEST, asset_root=ROOT)
    events = [
        _event(1, "run_started"),
        _tool_result(
            2,
            "decompose_chart_image",
            result={
                "data": {
                    "reuse": False,
                    "panels": [{"id": f"panel_{index}"} for index in range(1, 5)],
                }
            },
        ),
        *[
            _tool_result(2 + index, "measure_bars", panel_id=f"panel_{index}")
            for index in range(1, 5)
        ],
        _tool_result(
            7,
            "assemble_spec",
            result={"data": {"panel_ids": [f"panel_{index}" for index in range(1, 5)]}},
        ),
        _tool_result(8, "render_chart", result={"status": "available"}),
        _event(9, "chart_staged", {"staged_ref": "stg_preview_12345678", "call_id": "call_render"}),
        _event(10, "chart_verification_result", {"staged_ref": "stg_preview_12345678", "verification_ref": "ver_result_12345678", "verification": {"status": "pass"}}),
        _event(11, "chart_promotion_result", {"staged_ref": "stg_preview_12345678", "verification_ref": "ver_result_12345678", "artifact_id": "artifact_12345678"}),
        _event(12, "final_answer", {"answer": "完成"}),
    ]

    timeline = build_timeline(_history(events), sample=manifest.samples[0])
    stages = {stage.name: stage for stage in timeline.stages}

    assert stages["input"].status == "completed"
    assert stages["decomposition"].status == "completed"
    assert stages["panel_handoff"].status == "completed"
    assert stages["measurement"].status == "completed"
    assert stages["verification"].status == "completed"
    assert stages["assembly"].status == "completed"
    assert stages["render"].status == "completed"
    assert timeline.first_failure is None
    assert timeline.anomalies == []
    assert timeline.final_references["artifact_ids"] == ["artifact_12345678"]


def test_timeline_distinguishes_reused_split_and_unscoped_measurement():
    manifest = load_manifest(MANIFEST, asset_root=ROOT)
    events = [
        _event(1, "run_started"),
        _tool_result(
            2,
            "decompose_chart_image",
            result={"data": {"reuse": False, "panels": [{"id": "panel_1"}, {"id": "panel_2"}]}} ,
        ),
        _tool_result(
            3,
            "decompose_chart_image",
            result={"data": {"reuse": True, "panels": [{"id": "panel_1"}, {"id": "panel_2"}]}} ,
        ),
        _tool_result(4, "measure_bars", result={"data": {"scope": {"mode": "unscoped"}}}),
        _event(5, "run_interrupted", {"code": "user_cancelled"}),
    ]

    timeline = build_timeline(
        _history(events, status="interrupted"),
        sample=replace(manifest.samples[1], expected_panel_count=2),
    )
    codes = {item["code"] for item in timeline.anomalies}

    assert "repeated_decomposition" not in codes
    assert "unscoped_measurement" in codes
    assert timeline.first_failure["category"] == "panel_routing"
    assert timeline.first_failure["stage"] == "measurement"


def test_timeline_flags_repeated_split_and_failed_verification():
    manifest = load_manifest(MANIFEST, asset_root=ROOT)
    events = [
        _event(1, "run_started"),
        _tool_result(2, "decompose_chart_image", result={"data": {"panels": [{"id": "panel_1"}]}}),
        _tool_result(3, "decompose_chart_image", result={"data": {"panels": [{"id": "panel_1"}]}}),
        _event(4, "chart_verification_result", {"staged_ref": "stg_preview_12345678", "verification_ref": "ver_failed_12345678", "state": "fail", "verification": {"status": "fail", "issues": [{"code": "missing_series"}]}}),
    ]

    timeline = build_timeline(
        _history(events),
        sample=replace(manifest.samples[1], expected_panel_count=2),
    )
    codes = {item["code"] for item in timeline.anomalies}

    assert "repeated_decomposition" in codes
    stages = {stage.name: stage for stage in timeline.stages}
    assert stages["verification"].status == "failed"
    assert timeline.first_failure["category"] == "decomposition"


@pytest.mark.parametrize(
    ("mutations", "expected"),
    [
        ({"correlation_version": 1}, "unsupported_version"),
        ({"state": "completed"}, "malformed"),
    ],
)
def test_timeline_does_not_infer_status_from_unsupported_or_malformed_history(mutations, expected):
    event = _tool_result(2, "measure_bars")
    event["payload"].update(mutations)

    timeline = build_timeline(_history([event]))

    assert timeline.protocol_status == expected
    assert timeline.stages == ()
    assert timeline.anomalies == []
    assert timeline.first_failure is None


def test_timeline_uses_only_canonical_outer_status_for_diagnostics():
    event = _tool_result(
        2,
        "measure_bars",
        result={"status": "failed", "tool_status": "error", "data": {"measurement": {"status": "partial"}}},
    )
    timeline = build_timeline(_history([event]))
    stages = {stage.name: stage for stage in timeline.stages}

    assert stages["measurement"].status == "completed"
    assert stages["measurement"].failure_sequences == []


def test_timeline_flags_assembly_omission_after_successful_measurements():
    manifest = load_manifest(MANIFEST, asset_root=ROOT)
    events = [
        _event(1, "run_started"),
        _tool_result(
            2,
            "decompose_chart_image",
            result={"data": {"panels": [{"id": "panel_1"}, {"id": "panel_2"}]}},
        ),
        _tool_result(3, "measure_bars", panel_id="panel_1"),
        _tool_result(4, "measure_bars", panel_id="panel_2"),
        _tool_result(5, "assemble_spec", result={"data": {"panel_ids": ["panel_1"]}}),
        _tool_result(6, "render_chart", result={"status": "available"}),
        _event(7, "chart_promotion_result", {"artifact_id": "artifact_12345678", "staged_ref": "stg_preview_12345678", "verification_ref": "ver_result_12345678"}),
    ]

    timeline = build_timeline(
        _history(events),
        sample=replace(manifest.samples[1], expected_panel_count=2),
    )

    omission = next(item for item in timeline.anomalies if item["code"] == "assembly_missing_panels")
    assert omission["missing_panel_ids"] == ["panel_2"]
    assert timeline.first_failure["category"] == "assembly_render"


def test_timeline_preserves_insufficient_history_as_transport_failure():
    history = _history(
        [_event(1, "run_started"), _event(2, "run_interrupted", {"code": "gateway_restarted"})],
        status="interrupted",
    )
    history["historyGap"] = True

    timeline = build_timeline(history)

    assert timeline.history_gap is True
    assert timeline.first_failure["category"] == "transport_runtime"
    assert timeline.first_failure["code"] == "history_gap"
    stages = {stage.name: stage for stage in timeline.stages}
    assert stages["decomposition"].status == "not_reached"
    assert stages["render"].status == "not_reached"


def test_timeline_attributes_provider_failure_to_model_before_assembly_or_render():
    manifest = load_manifest(MANIFEST, asset_root=ROOT)
    events = [
        _event(1, "run_started"),
        _tool_result(
            2,
            "decompose_chart_image",
            result={"data": {"panels": [{"id": "panel_1"}]}},
        ),
        _tool_result(3, "measure_bars", panel_id="panel_1"),
        _event(4, "model_started", {"provider": "deepseek", "model": "deepseek-flash"}),
        _event(
            5,
            "model_completed",
            {
                "provider": "deepseek",
                "model": "deepseek-flash",
                "status": "error",
                "error_code": "provider_request_failed",
                "error_type": "BadRequestError",
                "provider_status": 400,
                "provider_error_code": "invalid_request_error",
                "provider_error_message": "tool message order is invalid",
            },
        ),
        _event(6, "run_failed", {"error_code": "agent_call_failed"}),
    ]

    timeline = build_timeline(
        _history(events, status="failed"),
        sample=replace(manifest.samples[0], expected_panel_count=1),
    )
    stages = {stage.name: stage for stage in timeline.stages}

    assert stages["model"].status == "failed"
    assert stages["verification"].status == "not_reached"
    assert stages["assembly"].status == "not_reached"
    assert stages["render"].status == "not_reached"
    assert timeline.first_failure["category"] == "transport_runtime"
    assert timeline.first_failure["stage"] == "model"
    assert timeline.first_failure["sequence"] == 5


def test_timeline_treats_partial_measurement_as_diagnostic_without_repair_stage():
    events = [
        _event(1, "run_started"),
        _tool_result(
            2,
            "measure_bars",
            result={
                "data": {
                    "measurement": {
                        "status": "partial",
                        "quality": {"issues": [{"code": "baseline_uncertain", "severity": "blocking"}]},
                    }
                }
            },
        ),
    ]

    timeline = build_timeline(_history(events), sample=None)
    stages = {stage.name: stage for stage in timeline.stages}

    assert stages["measurement"].status == "completed"
    assert "repair" not in stages
    assert timeline.first_failure is None


def test_report_is_bounded_and_does_not_reemit_raw_event_secrets_or_paths():
    manifest = load_manifest(MANIFEST, asset_root=ROOT)
    history = _history(
        [
            _event(1, "run_started", {"api_key": "secret-value", "path": "/Users/yezibin/private/chart.png"}),
            _event(2, "run_failed", {"error": "failed at /Users/yezibin/private/chart.png"}),
        ],
        status="failed",
    )
    report = build_report(history, manifest.samples[1], requested_provider="qwen")
    encoded = report.to_json()
    markdown = report.to_markdown()

    assert "secret-value" not in encoded
    assert "/Users/yezibin" not in encoded
    assert "/Users/yezibin" not in markdown
    assert "shareholders_and_adjusted_price" in encoded
    assert "第一个可确认失败" in markdown


def test_gateway_diagnostic_client_requires_provider_and_never_switches_it(monkeypatch):
    client = GatewayDiagnosticClient("http://127.0.0.1:8765/api/v1")
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider 校验失败前不应发请求")

    monkeypatch.setattr(client, "create_session", fail_if_called)
    sample = load_manifest(MANIFEST, asset_root=ROOT).samples[0]
    with pytest.raises(DiagnosticGatewayError, match="显式指定 provider"):
        client.run_sample(sample, provider="  ")
    assert called is False

    monkeypatch.setattr(
        client,
        "_request_json",
        lambda *args, **kwargs: {"run": {"runId": "run_1", "provider": "qwen"}},
    )
    with pytest.raises(DiagnosticGatewayError, match="非请求 provider"):
        client.start_run("session_1", attachment_id="attachment_1", provider="deepseek")


def test_gateway_diagnostic_client_uses_gateway_attachment_id_field(monkeypatch):
    client = GatewayDiagnosticClient("http://127.0.0.1:8765/api/v1")
    monkeypatch.setattr(
        client,
        "_request_json",
        lambda *args, **kwargs: {"attachment": {"attachment_id": "att_eval"}},
    )
    sample = load_manifest(MANIFEST, asset_root=ROOT).samples[0]

    assert client.upload_attachment("session_1", sample) == "att_eval"


def test_gateway_diagnostic_client_waits_on_history_without_fallback(monkeypatch):
    client = GatewayDiagnosticClient(
        "http://127.0.0.1:8765/api/v1",
        poll_interval=0.1,
    )
    histories = iter(
        [
            _history([], status="running", provider="deepseek"),
            _history([_event(1, "run_started")], status="completed", provider="deepseek"),
        ]
    )
    monkeypatch.setattr(client, "get_run_history", lambda *args, **kwargs: next(histories))

    run = client.wait_for_run(
        "session_1",
        {"runId": "run_eval", "provider": "deepseek"},
        timeout=1,
    )

    assert run.status == "completed"
    assert run.requested_provider == "deepseek"
    assert run.timed_out is False
