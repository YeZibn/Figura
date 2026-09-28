from __future__ import annotations

import sqlite3

import pytest

from figura.providers import (
    MODEL_IDS,
    FinishReason,
    ProviderContinuation,
    ProviderFactory,
    ProviderId,
    ProviderResponse,
    ProviderToolCall,
)
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import (
    ActionKind,
    NextAction,
    ProviderAttemptStatus,
    RunCreateRequest,
    RunStatus,
    TerminalCode,
)
from figura.runtime.store import FiguraRunStore
from figura.runtime.run_lock import PerRunExecutionLock
from figura.tools import ReplayEffect


def _factory() -> ProviderFactory:
    return ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )


def _app(tmp_path):
    store = FiguraRunStore(tmp_path)
    coordinator = RunCoordinator(store, _factory())
    session = coordinator.create_session()
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="请分析数据。",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="provider-attempt-test",
        )
    )
    return store, coordinator, session, run


def _response() -> ProviderResponse:
    return ProviderResponse(
        provider_id=ProviderId.QWEN,
        model_id=MODEL_IDS[ProviderId.QWEN],
        assistant_content="已完成分析。",
        tool_calls=(),
        finish_reason=FinishReason.STOP,
    )


def test_provider_attempt_claim_and_response_commit_are_durable(tmp_path) -> None:
    _store, app, session, run = _app(tmp_path)

    attempt = app.begin_provider_attempt(session.session_id, run.run_id, 1)
    claimed = app.read_run_state(session.session_id, run.run_id)

    assert claimed.checkpoint.revision == 2
    assert claimed.checkpoint.next_action == NextAction(
        ActionKind.PROVIDER_ATTEMPT, attempt_id=attempt.attempt_id
    )
    assert claimed.provider_attempts == (attempt,)

    record = app.commit_model_response(
        session.session_id,
        run.run_id,
        2,
        _response(),
        provider_attempt_id=attempt.attempt_id,
    )
    committed = app.read_run_state(session.session_id, run.run_id)

    assert committed.records[-1] == record
    assert committed.provider_attempts[0].status is ProviderAttemptStatus.RESPONSE_COMMITTED
    assert committed.provider_attempts[0].response_record_id == record.record_id
    assert committed.checkpoint.next_action.action_kind is ActionKind.FINAL


def test_provider_attempt_claim_uses_checkpoint_compare_and_swap(tmp_path) -> None:
    _store, app, session, run = _app(tmp_path)
    competing_app = RunCoordinator(FiguraRunStore(tmp_path), _factory())

    app.begin_provider_attempt(session.session_id, run.run_id, 1)

    with pytest.raises(RunError) as error:
        competing_app.begin_provider_attempt(session.session_id, run.run_id, 1)

    assert error.value.code is RunErrorCode.STALE_CHECKPOINT
    assert len(app.read_run_state(session.session_id, run.run_id).provider_attempts) == 1


@pytest.mark.parametrize(
    ("outcome_unknown", "failure_code", "attempt_status", "terminal_code"),
    [
        (
            False,
            "provider_rejected",
            ProviderAttemptStatus.KNOWN_FAILURE,
            TerminalCode.EXECUTION_FAILED,
        ),
        (
            True,
            "timeout",
            ProviderAttemptStatus.OUTCOME_UNKNOWN,
            TerminalCode.PROVIDER_OUTCOME_UNKNOWN,
        ),
    ],
)
def test_provider_attempt_failure_and_run_terminalize_atomically(
    tmp_path, outcome_unknown, failure_code, attempt_status, terminal_code
) -> None:
    _store, app, session, run = _app(tmp_path)
    attempt = app.begin_provider_attempt(session.session_id, run.run_id, 1)

    failed = app.fail_provider_attempt(
        session.session_id,
        run.run_id,
        2,
        attempt.attempt_id,
        outcome_unknown=outcome_unknown,
        failure_code=failure_code,
    )
    state = app.read_run_state(session.session_id, run.run_id)

    assert failed.status is RunStatus.FAILED
    assert failed.terminal_code == terminal_code.value
    assert state.run == failed
    assert state.provider_attempts[0].status is attempt_status
    assert state.provider_attempts[0].failure_code == failure_code
    assert state.events[-1].payload == {"terminal_code": terminal_code.value}


def test_orphaned_provider_attempt_requires_run_lock_then_fails_without_resend(tmp_path) -> None:
    store, app, session, run = _app(tmp_path)
    attempt = app.begin_provider_attempt(session.session_id, run.run_id, 1)
    lock = PerRunExecutionLock(store.data_root)

    with lock.acquire(run.run_id):
        with pytest.raises(RunError) as error:
            app.resolve_orphaned_provider_attempt(session.session_id, run.run_id)
        assert error.value.code is RunErrorCode.INVALID_TRANSITION

    still_started = app.read_run_state(session.session_id, run.run_id)
    assert still_started.run.status is RunStatus.RUNNING
    assert still_started.provider_attempts[0].status is ProviderAttemptStatus.STARTED

    recovered = app.resolve_orphaned_provider_attempt(session.session_id, run.run_id)

    assert recovered.run.status is RunStatus.FAILED
    assert recovered.run.terminal_code == TerminalCode.PROVIDER_OUTCOME_UNKNOWN.value
    assert recovered.provider_attempts[0].status is ProviderAttemptStatus.OUTCOME_UNKNOWN
    assert recovered.provider_attempts[0].attempt_id == attempt.attempt_id


def test_v3_migration_preserves_committed_responses_without_synthetic_attempts(tmp_path) -> None:
    store, app, session, run = _app(tmp_path)
    attempt = app.begin_provider_attempt(session.session_id, run.run_id, 1)
    response = ProviderResponse(
        provider_id=ProviderId.QWEN,
        model_id=MODEL_IDS[ProviderId.QWEN],
        assistant_content="检查一下数据。",
        tool_calls=(ProviderToolCall("legacy-call", "inspect", '{"value":1}'),),
        finish_reason=FinishReason.TOOL_CALLS,
        continuation=ProviderContinuation(ProviderId.QWEN, 1, "legacy continuation"),
    )
    record = app.commit_model_response(
        session.session_id,
        run.run_id,
        2,
        response,
        provider_attempt_id=attempt.attempt_id,
        registry_version="registry-v1",
    )
    pending = app.read_run_state(session.session_id, run.run_id)
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=pending.checkpoint.revision,
        tool_call_sequence=1,
        registry_version="registry-v1",
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="legacy-tool-attempt",
    )
    pending_tool = app.read_run_state(session.session_id, run.run_id)
    app.fail_run(
        session.session_id,
        run.run_id,
        pending_tool.checkpoint.revision,
        TerminalCode.EXECUTION_FAILED,
    )
    before_migration = app.read_run_state(session.session_id, run.run_id)

    database = sqlite3.connect(store.database_path)
    database.execute("DROP TABLE run_provider_attempts")
    database.execute("DROP INDEX attachments_by_session_created")
    database.execute("DROP TABLE attachments")
    database.execute("PRAGMA user_version = 3")
    database.commit()
    database.close()

    migrated = FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id)

    assert migrated.run == before_migration.run
    assert migrated.records == before_migration.records
    assert migrated.checkpoint == before_migration.checkpoint
    assert migrated.events == before_migration.events
    assert migrated.tool_facts == before_migration.tool_facts
    assert migrated.provider_continuations == before_migration.provider_continuations
    assert migrated.records[-1].record_id == record.record_id
    assert migrated.provider_attempts == ()
    assert migrated.run.status is RunStatus.FAILED
    assert migrated.checkpoint.next_action.action_kind is ActionKind.TOOL_ATTEMPT
