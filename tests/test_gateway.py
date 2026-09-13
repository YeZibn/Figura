"""Offline tests for the local ChartAgent gateway."""

from __future__ import annotations

import http.client
import hashlib
import io
import json
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from PIL import Image

from chartagent.attachments import AttachmentRegistry
from chartagent.agent import Agent
from chartagent.gateway.attachments import AttachmentStoreError, EphemeralAttachmentStore
from chartagent.gateway.history import GatewayHistoryStore
from chartagent.gateway.protocol import GatewayFault, RunEvent, validate_message_text, validate_session_name
from chartagent.gateway.projection import project_completed_runs
from chartagent.gateway.server import GatewayHTTPServer, serve
from chartagent.gateway.service import GatewayService
from chartagent.gateway.runs import ObservationStore, RunManager
from chartagent.memory import SQLiteAgentMemory, RunStatus
from chartagent.memory.models import Record, Run
from chartagent.runtime import AgentRuntime
from chartagent.tools.result import GeneratedImage
from chartagent.trace import TraceEvent
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools import Tool, ToolRegistry, ToolResult


def _completed_run(run_id: str, text: str = "问题", answer: str = "答案") -> Run:
    run = Run(run_id, "session", 1, RunStatus.COMPLETED)
    run.records = [
        Record("user", {"text": text}, created_at="2026-09-10T10:00:00+00:00"),
        Record("tool", {"result": "/private/chart.png", "credentials": "secret"}),
        Record("final", {"answer": answer}, created_at="2026-09-10T10:00:01+00:00"),
    ]
    return run


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (4, 3), (35, 140, 131)).save(output, format="PNG")
    return output.getvalue()


def test_gateway_input_validation_is_bounded():
    with pytest.raises(GatewayFault) as name_error:
        validate_session_name("  ")
    assert name_error.value.code == "invalid_request"

    with pytest.raises(GatewayFault) as text_error:
        validate_message_text("x" * 12001)
    assert text_error.value.status == 400
    assert "x" * 500 not in text_error.value.message


def test_gateway_health_separates_http_and_agent_readiness():
    ready = GatewayService(readiness_probe=lambda: {"status": "ready"})
    assert ready.health() == {
        "version": "v1",
        "status": "ok",
        "service": "Figura Gateway",
        "agent": {"status": "ready"},
    }

    unavailable = GatewayService(
        readiness_probe=lambda: {"status": "unavailable", "reason": "missing_configuration"}
    )
    health = unavailable.health()
    assert health["status"] == "ok"
    assert health["agent"] == {"status": "unavailable", "reason": "missing_configuration"}
    assert "secret" not in json.dumps(health).lower()


def test_gateway_health_redacts_unknown_readiness_reason():
    service = GatewayService(
        readiness_probe=lambda: {
            "status": "unavailable",
            "reason": "DASHSCOPE_API_KEY=secret-value",
        }
    )
    health = service.health()
    assert health["agent"] == {"status": "unavailable", "reason": "initialization_failed"}
    assert "secret-value" not in json.dumps(health)


def test_completed_projection_omits_partial_runs_and_sensitive_records(tmp_path):
    session = SQLiteAgentMemory("demo", database=tmp_path / "sessions.db").session
    partial = Run("partial", session.id, 2, RunStatus.INTERRUPTED)
    partial.records = [Record("user", {"text": "partial"})]
    transcript = project_completed_runs(session, [_completed_run("complete"), partial])

    assert [message.kind for message in transcript.messages] == ["user", "assistant"]
    assert transcript.messages[1].text == "答案"
    assert "/private/chart.png" not in json.dumps(transcript.to_dict())
    assert "credentials" not in json.dumps(transcript.to_dict())


def test_completed_projection_keeps_safe_attachment_ids_and_clean_user_text(tmp_path):
    session = SQLiteAgentMemory("demo", database=tmp_path / "sessions.db").session
    run = _completed_run(
        "complete",
        "请看图\n\nRegistered image attachments (load with load_image when useful):\n1. attachment_id=att_demo, filename=chart.png",
    )
    run.session_id = session.id
    run.records.insert(1, Record("attachment", {"attachment_id": "att_demo", "ordinal": 1}))
    transcript = project_completed_runs(session, [run])

    message = transcript.messages[0].to_dict()
    assert message["text"] == "请看图"
    assert message["attachmentIds"] == ["att_demo"]


def test_projection_marks_legacy_split_identity_without_merging_it(tmp_path):
    session = SQLiteAgentMemory("demo", database=tmp_path / "sessions.db").session
    run = _completed_run("memory-run", "旧问题", "旧答案")

    transcript = project_completed_runs(session, [run], canonical_run_ids=["gateway-run"])

    assert [message.id for message in transcript.messages] == ["memory-run:user", "memory-run:assistant"]
    assert all(message.association_status == "legacy_unassociated" for message in transcript.messages)
    payload = transcript.to_dict()
    assert all(item["associationStatus"] == "legacy_unassociated" for item in payload["messages"])


def test_gateway_service_lifecycle_and_message(tmp_path):
    database = tmp_path / "sessions.db"
    service = GatewayService(database=database)
    created = service.create_session("demo")
    session_id = created["session"]["id"]
    assert service.list_sessions()["sessions"][0]["runCount"] == 0

    class FakeAgent:
        def __init__(self, memory):
            self.memory = memory

        def run(self, text):
            run = self.memory.begin_run()
            self.memory.append(run, "user", {"text": text})
            self.memory.append(run, "final", {"answer": "来自模拟 Agent"})
            self.memory.finish(run, RunStatus.COMPLETED, "final")
            return "来自模拟 Agent"

    class FakeRuntime:
        def __init__(self, memory):
            self.agent = FakeAgent(memory)

        def close(self):
            self.agent.memory.close()

    def runtime_factory(name):
        return FakeRuntime(SQLiteAgentMemory(name, database=database, create=False))

    service = GatewayService(database=database, runtime_factory=runtime_factory)
    result = service.submit_message(session_id, "你好")
    assert result["answer"] == "来自模拟 Agent"
    assert [item["kind"] for item in result["messages"]] == ["user", "assistant"]
    assert service.list_sessions()["sessions"][0]["runCount"] == 1


def test_gateway_run_id_is_shared_by_runtime_memory_trace_and_projection(tmp_path):
    database = tmp_path / "sessions.db"
    captured: dict[str, object] = {}

    class FinalClient:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return NormalizedResult(
                    tool_calls=[ToolCall("chart-call", "make_chart", "{}")]
                )
            return NormalizedResult(content="统一身份完成")

    def runtime_factory(name, *, run_id, trace_sink, visual_observation_sink):
        memory = SQLiteAgentMemory(name, database=database, create=False)
        attachments = AttachmentRegistry(
            session_id=memory.session.id,
            save=memory.save_attachment,
            load=memory.get_attachment,
        )
        registry = ToolRegistry()
        registry.register(
            Tool(
                "make_chart",
                "生成用于测试的图表",
                {"type": "object", "properties": {}, "additionalProperties": False},
                lambda: ToolResult(
                    {"ok": True},
                    images=(
                        GeneratedImage(
                            _png_bytes(),
                            "image/png",
                            "生成测试图表",
                            metadata={
                                "kind": "generated_chart",
                                "chart_type": "bar",
                                "title": "统一身份图表",
                                "width": 4,
                                "height": 3,
                            },
                        ),
                    ),
                ),
            )
        )
        agent = Agent(
            FinalClient(),
            registry,
            memory=memory,
            run_id=run_id,
            trace=trace_sink,
            visual_observation_sink=visual_observation_sink,
            attachments=attachments,
        )
        captured["run_id"] = run_id
        return AgentRuntime(agent, memory, attachments)

    service = GatewayService(database=database, runtime_factory=runtime_factory)
    session_id = service.create_session("canonical-run")["session"]["id"]
    accepted = service.start_run(session_id, "检查身份")
    run_id = accepted["run"]["runId"]
    run = service.get_run(session_id, run_id)
    assert run.wait_terminal(timeout=2)

    assert captured["run_id"] == run_id
    assert all(event.run_id == run_id for event in run.iter_events())
    generated = next(event for event in run.iter_events() if event.kind == "generated_chart")
    artifact = generated.payload["artifacts"][0]
    assert service.get_generated_artifact(session_id, run_id, artifact["artifactId"]) == (_png_bytes(), "image/png")
    stored = SQLiteAgentMemory("canonical-run", database=database, create=False)
    try:
        completed = stored.completed_runs()
        assert [item.id for item in completed] == [run_id]
    finally:
        stored.close()
    transcript = service.get_session(session_id)
    assert [item["id"] for item in transcript["messages"]] == [f"{run_id}:user", f"{run_id}:assistant"]
    assert all("associationStatus" not in item for item in transcript["messages"])
    service.close()


def test_gateway_multiple_runs_restore_once_in_stable_order(tmp_path):
    database = tmp_path / "sessions.db"

    class FinalClient:
        def chat(self, messages, **kwargs):
            return NormalizedResult(content="历史恢复完成")

    def runtime_factory(name, *, run_id, trace_sink, visual_observation_sink):
        memory = SQLiteAgentMemory(name, database=database, create=False)
        attachments = AttachmentRegistry(
            session_id=memory.session.id,
            save=memory.save_attachment,
            load=memory.get_attachment,
        )
        agent = Agent(
            FinalClient(),
            ToolRegistry(),
            memory=memory,
            run_id=run_id,
            trace=trace_sink,
            attachments=attachments,
        )
        return AgentRuntime(agent, memory, attachments)

    service = GatewayService(database=database, runtime_factory=runtime_factory)
    session_id = service.create_session("history-runs")["session"]["id"]
    first = service.submit_message(session_id, "第一次")
    second = service.submit_message(session_id, "第二次")
    first_id = first["runId"]
    second_id = second["runId"]
    assert first_id != second_id

    restored_service = GatewayService(database=database, runtime_factory=runtime_factory)
    restored = restored_service.get_session(session_id)
    assert [item["id"] for item in restored["messages"]] == [
        f"{first_id}:user",
        f"{first_id}:assistant",
        f"{second_id}:user",
        f"{second_id}:assistant",
    ]
    assert [item["runId"] for item in restored["runs"]] == [first_id, second_id]
    assert len({item["id"] for item in restored["messages"]}) == 4
    service.close()
    restored_service.close()


def test_gateway_service_maps_unavailable_agent_and_preserves_history(tmp_path):
    database = tmp_path / "sessions.db"
    service = GatewayService(database=database)
    session_id = service.create_session("demo")["session"]["id"]

    def unavailable(_name):
        raise ValueError("An API key is required: secret-key-value")

    service = GatewayService(database=database, runtime_factory=unavailable)
    with pytest.raises(GatewayFault) as error:
        service.submit_message(session_id, "run")
    assert error.value.code == "agent_unavailable"
    assert error.value.reason == "missing_configuration"
    assert "secret-key" not in error.value.message
    assert service.get_session(session_id)["messages"] == []

    accepted = service.start_run(session_id, "run again")
    run = service.get_run(session_id, accepted["run"]["runId"])
    assert run.wait_terminal(timeout=2)
    failure = next(event for event in run.iter_events() if event.kind == "run_failed")
    assert failure.payload == {
        "code": "agent_unavailable",
        "reason": "missing_configuration",
        "message": "Agent service is unavailable",
    }


def test_attachment_upload_projects_safe_metadata_and_survives_restart(tmp_path):
    database = tmp_path / "sessions.db"
    attachment_root = tmp_path / "attachments"
    service = GatewayService(database=database, attachment_root=attachment_root)
    session_id = service.create_session("demo")["session"]["id"]
    content = _png_bytes()

    result = service.upload_attachment(session_id, "季度销售.png", "image/png", content)
    metadata = result["attachment"]
    encoded = json.dumps(result, ensure_ascii=False)
    assert metadata["attachment_id"].startswith("att_")
    assert metadata["filename"] == "季度销售.png"
    assert metadata["byte_count"] == len(content)
    assert metadata["sha256"] == hashlib.sha256(content).hexdigest()
    assert metadata["status"] == "registered"
    assert "canonical_path" not in encoded
    assert str(attachment_root) not in encoded
    assert content.decode("latin1") not in encoded
    assert service.get_session(session_id)["attachments"][0]["status"] == "registered"

    # A new Gateway process reuses the persistent attachment root.
    restarted = GatewayService(database=database, attachment_root=attachment_root)
    assert restarted.get_session(session_id)["attachments"][0]["status"] == "registered"
    restored, media_type = restarted.get_attachment_content(session_id, metadata["attachment_id"])
    assert restored == content
    assert media_type == "image/png"


def test_attachment_store_resolves_persistent_root_and_cleans_only_orphans(tmp_path):
    database = tmp_path / "sessions.db"
    store = EphemeralAttachmentStore(database=database)
    assert store.root == tmp_path / "attachments"
    owned = store.stage("session", "owned.png", "image/png", _png_bytes())
    orphan = store.stage("session", "orphan.png", "image/png", _png_bytes())
    assert store.cleanup_orphans({str(owned.resolve())}) == 1
    assert owned.exists()
    assert not orphan.exists()


def test_legacy_attachment_source_is_migrated_when_still_valid(tmp_path):
    database = tmp_path / "sessions.db"
    legacy_root = tmp_path / "legacy"
    first = GatewayService(database=database, attachment_root=legacy_root)
    session_id = first.create_session("demo")["session"]["id"]
    metadata = first.upload_attachment(session_id, "chart.png", "image/png", _png_bytes())["attachment"]

    restarted = GatewayService(database=database, attachment_root=tmp_path / "attachments")
    assert restarted.get_session(session_id)["attachments"][0]["status"] == "registered"
    restored, _ = restarted.get_attachment_content(session_id, metadata["attachment_id"])
    assert restored == _png_bytes()
    stored = SQLiteAgentMemory("demo", database=database, create=False)
    try:
        assert str(tmp_path / "attachments") in stored.get_attachment(metadata["attachment_id"]).canonical_path
    finally:
        stored.close()


def test_session_and_attachment_deletion_are_scoped_and_cascading(tmp_path):
    database = tmp_path / "sessions.db"
    root = tmp_path / "attachments"
    service = GatewayService(database=database, attachment_root=root)
    first_id = service.create_session("first")["session"]["id"]
    second_id = service.create_session("second")["session"]["id"]
    attachment_id = service.upload_attachment(first_id, "chart.png", "image/png", _png_bytes())["attachment"]["attachment_id"]

    with pytest.raises(GatewayFault) as cross_session:
        service.delete_attachment(second_id, attachment_id)
    assert cross_session.value.code == "attachment_not_found"
    assert service.get_attachment_content(first_id, attachment_id)[0] == _png_bytes()

    deleted_attachment = service.delete_attachment(first_id, attachment_id)
    assert deleted_attachment["deleted"] is True
    with pytest.raises(GatewayFault) as missing:
        service.get_attachment_content(first_id, attachment_id)
    assert missing.value.code == "attachment_not_found"

    attachment_id = service.upload_attachment(first_id, "chart.png", "image/png", _png_bytes())["attachment"]["attachment_id"]
    attachment_path = SQLiteAgentMemory("first", database=database, create=False)
    try:
        source = Path(attachment_path.get_attachment(attachment_id).canonical_path)
    finally:
        attachment_path.close()
    assert source.exists()
    assert service.delete_session(first_id)["deleted"] is True
    assert not source.exists()
    with pytest.raises(GatewayFault) as gone:
        service.get_session(first_id)
    assert gone.value.code == "session_not_found"
    assert service.get_session(second_id)["session"]["name"] == "second"


def test_session_deletion_rejects_active_run(tmp_path):
    database = tmp_path / "sessions.db"
    manager = RunManager()
    service = GatewayService(database=database, run_manager=manager)
    session_id = service.create_session("busy")["session"]["id"]
    run = manager.create(session_id)
    with pytest.raises(GatewayFault) as error:
        service.delete_session(session_id)
    assert error.value.code == "session_busy"
    assert service.get_session(session_id)["session"]["name"] == "busy"
    run.complete("done")
    assert service.delete_session(session_id)["deleted"] is True
    manager.close()


def test_attachment_store_rejects_bad_content_and_enforces_limits(tmp_path):
    store = EphemeralAttachmentStore(tmp_path / "attachments", max_bytes=64)
    with pytest.raises(AttachmentStoreError) as media_error:
        store.stage("session", "chart.png", "image/svg+xml", _png_bytes())
    assert getattr(media_error.value, "code", None) == "unsupported_media_type"

    with pytest.raises(AttachmentStoreError) as image_error:
        store.stage("session", "chart.png", "image/png", b"not an image")
    assert getattr(image_error.value, "code", None) == "invalid_image"

    large_store = EphemeralAttachmentStore(tmp_path / "large", max_bytes=64)
    with pytest.raises(AttachmentStoreError) as size_error:
        large_store.stage("session", "chart.png", "image/png", _png_bytes())
    assert getattr(size_error.value, "code", None) == "attachment_too_large"

    content = _png_bytes()
    aggregate_store = EphemeralAttachmentStore(
        tmp_path / "aggregate",
        max_session_bytes=len(content),
    )
    aggregate_store.stage("session", "first.png", "image/png", content)
    with pytest.raises(AttachmentStoreError) as aggregate_error:
        aggregate_store.stage("session", "second.png", "image/png", content)
    assert aggregate_error.value.code == "attachment_storage_limit"


def test_attachment_ids_are_session_scoped_and_message_stays_lazy(tmp_path):
    database = tmp_path / "sessions.db"
    service = GatewayService(database=database, attachment_root=tmp_path / "attachments")
    first_id = service.create_session("first")["session"]["id"]
    second_id = service.create_session("second")["session"]["id"]
    attachment_id = service.upload_attachment(first_id, "chart.png", "image/png", _png_bytes())["attachment"]["attachment_id"]

    with pytest.raises(GatewayFault) as isolated:
        service.submit_message(second_id, "inspect", [attachment_id])
    assert isolated.value.code == "attachment_not_found"

    calls = []

    class FakeAgent:
        def __init__(self, memory):
            self.memory = memory

        def run(self, prompt):
            calls.append(prompt)
            run = self.memory.begin_run()
            self.memory.append(run, "user", {"text": prompt})
            self.memory.append(run, "final", {"answer": "已收到"})
            self.memory.finish(run, RunStatus.COMPLETED, "final")
            return "已收到"

    class FakeRuntime:
        def __init__(self, memory):
            self.agent = FakeAgent(memory)

        def close(self):
            self.agent.memory.close()

    service = GatewayService(
        database=database,
        attachment_root=tmp_path / "attachments-2",
        runtime_factory=lambda name: FakeRuntime(SQLiteAgentMemory(name, database=database, create=False)),
    )
    # The fresh service deliberately loses the upload bytes; re-upload into the
    # active service to test message construction independently.
    attachment_id = service.upload_attachment(first_id, "chart.png", "image/png", _png_bytes())["attachment"]["attachment_id"]
    result = service.submit_message(first_id, "请看图", [attachment_id])
    assert result["answer"] == "已收到"
    assert "attachment_id=" + attachment_id in calls[0]
    assert "load_image" in calls[0]
    assert "data:image" not in calls[0]


def _binary_request(port: int, path: str, content: bytes, *, filename: str, media_type: str):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(
        "POST",
        path + "?filename=" + quote(filename),
        body=content,
        headers={
            "Content-Type": "application/octet-stream",
            "X-ChartAgent-Media-Type": media_type,
        },
    )
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, json.loads(raw) if raw else None


def _request(port: int, method: str, path: str, payload=None, *, origin=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if origin:
        headers["Origin"] = origin
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, json.loads(raw) if raw else None, response.getheader("Access-Control-Allow-Origin")


def test_gateway_http_routes_and_bounded_errors(tmp_path):
    service = GatewayService(database=tmp_path / "sessions.db")
    server = GatewayHTTPServer(("127.0.0.1", 0), service, allowed_origins={"http://127.0.0.1:1420"})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, health, cors = _request(port, "GET", "/api/v1/health", origin="http://127.0.0.1:1420")
        assert status == 200
        assert health["version"] == "v1"
        assert cors == "http://127.0.0.1:1420"

        status, created, _ = _request(port, "POST", "/api/v1/sessions", {"name": "demo"})
        assert status == 200
        session_id = created["session"]["id"]
        status, detail, _ = _request(port, "GET", f"/api/v1/sessions/{session_id}")
        assert status == 200
        assert detail["session"]["name"] == "demo"

        status, uploaded = _binary_request(
            port,
            f"/api/v1/sessions/{session_id}/attachments",
            _png_bytes(),
            filename="chart.png",
            media_type="image/png",
        )
        assert status == 200
        attachment_id = uploaded["attachment"]["attachment_id"]
        status, listed, _ = _request(port, "GET", f"/api/v1/sessions/{session_id}/attachments")
        assert status == 200
        assert listed["attachments"][0]["attachment_id"] == attachment_id
        assert "canonical_path" not in json.dumps(listed)

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request(
            "GET",
            f"/api/v1/sessions/{session_id}/attachments/{attachment_id}/content",
            headers={"Origin": "http://127.0.0.1:1420"},
        )
        response = connection.getresponse()
        image_body = response.read()
        allow_origin = response.getheader("Access-Control-Allow-Origin")
        content_type = response.getheader("Content-Type")
        connection.close()
        assert response.status == 200
        assert image_body == _png_bytes()
        assert content_type == "image/png"
        assert allow_origin == "http://127.0.0.1:1420"

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request(
            "POST",
            f"/api/v1/sessions/{session_id}/attachments?filename=bad.png",
            body=b"not-json",
            headers={
                "Content-Type": "application/json",
                "X-ChartAgent-Media-Type": "image/png",
            },
        )
        response = connection.getresponse()
        response.read()
        connection.close()
        assert response.status == 415

        status, duplicate, _ = _request(port, "POST", "/api/v1/sessions", {"name": "demo"})
        assert status == 409
        assert duplicate["error"]["code"] == "session_exists"

        status, bad, _ = _request(port, "POST", f"/api/v1/sessions/{session_id}/messages", {"text": " "})
        assert status == 400
        assert bad["error"]["code"] == "invalid_request"

        status, deleted, _ = _request(port, "DELETE", f"/api/v1/sessions/{session_id}/attachments/{attachment_id}")
        assert status == 200
        assert deleted["deleted"] is True
        status, deleted_session, _ = _request(port, "DELETE", f"/api/v1/sessions/{session_id}")
        assert status == 200
        assert deleted_session["deleted"] is True
        status, missing_session, _ = _request(port, "GET", f"/api/v1/sessions/{session_id}")
        assert status == 404
        assert missing_session["error"]["code"] == "session_not_found"

        status, missing, _ = _request(port, "GET", "/api/v1/unknown")
        assert status == 404
        assert "Traceback" not in json.dumps(missing)

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("POST", "/api/v1/sessions", b"not-json", {"Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        assert response.status == 400
        assert "Traceback" not in body.decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_gateway_rejects_non_loopback_server_host(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        serve(host="0.0.0.0", port=0, database=tmp_path / "sessions.db")


def test_run_manager_replays_ordered_events_and_expires_observations():
    manager = RunManager(retention_seconds=0.01)
    run = manager.create("session-1")
    run.publish("tool_call", {"tool_name": "measure_bars"})
    run.complete("done")
    events = list(run.iter_events())
    assert [event.kind for event in events] == ["run_started", "tool_call"]
    assert [event.sequence for event in events] == [1, 2]
    assert [event.kind for event in run.iter_events(1)] == ["tool_call"]
    bounded = RunEvent("run-1", 1, "tool_result", {"result": "x" * 20000})
    assert "truncated" in bounded.to_json()
    assert len(bounded.to_json()) < 13000

    observation_store = ObservationStore(retention_seconds=0)
    reference = observation_store.add(
        "run-1",
        "session-1",
        GeneratedImage(b"overlay", "image/png", "overlay"),
    )
    assert reference is not None
    assert observation_store.get("run-1", "session-1", reference.observation_id) is None
    manager.close()


def test_async_gateway_run_streams_trace_and_scoped_visual_observation(tmp_path):
    database = tmp_path / "sessions.db"

    class FakeAgent:
        def __init__(self, memory, trace_sink, visual_observation_sink):
            self.memory = memory
            self.trace_sink = trace_sink
            self.visual_observation_sink = visual_observation_sink

        def run(self, prompt):
            run = self.memory.begin_run()
            self.memory.append(run, "user", {"text": prompt})
            self.trace_sink(TraceEvent("tool_call", run_id="agent", turn=1, payload={"tool_name": "inspect", "call_id": "c1"}))
            image = GeneratedImage(b"overlay", "image/png", "检测结果")
            refs = self.visual_observation_sink("inspect", "c1", [image])
            self.trace_sink(TraceEvent("visual_observation", run_id="agent", turn=1, payload={"observations": refs}))
            self.memory.append(run, "final", {"answer": "已完成"})
            self.memory.finish(run, RunStatus.COMPLETED, "final")
            return "已完成"

    class FakeRuntime:
        def __init__(self, memory, trace_sink, visual_observation_sink):
            self.agent = FakeAgent(memory, trace_sink, visual_observation_sink)

        def close(self):
            self.agent.memory.close()

    def runtime_factory(name, *, trace_sink=None, visual_observation_sink=None):
        return FakeRuntime(
            SQLiteAgentMemory(name, database=database, create=False),
            trace_sink,
            visual_observation_sink,
        )

    service = GatewayService(database=database, runtime_factory=runtime_factory)
    first_id = service.create_session("first")["session"]["id"]
    second_id = service.create_session("second")["session"]["id"]
    accepted = service.start_run(first_id, "检查图表")
    run_id = accepted["run"]["runId"]
    run = service.get_run(first_id, run_id)
    assert run.wait_terminal(timeout=2)
    events = list(run.iter_events())
    assert [event.kind for event in events] == [
        "run_started",
        "tool_call",
        "visual_observation",
        "final_answer",
    ]
    observation_id = events[2].payload["observations"][0]["observationId"]
    assert service.get_observation(first_id, run_id, observation_id) == (b"overlay", "image/png")
    with pytest.raises(GatewayFault) as isolated:
        service.get_observation(second_id, run_id, observation_id)
    assert isolated.value.code == "run_not_found"
    assert [event.kind for event in run.iter_events(1)] == ["tool_call", "visual_observation", "final_answer"]
    service.close()


def test_http_async_run_returns_sse_stream(tmp_path):
    database = tmp_path / "sessions.db"

    class FakeAgent:
        def __init__(self, memory):
            self.memory = memory

        def run(self, prompt):
            run = self.memory.begin_run()
            self.memory.append(run, "user", {"text": prompt})
            self.memory.append(run, "final", {"answer": "流式完成"})
            self.memory.finish(run, RunStatus.COMPLETED, "final")
            return "流式完成"

    class FakeRuntime:
        def __init__(self, memory):
            self.agent = FakeAgent(memory)

        def close(self):
            self.agent.memory.close()

    service = GatewayService(
        database=database,
        runtime_factory=lambda name: FakeRuntime(SQLiteAgentMemory(name, database=database, create=False)),
    )
    server = GatewayHTTPServer(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, created, _ = _request(port, "POST", "/api/v1/sessions", {"name": "demo"})
        assert status == 200
        session_id = created["session"]["id"]
        status, accepted, _ = _request(
            port,
            "POST",
            f"/api/v1/sessions/{session_id}/runs",
            {"text": "开始"},
        )
        assert status == 202
        run_id = accepted["run"]["runId"]

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", f"/api/v1/sessions/{session_id}/runs/{run_id}/events")
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        connection.close()
        assert response.status == 200
        assert "event: run_started" in raw
        assert "event: final_answer" in raw
        assert '"answer":"流式完成"' in raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_gateway_history_survives_in_memory_run_expiry_and_scopes_artifacts(tmp_path):
    database = tmp_path / "sessions.db"
    service = GatewayService(database=database)
    session_id = service.create_session("history")['session']['id']
    store = GatewayHistoryStore(database, artifact_root=tmp_path / "run-artifacts")
    store.create_run("run_persisted", session_id)
    store.append_event(RunEvent("run_persisted", 1, "tool_call", {"tool_name": "inspect", "call_id": "c1"}))
    store.append_event(RunEvent("run_persisted", 2, "final_answer", {"answer": "# 已完成"}))
    store.update_run("run_persisted", RunStatus.COMPLETED, answer_source="# 已完成")

    history = store.history(session_id, "run_persisted")
    assert history is not None
    assert [item["sequence"] for item in history["events"]] == [1, 2]
    assert history["run"]["answer"] == "# 已完成"

    manager = RunManager(retention_seconds=0.01, history_store=store)
    active = manager.create(session_id)
    active.publish("tool_call", {"tool_name": "inspect", "call_id": "replay"})
    active.complete("恢复完成")
    time.sleep(0.03)
    manager.cleanup()
    restored = manager.historical(session_id, active.run_id)
    assert restored is not None
    assert [event.kind for event in restored.iter_events()] == ["run_started", "tool_call"]
    manager.close()

    restarted = GatewayService(database=database)
    historical = restarted.get_run(session_id, "run_persisted")
    assert historical.status == RunStatus.COMPLETED
    assert [event.kind for event in historical.iter_events()] == ["tool_call", "final_answer"]
    with pytest.raises(GatewayFault) as missing:
        restarted.get_run("other-session", "run_persisted")
    assert missing.value.code == "session_not_found"
    restarted.close()
    service.close()


def test_gateway_history_routes_return_runs_and_cursor_replay(tmp_path):
    database = tmp_path / "sessions.db"

    class FakeAgent:
        def __init__(self, memory):
            self.memory = memory

        def run(self, prompt):
            run = self.memory.begin_run()
            self.memory.append(run, "user", {"text": prompt})
            self.memory.append(run, "final", {"answer": "路由完成"})
            self.memory.finish(run, RunStatus.COMPLETED, "final")
            return "路由完成"

    class FakeRuntime:
        def __init__(self, memory):
            self.agent = FakeAgent(memory)

        def close(self):
            self.agent.memory.close()

    service = GatewayService(
        database=database,
        runtime_factory=lambda name: FakeRuntime(SQLiteAgentMemory(name, database=database, create=False)),
    )
    session_id = service.create_session("history-routes")["session"]["id"]
    server = GatewayHTTPServer(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, accepted, _ = _request(port, "POST", f"/api/v1/sessions/{session_id}/runs", {"text": "开始"})
        assert status == 202
        run_id = accepted["run"]["runId"]
        run = service.get_run(session_id, run_id)
        assert run.wait_terminal(timeout=2)
        status, runs, _ = _request(port, "GET", f"/api/v1/sessions/{session_id}/runs")
        assert status == 200
        assert runs["runs"][0]["runId"] == run_id
        status, history, _ = _request(port, "GET", f"/api/v1/sessions/{session_id}/runs/{run_id}?after=1")
        assert status == 200
        assert [event["sequence"] for event in history["events"]] == [2]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_gateway_history_bounds_payloads_and_cascades_visual_artifacts(tmp_path):
    database = tmp_path / "sessions.db"
    artifact_root = tmp_path / "run-artifacts"
    service = GatewayService(database=database, history_store=GatewayHistoryStore(database, artifact_root=artifact_root, max_events=2))
    session_id = service.create_session("bounded-history")["session"]["id"]
    service._history.create_run("run_bounded", session_id)
    service._history.append_event(RunEvent("run_bounded", 1, "tool_call", {"credentials": "secret", "value": "data:image/png;base64,hidden"}))
    service._history.append_event(RunEvent("run_bounded", 2, "tool_result", {"result": "kept"}))
    service._history.append_event(RunEvent("run_bounded", 3, "final_answer", {"answer": "完成"}))
    history = service._history.history(session_id, "run_bounded")
    assert history is not None
    assert history["historyGap"] is True
    assert [event["sequence"] for event in history["events"]] == [2, 3]
    encoded = json.dumps(history, ensure_ascii=False)
    assert "secret" not in encoded
    assert "data:image" not in encoded

    reference = service._history.add_artifact(
        "run_bounded",
        session_id,
        GeneratedImage(b"overlay", "image/png", "安全观察"),
    )
    assert reference is not None
    artifact_path = artifact_root / session_id / (reference["observationId"] + ".bin")
    assert artifact_path.is_file()
    assert service.get_observation(session_id, "run_bounded", reference["observationId"]) == (b"overlay", "image/png")
    artifact_path.write_bytes(b"tampered")
    # A modified managed file is rejected by the hash check.
    assert service._history.get_artifact(session_id, "run_bounded", reference["observationId"]) is None
    assert service.delete_session(session_id)["deleted"] is True
    assert not artifact_path.exists()
    service.close()


def test_generated_chart_artifact_is_distinct_authorized_and_reloadable(tmp_path):
    database = tmp_path / "sessions.db"
    artifact_root = tmp_path / "run-artifacts"
    store = GatewayHistoryStore(database, artifact_root=artifact_root)
    service = GatewayService(database=database, history_store=store)
    first_id = service.create_session("chart-owner")["session"]["id"]
    second_id = service.create_session("other-owner")["session"]["id"]
    store.create_run("run_chart", first_id)
    image = GeneratedImage(
        b"chart-bytes",
        "image/png",
        "生成图表：销售趋势",
        metadata={
            "kind": "generated_chart",
            "chart_type": "line",
            "title": "销售趋势",
            "width": 1200,
            "height": 800,
        },
    )
    reference = store.add_artifact("run_chart", first_id, image)
    assert reference is not None
    assert reference["artifactKind"] == "generated_chart"
    assert reference["artifactId"].startswith("artifact_")
    assert "observationId" not in reference
    assert reference["chartType"] == "line"
    assert service.get_generated_artifact(first_id, "run_chart", reference["artifactId"]) == (b"chart-bytes", "image/png")
    with pytest.raises(GatewayFault) as legacy_route:
        service.get_observation(first_id, "run_chart", reference["artifactId"])
    assert legacy_route.value.code == "observation_not_found"
    with pytest.raises(GatewayFault) as cross_session:
        service.get_generated_artifact(second_id, "run_chart", reference["artifactId"])
    assert cross_session.value.code == "run_unavailable"

    reloaded = GatewayHistoryStore(database, artifact_root=artifact_root)
    assert reloaded.get_artifact(first_id, "run_chart", reference["artifactId"], artifact_kind="generated_chart") == (b"chart-bytes", "image/png")
    service.close()
    reloaded.close()


def test_generated_chart_http_artifact_route_and_session_cascade(tmp_path):
    database = tmp_path / "sessions.db"
    store = GatewayHistoryStore(database, artifact_root=tmp_path / "run-artifacts")
    service = GatewayService(database=database, history_store=store)
    first_id = service.create_session("chart-http")["session"]["id"]
    second_id = service.create_session("chart-safe")["session"]["id"]
    store.create_run("run_http", first_id)
    store.create_run("run_safe", second_id)
    first = store.add_artifact(
        "run_http",
        first_id,
        GeneratedImage(b"first", "image/png", "第一张", metadata={"kind": "generated_chart", "chart_type": "bar", "title": "第一张", "width": 640, "height": 480}),
    )
    second = store.add_artifact(
        "run_safe",
        second_id,
        GeneratedImage(b"second", "image/png", "第二张", metadata={"kind": "generated_chart", "chart_type": "pie", "title": "第二张", "width": 640, "height": 480}),
    )
    assert first and second
    server = GatewayHTTPServer(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", f"/api/v1/sessions/{first_id}/runs/run_http/artifacts/{first['artifactId']}")
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        assert response.status == 200
        assert raw == b"first"
        status, body, _ = _request(port, "GET", f"/api/v1/sessions/{first_id}/runs/run_http/observations/{first['artifactId']}")
        assert status == 404
        assert body["error"]["code"] == "observation_not_found"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert service.delete_session(first_id)["deleted"] is True
    assert store.get_artifact(second_id, "run_safe", second["artifactId"], artifact_kind="generated_chart") == (b"second", "image/png")
    service.close()


def test_generated_chart_artifact_expires_without_becoming_readable(tmp_path):
    database = tmp_path / "sessions.db"
    store = GatewayHistoryStore(database, artifact_root=tmp_path / "run-artifacts", retention_seconds=0)
    service = GatewayService(database=database, history_store=store)
    session_id = service.create_session("chart-expiry")["session"]["id"]
    store.create_run("run_expiry", session_id)
    reference = store.add_artifact(
        "run_expiry",
        session_id,
        GeneratedImage(b"expired", "image/png", "过期图表", metadata={"kind": "generated_chart", "chart_type": "scatter", "title": "过期图表", "width": 640, "height": 480}),
    )
    assert reference is not None
    assert store.get_artifact(session_id, "run_expiry", reference["artifactId"], artifact_kind="generated_chart") is None
    service.close()


def test_async_gateway_orders_generated_chart_event_after_tool_result(tmp_path):
    database = tmp_path / "sessions.db"

    class FakeAgent:
        def __init__(self, memory, trace_sink, visual_observation_sink):
            self.memory = memory
            self.trace_sink = trace_sink
            self.visual_observation_sink = visual_observation_sink

        def run(self, prompt):
            run = self.memory.begin_run()
            image = GeneratedImage(
                b"generated-chart",
                "image/png",
                "生成图表：趋势",
                metadata={"kind": "generated_chart", "chart_type": "line", "title": "趋势", "width": 1200, "height": 800},
            )
            self.trace_sink(TraceEvent("tool_call", run_id="agent", turn=1, payload={"tool_name": "render_chart", "call_id": "c1"}))
            self.trace_sink(TraceEvent("tool_result", run_id="agent", turn=1, payload={"tool_name": "render_chart", "call_id": "c1", "status": "success"}))
            refs = self.visual_observation_sink("render_chart", "c1", [image])
            self.trace_sink(TraceEvent("generated_chart", run_id="agent", turn=1, payload={"tool_name": "render_chart", "call_id": "c1", "artifacts": refs}))
            self.memory.append(run, "final", {"answer": "已重绘"})
            self.memory.finish(run, RunStatus.COMPLETED, "final")
            return "已重绘"

    class FakeRuntime:
        def __init__(self, memory, trace_sink, visual_observation_sink):
            self.agent = FakeAgent(memory, trace_sink, visual_observation_sink)

        def close(self):
            self.agent.memory.close()

    def runtime_factory(name, *, trace_sink=None, visual_observation_sink=None):
        return FakeRuntime(SQLiteAgentMemory(name, database=database, create=False), trace_sink, visual_observation_sink)

    service = GatewayService(database=database, runtime_factory=runtime_factory)
    session_id = service.create_session("generated-run")["session"]["id"]
    accepted = service.start_run(session_id, "生成图表")
    run = service.get_run(session_id, accepted["run"]["runId"])
    assert run.wait_terminal(timeout=2)
    events = list(run.iter_events())
    assert [event.kind for event in events] == ["run_started", "tool_call", "tool_result", "generated_chart", "final_answer"]
    reference = events[3].payload["artifacts"][0]
    assert reference["artifactKind"] == "generated_chart"
    assert service.get_generated_artifact(session_id, run.run_id, reference["artifactId"]) == (b"generated-chart", "image/png")
    service.close()
