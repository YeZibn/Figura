from __future__ import annotations

from pathlib import Path
import json
import sqlite3

import pytest

from chartagent.gateway.history import GatewayHistoryStore
from chartagent.gateway.execution_context import recovery_state_from_entries
from chartagent.gateway.execution_record import ExecutionCursor, ExecutionEntry, NextAction
from chartagent.gateway.protocol import GatewayFault, RecoveryStatus, RunStatus
from chartagent.gateway.service import GatewayService
from chartagent import Agent, Tool, ToolRegistry
from chartagent.agent import AgentRecoveryBlocked
from chartagent.client.models import NormalizedResult, ToolCall
from chartagent.memory.models import RunStatus as MemoryRunStatus
from chartagent.memory.sqlite import SQLiteAgentMemory
from chartagent.tools.core import GeneratedImage, ToolResult


def _store(tmp_path: Path) -> tuple[GatewayHistoryStore, str, str]:
    database = tmp_path / "sessions.db"
    memory = SQLiteAgentMemory("恢复测试", database=database)
    session_id = memory.session.id
    memory.close()
    store = GatewayHistoryStore(database, retention_seconds=3600)
    run_id = "run_recovery_parent"
    store.create_run(run_id, session_id)
    return store, session_id, run_id


def test_execution_cursor_and_resume_identity_are_idempotent(tmp_path: Path):
    store, session_id, run_id = _store(tmp_path)
    entry = ExecutionEntry(
        run_id=run_id,
        sequence=1,
        kind="input",
        work_key="input:0",
        payload={"text": "继续", "attachmentIds": ["att_chart"]},
    )
    cursor = ExecutionCursor(run_id, 1, 0, NextAction("model"), {})
    store.commit_execution_step(entry, cursor)
    store.update_run(run_id, RunStatus.INTERRUPTED)
    recovery = store.get_recovery(session_id, run_id)
    assert recovery["status"] == RecoveryStatus.AVAILABLE.value
    assert recovery["cursorId"].startswith("cur_")

    with sqlite3.connect(store.database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "gateway_run_operations" not in tables
    assert "gateway_run_checkpoints" not in tables

    store.create_run("run_child", session_id, parent_run_id=run_id, root_run_id=run_id, continuation_kind="resume")
    binding = store.bind_resume_idempotency("resume-key", session_id, run_id, recovery["cursorId"], "fp", "run_child")
    duplicate = store.bind_resume_idempotency("resume-key", session_id, run_id, recovery["cursorId"], "fp", "run_other")
    assert binding["existing"] is False
    assert duplicate["existing"] is True
    assert duplicate["runId"] == "run_child"
    store.close()


def test_run_without_execution_cursor_is_unavailable(tmp_path: Path):
    store, session_id, run_id = _store(tmp_path)
    assert store.get_recovery(session_id, run_id)["status"] == RecoveryStatus.UNAVAILABLE.value
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


def test_resume_uses_the_execution_cursor_as_its_only_journal(tmp_path: Path):
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
    resumed = service.resume_run(session_id, parent['runId'], "resume-blocked")
    assert resumed["run"]["parentRunId"] == parent["runId"]
    service.close()


def test_agent_continuation_reuses_committed_tool_boundary():
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
    )
    assert agent.run("继续") == "done"
    assert calls == ["tool"]
    assert client.calls == 1


def test_agent_continuation_restores_panel_scope_from_committed_tool_results():
    registry = ToolRegistry()
    seen: list[dict] = []

    def sensor(attachment_id: str, layout_context: dict | None = None):
        assert attachment_id == "att_dashboard"
        assert layout_context is not None
        seen.append(layout_context)
        return ToolResult(
            # This test isolates checkpointed panel routing.  Keep the
            # payload non-measurement-shaped so the measurement decision gate
            # does not obscure the scope assertion under test.
            [{"bars": [{"measure": {"ratio": 1.0}}]}],
            [GeneratedImage(b"overlay", "image/png", "bar overlay")],
        )

    registry.register(Tool(
        "measure_bars",
        "measure bars",
        {
            "type": "object",
            "properties": {
                "attachment_id": {"type": "string"},
                "panel_id": {"type": "string"},
                "layout_context": {"type": "object", "additionalProperties": True},
            },
            "required": ["attachment_id", "panel_id"],
        },
        sensor,
    ))

    class Client:
        def chat(self, messages, **kwargs):
            return NormalizedResult(content="continued", tool_calls=[])

    scope = {
        "context_id": "panel_2_layout",
        "analysis_scope": {"bbox_px": [100, 200, 300, 240]},
        "validation": {"status": "accepted", "accepted_for_analysis": True},
    }
    run_id = "run_panel_replay"
    layout_arguments = json.dumps({"attachment_id": "att_dashboard"})
    measure_arguments = json.dumps({"attachment_id": "att_dashboard", "panel_id": "panel_2"})
    entries = [
        ExecutionEntry(run_id, 1, "input", {"text": "继续"}, "exe_input"),
        ExecutionEntry(run_id, 2, "model_response", {
            "content": "",
            "toolCalls": [{"id": "layout-call", "name": "inspect_chart_layout", "arguments": layout_arguments}],
        }, "exe_layout_model"),
        ExecutionEntry(run_id, 3, "tool_result", {
            "callId": "layout-call",
            "observation": json.dumps({"data": {"panels": [{"id": "panel_2", "layout_context": scope}]}}),
        }, "exe_layout_result"),
        ExecutionEntry(run_id, 4, "model_response", {
            "content": "",
            "toolCalls": [{"id": "call-1", "name": "measure_bars", "arguments": measure_arguments}],
        }, "exe_measure_model"),
    ]
    cursor = ExecutionCursor(
        run_id,
        4,
        2,
        NextAction("tool", message_entry_id="exe_measure_model", call_id="call-1"),
        {},
    )
    recovery = recovery_state_from_entries(entries, cursor)

    agent = Agent(
        Client(),
        registry,
        recovery_context=recovery,
    )

    assert agent.run("继续") == "continued"
    assert seen[0]["analysis_scope"] == scope["analysis_scope"]


def test_agent_continuation_blocks_tool_with_unreconciled_effect():
    registry = ToolRegistry()
    from chartagent.tools import ToolReplayEffect

    registry.register(Tool(
        "blocked_tool", "blocked", {"type": "object"}, lambda: {"ok": True},
        replay_effect=ToolReplayEffect.RECONCILE_REQUIRED,
    ))
    recovery = {
        "nextAction": "tool",
        "pendingToolCalls": [{"id": "call-1", "name": "blocked_tool", "arguments": "{}"}],
        "messages": [{"role": "user", "content": "继续"}],
    }
    agent = Agent(
        lambda: None,  # type: ignore[arg-type]
        registry,
        recovery_context=recovery,
    )
    with pytest.raises(AgentRecoveryBlocked):
        agent.run("继续")


@pytest.mark.parametrize(("completed_steps", "expected_calls"), [(1, 1), (2, 0)])
def test_resume_keeps_the_root_model_step_budget(completed_steps: int, expected_calls: int):
    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, *_args, **_kwargs):
            self.calls += 1
            return NormalizedResult(content="继续完成")

    client = Client()
    agent = Agent(
        client,
        ToolRegistry(),
        max_steps=2,
        recovery_context={
            "nextAction": "model",
            "modelStepCount": completed_steps,
            "currentTurn": completed_steps,
            "messages": [{"role": "user", "content": "继续"}],
        },
    )

    answer = agent.run("继续")

    assert client.calls == expected_calls
    assert answer == ("继续完成" if expected_calls else "*stopped: max_steps reached*")
