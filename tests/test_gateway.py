"""Offline tests for the local ChartAgent gateway."""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from chartagent.attachments import AttachmentRegistry
from chartagent.gateway.protocol import GatewayFault, validate_message_text, validate_session_name
from chartagent.gateway.projection import project_completed_runs
from chartagent.gateway.server import GatewayHTTPServer, serve
from chartagent.gateway.service import GatewayService
from chartagent.memory import SQLiteAgentMemory, RunStatus
from chartagent.memory.models import Record, Run
from chartagent.runtime import AgentRuntime


def _completed_run(run_id: str, text: str = "问题", answer: str = "答案") -> Run:
    run = Run(run_id, "session", 1, RunStatus.COMPLETED)
    run.records = [
        Record("user", {"text": text}, created_at="2026-09-10T10:00:00+00:00"),
        Record("tool", {"result": "/private/chart.png", "credentials": "secret"}),
        Record("final", {"answer": answer}, created_at="2026-09-10T10:00:01+00:00"),
    ]
    return run


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
