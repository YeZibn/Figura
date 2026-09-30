from __future__ import annotations

from tests.figura_sources_support import (
    make_attachment_service,
    make_execution_image_reader,
    make_panel_service,
)

import json
import hashlib
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
from figura.providers import FinishReason, MODEL_IDS, ProviderFactory, ProviderId, ProviderResponse, ProviderToolCall
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.models import RunCreateRequest, RunStatus, TerminalCode
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.tools import ToolRegistry
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


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(output, format="PNG")
    return output.getvalue()


def _commit_chart_render(app, store, session_id: str, run_id: str):
    registry = ToolRegistry(
        "figura-web-v6",
        (
            assemble_chart_figure_definition(app.execution_state.for_run),
            render_chart_figure_definition(
                app.execution_state.for_run,
                FiguraChartRenderService(store.data_root),
            ),
        ),
    )
    figure = {
        "schema_version": 1,
        "title": "Quarterly sales",
        "layout": {"columns": 1},
        "charts": [
            {
                "chart_id": "sales",
                "chart_spec": {
                    "schema_version": 1,
                    "metadata": {"chart_type": "pie", "title": "Share"},
                    "axes": None,
                    "dataset": [
                        {"category": "North", "value": 70},
                        {"category": "South", "value": 30},
                    ],
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
        assert payload["runs"][0]["executionState"] == "active"
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
