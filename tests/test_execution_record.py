"""Contracts for the private versioned execution record."""

from __future__ import annotations

import sqlite3
import stat

import pytest

from chartagent.gateway.execution_record import (
    EXECUTION_RECORD_VERSION,
    ExecutionCursor,
    ExecutionEntry,
    ExecutionRecordError,
    NextAction,
)
from chartagent.gateway.execution_context import recovery_state_from_entries
from chartagent.gateway.durable_execution import GatewayDurableExecutionPort
from chartagent.gateway.history import GatewayHistoryStore
from chartagent.gateway.run_lifecycle import ManagedRun
from chartagent.gateway.service import GatewayService
from chartagent.agent import Agent
from chartagent.client.models import NormalizedResult
from chartagent.memory import InMemoryAgentMemory, SQLiteAgentMemory
from chartagent.tools.core import ToolRegistry


@pytest.fixture
def execution_store(tmp_path):
    database = tmp_path / "execution-record.db"
    memory = SQLiteAgentMemory("execution-record-test", database=database)
    store = GatewayHistoryStore(database, artifact_root=tmp_path / "artifacts")
    run_id = "run_execution_record"
    store.create_run(run_id, memory.session.id)
    yield store, run_id, memory.session.id
    memory.close()
    store.close()


def test_cursor_round_trips_typed_next_action():
    cursor = ExecutionCursor(
        run_id="run_execution_record",
        entry_cursor=3,
        turn=2,
        next_action=NextAction(kind="tool", message_entry_id="exe_model_response", call_id="call_1"),
        references={},
    )

    restored = ExecutionCursor.from_json(cursor.to_json())

    assert restored.version == EXECUTION_RECORD_VERSION
    assert restored.entry_cursor == 3
    assert restored.next_action.to_dict() == {
        "kind": "tool",
        "messageEntryId": "exe_model_response",
        "callId": "call_1",
    }


def test_recovery_resumes_at_first_uncommitted_call_in_order():
    entries = [
        ExecutionEntry(
            run_id="run_execution_record",
            sequence=1,
            kind="input",
            payload={"text": "分析这张图", "attachmentIds": []},
            entry_id="exe_input",
        ),
        ExecutionEntry(
            run_id="run_execution_record",
            sequence=2,
            kind="model_response",
            payload={
                "content": "",
                "toolCalls": [
                    {"id": "call_1", "name": "inspect_a", "arguments": "{}", "replayEffect": "replay_safe"},
                    {"id": "call_2", "name": "inspect_b", "arguments": "{}", "replayEffect": "replay_safe"},
                ],
            },
            entry_id="exe_response",
            work_key="model:1",
        ),
        ExecutionEntry(
            run_id="run_execution_record",
            sequence=3,
            kind="tool_result",
            payload={
                "callId": "call_1",
                "modelEntryId": "exe_response",
                "observation": "{\"ok\":true}",
            },
            entry_id="exe_tool_1",
            work_key="tool:exe_response:call_1",
        ),
    ]
    cursor = ExecutionCursor(
        run_id="run_execution_record",
        entry_cursor=3,
        turn=1,
        next_action=NextAction(kind="tool", message_entry_id="exe_response", call_id="call_2"),
        references={},
    )

    state = recovery_state_from_entries(entries, cursor)

    assert state["pendingToolCalls"] == [
        {"id": "call_2", "name": "inspect_b", "arguments": "{}"}
    ]
    assert state["messages"][-1] == {
        "role": "tool", "tool_call_id": "call_1", "content": "{\"ok\":true}"
    }


@pytest.mark.parametrize("action", ["verify", "promote"])
def test_recovery_resumes_chart_checkpoint_without_committing_fake_tool_message(action):
    entries = [
        ExecutionEntry("run_execution_record", 1, "input", {"text": "绘制图表", "attachmentIds": []}, entry_id="exe_input").normalized(),
        ExecutionEntry(
            "run_execution_record", 2, "model_response",
            {"content": "", "toolCalls": [{"id": "call_render", "name": "render_chart", "arguments": "{}", "replayEffect": "idempotent_local_write"}]},
            entry_id="exe_response",
        ).normalized(),
        ExecutionEntry(
            "run_execution_record", 3, "tool_result",
            {"stagingCheckpoint": True, "toolName": "render_chart", "callId": "call_render", "modelEntryId": "exe_response", "outputOrdinal": 0, "stagedRef": "stg_chart_12345678"},
            entry_id="exe_stage",
            work_key="stage:chart:exe_response:call_render:0",
        ).normalized(),
    ]
    if action == "promote":
        entries.append(ExecutionEntry(
            "run_execution_record", 4, "verification_result",
            {
                "verification": {"stagedRef": "stg_chart_12345678", "verificationRef": "ver_chart_12345678", "status": "pass"},
                "modelEntryId": "exe_response",
                "toolCallId": "call_render",
            },
            entry_id="exe_verification",
        ).normalized())
    cursor = ExecutionCursor(
        "run_execution_record",
        len(entries),
        1,
        NextAction(
            kind=action,
            staged_ref="stg_chart_12345678",
            verification_ref="ver_chart_12345678" if action == "promote" else None,
        ),
        {},
    )

    state = recovery_state_from_entries(entries, cursor)

    assert state["nextAction"] == "tool"
    assert state["resumeCheckpointAction"] == action
    assert state["resumeStagedRef"] == "stg_chart_12345678"
    assert state["resumeToolCallId"] == "call_render"
    assert state["pendingToolCalls"] == [{"id": "call_render", "name": "render_chart", "arguments": "{}"}]
    assert not any(message.get("role") == "tool" for message in state["messages"])


def test_recovery_marks_uncommitted_unreconciled_tool_call():
    entries = [
        ExecutionEntry(
            run_id="run_execution_record",
            sequence=1,
            kind="input",
            payload={"text": "继续", "attachmentIds": []},
            entry_id="exe_input",
        ),
        ExecutionEntry(
            run_id="run_execution_record",
            sequence=2,
            kind="model_response",
            payload={
                "content": "",
                "toolCalls": [
                    {"id": "call_1", "name": "external_write", "arguments": "{}", "replayEffect": "reconcile_required"}
                ],
            },
            entry_id="exe_response",
        ),
    ]
    cursor = ExecutionCursor(
        run_id="run_execution_record",
        entry_cursor=2,
        turn=1,
        next_action=NextAction(kind="tool", message_entry_id="exe_response", call_id="call_1"),
        references={},
    )

    state = recovery_state_from_entries(entries, cursor)

    assert state["unreconciledToolCall"] == "call_1"


def test_cursor_rejects_ambiguous_or_untyped_actions():
    with pytest.raises(ExecutionRecordError, match="unexpected or missing"):
        NextAction.from_dict({"kind": "model", "callId": "call_1"})
    with pytest.raises(ExecutionRecordError, match="reference"):
        NextAction.from_dict({"kind": "verify", "stagedRef": "../outside"})


def test_cursor_rejects_snapshot_state_instead_of_opaque_parent_reference():
    cursor = ExecutionCursor(
        run_id="run_execution_record",
        entry_cursor=3,
        turn=2,
        next_action=NextAction(kind="model"),
        references={"messages": [{"role": "user", "content": "must not be stored"}]},
    )
    with pytest.raises(ExecutionRecordError, match="non-reference state"):
        cursor.to_json()


def test_commit_persists_entry_and_cursor_together(execution_store):
    store, run_id, session_id = execution_store
    assert stat.S_IMODE(store.database.stat().st_mode) & 0o077 == 0
    entry = ExecutionEntry(
        run_id=run_id,
        sequence=1,
        kind="model_response",
        work_key="model:1",
        payload={"content": "hello", "reasoning_content": "private"},
    )
    cursor = ExecutionCursor(
        run_id=run_id,
        entry_cursor=1,
        turn=1,
        next_action=NextAction(kind="model"),
        references={},
    )

    run = ManagedRun(session_id, history_store=store, run_id=run_id)
    committed = run.commit_execution_step(
        entry,
        cursor,
        event_kind="run_started",
        event_payload={"process_id": "run"},
    )

    assert committed.entry_id.startswith("exe_")
    assert store.get_execution_cursor(run_id) == cursor
    loaded = store.list_execution_entries(run_id)
    assert len(loaded) == 1
    assert loaded[0].payload["reasoning_content"] == "private"
    assert [event.kind for event in store.list_events(session_id, run_id)] == ["run_started"]


def test_identical_execution_work_reuses_its_committed_entry(execution_store):
    store, run_id, session_id = execution_store
    run = ManagedRun(session_id, history_store=store, run_id=run_id)
    payload = {"text": "hello", "attachmentIds": []}

    first = run.commit_execution_entry(
        "input",
        payload,
        turn=0,
        next_action_kind="model",
        work_key="input:0",
    )
    duplicate = run.commit_execution_entry(
        "input",
        payload,
        turn=0,
        next_action_kind="model",
        work_key="input:0",
    )

    assert duplicate.entry_id == first.entry_id
    assert len(store.list_execution_entries(run_id)) == 1
    with pytest.raises(RuntimeError, match="different committed result"):
        run.commit_execution_entry(
            "input",
            {"text": "changed", "attachmentIds": []},
            turn=0,
            next_action_kind="model",
            work_key="input:0",
        )


def test_cursor_mismatch_rolls_back_execution_entry(execution_store):
    store, run_id, _session_id = execution_store
    entry = ExecutionEntry(run_id, 1, "tool_result", {"ok": True}, work_key="tool:1")
    cursor = ExecutionCursor(run_id, 0, 1, NextAction(kind="model"), {})

    with pytest.raises(ExecutionRecordError, match="does not match"):
        store.commit_execution_step(entry, cursor)

    assert store.list_execution_entries(run_id) == []
    assert store.get_execution_cursor(run_id) is None


def test_cursor_write_failure_rolls_back_entry_and_event(execution_store):
    store, run_id, session_id = execution_store
    with store._database.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER reject_execution_cursor BEFORE INSERT ON gateway_run_execution_cursors "
            "BEGIN SELECT RAISE(ABORT, 'cursor write failed'); END"
        )
    run = ManagedRun(session_id, history_store=store, run_id=run_id)
    entry = ExecutionEntry(run_id, 1, "tool_result", {"ok": True}, work_key="tool:atomic")
    cursor = ExecutionCursor(run_id, 1, 1, NextAction(kind="model"), {})

    with pytest.raises(sqlite3.IntegrityError, match="cursor write failed"):
        run.commit_execution_step(entry, cursor, event_kind="run_started")

    assert store.list_execution_entries(run_id) == []
    assert store.get_execution_cursor(run_id) is None
    assert store.list_events(session_id, run_id) == []
    assert run._next_sequence == 0


def test_agent_model_and_final_answer_are_committed_privately(execution_store):
    store, run_id, session_id = execution_store
    managed_run = ManagedRun(session_id, history_store=store, run_id=run_id)

    class Client:
        def chat(self, *_args, **_kwargs):
            return NormalizedResult(content="answer", reasoning="private reasoning")

    memory = InMemoryAgentMemory()
    agent = Agent(
        Client(),
        ToolRegistry(),
        run_id=run_id,
        memory=memory,
        durable_execution_port=GatewayDurableExecutionPort(
            run=managed_run,
            session_id=session_id,
            history_store=store,
        ),
    )

    assert agent.run("hello") == "answer"

    entries = store.list_execution_entries(run_id)
    assert [entry.kind for entry in entries] == ["input", "model_response", "final_answer"]
    assert entries[1].payload["reasoning_content"] == "private reasoning"
    assert all("reasoning_content" not in str(record.payload) for record in memory.runs[0].records)


def test_recovery_context_replays_committed_prefix_and_only_pending_calls():
    entries = [
        ExecutionEntry("run_parent", 1, "input", {"text": "inspect", "attachmentIds": ["att_1"]}, entry_id="exe_input").normalized(),
        ExecutionEntry(
            "run_parent",
            2,
            "model_response",
            {
                "content": "",
                "reasoning_content": "private continuation",
                "toolCalls": [
                    {"id": "call_1", "name": "read_chart", "arguments": "{}"},
                    {"id": "call_2", "name": "measure_chart", "arguments": "{\"panel_id\":\"p1\"}"},
                ],
            },
            entry_id="exe_model",
        ).normalized(),
        ExecutionEntry(
            "run_parent",
            3,
            "tool_result",
            {"callId": "call_1", "modelEntryId": "exe_model", "observation": "read result"},
            entry_id="exe_tool_result",
        ).normalized(),
    ]
    cursor = ExecutionCursor(
        run_id="run_parent",
        entry_cursor=3,
        turn=1,
        next_action=NextAction(kind="tool", message_entry_id="exe_model", call_id="call_2"),
        references={},
    )

    state = recovery_state_from_entries(entries, cursor, provider="deepseek", parent_run_id="run_parent")

    assert [message["role"] for message in state["messages"]] == ["user", "assistant", "tool"]
    assert state["messages"][1]["reasoning_content"] == "private continuation"
    assert state["pendingToolCalls"] == [{"id": "call_2", "name": "measure_chart", "arguments": "{\"panel_id\":\"p1\"}"}]
    assert state["executionModelEntryId"] == "exe_model"


def test_recovery_context_restores_committed_final_action():
    entries = [
        ExecutionEntry("run_parent", 1, "input", {"text": "answer", "attachmentIds": []}, entry_id="exe_input").normalized(),
        ExecutionEntry("run_parent", 2, "model_response", {"content": "done", "toolCalls": []}, entry_id="exe_answer").normalized(),
    ]
    cursor = ExecutionCursor("run_parent", 2, 1, NextAction(kind="final", answer_entry_id="exe_answer"), {})

    state = recovery_state_from_entries(entries, cursor)

    assert state["nextAction"] == "final"
    assert state["pendingAnswer"] == "done"


def test_recovery_context_restores_committed_final_answer_entry():
    entries = [
        ExecutionEntry("run_parent", 1, "input", {"text": "answer", "attachmentIds": []}, entry_id="exe_input").normalized(),
        ExecutionEntry("run_parent", 2, "model_response", {"content": "candidate", "toolCalls": []}, entry_id="exe_candidate").normalized(),
        ExecutionEntry("run_parent", 3, "final_answer", {"answer": "guarded answer"}, entry_id="exe_final_answer").normalized(),
    ]
    cursor = ExecutionCursor("run_parent", 3, 1, NextAction(kind="final", answer_entry_id="exe_final_answer"), {})

    state = recovery_state_from_entries(entries, cursor)

    assert state["nextAction"] == "final"
    assert state["pendingAnswer"] == "guarded answer"


def test_recovery_context_restores_current_chart_claim_facts():
    entries = [
        ExecutionEntry("run_parent", 1, "input", {"text": "render", "attachmentIds": []}, entry_id="exe_input").normalized(),
        ExecutionEntry(
            "run_parent",
            2,
            "model_response",
            {"content": "", "toolCalls": [{"id": "call_chart", "name": "render_chart", "arguments": "{}", "replayEffect": "idempotent_local_write"}]},
            entry_id="exe_render_response",
        ).normalized(),
        ExecutionEntry(
            "run_parent",
            3,
            "verification_result",
            {
                "verification": {
                    "verificationRef": "ver_chart_12345678",
                    "stagedRef": "stg_chart_12345678",
                    "status": "pass",
                },
                "modelEntryId": "exe_render_response",
                "toolCallId": "call_chart",
            },
            entry_id="exe_verification",
        ).normalized(),
        ExecutionEntry(
            "run_parent",
            4,
            "promotion_result",
            {
                "artifactId": "artifact_0123456789abcdef",
                "stagedRef": "stg_chart_12345678",
                "verificationRef": "ver_chart_12345678",
            },
            entry_id="exe_promotion",
        ).normalized(),
        ExecutionEntry(
            "run_parent",
            5,
            "tool_result",
            {
                "toolName": "render_chart",
                "callId": "call_chart",
                "modelEntryId": "exe_render_response",
                "observation": (
                    '{"data":{"chartVerification":[{"stagedRef":"stg_chart_12345678",'
                    '"verification":{"verificationRef":"ver_chart_12345678","stagedRef":"stg_chart_12345678",'
                    '"status":"pass"},"artifactId":"artifact_0123456789abcdef"}]}}'
                ),
            },
            entry_id="exe_tool_result",
        ).normalized(),
        ExecutionEntry("run_parent", 6, "model_response", {"content": "done", "toolCalls": []}, entry_id="exe_answer").normalized(),
        ExecutionEntry("run_parent", 7, "final_answer", {"answer": "done"}, entry_id="exe_final_answer").normalized(),
    ]
    cursor = ExecutionCursor(
        "run_parent",
        7,
        2,
        NextAction(kind="final", answer_entry_id="exe_final_answer"),
        {},
    )

    state = recovery_state_from_entries(entries, cursor)

    assert state["currentOutputArtifacts"] == [{
        "artifact_id": "artifact_0123456789abcdef",
        "kind": "generated_chart",
        "status": "pass",
        "staged_ref": "stg_chart_12345678",
        "artifact_id_published": "artifact_0123456789abcdef",
        "verification": {
            "verificationRef": "ver_chart_12345678",
            "stagedRef": "stg_chart_12345678",
            "status": "pass",
        },
        "lineage": ["observation:call_chart"],
    }]
    assert state["currentOutputRecords"] == [
        {
            "kind": "verification_result",
            "payload": {
                "stagedRef": "stg_chart_12345678",
                "verificationRef": "ver_chart_12345678",
                "status": "pass",
            },
        },
        {
            "kind": "promotion_result",
            "payload": {
                "artifactId": "artifact_0123456789abcdef",
                "stagedRef": "stg_chart_12345678",
                "verificationRef": "ver_chart_12345678",
            },
        },
    ]


@pytest.mark.parametrize("answer_committed", [False, True])
def test_resume_from_committed_final_stage_does_not_call_model(execution_store, answer_committed):
    store, _run_id, session_id = execution_store
    store.create_run("run_final_parent", session_id)
    parent = ManagedRun(session_id, history_store=store, run_id="run_final_parent")
    parent.commit_execution_entry(
        "input",
        {"text": "answer", "attachmentIds": []},
        turn=0,
        next_action_kind="model",
        work_key="input:final-parent",
    )
    response = parent.commit_execution_entry(
        "model_response",
        {"content": "the answer", "toolCalls": []},
        turn=1,
        next_action_kind="final",
        work_key="model:final-parent",
    )
    if answer_committed:
        parent.commit_execution_entry(
            "final_answer",
            {"answer": "the answer", "finishReason": "stop"},
            turn=1,
            next_action_kind="final",
            work_key=f"final:{response.entry_id}",
            event_kind="final_answer_committed",
            event_payload={"answer_length": 9},
        )
    parent.interrupt("test_interruption", "test interruption")
    parent_cursor = store.get_execution_cursor("run_final_parent")
    assert parent_cursor is not None
    recovery = recovery_state_from_entries(
        store.list_execution_entries("run_final_parent", through=parent_cursor.entry_cursor),
        parent_cursor,
    )

    store.create_run("run_final_child", session_id, parent_run_id="run_final_parent", root_run_id="run_final_parent")
    child = ManagedRun(session_id, history_store=store, run_id="run_final_child", parent_run_id="run_final_parent")
    child.set_execution_prefix("run_final_parent", parent_cursor.entry_cursor)

    class NoModelClient:
        def chat(self, *_args, **_kwargs):
            raise AssertionError("committed final answer must not request the model")

    agent = Agent(
        NoModelClient(),
        ToolRegistry(),
        run_id="run_final_child",
        memory=InMemoryAgentMemory(),
        recovery_context=recovery,
        durable_execution_port=GatewayDurableExecutionPort(
            run=child,
            session_id=session_id,
            history_store=store,
        ),
    )

    answer = agent.run(recovery["prompt"], recovery_context=recovery)

    assert answer == "the answer"
    child_entries = store.list_execution_entries("run_final_child")
    assert [entry.kind for entry in child_entries] == ["final_answer"]
    child_cursor = store.get_execution_cursor("run_final_child")
    assert child_cursor is not None
    assert child_cursor.next_action.kind == "final"
    assert child_cursor.next_action.answer_entry_id == child_entries[0].entry_id

    if not child.has_event("final_answer"):
        child.publish("final_answer", {"answer": answer})
    child.complete(answer)
    child.complete("different answer")
    assert child.status.value == "completed"
    assert child.answer == answer
    assert len([event for event in store.list_events(session_id, "run_final_child") if event.kind == "final_answer"]) == 1


def test_child_execution_cursor_resolves_parent_prefix(tmp_path):
    service = GatewayService(database=tmp_path / "execution-lineage.db")
    session_id = service.create_session("execution-lineage")["session"]["id"]
    service._history.create_run("run_parent", session_id)
    parent = ManagedRun(session_id, history_store=service._history, run_id="run_parent")
    parent.commit_execution_entry(
        "input",
        {"text": "resume me", "attachmentIds": []},
        turn=0,
        next_action_kind="model",
        work_key="input:0",
    )
    model = parent.commit_execution_entry(
        "model_response",
        {"content": "", "toolCalls": [{"id": "call_1", "name": "inspect", "arguments": "{}"}]},
        turn=1,
        next_action_kind="tool",
        call_id="call_1",
        work_key="model:1",
    )
    parent_cursor = service._history.get_execution_cursor("run_parent")
    assert parent_cursor is not None

    service._history.create_run("run_child", session_id, parent_run_id="run_parent", root_run_id="run_parent")
    child = ManagedRun(session_id, history_store=service._history, run_id="run_child", parent_run_id="run_parent")
    child.set_execution_prefix("run_parent", parent_cursor.entry_cursor)
    child.commit_execution_entry(
        "tool_result",
        {"callId": "call_1", "modelEntryId": model.entry_id, "toolName": "inspect", "observation": "ok"},
        turn=1,
        next_action_kind="model",
        work_key=f"tool:{model.entry_id}:call_1",
    )
    child_cursor = service._history.get_execution_cursor("run_child")
    assert child_cursor is not None

    state = service._execution_recovery_state("run_child", child_cursor, provider="deepseek")

    assert state["executionParentRunId"] == "run_child"
    assert state["executionParentCursor"] == 1
    assert [message["role"] for message in state["messages"]] == ["user", "assistant", "tool"]
    assert state["messages"][-1]["content"] == "ok"
    assert service._history.get_execution_entry_by_work_key_in_lineage("run_child", "model:1").entry_id == model.entry_id
    service.close()


def test_get_recovery_accepts_a_resume_child_of_a_resume_child(execution_store):
    store, _run_id, session_id = execution_store

    store.create_run("run_lineage_root", session_id)
    root = ManagedRun(session_id, history_store=store, run_id="run_lineage_root")
    root.commit_execution_entry(
        "input",
        {"text": "inspect", "attachmentIds": []},
        turn=0,
        next_action_kind="model",
        work_key="input:0",
    )
    root_model = root.commit_execution_entry(
        "model_response",
        {"content": "", "toolCalls": [{"id": "call_root", "name": "inspect", "arguments": "{}"}]},
        turn=1,
        next_action_kind="tool",
        call_id="call_root",
        work_key="model:1",
    )
    root_cursor = store.get_execution_cursor("run_lineage_root")
    assert root_cursor is not None

    store.create_run("run_lineage_child", session_id, parent_run_id="run_lineage_root", root_run_id="run_lineage_root")
    child = ManagedRun(session_id, history_store=store, run_id="run_lineage_child", parent_run_id="run_lineage_root")
    child.set_execution_prefix("run_lineage_root", root_cursor.entry_cursor)
    child.commit_execution_entry(
        "tool_result",
        {"callId": "call_root", "modelEntryId": root_model.entry_id, "toolName": "inspect", "observation": "child result"},
        turn=1,
        next_action_kind="model",
        work_key="tool:root:call_root",
    )
    child_cursor = store.get_execution_cursor("run_lineage_child")
    assert child_cursor is not None

    store.create_run("run_lineage_grandchild", session_id, parent_run_id="run_lineage_child", root_run_id="run_lineage_root")
    grandchild = ManagedRun(
        session_id,
        history_store=store,
        run_id="run_lineage_grandchild",
        parent_run_id="run_lineage_child",
    )
    grandchild.set_execution_prefix("run_lineage_child", child_cursor.entry_cursor)
    grandchild.commit_execution_entry(
        "tool_result",
        {"callId": "call_child", "modelEntryId": root_model.entry_id, "toolName": "inspect", "observation": "grandchild result"},
        turn=2,
        next_action_kind="model",
        work_key="tool:child:call_child",
    )
    grandchild.interrupt("test_interruption", "test interruption")

    recovery = store.get_recovery(session_id, "run_lineage_grandchild")

    assert recovery is not None
    assert recovery["status"] == "available"


def test_get_recovery_rejects_a_broken_resume_ancestor(execution_store):
    store, _run_id, session_id = execution_store

    store.create_run("run_broken_root", session_id)
    root = ManagedRun(session_id, history_store=store, run_id="run_broken_root")
    root.commit_execution_entry(
        "input",
        {"text": "inspect", "attachmentIds": []},
        turn=0,
        next_action_kind="model",
        work_key="input:broken-root",
    )
    store.create_run("run_broken_child", session_id, parent_run_id="run_broken_root", root_run_id="run_broken_root")
    child = ManagedRun(session_id, history_store=store, run_id="run_broken_child", parent_run_id="run_broken_root")
    child.set_execution_prefix("run_broken_root", 1)
    child.commit_execution_entry(
        "tool_result",
        {"callId": "call_1", "modelEntryId": "exe_missing_model", "observation": "result"},
        turn=1,
        next_action_kind="model",
        work_key="tool:broken:call_1",
    )
    child.interrupt("test_interruption", "test interruption")

    broken_cursor = ExecutionCursor(
        run_id="run_broken_child",
        entry_cursor=1,
        turn=1,
        next_action=NextAction(kind="model"),
        references={"parentRunId": "run_broken_root", "parentCursor": 2},
    )
    with store._database.transaction() as connection:
        connection.execute(
            "UPDATE gateway_run_execution_cursors SET cursor_json = ? WHERE run_id = ?",
            (broken_cursor.to_json(), "run_broken_child"),
        )

    recovery = store.get_recovery(session_id, "run_broken_child")

    assert recovery is not None
    assert recovery["status"] == "unavailable"
    assert recovery["blockedReason"] == "execution_record_unavailable"
