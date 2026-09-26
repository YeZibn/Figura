from __future__ import annotations

import sqlite3
import threading
import hashlib
import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from figura.runtime import (
    ActionKind,
    DurableToolExecutor,
    FiguraRunStore,
    NextAction,
    RunCoordinator,
    RunCreateRequest,
    RunError,
    RunStatus,
    ToolAttemptStartedFact,
    ToolCallFact,
    ToolFactKind,
    ToolResultFact,
)
from figura.runtime._codec import (
    decode_tool_fact,
    encode_event_payload,
    encode_payload,
    encode_tool_fact,
    validate_tool_call_batch,
)
from figura.runtime.models import EventKind, RecordKind, RunInput
from figura.runtime.store import _CORE_SCHEMA
from figura.providers import (
    MODEL_IDS,
    FinishReason,
    ProviderFactory,
    ProviderId,
    ProviderResponse,
    ProviderToolCall,
)
from figura.json_schema import canonical_json_dumps
from figura.tools.contracts import (
    ReplayEffect,
    ToolExecutionError,
    ToolExecutionResult,
    ToolOutcome,
)
from figura.tools import ToolContext, ToolDefinition, ToolRegistry
from figura.runtime._run_lock import PerRunExecutionLock


def _call(
    *,
    call_id: str = "call-1",
    position: int = 0,
    arguments_json: str = '{"value":1}',
    response_record_id: str = "response-1",
) -> ToolCallFact:
    return ToolCallFact(
        response_record_id=response_record_id,
        call_id=call_id,
        tool_name="inspect",
        arguments_json=arguments_json,
        position=position,
        registry_version="registry-v1",
    )


def _app(tmp_path):
    store = FiguraRunStore(tmp_path)
    factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: pytest.fail("response commit must not call a provider"),
    )
    coordinator = RunCoordinator(store, factory)
    session = coordinator.create_session()
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="分析图表",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="initial-run",
        )
    )
    return store, coordinator, session, run


def _tool_response(*calls: ProviderToolCall) -> ProviderResponse:
    return ProviderResponse(
        provider_id=ProviderId.QWEN,
        model_id=MODEL_IDS[ProviderId.QWEN],
        assistant_content="",
        tool_calls=tuple(calls),
        finish_reason=FinishReason.TOOL_CALLS,
    )


def _registry(handler, *, replay_effect: ReplayEffect = ReplayEffect.REPLAY_SAFE) -> ToolRegistry:
    return ToolRegistry(
        "registry-v1",
        (
            ToolDefinition(
                name="inspect",
                description="Inspect a value.",
                parameters_schema={
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                result_schema={
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                replay_effect=replay_effect,
                handler=handler,
            ),
        ),
    )


def _create_v1_database(data_root, *, conflicting_tool_table: bool = False, invalid_foreign_key: bool = False):
    data_root.mkdir(parents=True, exist_ok=True)
    database_path = data_root / "figura.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("BEGIN")
    for statement in _CORE_SCHEMA:
        if statement.startswith("CREATE TABLE run_execution_checkpoints"):
            statement = statement.replace(
                "        last_committed_tool_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_committed_tool_sequence >= 0),\n",
                "",
            )
        connection.execute(statement)

    session_id = "legacy-session"
    run_id = "legacy-run"
    record_id = "legacy-input-record"
    now = "2026-09-26T00:00:00.000000Z"
    provider_id = ProviderId.QWEN.value
    model_id = MODEL_IDS[ProviderId.QWEN]
    input_json = encode_payload(
        RecordKind.INPUT,
        RunInput("legacy input", (), provider_id, model_id),
    )
    event_json = encode_event_payload(
        EventKind.RUN_CREATED,
        {"session_id": session_id, "ordinal": 1},
    )
    connection.execute(
        "INSERT INTO sessions(session_id, name, created_at, updated_at) VALUES (?, NULL, ?, ?)",
        (session_id, now, now),
    )
    connection.execute(
        "INSERT INTO runs(run_id, session_id, ordinal, input_record_id, status, provider, model, "
        "created_at, started_at, finished_at, terminal_code, terminal_message, final_record_id) "
        "VALUES (?, ?, 1, ?, 'running', ?, ?, ?, ?, NULL, NULL, NULL, NULL)",
        (run_id, session_id, record_id, provider_id, model_id, now, now),
    )
    connection.execute(
        "INSERT INTO run_execution_records(record_id, run_id, record_sequence, record_kind, schema_version, payload_json, created_at) "
        "VALUES (?, ?, 1, 'input', 1, ?, ?)",
        (record_id, run_id, input_json, now),
    )
    connection.execute(
        "INSERT INTO run_idempotency(session_id, idempotency_key_digest, request_fingerprint, run_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, "a" * 64, "b" * 64, run_id, now),
    )
    connection.execute(
        "INSERT INTO run_execution_checkpoints(run_id, revision, last_committed_record_sequence, next_action_json, schema_version, updated_at) "
        "VALUES (?, 1, 1, '{\"action_kind\":\"model\"}', 1, ?)",
        (run_id, now),
    )
    connection.execute(
        "INSERT INTO run_stream_events(run_id, event_sequence, event_kind, payload_json, created_at) "
        "VALUES (?, 1, 'run_created', ?, ?)",
        (run_id, event_json, now),
    )
    if conflicting_tool_table:
        connection.execute("CREATE TABLE run_tool_execution_facts (collision INTEGER)")
    connection.execute("PRAGMA user_version = 1")
    connection.commit()

    if invalid_foreign_key:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO run_idempotency(session_id, idempotency_key_digest, request_fingerprint, run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, "c" * 64, "d" * 64, "missing-run", now),
        )
        connection.commit()
    connection.close()
    return database_path


def test_tool_call_fact_codec_preserves_bounded_provider_arguments() -> None:
    fact = _call(arguments_json=' { "label" : "折线图" } ')

    raw = encode_tool_fact(ToolFactKind.TOOL_CALL, fact)
    decoded = decode_tool_fact(ToolFactKind.TOOL_CALL, 1, raw)

    assert decoded == fact
    assert decoded.arguments_json == fact.arguments_json


def test_tool_call_response_commits_core_record_and_ordered_tool_facts_atomically(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    response = _tool_response(
        ProviderToolCall("call-1", "inspect", '{"value":1}'),
        ProviderToolCall("call-2", "inspect", '{"value":2}'),
    )

    record = coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        response,
        registry_version="registry-v1",
    )
    state = coordinator.read_run_state(session.session_id, run.run_id)

    assert record.record_sequence == 2
    assert state.checkpoint.revision == 2
    assert state.checkpoint.last_committed_record_sequence == 2
    assert state.checkpoint.last_committed_tool_sequence == 2
    assert state.checkpoint.next_action == NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=1)
    assert len(state.records) == 2
    assert [fact.tool_sequence for fact in state.tool_facts] == [1, 2]
    assert [fact.payload.call_id for fact in state.tool_facts] == ["call-1", "call-2"]
    assert all(fact.payload.response_record_id == record.record_id for fact in state.tool_facts)
    assert state.run.status is RunStatus.RUNNING
    assert len(state.events) == 1
    assert store.database_path.exists()


def test_attempt_start_precedes_handler_and_success_result_advances_to_model(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )

    started = store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="attempt-1",
    )
    started_state = coordinator.read_run_state(session.session_id, run.run_id)

    assert started.tool_sequence == 2
    assert started_state.checkpoint.revision == 3
    assert started_state.checkpoint.last_committed_tool_sequence == 2
    assert started_state.checkpoint.next_action == NextAction(
        ActionKind.TOOL_ATTEMPT,
        tool_call_sequence=1,
        attempt_id="attempt-1",
    )

    result = store.commit_tool_result(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=3,
        attempt_id="attempt-1",
        result=ToolExecutionResult(
            call_id="call-1",
            tool_name="inspect",
            outcome=ToolOutcome.SUCCEEDED,
            result={"value": 1},
        ),
    )
    state = coordinator.read_run_state(session.session_id, run.run_id)

    assert result.tool_sequence == 3
    assert state.checkpoint.revision == 4
    assert state.checkpoint.last_committed_tool_sequence == 3
    assert state.checkpoint.next_action == NextAction(ActionKind.MODEL)
    assert state.tool_facts[-1].payload.result == {"value": 1}


def test_tool_batch_results_advance_serially_and_persist_known_failures(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(
            ProviderToolCall("call-1", "inspect", '{"value":1}'),
            ProviderToolCall("call-2", "inspect", '{"value":2}'),
        ),
        registry_version="registry-v1",
    )
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="attempt-1",
    )
    store.commit_tool_result(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=3,
        attempt_id="attempt-1",
        result=ToolExecutionResult(
            call_id="call-1",
            tool_name="inspect",
            outcome=ToolOutcome.SUCCEEDED,
            result={"ok": True},
        ),
    )
    midway = coordinator.read_run_state(session.session_id, run.run_id)
    assert midway.checkpoint.next_action == NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=2)

    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=4,
        tool_call_sequence=2,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.RECONCILE_REQUIRED,
        attempt_id="attempt-2",
    )
    store.commit_tool_result(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=5,
        attempt_id="attempt-2",
        result=ToolExecutionResult(
            call_id="call-2",
            tool_name="inspect",
            outcome=ToolOutcome.FAILED,
            error=ToolExecutionError("handler_failed", "工具执行失败。", False),
        ),
    )
    state = coordinator.read_run_state(session.session_id, run.run_id)

    assert state.checkpoint.revision == 6
    assert state.checkpoint.next_action == NextAction(ActionKind.MODEL)
    assert state.tool_facts[-1].payload.outcome is ToolOutcome.FAILED
    assert state.tool_facts[-1].payload.error.code == "handler_failed"


def test_attempt_and_result_transitions_reject_stale_or_mismatched_inputs(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )

    with pytest.raises(RunError):
        store.begin_tool_attempt(
            session_id=session.session_id,
            run_id=run.run_id,
            expected_revision=1,
            tool_call_sequence=1,
            registry_version="registry-v1",
            replay_effect=ReplayEffect.REPLAY_SAFE,
        )
    with pytest.raises(RunError):
        store.begin_tool_attempt(
            session_id=session.session_id,
            run_id=run.run_id,
            expected_revision=2,
            tool_call_sequence=1,
            registry_version="registry-v2",
            replay_effect=ReplayEffect.REPLAY_SAFE,
        )
    state = coordinator.read_run_state(session.session_id, run.run_id)
    assert len(state.tool_facts) == 1
    assert state.checkpoint.revision == 2
    assert state.checkpoint.last_committed_tool_sequence == 1
    assert state.checkpoint.next_action == NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=1)

    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="attempt-1",
    )
    with pytest.raises(RunError):
        store.commit_tool_result(
            session_id=session.session_id,
            run_id=run.run_id,
            expected_revision=3,
            attempt_id="attempt-1",
            result=ToolExecutionResult(
                call_id="different-call",
                tool_name="inspect",
                outcome=ToolOutcome.SUCCEEDED,
                result={"ok": True},
            ),
        )
    state = coordinator.read_run_state(session.session_id, run.run_id)
    assert len(state.tool_facts) == 2
    assert state.checkpoint.revision == 3
    assert state.checkpoint.next_action.attempt_id == "attempt-1"


@pytest.mark.parametrize(
    "kind,fact",
    [
        (
            ToolFactKind.TOOL_ATTEMPT_STARTED,
            ToolAttemptStartedFact(
                tool_call_sequence=1,
                call_id="call-1",
                attempt_id="attempt-1",
                attempt_number=1,
                replay_effect=ReplayEffect.REPLAY_SAFE,
                registry_version="registry-v1",
            ),
        ),
        (
            ToolFactKind.TOOL_RESULT,
            ToolResultFact(
                tool_call_sequence=1,
                attempt_id="attempt-1",
                call_id="call-1",
                tool_name="inspect",
                outcome=ToolOutcome.FAILED,
                error=ToolExecutionError("handler_failed", "工具执行失败。", False),
            ),
        ),
    ],
)
def test_attempt_and_failure_facts_round_trip(kind, fact) -> None:
    raw = encode_tool_fact(kind, fact)

    assert decode_tool_fact(kind, 1, raw) == fact


def test_success_result_is_canonical_and_round_trips_as_an_object() -> None:
    fact = ToolResultFact(
        tool_call_sequence=1,
        attempt_id="attempt-1",
        call_id="call-1",
        tool_name="inspect",
        outcome=ToolOutcome.SUCCEEDED,
        result={"value": 3, "label": "趋势"},
    )

    raw = encode_tool_fact(ToolFactKind.TOOL_RESULT, fact)
    decoded = decode_tool_fact(ToolFactKind.TOOL_RESULT, 1, raw)

    assert dict(decoded.result) == {"label": "趋势", "value": 3}
    assert '"fact_kind":"tool_result"' in raw


@pytest.mark.parametrize(
    "fact",
    [
        _call(arguments_json='{"x":1,"x":2}'),
        _call(arguments_json="[]"),
        _call(arguments_json='{"x":NaN}'),
        _call(arguments_json=r'{"x":"\ud800"}'),
        _call(arguments_json='{"x":"too-large"' + " " * (64 * 1024)),
    ],
)
def test_tool_call_codec_rejects_invalid_or_oversized_arguments(fact) -> None:
    with pytest.raises(RunError):
        encode_tool_fact(ToolFactKind.TOOL_CALL, fact)


def test_tool_call_batch_rejects_duplicate_ids_bad_positions_and_too_many_calls() -> None:
    with pytest.raises(RunError):
        validate_tool_call_batch((_call(), _call(call_id="call-2", position=2)))
    with pytest.raises(RunError):
        validate_tool_call_batch((_call(), _call(call_id="call-1", position=1)))
    with pytest.raises(RunError):
        validate_tool_call_batch(tuple(_call(call_id=f"call-{i}", position=i) for i in range(65)))


def test_tool_call_batch_enforces_aggregate_argument_budget() -> None:
    calls = tuple(
        _call(
            call_id=f"call-{i}",
            position=i,
            arguments_json='{"v":"' + ("x" * 61_990) + '"}',
        )
        for i in range(17)
    )

    with pytest.raises(RunError):
        validate_tool_call_batch(calls)


def test_result_codec_rejects_canonical_result_over_256_kib_and_unknown_versions() -> None:
    fact = ToolResultFact(
        tool_call_sequence=1,
        attempt_id="attempt-1",
        call_id="call-1",
        tool_name="inspect",
        outcome=ToolOutcome.SUCCEEDED,
        result={"value": "x" * (256 * 1024)},
    )

    with pytest.raises(RunError):
        encode_tool_fact(ToolFactKind.TOOL_RESULT, fact)
    with pytest.raises(RunError):
        decode_tool_fact(ToolFactKind.TOOL_RESULT, 2, '{"schema_version":2}')
    with pytest.raises(RunError):
        decode_tool_fact(ToolFactKind.TOOL_CALL, 1, '{"schema_version":1,"fact_kind":"tool_call","call_id":"x","call_id":"y"}')


def test_v1_migration_preserves_run_records_checkpoint_events_and_idempotency(tmp_path) -> None:
    _create_v1_database(tmp_path)

    store = FiguraRunStore(tmp_path)
    state = store.read_run_state("legacy-session", "legacy-run")
    with sqlite3.connect(store.database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        idempotency = connection.execute(
            "SELECT session_id, idempotency_key_digest, request_fingerprint, run_id "
            "FROM run_idempotency"
        ).fetchone()
        trigger_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )
        }

    assert version == 2
    assert foreign_key_violations == []
    assert idempotency == ("legacy-session", "a" * 64, "b" * 64, "legacy-run")
    assert {
        "immutable_run_record_update",
        "immutable_run_record_delete",
        "immutable_run_event_update",
        "immutable_run_event_delete",
        "immutable_run_tool_fact_update",
        "immutable_run_tool_fact_delete",
    } <= trigger_names
    assert state.run.run_id == "legacy-run"
    assert state.run.session_id == "legacy-session"
    assert len(state.records) == 1
    assert state.records[0].record_id == "legacy-input-record"
    assert state.checkpoint.revision == 1
    assert state.checkpoint.last_committed_record_sequence == 1
    assert state.checkpoint.last_committed_tool_sequence == 0
    assert state.checkpoint.next_action == NextAction(ActionKind.MODEL)
    assert len(state.events) == 1
    assert state.events[0].event_kind is EventKind.RUN_CREATED
    assert state.tool_facts == ()


def test_v1_migration_rolls_back_schema_version_and_added_column_on_failure(tmp_path) -> None:
    database_path = _create_v1_database(tmp_path, conflicting_tool_table=True)

    with pytest.raises(RunError):
        FiguraRunStore(tmp_path)

    with sqlite3.connect(database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        checkpoint_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(run_execution_checkpoints)")
        }
        connection.execute("DROP TABLE run_tool_execution_facts")
        connection.commit()

    assert version == 1
    assert "last_committed_tool_sequence" not in checkpoint_columns

    store = FiguraRunStore(tmp_path)
    assert store.read_run_state("legacy-session", "legacy-run").checkpoint.last_committed_tool_sequence == 0


def test_v1_migration_rejects_foreign_key_violation_and_can_retry_after_repair(tmp_path) -> None:
    database_path = _create_v1_database(tmp_path, invalid_foreign_key=True)

    with pytest.raises(RunError):
        FiguraRunStore(tmp_path)

    with sqlite3.connect(database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        checkpoint_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(run_execution_checkpoints)")
        }
        connection.execute("DELETE FROM run_idempotency WHERE idempotency_key_digest = ?", ("c" * 64,))
        connection.commit()

    assert version == 1
    assert "last_committed_tool_sequence" not in checkpoint_columns
    store = FiguraRunStore(tmp_path)
    assert store.read_run_state("legacy-session", "legacy-run").run.run_id == "legacy-run"


def test_model_response_and_tool_intents_roll_back_together_when_tool_insert_fails(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_tool_intent BEFORE INSERT ON run_tool_execution_facts "
            "WHEN NEW.fact_kind = 'tool_call' BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
        connection.commit()

    with pytest.raises(RunError):
        coordinator.commit_model_response(
            session.session_id,
            run.run_id,
            1,
            _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
            registry_version="registry-v1",
        )

    state = coordinator.read_run_state(session.session_id, run.run_id)
    assert [record.record_sequence for record in state.records] == [1]
    assert state.checkpoint.revision == 1
    assert state.checkpoint.last_committed_record_sequence == 1
    assert state.checkpoint.last_committed_tool_sequence == 0
    assert state.checkpoint.next_action == NextAction(ActionKind.MODEL)
    assert state.tool_facts == ()


def test_record_and_tool_sequences_advance_independently_across_model_rounds(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    first_response = coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="attempt-1",
    )
    store.commit_tool_result(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=3,
        attempt_id="attempt-1",
        result=ToolExecutionResult(
            call_id="call-1",
            tool_name="inspect",
            outcome=ToolOutcome.SUCCEEDED,
            result={"ok": True},
        ),
    )
    second_response = coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        4,
        ProviderResponse(
            provider_id=ProviderId.QWEN,
            model_id=MODEL_IDS[ProviderId.QWEN],
            assistant_content="分析完成",
            tool_calls=(),
            finish_reason=FinishReason.STOP,
        ),
    )
    state = coordinator.read_run_state(session.session_id, run.run_id)

    assert first_response.record_sequence == 2
    assert second_response.record_sequence == 3
    assert [fact.tool_sequence for fact in state.tool_facts] == [1, 2, 3]
    assert state.checkpoint.last_committed_record_sequence == 3
    assert state.checkpoint.last_committed_tool_sequence == 3
    assert state.checkpoint.next_action == NextAction(ActionKind.FINAL, second_response.record_id)


def test_concurrent_attempt_claims_use_checkpoint_compare_and_swap(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    competing_store = FiguraRunStore(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    barrier = threading.Barrier(2)

    def claim(store_to_use: FiguraRunStore, attempt_id: str):
        barrier.wait(timeout=5)
        try:
            fact = store_to_use.begin_tool_attempt(
                session_id=session.session_id,
                run_id=run.run_id,
                expected_revision=2,
                tool_call_sequence=1,
                registry_version="registry-v1",
                replay_effect=ReplayEffect.REPLAY_SAFE,
                attempt_id=attempt_id,
            )
            return ("claimed", fact.payload.attempt_id)
        except RunError:
            return ("stale", attempt_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda pair: claim(*pair),
                ((store, "attempt-a"), (competing_store, "attempt-b")),
            )
        )

    state = coordinator.read_run_state(session.session_id, run.run_id)
    assert sorted(result[0] for result in results) == ["claimed", "stale"]
    assert len(state.tool_facts) == 2
    assert state.tool_facts[-1].fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
    assert state.checkpoint.revision == 3


def test_durable_executor_dispatches_calls_serially_after_attempt_start(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(
            ProviderToolCall("call-1", "inspect", '{"value":1}'),
            ProviderToolCall("call-2", "inspect", '{"value":2}'),
        ),
        registry_version="registry-v1",
    )
    observed: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        current = coordinator.read_run_state(session.session_id, run.run_id)
        assert current.checkpoint.next_action is not None
        assert current.checkpoint.next_action.action_kind is ActionKind.TOOL_ATTEMPT
        assert current.tool_facts[-1].fact_kind is ToolFactKind.TOOL_ATTEMPT_STARTED
        observed.append(arguments["value"])
        return {"value": arguments["value"]}

    executor = DurableToolExecutor(store, _registry(handler))
    state = executor.execute_pending(session.session_id, run.run_id)

    assert observed == [1, 2]
    assert state.checkpoint.next_action == NextAction(ActionKind.MODEL)
    assert [fact.fact_kind for fact in state.tool_facts] == [
        ToolFactKind.TOOL_CALL,
        ToolFactKind.TOOL_CALL,
        ToolFactKind.TOOL_ATTEMPT_STARTED,
        ToolFactKind.TOOL_RESULT,
        ToolFactKind.TOOL_ATTEMPT_STARTED,
        ToolFactKind.TOOL_RESULT,
    ]
    assert [fact.payload.attempt_number for fact in state.tool_facts if isinstance(fact.payload, ToolAttemptStartedFact)] == [1, 1]
    restarted_state = FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id)
    assert restarted_state.checkpoint == state.checkpoint
    assert restarted_state.tool_facts == state.tool_facts


def test_durable_executor_persists_known_handler_failure_then_advances(tmp_path, caplog) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(
            ProviderToolCall("call-1", "inspect", '{"value":1}'),
            ProviderToolCall("call-2", "inspect", '{"value":2}'),
        ),
        registry_version="registry-v1",
    )
    invoked: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        invoked.append(arguments["value"])
        if arguments["value"] == 1:
            raise RuntimeError("private handler detail")
        return {"value": arguments["value"]}

    with caplog.at_level(logging.DEBUG):
        state = DurableToolExecutor(store, _registry(handler)).execute_pending(
            session.session_id,
            run.run_id,
        )
    result_facts = [fact.payload for fact in state.tool_facts if isinstance(fact.payload, ToolResultFact)]
    public_data = repr(state.run.to_public_dict()) + repr([event.to_public_dict() for event in state.events])

    assert invoked == [1, 2]
    assert [result.outcome for result in result_facts] == [ToolOutcome.FAILED, ToolOutcome.SUCCEEDED]
    assert result_facts[0].error is not None
    assert result_facts[0].error.code == "handler_failed"
    assert "private handler detail" not in repr(state)
    assert "handler_failed" not in public_data
    assert "private handler detail" not in public_data
    assert "handler_failed" not in caplog.text
    assert "private handler detail" not in caplog.text
    assert state.checkpoint.next_action == NextAction(ActionKind.MODEL)


def test_run_lock_contention_fails_closed_without_starting_a_tool(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    invoked: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        invoked.append(arguments["value"])
        return {"value": arguments["value"]}

    executor = DurableToolExecutor(store, _registry(handler))
    lock = PerRunExecutionLock(tmp_path)
    with lock.acquire(run.run_id):
        with pytest.raises(RunError):
            executor.execute_pending(session.session_id, run.run_id)

    state = coordinator.read_run_state(session.session_id, run.run_id)
    assert invoked == []
    assert state.checkpoint.revision == 2
    assert state.checkpoint.next_action == NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=1)
    assert [fact.fact_kind for fact in state.tool_facts] == [ToolFactKind.TOOL_CALL]


def test_different_run_can_execute_while_another_run_lock_is_held(tmp_path) -> None:
    store, coordinator, session, first_run = _app(tmp_path)
    second_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="分析第二个运行",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="second-run",
        )
    )
    for target_run in (first_run, second_run):
        coordinator.commit_model_response(
            session.session_id,
            target_run.run_id,
            1,
            _tool_response(ProviderToolCall(f"call-{target_run.ordinal}", "inspect", '{"value":1}')),
            registry_version="registry-v1",
        )
    invoked: list[str] = []

    def handler(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        invoked.append(context.run_id)
        return {"value": arguments["value"]}

    executor = DurableToolExecutor(store, _registry(handler))
    with PerRunExecutionLock(tmp_path).acquire(first_run.run_id):
        second_state = executor.execute_pending(session.session_id, second_run.run_id)

    first_state = coordinator.read_run_state(session.session_id, first_run.run_id)
    assert invoked == [second_run.run_id]
    assert first_state.checkpoint.next_action == NextAction(ActionKind.TOOL_EXECUTION, tool_call_sequence=1)
    assert second_state.checkpoint.next_action == NextAction(ActionKind.MODEL)


def test_run_state_reads_and_public_logs_hide_tool_payloads(tmp_path, caplog) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("private-call-id", "inspect", '{"value":71}')),
        registry_version="registry-v1",
    )
    invoked: list[int] = []
    keys: list[str | None] = []

    def handler(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        invoked.append(arguments["value"])
        keys.append(context.idempotency_key)
        return {"value": arguments["value"]}

    state = coordinator.read_run_state(session.session_id, run.run_id)
    assert invoked == []
    with caplog.at_level(logging.DEBUG):
        state = DurableToolExecutor(
            store,
            _registry(handler, replay_effect=ReplayEffect.IDEMPOTENT_LOCAL_WRITE),
        ).execute_pending(session.session_id, run.run_id)
    raw_public = repr(state.run.to_public_dict()) + repr([event.to_public_dict() for event in state.events])
    sensitive_values = ("private-call-id", '{"value":71}', '"value":71', keys[0])

    assert invoked == [71]
    assert keys[0] is not None
    assert all(value not in raw_public for value in sensitive_values)
    assert all(value not in repr(state) for value in sensitive_values)
    assert all(value not in caplog.text for value in sensitive_values)


def test_tool_context_validates_and_hides_idempotency_key() -> None:
    key = "a" * 64
    context = ToolContext("run-1", "session-1", "call-1", idempotency_key=key)

    assert context.idempotency_key == key
    assert key not in repr(context)
    with pytest.raises(ValueError):
        ToolContext("run-1", "session-1", "call-1", idempotency_key="not-a-digest")


@pytest.mark.parametrize("started", [False, True])
def test_completion_rejects_corrupt_final_action_with_pending_or_unknown_tool_work(tmp_path, started: bool) -> None:
    store, coordinator, session, run = _app(tmp_path)
    response_record = coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    expected_revision = 2
    if started:
        store.begin_tool_attempt(
            session_id=session.session_id,
            run_id=run.run_id,
            expected_revision=2,
            tool_call_sequence=1,
            registry_version="registry-v1",
            replay_effect=ReplayEffect.REPLAY_SAFE,
            attempt_id="attempt-without-result",
        )
        expected_revision = 3
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE run_execution_checkpoints SET next_action_json = ? WHERE run_id = ?",
            (
                '{"action_kind":"final","response_record_id":"'
                + response_record.record_id
                + '"}',
                run.run_id,
            ),
        )

    with pytest.raises(RunError):
        coordinator.complete_run(session.session_id, run.run_id, expected_revision)

    with sqlite3.connect(store.database_path) as connection:
        status = connection.execute("SELECT status FROM runs WHERE run_id = ?", (run.run_id,)).fetchone()[0]
        record_count = connection.execute(
            "SELECT COUNT(*) FROM run_execution_records WHERE run_id = ?",
            (run.run_id,),
        ).fetchone()[0]
        event_count = connection.execute(
            "SELECT COUNT(*) FROM run_stream_events WHERE run_id = ?",
            (run.run_id,),
        ).fetchone()[0]
    assert status == "running"
    assert record_count == 2
    assert event_count == 1


def test_duplicate_tool_result_commit_cannot_duplicate_a_committed_result(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="attempt-1",
    )
    result = ToolExecutionResult(
        call_id="call-1",
        tool_name="inspect",
        outcome=ToolOutcome.SUCCEEDED,
        result={"value": 1},
    )
    store.commit_tool_result(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=3,
        attempt_id="attempt-1",
        result=result,
    )

    with pytest.raises(RunError):
        store.commit_tool_result(
            session_id=session.session_id,
            run_id=run.run_id,
            expected_revision=4,
            attempt_id="attempt-1",
            result=result,
        )
    state = coordinator.read_run_state(session.session_id, run.run_id)
    assert len([fact for fact in state.tool_facts if fact.fact_kind is ToolFactKind.TOOL_RESULT]) == 1
    assert state.checkpoint.revision == 4


def test_recovery_replays_replay_safe_attempt_after_acquiring_run_lock(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="attempt-before-crash",
    )
    invoked: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        invoked.append(arguments["value"])
        return {"value": arguments["value"]}

    executor = DurableToolExecutor(store, _registry(handler))
    state = executor.recover_unknown_attempt(session.session_id, run.run_id)
    starts = [fact.payload for fact in state.tool_facts if isinstance(fact.payload, ToolAttemptStartedFact)]

    assert invoked == [1]
    assert [item.attempt_number for item in starts] == [1, 2]
    assert [item.replay_effect for item in starts] == [ReplayEffect.REPLAY_SAFE] * 2
    assert state.checkpoint.next_action == NextAction(ActionKind.MODEL)


def test_idempotent_local_write_replay_reuses_stable_key_and_original_result(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.IDEMPOTENT_LOCAL_WRITE,
        attempt_id="attempt-before-crash",
    )
    expected_key = hashlib.sha256(
        canonical_json_dumps([run.run_id, "call-1"]).encode("utf-8")
    ).hexdigest()
    applied_operations: dict[str, dict[str, int]] = {}
    observed_keys: list[str | None] = []

    def handler(context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        observed_keys.append(context.idempotency_key)
        assert context.idempotency_key is not None
        if context.idempotency_key not in applied_operations:
            applied_operations[context.idempotency_key] = {"value": arguments["value"] + 10}
        return applied_operations[context.idempotency_key]

    registry = _registry(handler, replay_effect=ReplayEffect.IDEMPOTENT_LOCAL_WRITE)
    # Simulate a process dying after its write succeeded but before the result fact was committed.
    original_result = handler(
        ToolContext(
            run_id=run.run_id,
            session_id=session.session_id,
            call_id="call-1",
            idempotency_key=expected_key,
        ),
        {"value": 1},
    )
    state = DurableToolExecutor(store, registry).recover_unknown_attempt(session.session_id, run.run_id)
    result = next(fact.payload for fact in state.tool_facts if isinstance(fact.payload, ToolResultFact))

    assert observed_keys == [expected_key, expected_key]
    assert result.result == original_result == {"value": 11}
    assert len(applied_operations) == 1
    assert state.checkpoint.next_action == NextAction(ActionKind.MODEL)


def test_reconcile_required_recovery_waits_without_dispatch_then_commits_trusted_result(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.RECONCILE_REQUIRED,
        attempt_id="attempt-to-reconcile",
    )
    invoked: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        invoked.append(arguments["value"])
        return {"value": arguments["value"]}

    executor = DurableToolExecutor(
        store,
        _registry(handler, replay_effect=ReplayEffect.RECONCILE_REQUIRED),
    )
    waiting = executor.recover_unknown_attempt(session.session_id, run.run_id)
    assert waiting.checkpoint.revision == 3
    assert waiting.checkpoint.next_action == NextAction(
        ActionKind.TOOL_ATTEMPT,
        tool_call_sequence=1,
        attempt_id="attempt-to-reconcile",
    )
    assert invoked == []

    reconciled = executor.reconcile_unknown_attempt(
        session.session_id,
        run.run_id,
        ToolExecutionResult(
            call_id="call-1",
            tool_name="inspect",
            outcome=ToolOutcome.SUCCEEDED,
            result={"value": 99},
        ),
    )
    result_fact = next(fact.payload for fact in reconciled.tool_facts if isinstance(fact.payload, ToolResultFact))

    assert invoked == []
    assert result_fact.attempt_id == "attempt-to-reconcile"
    assert result_fact.result == {"value": 99}
    assert reconciled.checkpoint.next_action == NextAction(ActionKind.MODEL)


def test_recovery_registry_mismatch_fails_closed_without_new_attempt(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="attempt-before-crash",
    )
    invoked: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        invoked.append(arguments["value"])
        return {"value": arguments["value"]}

    old_registry = _registry(handler)
    changed_registry = ToolRegistry("registry-v2", old_registry.definitions)
    executor = DurableToolExecutor(store, changed_registry)
    with pytest.raises(RunError):
        executor.recover_unknown_attempt(session.session_id, run.run_id)

    state = coordinator.read_run_state(session.session_id, run.run_id)
    assert invoked == []
    assert state.checkpoint.revision == 3
    assert len(state.tool_facts) == 2
    assert state.checkpoint.next_action.attempt_id == "attempt-before-crash"


def test_recovery_lock_contention_leaves_unknown_attempt_unchanged(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="attempt-before-crash",
    )
    invoked: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        invoked.append(arguments["value"])
        return {"value": arguments["value"]}

    executor = DurableToolExecutor(store, _registry(handler))
    with PerRunExecutionLock(tmp_path).acquire(run.run_id):
        with pytest.raises(RunError):
            executor.recover_unknown_attempt(session.session_id, run.run_id)

    state = coordinator.read_run_state(session.session_id, run.run_id)
    assert invoked == []
    assert state.checkpoint.revision == 3
    assert len(state.tool_facts) == 2
    assert state.checkpoint.next_action.attempt_id == "attempt-before-crash"


def test_known_failed_tool_result_is_not_replayed_during_recovery(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')),
        registry_version="registry-v1",
    )
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=2,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="attempt-failed",
    )
    store.commit_tool_result(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=3,
        attempt_id="attempt-failed",
        result=ToolExecutionResult(
            call_id="call-1",
            tool_name="inspect",
            outcome=ToolOutcome.FAILED,
            error=ToolExecutionError("handler_failed", "工具执行失败。", True),
        ),
    )
    invoked: list[int] = []

    def handler(_context: ToolContext, arguments: Mapping[str, Any]) -> dict[str, int]:
        invoked.append(arguments["value"])
        return {"value": arguments["value"]}

    state = DurableToolExecutor(store, _registry(handler)).recover_unknown_attempt(
        session.session_id,
        run.run_id,
    )
    assert invoked == []
    assert state.checkpoint.next_action == NextAction(ActionKind.MODEL)
    assert state.checkpoint.revision == 4
