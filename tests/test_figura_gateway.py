from __future__ import annotations

from tests.figura_sources_support import (
    make_attachment_service,
    make_execution_image_reader,
    make_panel_service,
)

import json
import hashlib
import sqlite3
import threading
from time import monotonic, sleep
from http.client import HTTPConnection
from io import BytesIO
from threading import Event

from PIL import Image

from figura.sources.models import PanelPoint
from figura.sources.chart_renders import FiguraChartRenderService
from figura.shared.json_schema import canonical_json_dumps
from figura.agent.execution_state import RunExecutionStateService
from figura.bootstrap import recover_running_runs
from figura.gateway.application import FiguraGatewayApplication
from figura.gateway.dispatcher import RunDispatcher
from figura.gateway.server import FiguraHTTPServer
from figura.gateway.session_deletion import FiguraSessionDeletion
from figura.providers import FinishReason, MODEL_IDS, ProviderFactory, ProviderId, ProviderResponse, ProviderToolCall
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.models import RunCreateRequest, RunStatus, TerminalCode
from figura.runtime.store import FiguraRunStore
from figura.runtime.run_lock import RunExecutionOwnership
from figura.runtime.tool_execution import DurableToolExecutor
from figura.sources.repository import SourcesRepository
from figura.tools import ReplayEffect, ToolExecutionResult, ToolOutcome, ToolRegistry
from figura.tools.contracts import ToolExecutionError
from figura.tools.implementations.assemble_chart_figure import assemble_chart_figure_definition
from figura.tools.implementations.image import image_tool_definitions
from figura.tools.implementations.render_chart_figure import render_chart_figure_definition


ORIGIN = "http://127.0.0.1:1421"


class PassiveExecutor:
    def __init__(self, started: Event | None = None, release: Event | None = None) -> None:
        self.started = started
        self.release = release
        self.calls: list[tuple[str, str]] = []

    def execute(self, session_id: str, run_id: str) -> None:
        self.calls.append((session_id, run_id))
        if self.started:
            self.started.set()
        if self.release:
            self.release.wait(timeout=2)


def _provider_factory(transport_calls: list[object] | None = None) -> ProviderFactory:
    values = {
        "FIGURA_QWEN_API_KEY": "qwen-secret",
        "FIGURA_QWEN_BASE_URL": "https://qwen.private.example/v1",
        "FIGURA_DEEPSEEK_API_KEY": "deepseek-secret",
        "FIGURA_MIMO_API_KEY": "mimo-secret",
    }

    def transport(profile):
        if transport_calls is not None:
            transport_calls.append(profile)
        return None

    return ProviderFactory.from_env(values, transport_factory=transport)


def _application(tmp_path, executor: PassiveExecutor | None = None):
    store = FiguraRunStore(tmp_path)
    attachments = make_attachment_service(store)
    providers = _provider_factory()
    coordinator = RunCoordinator(store, providers)
    panels = make_panel_service(store, attachments)
    chart_renders = FiguraChartRenderService(store.data_root)
    session_deletion = FiguraSessionDeletion(
        store,
        SourcesRepository(store.database),
        attachments,
        panels,
        chart_renders,
    )
    execution_state = RunExecutionStateService(coordinator, panels)
    selected_executor = executor or PassiveExecutor()
    dispatcher = RunDispatcher(selected_executor)  # type: ignore[arg-type]
    app = FiguraGatewayApplication(
        coordinator,
        attachments,
        panels,
        execution_state,
        make_execution_image_reader(attachments, panels, chart_renders),
        providers,
        dispatcher,
        session_deletion,
        allowed_origins=(ORIGIN,),
    )
    return app, store, coordinator, attachments, selected_executor


def _create_run(coordinator, session_id: str, *, key: str = "gateway-test", attachment_ids=()):
    return coordinator.create_run(
        RunCreateRequest(
            session_id=session_id,
            text="分析图表中的趋势。",
            attachment_ids=tuple(attachment_ids),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key=key,
        )
    )


def _finish_run(coordinator, session_id: str, run_id: str) -> None:
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "分析已完成。",
            (),
            FinishReason.STOP,
        ),
        provider_attempt_id=attempt.attempt_id,
    )
    finished = coordinator.read_run_state(session_id, run_id)
    coordinator.complete_run(session_id, run_id, finished.checkpoint.revision)


def _commit_tool_calls(coordinator, session_id: str, run_id: str, calls, *, registry_version="timeline-v1"):
    state = coordinator.read_run_state(session_id, run_id)
    provider_attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "处理图像。",
            tuple(calls),
            FinishReason.TOOL_CALLS,
        ),
        provider_attempt_id=provider_attempt.attempt_id,
        registry_version=registry_version,
    )


def _begin_tool_attempt(store, coordinator, session_id, run_id, call_id, *, registry_version="timeline-v1"):
    state = coordinator.read_run_state(session_id, run_id)
    call_fact = next(
        fact
        for fact in state.tool_facts
        if getattr(fact.payload, "call_id", None) == call_id
        and fact.fact_kind.value == "tool_call"
    )
    return store.begin_tool_attempt(
        session_id=session_id,
        run_id=run_id,
        expected_revision=state.checkpoint.revision,
        tool_call_sequence=call_fact.tool_sequence,
        registry_version=registry_version,
        replay_effect=ReplayEffect.REPLAY_SAFE,
    )


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(output, format="PNG")
    return output.getvalue()


def _commit_chart_render(app, store, session_id: str, run_id: str):
    registry = ToolRegistry(
        "figura-web-v9",
        (
            assemble_chart_figure_definition(app.execution_state.for_run),
            render_chart_figure_definition(
                app.execution_state.for_run,
                FiguraChartRenderService(store.data_root),
            ),
        ),
    )
    figure = {
        "schema_version": 2,
        "title": "Quarterly sales",
        "layout": {"columns": 1},
        "charts": [
            {
                "chart_id": "sales",
                "chart_spec": {
                    "schema_version": 2,
                    "metadata": {"chart_type": "pie", "title": "Share"},
                    "coordinate_system": {"kind": "none"},
                    "dataset": {"slices": [
                        {"id": "north", "label": "North", "value": 70},
                        {"id": "south", "label": "South", "value": 30},
                    ]},
                },
            }
        ],
    }
    state = app.coordinator.read_run_state(session_id, run_id)
    attempt = app.coordinator.begin_provider_attempt(session_id, run_id, state.checkpoint.revision)
    claimed = app.coordinator.read_run_state(session_id, run_id)
    calls = (
        ProviderToolCall(
            "gateway-figure",
            "assemble_chart_figure",
            json.dumps(figure, ensure_ascii=False, separators=(",", ":")),
        ),
        ProviderToolCall(
            "gateway-render",
            "render_chart_figure",
            json.dumps(
                {"figure_ref": {"run_id": run_id, "call_id": "gateway-figure"}},
                separators=(",", ":"),
            ),
        ),
    )
    app.coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        ProviderResponse(
            ProviderId.QWEN,
            MODEL_IDS[ProviderId.QWEN],
            "组合并绘制图表。",
            calls,
            FinishReason.TOOL_CALLS,
        ),
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry.version,
    )
    return DurableToolExecutor(store, registry).execute_pending(session_id, run_id)


def _json(response):
    return json.loads(response.body.decode("utf-8"))


def test_health_reports_configuration_without_calling_provider(tmp_path):
    calls: list[object] = []
    providers = _provider_factory(calls)
    app, _, _, _, _ = _application(tmp_path)
    app.providers = providers
    try:
        response = app.handle("GET", "/api/v1/health", {}, b"")
        payload = _json(response)
        assert response.status == 200
        assert [item["modelId"] for item in payload["providers"]] == [
            "qwen3.8-flash",
            "deepseek-flash",
            "mimo-v2.6-flash",
        ]
        assert "qwen-secret" not in response.body.decode()
        assert "qwen.private.example" not in response.body.decode()
        assert calls == []
    finally:
        app.close()


def test_session_projection_preserves_run_input_and_hides_internal_records(tmp_path):
    app, _, coordinator, _, _ = _application(tmp_path)
    try:
        session = coordinator.create_session("销售趋势")
        run = _create_run(coordinator, session.session_id)
        response = app.handle("GET", f"/api/v1/sessions/{session.session_id}", {}, b"")
        payload = _json(response)
        assert response.status == 200
        assert payload["session"]["runCount"] == 1
        assert payload["messages"] == [
            {
                "id": f"{run.run_id}:user",
                "runId": run.run_id,
                "kind": "user",
                "text": "分析图表中的趋势。",
                "timestamp": run.created_at,
            }
        ]
        assert payload["runs"][0]["executionState"] == "queued"
        assert not {"records", "events", "toolFacts", "providerContinuations"} & payload.keys()
        assert "qwen-secret" not in response.body.decode()
    finally:
        app.close()


def test_session_snapshot_queries_and_attachment_ownership(tmp_path):
    app, _, coordinator, attachments, _ = _application(tmp_path)
    try:
        first = coordinator.create_session("甲")
        second = coordinator.create_session("乙")
        image = attachments.upload(first.session_id, "chart.png", _png_bytes())
        run = _create_run(coordinator, first.session_id, attachment_ids=(image.attachment_id,))

        listed = _json(app.handle("GET", "/api/v1/sessions", {}, b""))["sessions"]
        first_summary = next(item for item in listed if item["id"] == first.session_id)
        assert first_summary["runCount"] == 1
        assert first_summary["updatedAt"] >= image.created_at

        content = app.handle(
            "GET",
            f"/api/v1/sessions/{first.session_id}/attachments/{image.attachment_id}/content",
            {},
        )
        assert content.status == 200
        assert content.body == _png_bytes()
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{second.session_id}/attachments/{image.attachment_id}/content",
            {},
        ).status == 404
        assert app.handle(
            "DELETE",
            f"/api/v1/sessions/{first.session_id}/attachments/{image.attachment_id}",
            {"origin": ORIGIN},
        ).status == 409

        upload_response = app.handle(
            "POST",
            f"/api/v1/sessions/{second.session_id}/attachments?filename=second.png",
            {"origin": ORIGIN, "content-type": "image/png"},
            _png_bytes(),
        )
        assert upload_response.status == 201
        uploaded_id = _json(upload_response)["attachment"]["id"]
        listed_attachments = app.handle(
            "GET", f"/api/v1/sessions/{second.session_id}/attachments", {}
        )
        assert [item["id"] for item in _json(listed_attachments)["attachments"]] == [uploaded_id]
        assert app.handle(
            "DELETE",
            f"/api/v1/sessions/{second.session_id}/attachments/{uploaded_id}",
            {"origin": ORIGIN},
        ).status == 204

        invalid = app.handle(
            "POST",
            f"/api/v1/sessions/{second.session_id}/attachments?filename=bad.png",
            {"origin": ORIGIN},
            b"not an image",
        )
        assert invalid.status == 400
        assert attachments.list(second.session_id) == ()
        assert coordinator.read_run_state(first.session_id, run.run_id).run.status is RunStatus.RUNNING
    finally:
        app.close()


def test_panel_routes_expose_only_committed_session_owned_pngs(tmp_path):
    app, store, coordinator, attachments, _ = _application(tmp_path)
    try:
        first = coordinator.create_session("甲")
        second = coordinator.create_session("乙")
        image = attachments.upload(first.session_id, "chart.png", _png_bytes())
        run = _create_run(coordinator, first.session_id, attachment_ids=(image.attachment_id,))
        uncommitted = app.panels.decompose(
            first.session_id,
            run.run_id,
            image.attachment_id,
            (("未提交", (PanelPoint(0, 0), PanelPoint(1000, 0), PanelPoint(0, 1000))),),
            "u" * 64,
        )[0]
        panel_list = app.handle("GET", f"/api/v1/sessions/{first.session_id}/panels", {})
        assert panel_list.status == 200
        assert _json(panel_list)["panels"] == []
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{first.session_id}/panels/{uncommitted.panel_id}/content",
            {},
        ).status == 404

        registry = ToolRegistry(
            "gateway-panel-v1",
            image_tool_definitions(
                app.execution_state.for_run,
                make_execution_image_reader(attachments, app.panels),
                app.panels,
            ),
        )
        state = coordinator.read_run_state(first.session_id, run.run_id)
        attempt = coordinator.begin_provider_attempt(first.session_id, run.run_id, state.checkpoint.revision)
        claimed = coordinator.read_run_state(first.session_id, run.run_id)
        call = ProviderToolCall(
            "decompose-web",
            "decompose_chart_image",
            json.dumps({
                "attachment_id": image.attachment_id,
                "panels": [{
                    "name": "独立图像",
                    "points": [{"x": 0, "y": 0}, {"x": 1000, "y": 0}, {"x": 1000, "y": 1000}, {"x": 0, "y": 1000}],
                }],
            }),
        )
        coordinator.commit_model_response(
            first.session_id,
            run.run_id,
            claimed.checkpoint.revision,
            ProviderResponse(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN], "正在分割。", (call,), FinishReason.TOOL_CALLS),
            provider_attempt_id=attempt.attempt_id,
            registry_version=registry.version,
        )
        DurableToolExecutor(store, registry).execute_pending(first.session_id, run.run_id)

        listed = app.handle("GET", f"/api/v1/sessions/{first.session_id}/panels", {})
        metadata = _json(listed)["panels"]
        assert [item["name"] for item in metadata] == ["独立图像"]
        assert set(metadata[0]) == {"panelId", "runId", "sourceAttachmentId", "name", "points"}
        panel_id = metadata[0]["panelId"]
        content = app.handle(
            "GET", f"/api/v1/sessions/{first.session_id}/panels/{panel_id}/content", {}
        )
        assert content.status == 200
        assert content.headers["Content-Type"] == "image/png"
        assert content.headers["Cache-Control"] == "no-store"
        assert Image.open(BytesIO(content.body)).format == "PNG"
        assert app.handle(
            "GET", f"/api/v1/sessions/{second.session_id}/panels/{panel_id}/content", {}
        ).status == 404
        assert _json(app.handle("GET", f"/api/v1/sessions/{second.session_id}/panels", {}))["panels"] == []

        (tmp_path / "panels" / f"{panel_id}.png").unlink()
        failed_content = app.handle(
            "GET", f"/api/v1/sessions/{first.session_id}/panels/{panel_id}/content", {}
        )
        assert failed_content.status == 500
        assert str(tmp_path) not in failed_content.body.decode()
    finally:
        app.close()


def test_chart_render_summaries_and_session_scoped_png_route(tmp_path):
    app, store, coordinator, _attachments, _ = _application(tmp_path)
    try:
        session = coordinator.create_session("图表预览")
        other_session = coordinator.create_session("另一个 Session")
        run = _create_run(coordinator, session.session_id, key="chart-render-gateway")
        _commit_chart_render(app, store, session.session_id, run.run_id)

        snapshot = _json(app.handle("GET", f"/api/v1/sessions/{session.session_id}", {}))
        history = _json(
            app.handle(
                "GET",
                f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/history",
                {},
            )
        )
        summary = snapshot["runs"][0]["chartRenders"][0]
        assert set(summary) == {
            "callId",
            "figureRef",
            "figureTitle",
            "figureDigest",
            "imageSha256",
            "mediaType",
            "byteCount",
            "width",
            "height",
        }
        assert summary["callId"] == "gateway-render"
        assert summary["figureRef"] == {"runId": run.run_id, "callId": "gateway-figure"}
        assert summary["figureTitle"] == "Quarterly sales"
        assert history["run"]["chartRenders"] == [summary]

        content_path = (
            f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/"
            "chart-renders/gateway-render/content"
        )
        content = app.handle("GET", content_path, {})
        assert content.status == 200
        assert content.headers["Content-Type"] == "image/png"
        assert content.headers["Cache-Control"] == "no-store"
        assert content.headers["X-Content-Type-Options"] == "nosniff"
        assert content.headers["Content-Length"] == str(summary["byteCount"])
        assert Image.open(BytesIO(content.body)).format == "PNG"
        assert app.handle(
            "GET",
            content_path.replace(session.session_id, other_session.session_id),
            {},
        ).status == 404
        assert app.handle(
            "GET",
            content_path.replace("gateway-render", "not-committed"),
            {},
        ).status == 404

        FiguraChartRenderService(store.data_root).store(run.run_id, "orphan-render", _png_bytes())
        assert app.handle(
            "GET",
            content_path.replace("gateway-render", "orphan-render"),
            {},
        ).status == 404

        identity = canonical_json_dumps([run.run_id, "gateway-render"]).encode("utf-8")
        render_path = store.data_root / "chart-renders" / f"{hashlib.sha256(identity).hexdigest()}.png"
        render_path.write_bytes(b"corrupted")
        corrupted = app.handle("GET", content_path, {})
        assert corrupted.status == 500
        assert str(store.data_root) not in corrupted.body.decode()
    finally:
        app.close()


def test_mutating_routes_reject_unconfigured_origin_before_creation(tmp_path):
    app, _, coordinator, _, _ = _application(tmp_path)
    try:
        response = app.handle(
            "POST",
            "/api/v1/sessions",
            {"origin": "http://attacker.example"},
            b"{}",
        )
        assert response.status == 403
        assert coordinator.list_sessions() == ()
        created = app.handle(
            "POST",
            "/api/v1/sessions",
            {"origin": ORIGIN, "content-type": "application/json"},
            '{"name":"网页创建"}'.encode("utf-8"),
        )
        assert created.status == 201
        assert _json(created)["session"]["name"] == "网页创建"
    finally:
        app.close()


def test_http_origin_aliases_are_allowed_and_rejected_origin_gets_json_response(tmp_path):
    app, _, coordinator, _, _ = _application(tmp_path)
    app.allowed_origins = frozenset((ORIGIN, "http://localhost:1421"))
    server = FiguraHTTPServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        allowed = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        allowed.request(
            "POST",
            "/api/v1/sessions",
            body='{"name":"localhost 页面"}'.encode("utf-8"),
            headers={"Origin": "http://localhost:1421", "Content-Type": "application/json"},
        )
        allowed_response = allowed.getresponse()
        allowed_payload = json.loads(allowed_response.read().decode("utf-8"))
        assert allowed_response.status == 201
        assert allowed_response.getheader("Access-Control-Allow-Origin") == "http://localhost:1421"
        assert allowed_payload["session"]["name"] == "localhost 页面"
        allowed.close()

        rejected = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        rejected.request(
            "POST",
            "/api/v1/sessions",
            body=b'{"name":"blocked"}',
            headers={"Origin": "http://attacker.example", "Content-Type": "application/json"},
        )
        rejected_response = rejected.getresponse()
        rejected_payload = json.loads(rejected_response.read().decode("utf-8"))
        assert rejected_response.status == 403
        assert rejected_payload["error"]["code"] == "origin_not_allowed"
        assert len(coordinator.list_sessions()) == 1
        rejected.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        app.close()


def test_run_creation_is_async_idempotent_and_uses_fixed_model(tmp_path):
    started, release = Event(), Event()
    executor = PassiveExecutor(started, release)
    app, _, coordinator, _, _ = _application(tmp_path, executor)
    try:
        session = coordinator.create_session("异步任务")
        target = f"/api/v1/sessions/{session.session_id}/runs"
        request = json.dumps({"text": "分析一下", "attachmentIds": [], "providerId": "qwen"}).encode()
        headers = {"origin": ORIGIN, "content-type": "application/json", "idempotency-key": "same-request"}
        first = app.handle("POST", target, headers, request)
        assert first.status == 202
        assert started.wait(timeout=1)
        first_run_id = _json(first)["run"]["runId"]
        second = app.handle("POST", target, headers, request)
        assert second.status == 202
        assert _json(second)["run"]["runId"] == first_run_id
        assert len(executor.calls) == 1
        assert _json(first)["run"]["model"] == "qwen3.8-flash"
        conflict = app.handle(
            "POST",
            target,
            headers,
            json.dumps({"text": "不同请求", "attachmentIds": [], "providerId": "qwen"}).encode(),
        )
        assert conflict.status == 409
        assert len(executor.calls) == 1
        release.set()
    finally:
        release.set()
        app.close()


def test_startup_recovery_schedules_persisted_running_runs_once(tmp_path):
    app, _, coordinator, _, executor = _application(tmp_path)
    try:
        first_session = coordinator.create_session("恢复甲")
        second_session = coordinator.create_session("恢复乙")
        first = _create_run(coordinator, first_session.session_id, key="recover-1")
        second = _create_run(coordinator, second_session.session_id, key="recover-2")
        running_runs = coordinator.list_running_runs()
        assert [(run.session_id, run.run_id) for run in running_runs] == sorted(
            [
                (first.session_id, first.run_id),
                (second.session_id, second.run_id),
            ]
        )
        assert recover_running_runs(app) == 2
        deadline = monotonic() + 2
        while len(executor.calls) < 2 and monotonic() < deadline:
            sleep(0.01)
        assert set(executor.calls) == {
            (first_session.session_id, first.run_id),
            (second_session.session_id, second.run_id),
        }
    finally:
        app.close()


def test_history_and_sse_replay_safe_lifecycle_events(tmp_path):
    app, _, coordinator, _, _ = _application(tmp_path)
    server = FiguraHTTPServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    try:
        session = coordinator.create_session()
        run = _create_run(coordinator, session.session_id)
        coordinator.fail_run(
            session.session_id,
            run.run_id,
            1,
            terminal_code=TerminalCode.EXECUTION_FAILED,
        )
        history = app.handle(
            "GET",
            f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/history?afterSequence=0",
            {},
        )
        events = _json(history)["events"]
        assert [item["sequence"] for item in events] == [1, 2]
        assert events[0]["payload"] == {"ordinal": 1}
        assert events[1]["payload"] == {"terminalCode": "execution_failed"}

        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request(
            "GET",
            f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/events?afterSequence=0",
            headers={"Origin": ORIGIN},
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()
        assert response.status == 200
        assert f"id: {run.run_id}:1" in body
        assert f"id: {run.run_id}:2" in body
        assert "run_failed" in body
        assert "分析图表中的趋势" not in body
    finally:
        server.shutdown()
        server.server_close()
        app.close()


def test_timeline_status_uses_run_facts_and_dispatcher_ownership(tmp_path):
    started, release = Event(), Event()
    executor = PassiveExecutor(started, release)
    app, store, coordinator, _, _ = _application(tmp_path, executor)
    try:
        session = coordinator.create_session("运行时间线")
        run = _create_run(coordinator, session.session_id, key="timeline-status")
        _commit_tool_calls(
            coordinator,
            session.session_id,
            run.run_id,
            (
                ProviderToolCall("call-measure", "measure_chart", '{"source_kind":"attachment","source_id":"secret-source","chart_type":"bar","private":"PRIVATE_ARGUMENT"}'),
                ProviderToolCall("call-unknown", "unregistered_tool", '{"prompt":"PRIVATE_UNKNOWN_ARGUMENT"}'),
            ),
        )
        _begin_tool_attempt(store, coordinator, session.session_id, run.run_id, "call-measure")

        url = f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/timeline"
        unresolved = _json(app.handle("GET", url, {}))
        assert [step["status"] for step in unresolved["steps"]] == [
            "needs_reconciliation",
            "pending",
        ]
        assert "PRIVATE_ARGUMENT" not in json.dumps(unresolved)
        assert "PRIVATE_UNKNOWN_ARGUMENT" not in json.dumps(unresolved)

        app.dispatcher.ensure_scheduled(run)
        assert started.wait(timeout=1)
        # A queued task alone is not proof of handler ownership.
        assert _json(app.handle("GET", url, {}))["steps"][0]["status"] == "needs_reconciliation"
        with RunExecutionOwnership(store.data_root).acquire(run.run_id):
            owned = _json(app.handle("GET", url, {}))
            assert [step["status"] for step in owned["steps"]] == ["running", "pending"]

        unknown = app.handle(
            "GET",
            f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/timeline/call-unknown",
            {},
        )
        detail = _json(unknown)
        assert set(detail) == {
            "runId",
            "callId",
            "toolName",
            "status",
            "createdAt",
            "updatedAt",
        }
        assert "PRIVATE_UNKNOWN_ARGUMENT" not in unknown.body.decode()

        current = coordinator.read_run_state(session.session_id, run.run_id)
        coordinator.fail_run(
            session.session_id,
            run.run_id,
            current.checkpoint.revision,
            terminal_code=TerminalCode.EXECUTION_FAILED,
        )
        terminal = _json(app.handle("GET", url, {}))
        assert [step["status"] for step in terminal["steps"]] == ["unknown", "not_started"]
    finally:
        release.set()
        app.close()


def test_timeline_ocr_detail_and_observation_are_session_scoped(tmp_path):
    app, store, coordinator, attachments, _ = _application(tmp_path)
    try:
        session = coordinator.create_session("OCR 时间线")
        other = coordinator.create_session("其他会话")
        attachment = attachments.upload(session.session_id, "sales chart.png", _png_bytes())
        run = _create_run(
            coordinator,
            session.session_id,
            key="timeline-ocr",
            attachment_ids=(attachment.attachment_id,),
        )
        arguments = json.dumps(
            {
                "source_kind": "attachment",
                "source_id": attachment.attachment_id,
                "private": "PRIVATE_ARGUMENT",
            },
            separators=(",", ":"),
        )
        _commit_tool_calls(
            coordinator,
            session.session_id,
            run.run_id,
            (ProviderToolCall("call-ocr", "extract_text", arguments),),
        )
        started = _begin_tool_attempt(
            store, coordinator, session.session_id, run.run_id, "call-ocr"
        )
        result = {
            "source_kind": "attachment",
            "source_id": attachment.attachment_id,
            "image_size": {"width": 2, "height": 2},
            "coordinate_system": "attachment_px",
            "available": True,
            "truncated": False,
            "snippets": [
                {
                    "snippet_id": "snippet-1",
                    "text": "CONFIDENTIAL OCR TEXT",
                    "bbox_px": [0, 0, 2, 2],
                    "confidence": 0.9,
                }
            ],
        }
        current = coordinator.read_run_state(session.session_id, run.run_id)
        store.commit_tool_result(
            session_id=session.session_id,
            run_id=run.run_id,
            expected_revision=current.checkpoint.revision,
            attempt_id=started.payload.attempt_id,
            result=ToolExecutionResult(
                "call-ocr",
                "extract_text",
                ToolOutcome.SUCCEEDED,
                result=result,
            ),
        )

        detail_response = app.handle(
            "GET",
            f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/timeline/call-ocr",
            {},
        )
        detail = _json(detail_response)
        assert detail["status"] == "completed"
        assert detail["observationAvailable"] is True
        assert detail["source"] == {
            "kind": "attachment",
            "id": attachment.attachment_id,
            "name": "sales chart.png",
        }
        assert detail["resultSummary"] == "结果可用 · 1 条文字记录"
        assert detail["attempts"][0]["status"] == "completed"
        assert "PRIVATE_ARGUMENT" not in detail_response.body.decode()
        assert "CONFIDENTIAL OCR TEXT" not in detail_response.body.decode()

        preview = app.handle(
            "GET",
            f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/timeline/call-ocr/observation",
            {},
        )
        assert preview.status == 200
        assert preview.headers["Content-Type"] == "image/png"
        assert preview.headers["Cache-Control"] == "no-store"
        assert Image.open(BytesIO(preview.body)).format == "PNG"
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{other.session_id}/runs/{run.run_id}/timeline",
            {},
        ).status == 404
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/timeline/missing",
            {},
        ).status == 404
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/timeline/call-ocr/observation",
            {"origin": ORIGIN},
        ).status == 200
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{other.session_id}/runs/{run.run_id}/timeline/call-ocr/observation",
            {},
        ).status == 404

        terminal_state = coordinator.read_run_state(session.session_id, run.run_id)
        coordinator.fail_run(
            session.session_id,
            run.run_id,
            terminal_state.checkpoint.revision,
            terminal_code=TerminalCode.EXECUTION_FAILED,
        )
        failed_run = _create_run(
            coordinator,
            session.session_id,
            key="timeline-ocr-failed",
            attachment_ids=(attachment.attachment_id,),
        )
        _commit_tool_calls(
            coordinator,
            session.session_id,
            failed_run.run_id,
            (
                ProviderToolCall(
                    "call-ocr-failed",
                    "extract_text",
                    json.dumps(
                        {"source_kind": "attachment", "source_id": attachment.attachment_id},
                        separators=(",", ":"),
                    ),
                ),
            ),
        )
        failed_attempt = _begin_tool_attempt(
            store, coordinator, session.session_id, failed_run.run_id, "call-ocr-failed"
        )
        failed_state = coordinator.read_run_state(session.session_id, failed_run.run_id)
        store.commit_tool_result(
            session_id=session.session_id,
            run_id=failed_run.run_id,
            expected_revision=failed_state.checkpoint.revision,
            attempt_id=failed_attempt.payload.attempt_id,
            result=ToolExecutionResult(
                "call-ocr-failed",
                "extract_text",
                ToolOutcome.FAILED,
                error=ToolExecutionError(
                    "image_unavailable",
                    "/private/tmp/SECRET_PATH: PRIVATE_ERROR",
                    False,
                ),
            ),
        )
        failed_detail = app.handle(
            "GET",
            f"/api/v1/sessions/{session.session_id}/runs/{failed_run.run_id}/timeline/call-ocr-failed",
            {},
        )
        failed_projection = _json(failed_detail)
        assert failed_projection["status"] == "failed"
        assert failed_projection["errorSummary"] == "图像暂时无法读取"
        assert "/private/tmp/SECRET_PATH" not in failed_detail.body.decode()
        assert "PRIVATE_ERROR" not in failed_detail.body.decode()
    finally:
        app.close()


def test_progress_history_and_sse_expose_only_checkpoint_revision(tmp_path):
    app, _, coordinator, _, _ = _application(tmp_path)
    server = FiguraHTTPServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    try:
        session = coordinator.create_session()
        run = _create_run(coordinator, session.session_id, key="timeline-progress")
        _commit_tool_calls(
            coordinator,
            session.session_id,
            run.run_id,
            (ProviderToolCall("call-safe", "load_image", '{"source_kind":"attachment","source_id":"opaque","private":"PRIVATE_ARGUMENT"}'),),
        )
        current = coordinator.read_run_state(session.session_id, run.run_id)
        coordinator.fail_run(
            session.session_id,
            run.run_id,
            current.checkpoint.revision,
            terminal_code=TerminalCode.EXECUTION_FAILED,
        )
        history = app.handle(
            "GET",
            f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/history",
            {},
        )
        events = _json(history)["events"]
        progress = next(event for event in events if event["kind"] == "run_progress")
        assert progress["payload"] == {"checkpointRevision": 3}
        assert "PRIVATE_ARGUMENT" not in history.body.decode()

        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request(
            "GET",
            f"/api/v1/sessions/{session.session_id}/runs/{run.run_id}/events?afterSequence=0",
            headers={"Origin": ORIGIN},
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()
        assert response.status == 200
        assert f"id: {run.run_id}:{progress['sequence']}" in body
        assert "event: run_progress" in body
        assert '"payload":{"checkpointRevision":3}' in body
        assert "PRIVATE_ARGUMENT" not in body
    finally:
        server.shutdown()
        server.server_close()
        app.close()


def test_session_scoped_run_history_does_not_leak_across_sessions(tmp_path):
    app, _, coordinator, _, _ = _application(tmp_path)
    try:
        first = coordinator.create_session()
        second = coordinator.create_session()
        run = _create_run(coordinator, first.session_id)
        response = app.handle(
            "GET",
            f"/api/v1/sessions/{second.session_id}/runs/{run.run_id}/history",
            {},
        )
        assert response.status == 404
        assert "分析图表中的趋势" not in response.body.decode()
    finally:
        app.close()


def test_session_delete_removes_owned_runtime_sources_and_render_data(tmp_path):
    app, store, coordinator, attachments, _ = _application(tmp_path)
    try:
        selected = coordinator.create_session("要删除的会话")
        remaining = coordinator.create_session("保留的会话")
        image = attachments.upload(selected.session_id, "source.png", _png_bytes())
        panel_run = _create_run(
            coordinator,
            selected.session_id,
            key="session-delete-panel",
            attachment_ids=(image.attachment_id,),
        )
        panel = app.panels.decompose(
            selected.session_id,
            panel_run.run_id,
            image.attachment_id,
            (("独立 Panel", (PanelPoint(0, 0), PanelPoint(1000, 0), PanelPoint(1000, 1000), PanelPoint(0, 1000))),),
            "p" * 64,
        )[0]
        _finish_run(coordinator, selected.session_id, panel_run.run_id)

        render_run = _create_run(coordinator, selected.session_id, key="session-delete-render")
        _commit_chart_render(app, store, selected.session_id, render_run.run_id)
        _finish_run(coordinator, selected.session_id, render_run.run_id)
        FiguraChartRenderService(store.data_root).resolve(render_run.run_id, "gateway-render")

        other_image = attachments.upload(remaining.session_id, "keep.png", _png_bytes())
        other_run = _create_run(coordinator, remaining.session_id, key="session-delete-keep")

        response = app.handle(
            "DELETE",
            f"/api/v1/sessions/{selected.session_id}",
            {"origin": ORIGIN},
        )

        assert response.status == 204
        assert response.body == b""
        assert app.handle("GET", f"/api/v1/sessions/{selected.session_id}", {}).status == 404
        assert app.handle(
            "GET", f"/api/v1/sessions/{selected.session_id}/attachments", {}
        ).status == 404
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{selected.session_id}/attachments/{image.attachment_id}/content",
            {},
        ).status == 404
        assert app.handle(
            "GET", f"/api/v1/sessions/{selected.session_id}/panels", {}
        ).status == 404
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{selected.session_id}/panels/{panel.panel_id}/content",
            {},
        ).status == 404
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{selected.session_id}/runs/{render_run.run_id}/history",
            {},
        ).status == 404
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{selected.session_id}/runs/{render_run.run_id}/timeline",
            {},
        ).status == 404
        assert app.handle(
            "GET",
            f"/api/v1/sessions/{selected.session_id}/runs/{render_run.run_id}/chart-renders/gateway-render/content",
            {},
        ).status == 404
        assert not (store.data_root / "attachments" / f"{image.attachment_id}.bin").exists()
        assert not (store.data_root / "panels" / f"{panel.panel_id}.png").exists()
        identity = canonical_json_dumps([render_run.run_id, "gateway-render"]).encode("utf-8")
        render_name = hashlib.sha256(identity).hexdigest() + ".png"
        assert not (store.data_root / "chart-renders" / render_name).exists()

        assert attachments.resolve(remaining.session_id, other_image.attachment_id).image_bytes == _png_bytes()
        assert coordinator.read_run_state(remaining.session_id, other_run.run_id).run.status is RunStatus.RUNNING
        with sqlite3.connect(store.database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM session_deletion_scopes"
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE session_id = ?",
                (remaining.session_id,),
            ).fetchone()[0] == 1
    finally:
        app.close()


def test_session_delete_rejects_running_run_and_unknown_session(tmp_path):
    app, _, coordinator, _, _ = _application(tmp_path)
    try:
        session = coordinator.create_session("运行中")
        run = _create_run(coordinator, session.session_id, key="session-delete-running")

        active = app.handle(
            "DELETE",
            f"/api/v1/sessions/{session.session_id}",
            {"origin": ORIGIN},
        )
        unknown = app.handle(
            "DELETE",
            f"/api/v1/sessions/{'a' * 32}",
            {"origin": ORIGIN},
        )

        assert active.status == 409
        assert _json(active)["error"]["code"] == "session_has_running_run"
        assert unknown.status == 404
        assert app.handle("GET", f"/api/v1/sessions/{session.session_id}", {}).status == 200
        assert coordinator.read_run_state(session.session_id, run.run_id).run.status is RunStatus.RUNNING
        assert app.handle(
            "DELETE", f"/api/v1/sessions/{session.session_id}", {"origin": "http://evil.test"}
        ).status == 403
    finally:
        app.close()


def test_session_delete_rolls_back_and_restores_partially_staged_files(tmp_path, monkeypatch):
    app, store, coordinator, attachments, _ = _application(tmp_path)
    try:
        session = coordinator.create_session("删除失败恢复")
        image = attachments.upload(session.session_id, "source.png", _png_bytes())
        run = _create_run(
            coordinator,
            session.session_id,
            key="session-delete-rollback",
            attachment_ids=(image.attachment_id,),
        )
        panel = app.panels.decompose(
            session.session_id,
            run.run_id,
            image.attachment_id,
            (("Panel", (PanelPoint(0, 0), PanelPoint(1000, 0), PanelPoint(1000, 1000), PanelPoint(0, 1000))),),
            "r" * 64,
        )[0]
        _finish_run(coordinator, session.session_id, run.run_id)
        with sqlite3.connect(store.database_path) as connection:
            connection.execute(
                "CREATE TRIGGER reject_session_run_delete BEFORE DELETE ON runs "
                "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )

        response = app.handle(
            "DELETE", f"/api/v1/sessions/{session.session_id}", {"origin": ORIGIN}
        )

        assert response.status == 500
        assert app.handle("GET", f"/api/v1/sessions/{session.session_id}", {}).status == 200
        assert attachments.resolve(session.session_id, image.attachment_id).image_bytes == _png_bytes()
        assert app.panels.resolve(session.session_id, panel.panel_id)[0] == panel
        assert not (store.data_root / "session-trash" / session.session_id).exists()

        with sqlite3.connect(store.database_path) as connection:
            connection.execute("DROP TRIGGER reject_session_run_delete")

        def fail_panel_staging(_panel_service, _session_trash, _panel_ids):
            raise OSError("injected partial staging failure")

        monkeypatch.setattr(type(app.panels), "stage_session_deletion", fail_panel_staging)
        partial = app.handle(
            "DELETE", f"/api/v1/sessions/{session.session_id}", {"origin": ORIGIN}
        )
        assert partial.status == 500
        assert app.handle("GET", f"/api/v1/sessions/{session.session_id}", {}).status == 200
        assert attachments.resolve(session.session_id, image.attachment_id).image_bytes == _png_bytes()
        assert app.panels.resolve(session.session_id, panel.panel_id)[0] == panel
        assert not (store.data_root / "session-trash" / session.session_id).exists()
    finally:
        app.close()


def test_startup_restores_staged_files_when_session_row_remains(tmp_path):
    app, store, coordinator, attachments, _ = _application(tmp_path)
    session = coordinator.create_session("启动时恢复")
    image = attachments.upload(session.session_id, "source.png", _png_bytes())
    run = _create_run(coordinator, session.session_id, key="session-trash-recovery")
    panel = app.panels.decompose(
        session.session_id,
        run.run_id,
        image.attachment_id,
        (("Panel", (PanelPoint(0, 0), PanelPoint(1000, 0), PanelPoint(1000, 1000), PanelPoint(0, 1000))),),
        "s" * 64,
    )[0]
    session_trash = store.data_root / "session-trash" / session.session_id
    try:
        attachments.stage_session_deletion(session_trash, (image.attachment_id,))
        app.panels.stage_session_deletion(session_trash, (panel.panel_id,))
    finally:
        app.close()

    reopened, _, _, reopened_attachments, _ = _application(tmp_path)
    try:
        assert reopened_attachments.resolve(session.session_id, image.attachment_id).image_bytes == _png_bytes()
        assert reopened.panels.resolve(session.session_id, panel.panel_id)[0] == panel
        assert not session_trash.exists()
    finally:
        reopened.close()


def test_startup_discards_staged_files_after_committed_deletion(tmp_path):
    app, store, coordinator, attachments, _ = _application(tmp_path)
    session = coordinator.create_session("提交后清理")
    image = attachments.upload(session.session_id, "source.png", _png_bytes())
    session_trash = store.data_root / "session-trash" / session.session_id
    app.session_deletion._discard = lambda _path: None
    try:
        response = app.handle(
            "DELETE", f"/api/v1/sessions/{session.session_id}", {"origin": ORIGIN}
        )
        assert response.status == 204
        assert session_trash.exists()
        assert not (store.data_root / "attachments" / f"{image.attachment_id}.bin").exists()
    finally:
        app.close()

    reopened, _, _, _, _ = _application(tmp_path)
    try:
        assert not session_trash.exists()
    finally:
        reopened.close()
