from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from chartagent.gateway.history import GatewayHistoryStore
from chartagent.gateway.recovery import CheckpointError, deserialize_checkpoint, serialize_checkpoint
from chartagent.gateway.protocol import GatewayFault, RecoveryStatus, RunStatus
from chartagent.gateway.service import GatewayService
from chartagent import Agent, Tool, ToolRegistry
from chartagent.agent import AgentRecoveryBlocked
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.memory.models import RunStatus as MemoryRunStatus
from chartagent.memory.sqlite import SQLiteAgentMemory


def _store(tmp_path: Path) -> tuple[GatewayHistoryStore, str, str]:
    database = tmp_path / "sessions.db"
    memory = SQLiteAgentMemory("恢复测试", database=database)
    session_id = memory.session.id
    memory.close()
    store = GatewayHistoryStore(database, retention_seconds=3600)
    run_id = "run_recovery_parent"
    store.create_run(run_id, session_id)
    return store, session_id, run_id


def test_checkpoint_and_operation_journal_are_bounded_and_idempotent(tmp_path: Path):
    store, session_id, run_id = _store(tmp_path)
    checkpoint = store.create_checkpoint(
        session_id,
        run_id,
        {"prompt": "继续", "attachmentIds": ["att_chart"], "local_path": "/private/secret.png"},
        phase="accepted",
        next_action="model",
    )
    loaded = store.get_checkpoint(session_id, run_id)
    assert loaded is not None
    assert loaded.state["prompt"] == "继续"
    assert "local_path" not in loaded.state
    assert loaded.digest == checkpoint.digest
    assert store.get_recovery(session_id, run_id)["status"] == RecoveryStatus.AVAILABLE.value

    started = store.begin_operation(run_id, "model:1", "model")
    assert started["state"] == "in_flight"
    assert store.complete_operation(run_id, "model:1", result={"content": "安全结果"})["state"] == "completed"
    assert store.get_operation(run_id, "model:1")["result"]["content"] == "安全结果"

    store.create_run("run_child", session_id, parent_run_id=run_id, root_run_id=run_id, continuation_kind="resume")
    binding = store.bind_resume_idempotency("resume-key", session_id, run_id, checkpoint.checkpoint_id, "fp", "run_child")
    duplicate = store.bind_resume_idempotency("resume-key", session_id, run_id, checkpoint.checkpoint_id, "fp", "run_other")
    assert binding["existing"] is False
    assert duplicate["existing"] is True
    assert duplicate["runId"] == "run_child"
    with pytest.raises(CheckpointError):
        serialize_checkpoint({"too": "large"}, phase="accepted", next_action="model", version=2)
    with pytest.raises(CheckpointError):
        deserialize_checkpoint(checkpoint.state and '{"version": 2}', version=1)
    store.close()


def test_legacy_run_without_checkpoint_is_unavailable(tmp_path: Path):
    store, session_id, run_id = _store(tmp_path)
    assert store.get_recovery(session_id, run_id)["status"] == RecoveryStatus.UNAVAILABLE.value
    assert store.get_checkpoint(session_id, run_id) is None
    with sqlite3.connect(store.database) as connection:
        connection.execute(
            "UPDATE gateway_runs SET expires_at = ?, status = ? WHERE run_id = ?",
            (0, RunStatus.COMPLETED.value, run_id),
        )
    assert store.get_recovery(session_id, run_id) is None
    store.close()


def test_resume_creates_child_and_keeps_parent_terminal(tmp_path: Path):
    database = tmp_path / "sessions.db"

    class FakeAgent:
        def __init__(self, name: str):
            self.memory = SQLiteAgentMemory(name, database=database, create=False)

        def run(self, prompt: str) -> str:
            run = self.memory.begin_run()
            self.memory.append(run, "user", {"text": prompt})
            self.memory.append(run, "final", {"answer": "continued"})
            self.memory.finish(run, MemoryRunStatus.COMPLETED, "final")
            return "continued"

    class FakeRuntime:
        def __init__(self, name: str):
            self.agent = FakeAgent(name)

        def close(self):
            self.agent.memory.close()

    service = GatewayService(
        database=database,
        runtime_factory=lambda name, **kwargs: FakeRuntime(name),
        readiness_probe=lambda: {"status": "ready", "provider": "openai", "model": "test-model"},
    )
    session_id = service.create_session("resume-service")['session']['id']
    parent = service.start_run(session_id, "原始请求")['run']
    parent_run = service.get_run(session_id, parent['runId'])
    assert parent_run.wait_terminal(timeout=2)
    resumed = service.resume_run(session_id, parent['runId'], "resume-once")['run']
    child = service.get_run(session_id, resumed['runId'])
    assert child.wait_terminal(timeout=2)
    duplicate = service.resume_run(session_id, parent['runId'], "resume-once")
    assert duplicate['duplicate'] is True
    assert duplicate['run']['runId'] == child.run_id
    assert resumed['parentRunId'] == parent['runId']
    assert resumed['continuationKind'] == 'resume'
    assert service.get_run(session_id, parent['runId']).status is RunStatus.COMPLETED
    service.close()


def test_resume_blocks_uncertain_operation(tmp_path: Path):
    database = tmp_path / "sessions.db"

    class FakeRuntime:
        class Agent:
            def run(self, prompt: str) -> str:
                return "done"

        agent = Agent()
        def close(self):
            return None

    service = GatewayService(
        database=database,
        runtime_factory=lambda name, **kwargs: FakeRuntime(),
        readiness_probe=lambda: {"status": "ready", "provider": "openai", "model": "test-model"},
    )
    session_id = service.create_session("resume-blocked")['session']['id']
    parent = service.start_run(session_id, "原始请求")['run']
    parent_run = service.get_run(session_id, parent['runId'])
    assert parent_run.wait_terminal(timeout=2)
    service._history.begin_operation(parent['runId'], "tool:1:uncertain", "tool")
    with pytest.raises(GatewayFault) as error:
        service.resume_run(session_id, parent['runId'], "resume-blocked")
    assert error.value.code == 'recovery_blocked'
    assert service._history.get_recovery(session_id, parent['runId'])['status'] == 'blocked'
    service.close()


def test_agent_continuation_reuses_checkpointed_tool_boundary():
    registry = ToolRegistry()
    calls: list[str] = []
    registry.register(Tool(
        "continue_tool",
        "continue",
        {"type": "object"},
        lambda: calls.append("tool") or {"ok": True},
    ))

    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            return NormalizedResult(content="done")

    client = Client()
    recovery = {
        "nextAction": "tool",
        "pendingToolCalls": [{"id": "call-1", "name": "continue_tool", "arguments": "{}"}],
        "messages": [{"role": "user", "content": "继续"}, {"role": "assistant", "tool_calls": []}],
    }
    agent = Agent(
        client,
        registry,
        recovery_context=recovery,
        operation_begin=lambda operation_id, kind: {"operationId": operation_id, "state": "not_started"},
    )
    assert agent.run("继续") == "done"
    assert calls == ["tool"]
    assert client.calls == 1


def test_agent_continuation_blocks_in_flight_tool():
    registry = ToolRegistry()
    registry.register(Tool("blocked_tool", "blocked", {"type": "object"}, lambda: {"ok": True}))
    recovery = {
        "nextAction": "tool",
        "pendingToolCalls": [{"id": "call-1", "name": "blocked_tool", "arguments": "{}"}],
        "messages": [{"role": "user", "content": "继续"}],
    }
    agent = Agent(
        lambda: None,  # type: ignore[arg-type]
        registry,
        recovery_context=recovery,
        operation_begin=lambda operation_id, kind: {"operationId": operation_id, "state": "in_flight"},
    )
    with pytest.raises(AgentRecoveryBlocked):
        agent.run("继续")
