from __future__ import annotations

import hashlib
import http.client
import io
import json
import sqlite3
import threading
from pathlib import Path
from urllib.parse import quote

from PIL import Image
import pytest

from chartagent.evaluation.reader import EvaluationReader, EvaluationReaderError, MAX_RESOURCE_BYTES
from chartagent.gateway.history import GatewayHistoryStore
from chartagent.gateway.protocol import RunEvent, RunStatus
from chartagent.gateway.server import GatewayHTTPServer
from chartagent.gateway.service import GatewayService


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (4, 3), (35, 140, 131)).save(output, format="PNG")
    return output.getvalue()


def _write_bundle(data_root: Path, *, evaluation_id: str = "eval_20260920T000000Z_fixture", status: str = "partial") -> Path:
    root = data_root / "evaluations" / evaluation_id
    (root / "diagnostics").mkdir(parents=True)
    (root / "report-assets").mkdir()
    asset = data_root / "source.png"
    asset.write_bytes(_png_bytes())
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    case_id = "bar_line_dashboard"
    index = {
        "schema_version": 1,
        "evaluation_id": evaluation_id,
        "status": status,
        "started_at": "2026-09-20T00:00:00Z",
        "ended_at": None if status == "running" else "2026-09-20T00:01:00Z",
        "provider": "deepseek",
        "model": "deepseek-flash",
        "cases": {
            case_id: {
                "case_id": case_id,
                "asset": "source.png",
                "sha256": digest,
                "status": "failed" if status != "running" else "running",
                "session_id": "session_fixture",
                "run_id": "run_fixture",
                "report": {"json": "diagnostics/bar_line_dashboard.json", "markdown": "diagnostics/bar_line_dashboard.md"},
                "first_failure": {"code": "run_failed", "category": "transport_runtime", "stage": "render", "sequence": 4, "message": "失败原因"},
                "error": None,
            },
        },
    }
    (root / "evaluation.json").write_text(json.dumps(index), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "samples": [{
            "case_id": case_id,
            "asset": "source.png",
            "sha256": digest,
            "expected_panels": {"count": 2, "items": [{"name": "柱状图", "chart_type": "bar"}, {"name": "折线图", "chart_type": "line"}]},
        }],
    }), encoding="utf-8")
    (root / "summary.json").write_text("{}", encoding="utf-8")
    (root / "summary.md").write_text("# summary\n", encoding="utf-8")
    (root / "diagnostics/bar_line_dashboard.json").write_text(json.dumps({
        "timeline": {
            "stages": [{"name": "decomposition", "status": "completed", "sequences": [2], "panel_ids": ["panel_1"]}],
            "anomalies": [],
            "history_gap": False,
            "first_failure": index["cases"][case_id]["first_failure"],
        },
    }), encoding="utf-8")
    (root / "diagnostics/bar_line_dashboard.md").write_text("# 诊断报告\n\n失败原因。\n", encoding="utf-8")
    (root / "report.md").write_text("# 评测报告\n\n报告正文。\n", encoding="utf-8")
    (root / "report-assets/input.png").write_bytes(_png_bytes())
    return root


def _write_history(root: Path, *, include_records: bool = True, large_result: bool = False) -> None:
    database = root / "sessions.db"
    store = GatewayHistoryStore(database, artifact_root=root / "run-artifacts")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO sessions(id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("session_fixture", "评测会话", "2026-09-20T00:00:00Z", "2026-09-20T00:01:00Z"),
        )
    store.create_run("run_fixture", "session_fixture", provider="deepseek", model="deepseek-flash")
    store.append_event(RunEvent(
        "run_fixture", 1, "run_started", {"provider": "deepseek", "model": "deepseek-flash", "authorization": "secret"}, "2026-09-20T00:00:01Z"
    ))
    store.append_event(RunEvent(
        "run_fixture", 2, "tool_call", {"tool_name": "measure_bars", "call_id": "call_1", "arguments": {"path": "/Users/private/chart.png"}}, "2026-09-20T00:00:02Z"
    ))
    store.append_event(RunEvent(
        "run_fixture", 3, "tool_result", {"tool_name": "measure_bars", "call_id": "call_1", "status": "success", "result": {"data": {"bars": 2, "api_key": "secret"}, "warnings": []}}, "2026-09-20T00:00:03Z"
    ))
    if large_result:
        store.append_event(RunEvent(
            "run_fixture",
            4,
            "tool_result",
            {
                "tool_name": "measure_bars",
                "call_id": "call_large",
                "status": "success",
                "result": {"data": {"points": [{"bbox_px": [1, 2, 3, 4], "note": "safe measurement detail " + ("x" * 180)} for _ in range(100)]}},
            },
            "2026-09-20T00:00:04Z",
        ))
    store.update_run("run_fixture", RunStatus.FAILED, terminal_code="agent_failed", terminal_message="Agent run failed")
    store.close()
    if include_records:
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, sequence INTEGER NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            records = [
                ("user", {"message": {"role": "user", "content": "请分析这张图"}}, "2026-09-20T00:00:00Z"),
                ("assistant", {"message": {"role": "assistant", "content": "我会先读取图表并测量。", "reasoning_content": "private reasoning"}}, "2026-09-20T00:00:01Z"),
                ("tool", {"message": {"role": "tool", "tool_call_id": "call_1", "content": json.dumps({"bars": 2, "authorization": "secret", "path": "/Users/private/chart.png"})}, "tool_name": "measure_bars", "status": "success"}, "2026-09-20T00:00:03Z"),
                ("tool", {"message": {"role": "tool", "name": "measure_bars", "content": "测量结果"}, "tool_name": "measure_bars", "status": "success"}, "2026-09-20T00:00:04Z"),
            ]
            connection.executemany(
                "INSERT INTO records(run_id, sequence, kind, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                [("run_fixture", sequence, kind, json.dumps(payload, ensure_ascii=False), created_at) for sequence, (kind, payload, created_at) in enumerate(records)],
            )


def test_reader_lists_valid_bundle_and_projects_complete_safe_history(tmp_path):
    root = _write_bundle(tmp_path)
    _write_history(root)
    reader = EvaluationReader(tmp_path)

    summaries = reader.list_summaries()
    assert summaries[0]["evaluationId"] == root.name
    assert summaries[0]["status"] == "partial"
    detail = reader.get_case(root.name, "bar_line_dashboard")["case"]
    assert detail["expectedPanels"][0]["chartType"] == "bar"
    assert detail["report"]["text"].startswith("# 评测报告")
    assert any(item["kind"] == "input" for item in detail["resources"])

    history = reader.get_history(root.name, "bar_line_dashboard")
    assert history["run"]["runId"] == "run_fixture"
    encoded = json.dumps(history, ensure_ascii=False)
    assert "authorization" not in encoded
    assert "/Users/private" not in encoded
    assert history["events"][1]["payload"]["arguments"]["path"] == "[已隐藏路径]"
    assert history["events"][2]["payload"]["result"]["data"]["bars"] == 2
    assert history["integrity"]["status"] == "redacted"


def test_reader_rejects_cross_case_and_sensitive_resources(tmp_path):
    root = _write_bundle(tmp_path)
    reader = EvaluationReader(tmp_path)
    resource = reader.get_case(root.name, "bar_line_dashboard")["case"]["resources"][0]
    content, media_type = reader.get_resource(root.name, resource["resourceId"], case_id="bar_line_dashboard")
    assert content == _png_bytes()
    assert media_type == "image/png"
    try:
        reader.get_resource(root.name, "../sessions.db")
    except Exception as exc:
        assert getattr(exc, "code", None) == "evaluation_resource_not_found"
    else:
        raise AssertionError("path traversal unexpectedly succeeded")


def test_reader_details_combine_visible_records_and_gateway_events_safely(tmp_path):
    root = _write_bundle(tmp_path)
    _write_history(root)
    details = EvaluationReader(tmp_path).get_history_details(root.name, "bar_line_dashboard")

    assert details["recordsAvailable"] is True
    assert details["eventsAvailable"] is True
    assert details["recordCount"] == 4
    assert details["eventCount"] == 3
    assert any(item["recordSequence"] == 0 and item["kind"] == "conversation" for item in details["entries"])
    tool_call = next(item for item in details["entries"] if item["kind"] == "tool_call")
    tool_result = next(item for item in details["entries"] if item["kind"] == "tool_result")
    assert tool_call["eventSequence"] == 2
    assert tool_call["arguments"]["path"] == "[已隐藏路径]"
    assert tool_result["result"]["data"]["bars"] == 2
    assert sum(item["kind"] == "tool_result" for item in details["entries"]) == 1
    assert not any(item["kind"] == "tool_message" and item.get("callId") == "call_1" for item in details["entries"])
    encoded = json.dumps(details, ensure_ascii=False)
    assert "authorization" not in encoded
    assert "reasoning_content" not in encoded
    assert "/Users/private" not in encoded
    assert details["redacted"] is True


def test_reader_details_falls_back_when_records_are_missing(tmp_path):
    root = _write_bundle(tmp_path)
    _write_history(root, include_records=False)
    details = EvaluationReader(tmp_path).get_history_details(root.name, "bar_line_dashboard")

    assert details["recordsAvailable"] is False
    assert details["sourceAvailability"] == {"records": False, "gatewayEvents": True}
    assert details["eventsAvailable"] is True
    assert any(item["kind"] == "tool_result" for item in details["entries"])
    assert "records 不可用" in details["notice"]


def test_reader_exposes_large_safe_event_result_as_scoped_resource(tmp_path):
    root = _write_bundle(tmp_path)
    _write_history(root, include_records=False, large_result=True)
    reader = EvaluationReader(tmp_path)

    history = reader.get_history(root.name, "bar_line_dashboard")
    large_event = next(event for event in history["events"] if event["sequence"] == 4)
    resource = large_event["payload"].get("detailResource")
    assert resource and resource["kind"] == "history_detail"
    assert len(resource["sha256"]) == 64
    assert history["integrity"]["detailResourceCount"] == 1

    content, media_type = reader.get_resource(root.name, resource["resourceId"], case_id="bar_line_dashboard")
    assert media_type == "application/json"
    payload = json.loads(content)
    assert payload["payload"]["result"]["data"]["points"][0]["bbox_px"] == [1, 2, 3, 4]
    assert "safe measurement detail" in json.dumps(payload, ensure_ascii=False)

    with pytest.raises(EvaluationReaderError) as error:
        reader.get_resource(root.name, resource["resourceId"], case_id="other_case")
    assert error.value.code == "evaluation_case_not_found"

    detail_file = next((root / "run-artifacts" / "history-details" / "run_fixture").glob("*.json"))
    detail_file.unlink()
    with pytest.raises(EvaluationReaderError) as error:
        reader.get_resource(root.name, resource["resourceId"], case_id="bar_line_dashboard")
    assert error.value.code == "evaluation_resource_not_found"

    detail_file.write_text("{", encoding="utf-8")
    with pytest.raises(EvaluationReaderError) as error:
        reader.get_resource(root.name, resource["resourceId"], case_id="bar_line_dashboard")
    assert error.value.code == "evaluation_resource_unavailable"


def test_reader_preserves_deep_chart_geometry_without_depth_only_truncation(tmp_path):
    reader = EvaluationReader(tmp_path)
    projected, truncated, redacted = reader._safe_projection({
        "result": {
            "data": {
                "panels": [{
                    "proposal": {
                        "bbox_px": [12, 24, 480, 320],
                        "polygon_px": [[12, 24], [480, 24], [480, 320], [12, 320]],
                    },
                    "axes": {"x": {"ticks": [0, 10, 20]}, "y": {"ticks": [0, 100]}},
                    "baseline": {"points_px": [[12, 320], [480, 320]]},
                    "bars": [{"measure": {"top_px": 100, "bottom_px": 320}}],
                    "series": [{"points_px": [[1, 2], [3, 4]]}],
                }],
            },
        },
    })
    assert truncated is False
    assert redacted is False
    panel = projected["result"]["data"]["panels"][0]
    assert panel["proposal"]["bbox_px"] == [12, 24, 480, 320]
    assert panel["proposal"]["polygon_px"][2] == [480, 320]
    assert panel["baseline"]["points_px"] == [[12, 320], [480, 320]]


def test_reader_marks_sensitive_and_legacy_truncation_boundaries(tmp_path):
    reader = EvaluationReader(tmp_path)
    projected, truncated, redacted = reader._safe_projection({
        "api_key": "secret",
        "image": "data:image/png;base64,AAAA",
        "nested": {"path": "/Users/private/chart.png"},
    })
    encoded = json.dumps(projected, ensure_ascii=False)
    assert "secret" not in encoded
    assert "/Users/private" not in encoded
    assert redacted is True
    assert truncated is False


def test_reader_reports_projection_limits_and_legacy_unrecoverable_results(tmp_path):
    reader = EvaluationReader(tmp_path)
    projected, truncated, _ = reader._safe_projection({
        "text": "x" * 20_000,
        "items": list(range(100)),
        "nested": {str(index): index for index in range(100)},
    })
    assert truncated is True
    assert len(projected["items"]) == 64
    assert len(projected["text"]) == 12_000

    root = _write_bundle(tmp_path / "legacy")
    _write_history(root, include_records=False)
    database = root / "sessions.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE gateway_run_events SET payload_json = ? WHERE run_id = ? AND sequence = ?",
            (json.dumps({"tool_name": "measure_bars", "call_id": "call_1", "result": {"truncated": True, "preview": "old"}}), "run_fixture", 3),
        )
    history = EvaluationReader(tmp_path / "legacy").get_history(root.name, "bar_line_dashboard")
    event = next(item for item in history["events"] if item["sequence"] == 3)
    assert event["payload"]["detailUnavailable"] is True
    assert history["integrity"]["status"] == "unavailable"


def test_reader_projects_current_bar_line_dashboard_bundle_when_present():
    data_root = Path(__file__).resolve().parents[1] / ".chartagent"
    evaluation_root = data_root / "evaluations" / "eval_20260920T024408Z_d4962355"
    if not evaluation_root.is_dir():
        pytest.skip("当前工作区没有保存的 bar_line_dashboard 评测 bundle")
    reader = EvaluationReader(data_root)
    detail = reader.get_evaluation(evaluation_root.name)
    case_id = detail["cases"][0]["caseId"]
    history_details = reader.get_history_details(evaluation_root.name, case_id)

    assert history_details["eventsAvailable"] is True
    assert history_details["eventCount"] > 0
    assert any(item["kind"] == "tool_call" for item in history_details["entries"])
    assert any(item["kind"] == "tool_result" for item in history_details["entries"])
    history = reader.get_history(evaluation_root.name, case_id)
    bar_data = next(
        event["payload"]["result"]["data"]
        for event in history["events"]
        if event["kind"] == "tool_result" and event["payload"].get("tool_name") == "measure_bars"
    )
    line_data = next(
        event["payload"]["result"]["data"]
        for event in history["events"]
        if event["kind"] == "tool_result" and event["payload"].get("tool_name") == "extract_line_series"
    )
    assert isinstance(bar_data.get("bars"), list)
    assert isinstance(bar_data.get("baseline"), dict)
    assert isinstance(line_data.get("series"), list)
    assert isinstance(line_data.get("axes"), dict)
    encoded = json.dumps(history_details, ensure_ascii=False)
    assert "/Users/yezibin" not in encoded
    with pytest.raises(Exception) as error:
        reader.get_history_details(evaluation_root.name, "unknown_case")
    assert getattr(error.value, "code", None) == "evaluation_case_not_found"


def test_reader_catalog_keeps_empty_and_valid_terminal_states_and_skips_corrupt(tmp_path):
    evaluations = tmp_path / "evaluations"
    evaluations.mkdir()
    _write_bundle(tmp_path, evaluation_id="eval_20260920T000001Z_running", status="running")
    _write_bundle(tmp_path, evaluation_id="eval_20260920T000002Z_completed", status="completed")
    _write_bundle(tmp_path, evaluation_id="eval_20260920T000003Z_blocked", status="blocked")
    _write_bundle(tmp_path, evaluation_id="eval_20260920T000005Z_partial", status="partial")
    corrupt = evaluations / "eval_20260920T000004Z_corrupt"
    corrupt.mkdir()
    (corrupt / "evaluation.json").write_text("not-json", encoding="utf-8")

    statuses = {item["status"] for item in EvaluationReader(tmp_path).list_summaries()}
    assert statuses == {"running", "completed", "blocked", "partial"}
    assert EvaluationReader(tmp_path / "empty").list_summaries() == []


def test_reader_does_not_register_wrong_media_oversized_or_sensitive_files(tmp_path):
    root = _write_bundle(tmp_path)
    (root / "report-assets" / "notes.txt").write_text("not an image", encoding="utf-8")
    (root / "report-assets" / "oversized.png").write_bytes(b"x" * (MAX_RESOURCE_BYTES + 1))
    (root / ".env").write_text("API_KEY=secret", encoding="utf-8")
    index_path = root / "evaluation.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["cases"]["bar_line_dashboard"]["report"]["markdown"] = ".env"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    reader = EvaluationReader(tmp_path)
    resources = reader.get_case(root.name, "bar_line_dashboard")["case"]["resources"]
    assert not any(item["label"] in {"notes", "oversized", "API_KEY=secret"} for item in resources)
    assert "API_KEY=secret" not in json.dumps(reader.get_case(root.name, "bar_line_dashboard"), ensure_ascii=False)

    index["cases"]["other_case"] = dict(index["cases"]["bar_line_dashboard"], case_id="other_case")
    index_path.write_text(json.dumps(index), encoding="utf-8")
    resource_id = resources[0]["resourceId"]
    with pytest.raises(Exception) as error:
        reader.get_resource(root.name, resource_id, case_id="other_case")
    assert getattr(error.value, "code", None) == "evaluation_resource_not_found"


def test_gateway_evaluation_routes_are_read_only_and_isolated(tmp_path):
    root = _write_bundle(tmp_path)
    _write_history(root)
    service = GatewayService(data_dir=tmp_path)
    server = GatewayHTTPServer(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    evaluation_id = "eval_20260920T000000Z_fixture"
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", "/api/v1/evaluations")
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        assert response.status == 200
        assert payload["evaluations"][0]["evaluationId"] == evaluation_id

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", f"/api/v1/evaluations/{quote(evaluation_id)}/cases/bar_line_dashboard")
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        assert response.status == 200
        assert payload["case"]["caseId"] == "bar_line_dashboard"

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", f"/api/v1/evaluations/{evaluation_id}/cases/unknown")
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        assert response.status == 404
        assert payload["error"]["code"] == "evaluation_case_not_found"

        reader_case = EvaluationReader(tmp_path).get_case(evaluation_id, "bar_line_dashboard")["case"]
        resource_id = reader_case["resources"][0]["resourceId"]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", f"/api/v1/evaluations/{evaluation_id}/cases/bar_line_dashboard/history")
        response = connection.getresponse()
        history = json.loads(response.read())
        connection.close()
        assert response.status == 200
        assert history["run"]["runId"] == "run_fixture"
        assert "authorization" not in json.dumps(history, ensure_ascii=False)

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", f"/api/v1/evaluations/{evaluation_id}/cases/bar_line_dashboard/history/details")
        response = connection.getresponse()
        history_details = json.loads(response.read())
        connection.close()
        assert response.status == 200
        assert history_details["recordsAvailable"] is True
        assert any(item["kind"] == "tool_result" for item in history_details["entries"])
        assert "authorization" not in json.dumps(history_details, ensure_ascii=False)

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", f"/api/v1/evaluations/{evaluation_id}/resources/{quote(resource_id, safe='')}?case_id=bar_line_dashboard")
        response = connection.getresponse()
        resource_body = response.read()
        resource_type = response.getheader("Content-Type")
        connection.close()
        assert response.status == 200
        assert resource_type == "image/png"
        assert resource_body == _png_bytes()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", f"/api/v1/evaluations/{evaluation_id}/resources/{quote('../sessions.db', safe='')}")
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        assert response.status == 404
        assert payload["error"]["code"] == "evaluation_resource_not_found"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
