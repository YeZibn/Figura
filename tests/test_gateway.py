"""Offline tests for the local ChartAgent gateway."""

from __future__ import annotations

import http.client
import hashlib
import io
import json
import threading
from pathlib import Path
from urllib.parse import quote

import pytest
from PIL import Image

from chartagent.attachments import AttachmentRegistry
from chartagent.gateway.attachments import AttachmentStoreError, EphemeralAttachmentStore
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
    assert "secret-key" not in error.value.message
    assert service.get_session(session_id)["messages"] == []


def test_attachment_upload_projects_safe_metadata_and_cleans_on_restart(tmp_path):
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

    # A new Gateway process owns a fresh temporary root. SQLite keeps the safe
    # reference, while the source becomes unavailable and can be re-uploaded.
    restarted = GatewayService(database=database, attachment_root=attachment_root)
    assert restarted.get_session(session_id)["attachments"][0]["status"] == "unavailable"


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
