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
from chartagent.gateway.protocol import GatewayFault, RunEvent, validate_message_text, validate_provider, validate_session_name
from chartagent.gateway.projection import project_completed_runs
from chartagent.gateway.server import GatewayHTTPServer, serve
from chartagent.gateway.service import GatewayService
from chartagent.gateway.runs import ObservationStore, RunManager
from chartagent.memory import SQLiteAgentMemory, RunStatus
from chartagent.memory.models import Record, Run
from chartagent.runtime import AgentRuntime
import chartagent.runtime.readiness as readiness_module
from chartagent.tools.core.result import GeneratedImage
from chartagent.trace import TraceEvent
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.tools import Tool, ToolRegistry, ToolResult
from chartagent.tools.chart import register_chart_tools
from chartagent.agent.review_gate import _BUDGET_MSG
from tests.test_dashboard_decomposition import COMPLEX_IMAGE, REGIONS


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


def test_gateway_health_sanitizes_provider_statuses():
    service = GatewayService(
        readiness_probe=lambda: {
            "status": "ready",
            "provider": "openai",
            "providers": {
                "openai": {"status": "ready", "model": "relay-model"},
                "qwen": {"status": "unavailable", "reason": "QWEN_API_KEY=sentinel-secret"},
            },
        }
    )

    health = service.health()

    assert health["agent"]["providers"]["qwen"] == {
        "status": "unavailable",
        "provider": "qwen",
        "reason": "initialization_failed",
    }
    assert "sentinel-secret" not in json.dumps(health)


def test_agent_readiness_rejects_invalid_default_provider(monkeypatch):
    monkeypatch.setenv("CHARTAGENT_PROVIDER", "unsupported-provider")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    monkeypatch.setattr(readiness_module, "load_environment", lambda: None)

    result = readiness_module.probe_agent_readiness()

    assert result == {
        "status": "unavailable",
        "reason": "invalid_configuration",
        "providers": {},
    }


def test_gateway_readiness_failure_is_bounded_before_run(tmp_path):
    called = False

    def runtime_factory(name, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("runtime must not be constructed")

    service = GatewayService(
        database=tmp_path / "sessions.db",
        runtime_factory=runtime_factory,
        readiness_probe=lambda: (_ for _ in ()).throw(RuntimeError("probe failed")),
    )
    session_id = service.create_session("readiness-failure")["session"]["id"]

    with pytest.raises(GatewayFault) as error:
        service.start_run(session_id, "hello")

    assert error.value.code == "agent_unavailable"
    assert error.value.reason == "initialization_failed"
    assert called is False


def test_gateway_provider_selection_is_snapshotted_and_persisted(tmp_path):
    database = tmp_path / "sessions.db"
    captured: list[dict[str, object]] = []

    class FakeAgent:
        def run(self, text):
            return "provider run complete"

    class FakeRuntime:
        agent = FakeAgent()

        def close(self):
            return None

    def runtime_factory(name, *, provider=None, model=None, run_id=None, trace_sink=None, visual_observation_sink=None):
        captured.append({"name": name, "provider": provider, "model": model, "run_id": run_id})
        return FakeRuntime()

    readiness = lambda: {
        "status": "ready",
        "provider": "openai",
        "providers": {
            "openai": {"status": "ready", "provider": "openai", "model": "relay-model"},
            "qwen": {"status": "ready", "provider": "qwen", "model": "qwen3.8-flash"},
            "deepseek": {"status": "ready", "provider": "deepseek", "model": "deepseek-flash"},
        },
    }
    service = GatewayService(database=database, runtime_factory=runtime_factory, readiness_probe=readiness)
    session_id = service.create_session("provider-selection")["session"]["id"]
    accepted = service.start_run(session_id, "use qwen", raw_provider="qwen")
    run_id = accepted["run"]["runId"]
    run = service.get_run(session_id, run_id)
    assert run.wait_terminal(timeout=2)
    assert accepted["run"]["provider"] == "qwen"
    assert accepted["run"]["model"] == "qwen3.8-flash"
    assert captured[0]["provider"] == "qwen"
    assert captured[0]["model"] == "qwen3.8-flash"
    history = service.get_run_history(session_id, run_id)
    assert history["run"]["provider"] == "qwen"
    assert history["run"]["model"] == "qwen3.8-flash"
    assert history["events"][0]["payload"]["provider"] == "qwen"
    assert history["events"][0]["payload"]["model"] == "qwen3.8-flash"


def test_gateway_provider_selection_snapshots_deepseek_model(tmp_path):
    captured: list[dict[str, object]] = []

    class FakeAgent:
        def run(self, text):
            return "deepseek run complete"

    class FakeRuntime:
        agent = FakeAgent()

        def close(self):
            return None

    def runtime_factory(name, *, provider=None, model=None, run_id=None, **kwargs):
        captured.append({"provider": provider, "model": model})
        return FakeRuntime()

    service = GatewayService(
        database=tmp_path / "deepseek.db",
        runtime_factory=runtime_factory,
        readiness_probe=lambda: {
            "status": "ready",
            "provider": "openai",
            "providers": {
                "openai": {"status": "ready", "provider": "openai", "model": "relay-model"},
                "qwen": {"status": "unavailable", "reason": "missing_configuration"},
                "deepseek": {"status": "ready", "provider": "deepseek", "model": "deepseek-flash"},
            },
        },
    )
    session_id = service.create_session("deepseek-selection")["session"]["id"]
    accepted = service.start_run(session_id, "use deepseek", raw_provider="deepseek")
    run = service.get_run(session_id, accepted["run"]["runId"])
    assert run.wait_terminal(timeout=2)
    assert accepted["run"]["provider"] == "deepseek"
    assert accepted["run"]["model"] == "deepseek-flash"
    assert captured == [{"provider": "deepseek", "model": "deepseek-flash"}]


def test_gateway_rejects_unavailable_provider_before_runtime(tmp_path):
    database = tmp_path / "sessions.db"
    called = False

    def runtime_factory(name, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("runtime must not be constructed")

    service = GatewayService(
        database=database,
        runtime_factory=runtime_factory,
        readiness_probe=lambda: {
            "status": "ready",
            "provider": "openai",
            "providers": {
                "openai": {"status": "ready", "model": "relay-model"},
                "qwen": {"status": "unavailable", "reason": "missing_configuration"},
            },
        },
    )
    session_id = service.create_session("provider-unavailable")["session"]["id"]
    with pytest.raises(GatewayFault) as error:
        service.start_run(session_id, "run", raw_provider="qwen")
    assert error.value.code == "agent_unavailable"
    assert error.value.reason == "missing_configuration"
    assert called is False


def test_gateway_provider_validation_is_bounded():
    assert validate_provider(" QWEN ") == "qwen"
    with pytest.raises(GatewayFault) as error:
        validate_provider({"provider": "qwen"})
    assert error.value.code == "invalid_provider"


def test_gateway_idempotency_reuses_accepted_run_and_rejects_conflicts(tmp_path):
    database = tmp_path / "sessions.db"
    calls = 0

    class FakeAgent:
        def run(self, prompt):
            nonlocal calls
            calls += 1
            return "幂等完成"

    class FakeRuntime:
        agent = FakeAgent()

        def close(self):
            return None

    service = GatewayService(
        database=database,
        runtime_factory=lambda name, **kwargs: FakeRuntime(),
        readiness_probe=lambda: {"status": "ready", "provider": "openai", "model": "test-model"},
    )
    session_id = service.create_session("idempotency")['session']['id']

    first = service.start_run(session_id, "同一请求", raw_idempotency_key="intent-1")
    duplicate = service.start_run(session_id, "同一请求", raw_idempotency_key="intent-1")
    assert duplicate["run"]["runId"] == first["run"]["runId"]
    assert calls == 1

    with pytest.raises(GatewayFault) as conflict:
        service.start_run(session_id, "另一请求", raw_idempotency_key="intent-1")
    assert conflict.value.code == "idempotency_conflict"
    service.close()


def test_gateway_inherits_persisted_active_source_for_follow_up_prompt(tmp_path):
    database = tmp_path / "sessions.db"
    source = tmp_path / "source.png"
    source.write_bytes(_png_bytes())
    service = GatewayService(database=database, readiness_probe=lambda: {"status": "ready"})
    session_id = service.create_session("active-source")['session']['id']
    memory = SQLiteAgentMemory("active-source", database=database, create=False)
    try:
        registry = AttachmentRegistry(
            session_id=memory.session.id,
            save=memory.save_attachment,
            load=memory.get_attachment,
        )
        attachment = registry.register(str(source))
        memory.set_active_source([attachment.id])
    finally:
        memory.close()

    session, prompt, resolved = service._prepare_prompt(session_id, "继续分析", [])
    assert session.id == session_id
    assert resolved == (attachment.id,)
    assert attachment.id in prompt
    service.close()


def test_gateway_dashboard_follow_up_reuses_panel_and_measures_local_scope(tmp_path):
    database = tmp_path / "dashboard-reuse.db"
    service = GatewayService(database=database, readiness_probe=lambda: {"status": "ready"})
    session_id = service.create_session("dashboard-reuse")['session']['id']
    uploaded = service.upload_attachment(session_id, "dashboard.png", "image/png", COMPLEX_IMAGE.read_bytes())
    attachment_id = uploaded["attachment"]["attachment_id"]
    tool_names: list[str] = []
    panel_id: str | None = None
    runtime_number = 0

    class ScriptedClient:
        def __init__(self, follow_up: bool):
            self.follow_up = follow_up
            self.steps = 0

        def chat(self, messages, **_kwargs):
            nonlocal panel_id
            self.steps += 1
            if self.steps > 1:
                return NormalizedResult(content="已完成")
            if self.follow_up:
                assert panel_id
                name = "measure_bars"
                arguments = {"attachment_id": attachment_id, "panel_id": panel_id}
            else:
                name = "decompose_chart_image"
                arguments = {"attachment_id": attachment_id, "regions": REGIONS}
            tool_names.append(name)
            return NormalizedResult(tool_calls=[ToolCall(f"call-{len(tool_names)}", name, json.dumps(arguments, ensure_ascii=False))])

    def runtime_factory(name, *, run_id, trace_sink, visual_observation_sink):
        nonlocal runtime_number
        runtime_number += 1
        memory = SQLiteAgentMemory(name, database=database, create=False)
        attachments = AttachmentRegistry(
            session_id=memory.session.id,
            save=memory.save_attachment,
            load=memory.get_attachment,
            panel_store=memory,
        )
        registry = ToolRegistry()
        register_chart_tools(registry, attachments=attachments)
        agent = Agent(
            ScriptedClient(runtime_number > 1),
            registry,
            memory=memory,
            run_id=run_id,
            trace=trace_sink,
            visual_observation_sink=visual_observation_sink,
            attachments=attachments,
        )
        return AgentRuntime(agent, memory, attachments)

    service._runtime_factory = runtime_factory
    first = service.start_run(session_id, "拆解 dashboard", [attachment_id], raw_idempotency_key="dashboard-1")
    first_run = service.get_run(session_id, first["run"]["runId"])
    assert first_run.wait_terminal(timeout=8)
    memory = SQLiteAgentMemory("dashboard-reuse", database=database, create=False)
    try:
        handoffs = memory.list_panel_handoffs(attachment_id)
        assert handoffs, [(event.kind, event.payload) for event in first_run.iter_events()]
        panel_id = handoffs[0].panel_id
    finally:
        memory.close()

    second = service.start_run(session_id, "测量刚才的柱状图", [], raw_idempotency_key="dashboard-2")
    second_run = service.get_run(session_id, second["run"]["runId"])
    assert second_run.wait_terminal(timeout=8)
    assert tool_names == ["decompose_chart_image", "measure_bars"]
    measurement = next(event for event in second_run.iter_events() if event.kind == "tool_result" and event.payload.get("tool_name") == "measure_bars")
    result = measurement.payload["result"]
    assert "data" in result, result
    assert result["data"]["scope"]["mode"] == "panel"
    assert result["data"]["scope"]["local_image_size"][0] < result["data"]["scope"]["source_image_size"][0]
    service.close()


def test_gateway_concurrent_equivalent_submissions_share_one_run(tmp_path):
    database = tmp_path / "sessions.db"
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    class BlockingAgent:
        def run(self, prompt):
            nonlocal calls
            with calls_lock:
                calls += 1
            started.set()
            release.wait(timeout=2)
            return "并发请求完成"

    class FakeRuntime:
        agent = BlockingAgent()

        def close(self):
            return None

    service = GatewayService(
        database=database,
        runtime_factory=lambda name, **kwargs: FakeRuntime(),
        readiness_probe=lambda: {"status": "ready", "provider": "openai", "model": "test-model"},
    )
    session_id = service.create_session("concurrent-idempotency")["session"]["id"]
    results = []
    errors = []

    def submit():
        try:
            results.append(service.start_run(session_id, "同一个并发请求", raw_idempotency_key="concurrent-1"))
        except Exception as exc:  # pragma: no cover - assertion below reports unexpected failures
            errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    assert not errors
    assert len(results) == 2
    assert results[0]["run"]["runId"] == results[1]["run"]["runId"]
    assert started.wait(timeout=2)
    assert calls == 1
    release.set()
    assert service.get_run(session_id, results[0]["run"]["runId"]).wait_terminal(timeout=2)
    service.close()


def test_gateway_worker_submit_failure_is_terminal_and_replayable(tmp_path):
    database = tmp_path / "sessions.db"
    service = GatewayService(
        database=database,
        runtime_factory=lambda name, **kwargs: pytest.fail("worker must not construct a runtime"),
        readiness_probe=lambda: {"status": "ready", "provider": "openai", "model": "test-model"},
    )
    service._runs._executor.submit = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("submit failed"))
    session_id = service.create_session("worker-submit-failure")["session"]["id"]

    accepted = service.start_run(session_id, "提交失败", raw_idempotency_key="submit-failure-1")
    assert accepted["run"]["status"] == "failed"
    run_id = accepted["run"]["runId"]
    history = service.get_run_history(session_id, run_id)
    assert history["run"]["terminalCode"] == "worker_error"
    assert [event["kind"] for event in history["events"]] == ["run_started", "run_failed"]
    duplicate = service.start_run(session_id, "提交失败", raw_idempotency_key="submit-failure-1")
    assert duplicate["run"]["runId"] == run_id
    service.close()


def test_gateway_restart_recovery_persists_interruption_event(tmp_path):
    database = tmp_path / "sessions.db"
    store = GatewayHistoryStore(database)
    memory = SQLiteAgentMemory("restart-recovery", database=database)
    session_id = memory.session.id
    store.create_run("run_restart", session_id)
    store.append_event(RunEvent("run_restart", 1, "model_started", {"turn": 1}))
    memory.close()

    service = GatewayService(database=database)
    run = service.get_run(session_id, "run_restart")
    assert run.status.value == "interrupted"
    assert run.error_code == "gateway_restarted"
    assert [event.kind for event in run.iter_events()] == ["model_started", "run_interrupted"]
    service.close()


def test_gateway_retry_creates_new_identity_and_preserves_parent(tmp_path):
    database = tmp_path / "sessions.db"

    class FakeAgent:
        def run(self, prompt):
            return "重试完成"

    class FakeRuntime:
        agent = FakeAgent()

        def close(self):
            return None

    service = GatewayService(
        database=database,
        runtime_factory=lambda name, **kwargs: FakeRuntime(),
        readiness_probe=lambda: {"status": "ready", "provider": "openai", "model": "test-model"},
    )
    session_id = service.create_session("retry-lineage")["session"]["id"]
    parent = service.start_run(session_id, "第一次", raw_idempotency_key="retry-parent")
    parent_id = parent["run"]["runId"]
    assert service.get_run(session_id, parent_id).wait_terminal(timeout=2)
    child = service.start_run(
        session_id,
        "第一次",
        raw_idempotency_key="retry-child",
        raw_retry_of=parent_id,
    )
    child_id = child["run"]["runId"]
    assert child_id != parent_id
    assert child["run"]["retryOf"] == parent_id
    assert service.start_run(
        session_id,
        "第一次",
        raw_idempotency_key="retry-child",
        raw_retry_of=parent_id,
    )["run"]["runId"] == child_id
    assert service.get_run(session_id, child_id).wait_terminal(timeout=2)
    assert service._history.get_run(session_id, child_id)["retryOf"] == parent_id
    service.close()


def test_managed_run_interrupt_is_terminal_and_blocks_late_events(tmp_path):
    store = GatewayHistoryStore(tmp_path / "sessions.db")
    memory = SQLiteAgentMemory("interrupt", database=tmp_path / "sessions.db")
    manager = RunManager(history_store=store)
    run = manager.create(memory.session.id)
    run.publish(
        "tool_call",
        {
            "unit_id": "observation:slow-call",
            "unit_type": "observation",
            "phase": "action",
            "actor": "tool",
            "role": "action",
            "transition_id": "observation:slow-call:started",
            "state": "running",
            "tool_name": "slow_tool",
            "call_id": "slow-call",
        },
    )

    assert run.interrupt() is True
    assert run.status.value == "interrupted"
    assert run.interrupt() is False
    assert run.publish("final_answer", {"answer": "迟到结果"}) is None
    assert [event.kind for event in run.iter_events()] == ["run_started", "tool_call", "run_interrupted"]
    history = store.history(memory.session.id, run.run_id)
    assert history is not None
    assert history["run"]["status"] == "interrupted"
    assert history["run"]["terminalCode"] == "user_cancelled"
    memory.close()
    manager.close()


def test_gateway_replays_measurement_repair_events_and_checkpoint_after_reconnect(tmp_path):
    database = tmp_path / "measurement-repair-replay.db"
    store = GatewayHistoryStore(database)
    memory = SQLiteAgentMemory("measurement-repair-replay", database=database)
    manager = RunManager(history_store=store)
    run = manager.create(memory.session.id)
    parent_attempt = "matt_parent"
    target = {
        "target_id": "baseline-focus",
        "panel_id": "panel_bars",
        "parent_attempt_id": parent_attempt,
        "region_kind": "baseline",
        "fields": ["baseline", "bars.measure"],
        "bbox_source_px": [120, 300, 420, 36],
        "source_image_size": [640, 480],
        "reason": "复查 /Users/yezibin/Project/Figura/private-chart.png",
    }
    run.publish(
        "measurement_repair_required",
        {
            "attachment_id": "att_eval",
            "unit_id": "measurement:matt_parent",
            "unit_type": "measurement",
            "phase": "repair",
            "actor": "system",
            "role": "gate",
            "transition_id": "measurement:matt_parent:repair_required",
            "panel_id": "panel_bars",
            "parent_attempt_id": parent_attempt,
            "target": target,
            "status": "available",
            "next_action": "在同一 panel 内重新测量",
        },
    )
    checkpoint = run.create_checkpoint(
        {
            "measurementSessions": {
                "ms_eval": {
                    "session_id": "ms_eval",
                    "attachment_id": "att_eval",
                    "panel_id": "panel_bars",
                    "current_attempt_id": parent_attempt,
                    "max_repair_attempts": 3,
                    "attempts": [],
                }
            },
            "pendingMeasurementRepair": {
                "status": "available",
                "parent_attempt_id": parent_attempt,
                "target": target,
            },
        },
        phase="tool",
        next_action="model",
    )
    assert checkpoint is True
    run.publish(
        "measurement_repair_exhausted",
        {
            "attachment_id": "att_eval",
            "unit_id": "measurement:matt_parent",
            "unit_type": "measurement",
            "phase": "repair",
            "actor": "system",
            "role": "gate",
            "transition_id": "measurement:matt_parent:repair_exhausted",
            "panel_id": "panel_bars",
            "parent_attempt_id": parent_attempt,
            "status": "exhausted",
            "next_action": "保留失败证据并停止定向重测",
        },
    )
    run.complete("未发布")

    history = store.get_checkpoint(memory.session.id, run.run_id)
    assert history is not None
    assert history.state["pendingMeasurementRepair"]["status"] == "available"
    assert "/Users/yezibin/Project/Figura" not in json.dumps(history.state)

    events = list(run.iter_events(after_sequence=1))
    assert [event.kind for event in events] == [
        "measurement_repair_required",
        "measurement_repair_exhausted",
    ]
    assert events[0].payload["target"]["target_id"] == "baseline-focus"
    assert "/Users/yezibin/Project/Figura" not in json.dumps(events[0].payload)

    memory.close()
    manager.close()


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


@pytest.mark.parametrize(
    ("event_kind", "expected_code"),
    [
        ("measurement_repair_exhausted", "measurement_repair_exhausted"),
        ("assembly_validation_failure", "assembly_validation_failure"),
    ],
)
def test_gateway_classifies_bounded_evidence_terminal_failures(tmp_path, event_kind, expected_code):
    database = tmp_path / f"{event_kind}.db"

    class FakeAgent:
        def __init__(self, trace_sink):
            self.trace_sink = trace_sink

        def run(self, _text):
            self.trace_sink(
                TraceEvent(
                    event_kind,
                    payload={
                        "unit_id": "measurement:fake" if event_kind.startswith("measurement_") else "generation:fake",
                        "unit_type": "measurement" if event_kind.startswith("measurement_") else "generation",
                        "phase": "repair" if event_kind.startswith("measurement_") else "assemble",
                        "actor": "system" if event_kind.startswith("measurement_") else "tool",
                        "role": "gate" if event_kind.startswith("measurement_") else "action",
                        "transition_id": f"fake:{event_kind}",
                        "state": "exhausted" if event_kind.startswith("measurement_") else "failed",
                        "tool_name": "assemble_spec",
                        "blocking": False,
                    },
                )
            )
            return _BUDGET_MSG

    class FakeRuntime:
        def __init__(self, trace_sink):
            self.agent = FakeAgent(trace_sink)

        def close(self):
            return None

    def runtime_factory(name, *, trace_sink, **_kwargs):
        return FakeRuntime(trace_sink)

    service = GatewayService(
        database=database,
        runtime_factory=runtime_factory,
        readiness_probe=lambda: {"status": "ready", "provider": "openai", "model": "test-model"},
    )
    session_id = service.create_session(event_kind)["session"]["id"]
    accepted = service.start_run(session_id, "触发边界失败")
    run = service.get_run(session_id, accepted["run"]["runId"])
    assert run.wait_terminal(timeout=2)
    assert run.error_code == expected_code
    history = service.get_run_history(session_id, run.run_id)
    assert history["run"]["terminalCode"] == expected_code
    assert any(event["kind"] == event_kind for event in history["events"])
    assert history["events"][-1]["kind"] == "run_failed"
    assert history["events"][-1]["payload"]["code"] == expected_code
    service.close()


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
    assert failure.payload["code"] == "agent_unavailable"
    assert failure.payload["reason"] == "missing_configuration"
    assert failure.payload["message"] == "Agent service is unavailable"
    assert failure.payload["process_id"] == "run"
    assert failure.payload["failure_category"] == "agent_setup"
    assert failure.payload["failure_code"] == "agent_unavailable"
    assert failure.payload["safe_message"] == "Agent service is unavailable"
    assert failure.payload["outcome_known"] is True
    assert failure.payload["first_failure_ref"] == {"kind": "run_failed", "stage": "setup"}


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


def _request(port: int, method: str, path: str, payload=None, *, origin=None, extra_headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if origin:
        headers["Origin"] = origin
    if extra_headers:
        headers.update(extra_headers)
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
    run.publish(
        "tool_call",
        {
            "unit_id": "measurement:measure-call",
            "unit_type": "measurement",
            "phase": "action",
            "actor": "tool",
            "role": "action",
            "transition_id": "measurement:measure-call:started",
            "state": "running",
            "tool_name": "measure_bars",
            "call_id": "measure-call",
        },
    )
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


def test_oversized_tool_result_retains_outer_call_identity():
    event = RunEvent(
        "run-identity",
        7,
        "tool_result",
        {
            "tool_name": "extract_line_series",
            "call_id": "line-call-7",
            "status": "success",
            "tool_status": "success",
            "turn": 3,
            "correlation_version": 1,
            "unit_id": "observation:line-call-7",
            "unit_type": "observation",
            "phase": "action",
            "actor": "tool",
            "role": "action",
            "parent_unit_id": "generation:candidate-1",
            "transition_id": "transition:line-call-7",
            "next_action": {"required": False, "allowed": ["decide"], "blocked": []},
            "result": {"polyline": ["trace-" + ("x" * 2000) for _ in range(32)]},
        },
    )
    payload = event.to_dict()["payload"]
    assert payload["tool_name"] == "extract_line_series"
    assert payload["call_id"] == "line-call-7"
    assert payload["status"] == "success"
    assert payload["turn"] == 3
    assert payload["unit_id"] == "observation:line-call-7"
    assert payload["parent_unit_id"] == "generation:candidate-1"
    assert payload["transition_id"] == "transition:line-call-7"
    assert payload["result"]["truncated"] is True
    assert len(event.to_json()) <= 13000


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
            self.trace_sink(TraceEvent("tool_call", run_id="agent", turn=1, payload={"unit_id": "observation:c1", "unit_type": "observation", "phase": "action", "actor": "tool", "role": "action", "transition_id": "observation:c1:started", "state": "running", "tool_name": "inspect", "call_id": "c1"}))
            image = GeneratedImage(b"overlay", "image/png", "检测结果")
            refs = self.visual_observation_sink("inspect", "c1", [image])
            self.trace_sink(TraceEvent("visual_observation", run_id="agent", turn=1, payload={"unit_id": "observation:c1", "unit_type": "observation", "phase": "observe", "actor": "tool", "role": "observation", "transition_id": "observation:c1:observed", "state": "observed", "tool_name": "inspect", "call_id": "c1", "observations": refs}))
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


def test_http_idempotency_and_interrupt_route(tmp_path):
    database = tmp_path / "sessions.db"
    started = threading.Event()
    release = threading.Event()
    calls = 0

    class BlockingAgent:
        def run(self, prompt):
            nonlocal calls
            calls += 1
            started.set()
            release.wait(timeout=2)
            return "不应发布"

    class FakeRuntime:
        agent = BlockingAgent()

        def close(self):
            return None

    service = GatewayService(
        database=database,
        runtime_factory=lambda name, **kwargs: FakeRuntime(),
        readiness_probe=lambda: {"status": "ready", "provider": "openai", "model": "test-model"},
    )
    server = GatewayHTTPServer(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, created, _ = _request(port, "POST", "/api/v1/sessions", {"name": "interrupt-http"})
        assert status == 200
        session_id = created["session"]["id"]
        key = "http-intent-1"
        status, first, _ = _request(
            port,
            "POST",
            f"/api/v1/sessions/{session_id}/runs",
            {"text": "等待"},
            extra_headers={"Idempotency-Key": key},
        )
        assert status == 202
        run_id = first["run"]["runId"]
        assert started.wait(timeout=2)
        status, duplicate, _ = _request(
            port,
            "POST",
            f"/api/v1/sessions/{session_id}/runs",
            {"text": "等待"},
            extra_headers={"Idempotency-Key": key},
        )
        assert status == 202
        assert duplicate["run"]["runId"] == run_id
        assert calls == 1
        status, interrupted, _ = _request(
            port,
            "POST",
            f"/api/v1/sessions/{session_id}/runs/{run_id}/interrupt",
            {},
        )
        assert status == 200
        assert interrupted["run"]["status"] == "interrupted"
        release.set()
        status, history, _ = _request(
            port,
            "GET",
            f"/api/v1/sessions/{session_id}/runs/{run_id}",
        )
        assert status == 200
        assert history["run"]["status"] == "interrupted"
        assert any(event["kind"] == "run_interrupted" for event in history["events"])
    finally:
        release.set()
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
    active.publish("tool_call", {"unit_id": "observation:replay", "unit_type": "observation", "phase": "action", "actor": "tool", "role": "action", "transition_id": "observation:replay:started", "state": "running", "tool_name": "inspect", "call_id": "replay"})
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


def test_gateway_replays_scope_lifecycle_fields_without_merging_event_kinds(tmp_path):
    database = tmp_path / "scope-history.db"
    service = GatewayService(database=database)
    session_id = service.create_session("scope-history")['session']['id']
    store = GatewayHistoryStore(database, artifact_root=tmp_path / "run-artifacts")
    run_id = "run_scope_history"
    store.create_run(run_id, session_id)
    scope = {"attachment_id": "att_source", "panel_ids": ["panel_left"], "revision": 3}
    common = {
        "candidate_id": "cand_scope",
        "attempt": 2,
        "parent_attempt": "cand_parent",
        "source_scope": scope,
    }
    store.append_event(RunEvent(run_id, 1, "measurement_observed", {**common, "unit_id": "measurement:matt_scope", "unit_type": "measurement", "phase": "observe", "actor": "tool", "role": "observation", "state": "partial", "transition_id": "measurement:matt_scope:observed"}))
    store.append_event(RunEvent(run_id, 2, "measurement_evidence_selected", {**common, "unit_id": "measurement:matt_scope", "unit_type": "measurement", "phase": "decide", "actor": "agent", "role": "decision", "state": "selected", "transition_id": "measurement:matt_scope:selected", "refs": ["B1"]}))
    store.append_event(RunEvent(run_id, 3, "review_started", {**common, "unit_id": "review:review_scope", "unit_type": "review", "phase": "review", "actor": "system", "role": "review", "review_id": "review_scope", "review_type": "generated_chart", "state": "reviewing", "transition_id": "review:review_scope:started", "repair_kind": "evidence_needed"}))
    store.append_event(RunEvent(run_id, 4, "generated_chart_rejected", {**common, "unit_id": "publication:cand_scope", "unit_type": "publication", "phase": "publish", "actor": "system", "role": "publication", "review_id": "review_scope", "state": "rejected", "publication_status": "rejected", "transition_id": "publication:cand_scope:rejected", "repair_kind": "evidence_needed"}))
    store.update_run(run_id, RunStatus.COMPLETED, answer_source="已完成")

    reopened = GatewayHistoryStore(database, artifact_root=tmp_path / "run-artifacts")
    history = reopened.history(session_id, run_id)
    assert history is not None
    assert [event["kind"] for event in history["events"]] == [
        "measurement_observed",
        "measurement_evidence_selected",
        "review_started",
        "generated_chart_rejected",
    ]
    assert history["events"][2]["payload"]["source_scope"] == scope
    assert history["events"][2]["payload"]["repair_kind"] == "evidence_needed"
    assert history["events"][3]["payload"]["parent_attempt"] == "cand_parent"
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


def test_chart_preview_route_follows_candidate_promotion_and_exposes_binary_headers(tmp_path):
    database = tmp_path / "sessions.db"
    store = GatewayHistoryStore(database, artifact_root=tmp_path / "run-artifacts")
    service = GatewayService(database=database, history_store=store)
    session_id = service.create_session("chart-preview")["session"]["id"]
    other_session_id = service.create_session("chart-preview-other")["session"]["id"]
    store.create_run("run_preview", session_id)
    candidate_id = "cand_preview"
    candidate = store.add_candidate(
        "run_preview",
        session_id,
        GeneratedImage(
            _png_bytes(),
            "image/png",
            "待审核图表",
            metadata={
                "kind": "generated_chart",
                "candidateId": candidate_id,
                "reviewId": "review_preview",
                "chartSpecDigest": "a" * 64,
                "candidateStatus": "verified",
                "reviewStatus": "pending",
                "publicationStatus": "unpublished",
                "chart_type": "bar",
                "title": "待审核图表",
                "width": 640,
                "height": 480,
            },
        ),
    )
    assert candidate is not None
    server = GatewayHTTPServer(
        ("127.0.0.1", 0),
        service,
        allowed_origins={"http://tauri.localhost"},
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    preview_path = f"/api/v1/sessions/{session_id}/runs/run_preview/chart-previews/{candidate_id}"
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", preview_path, headers={"Origin": "http://tauri.localhost"})
        response = connection.getresponse()
        body = response.read()
        assert response.status == 200
        assert body == _png_bytes()
        assert response.getheader("Content-Type") == "image/png"
        assert response.getheader("Content-Length") == str(len(_png_bytes()))
        assert response.getheader("Content-Disposition") == "inline"
        assert response.getheader("Cache-Control") == "no-store"
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        assert response.getheader("Access-Control-Allow-Origin") == "http://tauri.localhost"
        connection.close()

        promoted = store.promote_candidate(
            "run_preview",
            session_id,
            candidate_id,
            "review_preview",
            "a" * 64,
            candidate_status="verified",
            review_status="completed",
            publication_status="published",
        )
        assert promoted is not None
        assert promoted["artifactId"].startswith("artifact_")

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", preview_path)
        response = connection.getresponse()
        assert response.status == 200
        assert response.read() == _png_bytes()
        connection.close()

        status, body, _ = _request(
            port,
            "GET",
            f"/api/v1/sessions/{other_session_id}/runs/run_preview/chart-previews/{candidate_id}",
        )
        assert status == 404
        assert body["error"]["code"] == "run_unavailable"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
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
            self.trace_sink(TraceEvent("tool_call", run_id="agent", turn=1, payload={"unit_id": "generation:c1", "unit_type": "generation", "phase": "action", "actor": "tool", "role": "action", "transition_id": "generation:c1:started", "state": "running", "tool_name": "render_chart", "call_id": "c1"}))
            self.trace_sink(TraceEvent("tool_result", run_id="agent", turn=1, payload={"unit_id": "generation:c1", "unit_type": "generation", "phase": "action", "actor": "tool", "role": "action", "transition_id": "generation:c1:completed", "state": "completed", "tool_name": "render_chart", "call_id": "c1", "status": "success"}))
            refs = self.visual_observation_sink("render_chart", "c1", [image])
            self.trace_sink(TraceEvent("generated_chart", run_id="agent", turn=1, payload={"unit_id": "generation:c1", "unit_type": "generation", "phase": "render", "actor": "tool", "role": "action", "transition_id": "generation:c1:generated", "state": "available", "tool_name": "render_chart", "call_id": "c1", "artifacts": refs}))
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
