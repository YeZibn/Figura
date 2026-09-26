from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from figura.providers import (
    MODEL_IDS,
    FinishReason,
    ProviderContinuation,
    ProviderFactory,
    ProviderId,
    ProviderResponse,
    ProviderToolCall,
    ProviderUsage,
)
from figura.runtime import (
    ActionKind,
    EventKind,
    FiguraRunStore,
    RunCoordinator,
    RunCreateRequest,
    RunError,
    RunErrorCode,
    RunStatus,
    TerminalCode,
)


def _factory(environ: dict[str, str] | None = None) -> ProviderFactory:
    values = {
        "FIGURA_QWEN_API_KEY": "qwen-secret",
        "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        "FIGURA_DEEPSEEK_API_KEY": "deepseek-secret",
        "FIGURA_MIMO_API_KEY": "mimo-secret",
    }
    if environ is not None:
        values = environ
    return ProviderFactory.from_env(
        values,
        transport_factory=lambda _profile: pytest.fail("availability must not create a transport"),
    )


def _app(tmp_path, *, environ: dict[str, str] | None = None):
    store = FiguraRunStore(tmp_path)
    return store, RunCoordinator(store, _factory(environ))


def _request(session_id: str, *, text: str = "请分析这张图表。", key: str = "request-1") -> RunCreateRequest:
    return RunCreateRequest(
        session_id=session_id,
        text=text,
        provider_id=ProviderId.QWEN.value,
        model_id=MODEL_IDS[ProviderId.QWEN],
        idempotency_key=key,
    )


def _response(
    *,
    content: str = "图表显示数值持续上升。",
    finish_reason: FinishReason = FinishReason.STOP,
    tool_calls=(),
    continuation=None,
) -> ProviderResponse:
    return ProviderResponse(
        provider_id=ProviderId.QWEN,
        model_id=MODEL_IDS[ProviderId.QWEN],
        assistant_content=content,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=ProviderUsage(prompt_tokens=11, completion_tokens=9, total_tokens=20),
        provider_response_id="provider-response-1",
        continuation=continuation,
    )


def test_create_run_persists_atomic_initial_bundle_and_idempotency(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session("分析")

    run = app.create_run(_request(session.session_id))
    state = app.read_run_state(session.session_id, run.run_id)

    assert run.ordinal == 1
    assert run.status is RunStatus.RUNNING
    assert (run.provider, run.model) == (ProviderId.QWEN.value, MODEL_IDS[ProviderId.QWEN])
    assert state.records[0].record_sequence == 1
    assert state.records[0].payload.text == "请分析这张图表。"
    assert state.checkpoint.revision == 1
    assert state.checkpoint.last_committed_record_sequence == 1
    assert state.checkpoint.next_action.action_kind is ActionKind.MODEL
    assert [event.event_kind for event in state.events] == [EventKind.RUN_CREATED]

    repeated = app.create_run(_request(session.session_id))
    assert repeated.run_id == run.run_id
    assert app.read_run_state(session.session_id, run.run_id) == state


@pytest.mark.parametrize(
    "request_kwargs, expected_code",
    [
        ({"text": ""}, RunErrorCode.INVALID_REQUEST),
        ({"text": "   "}, RunErrorCode.INVALID_REQUEST),
        ({"attachment_ids": ("attachment-1",)}, RunErrorCode.UNSUPPORTED_PAYLOAD),
        ({"model_id": "unknown-model"}, RunErrorCode.INVALID_REQUEST),
        ({"provider_id": "unknown-provider"}, RunErrorCode.INVALID_REQUEST),
    ],
)
def test_rejected_creation_leaves_no_run_rows(tmp_path, request_kwargs, expected_code) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    fields = {
        "session_id": session.session_id,
        "text": "有效输入",
        "provider_id": ProviderId.QWEN.value,
        "model_id": MODEL_IDS[ProviderId.QWEN],
        "idempotency_key": "request-1",
    }
    fields.update(request_kwargs)
    error = None
    try:
        app.create_run(RunCreateRequest(**fields))
    except RunError as caught:
        error = caught
    if expected_code is None:
        assert error is None
    else:
        assert error is not None and error.code is expected_code
    with sqlite3.connect(store.database_path) as connection:
        for table in (
            "runs",
            "run_execution_records",
            "run_execution_checkpoints",
            "run_idempotency",
            "run_stream_events",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_unavailable_provider_and_unknown_session_are_rejected_before_writes(tmp_path) -> None:
    store, app = _app(
        tmp_path,
        environ={"FIGURA_QWEN_API_KEY": "", "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1"},
    )
    session = app.create_session()
    with pytest.raises(RunError) as unavailable:
        app.create_run(_request(session.session_id))
    assert unavailable.value.code is RunErrorCode.PROVIDER_UNAVAILABLE
    with pytest.raises(RunError) as missing:
        app.create_run(_request("missing-session"))
    assert missing.value.code is RunErrorCode.SESSION_NOT_FOUND
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_same_key_with_changed_content_conflicts_without_mutating_original(tmp_path) -> None:
    _store, app = _app(tmp_path)
    session = app.create_session()
    original = app.create_run(_request(session.session_id))

    with pytest.raises(RunError) as conflict:
        app.create_run(_request(session.session_id, text="不同输入"))

    assert conflict.value.code is RunErrorCode.IDEMPOTENCY_CONFLICT
    assert app.read_run_state(session.session_id, original.run_id).run.ordinal == 1


def test_text_response_commit_advances_checkpoint_and_rejects_private_or_tool_payloads(tmp_path) -> None:
    _store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))

    unsupported = [
        _response(tool_calls=(ProviderToolCall("tool-1", "inspect", "{}"),)),
        _response(continuation=ProviderContinuation(ProviderId.QWEN, 1, "private reasoning")),
    ]
    for response in unsupported:
        with pytest.raises(RunError) as error:
            app.commit_model_response(session.session_id, run.run_id, 1, response)
        assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD

    state = app.read_run_state(session.session_id, run.run_id)
    assert len(state.records) == 1
    assert state.checkpoint.revision == 1
    assert len(state.events) == 1

    record = app.commit_model_response(session.session_id, run.run_id, 1, _response())
    state = app.read_run_state(session.session_id, run.run_id)
    assert record.record_sequence == 2
    assert state.checkpoint.revision == 2
    assert state.checkpoint.last_committed_record_sequence == 2
    assert state.checkpoint.next_action.action_kind is ActionKind.FINAL
    assert state.checkpoint.next_action.response_record_id == record.record_id
    assert [event.event_sequence for event in state.events] == [1]


def test_completion_commits_final_record_status_checkpoint_and_safe_event_together(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    app.commit_model_response(session.session_id, run.run_id, 1, _response())

    final_record = app.complete_run(session.session_id, run.run_id, 2)
    state = app.read_run_state(session.session_id, run.run_id)

    assert final_record.record_kind.value == "final_answer"
    assert final_record.record_sequence == 3
    assert state.run.status is RunStatus.COMPLETED
    assert state.run.final_record_id == final_record.record_id
    assert state.checkpoint.revision == 3
    assert state.checkpoint.last_committed_record_sequence == 3
    assert state.checkpoint.next_action is None
    assert [event.event_sequence for event in state.events] == [1, 2]
    assert state.events[-1].event_kind is EventKind.RUN_COMPLETED
    assert state.events[-1].payload == {"final_artifact_refs": ()}

    public_run = repr(state.run.to_public_dict())
    public_events = repr([event.to_public_dict() for event in state.events])
    assert "请分析这张图表" not in public_run + public_events
    assert "图表显示数值持续上升" not in public_run + public_events
    assert "provider-response-1" not in public_run + public_events
    assert str(store.database_path) not in public_run + public_events

    with pytest.raises(RunError) as terminal:
        app.interrupt_run(session.session_id, run.run_id, 3)
    assert terminal.value.code is RunErrorCode.INVALID_TRANSITION


def test_invalid_finalization_rolls_back_final_record_and_terminal_event(tmp_path) -> None:
    _store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    app.commit_model_response(
        session.session_id,
        run.run_id,
        1,
        _response(finish_reason=FinishReason.LENGTH),
    )

    with pytest.raises(RunError) as invalid:
        app.complete_run(session.session_id, run.run_id, 2)

    assert invalid.value.code is RunErrorCode.INVALID_TRANSITION
    state = app.read_run_state(session.session_id, run.run_id)
    assert [record.record_kind.value for record in state.records] == ["input", "model_response"]
    assert [event.event_kind for event in state.events] == [EventKind.RUN_CREATED]
    assert state.checkpoint.next_action.action_kind is ActionKind.FINAL


def test_failure_and_interruption_keep_checkpoint_and_are_terminal(tmp_path) -> None:
    _store, app = _app(tmp_path)
    first_session = app.create_session()
    failed = app.create_run(_request(first_session.session_id))
    app.commit_model_response(first_session.session_id, failed.run_id, 1, _response())
    app.fail_run(first_session.session_id, failed.run_id, 2, TerminalCode.EXECUTION_FAILED)
    failed_state = app.read_run_state(first_session.session_id, failed.run_id)
    assert failed_state.run.status is RunStatus.FAILED
    assert failed_state.run.terminal_message == "Run 执行未能完成。"
    assert failed_state.checkpoint.revision == 3
    assert failed_state.checkpoint.last_committed_record_sequence == 2
    assert failed_state.checkpoint.next_action.action_kind is ActionKind.FINAL
    assert failed_state.events[-1].event_kind is EventKind.RUN_FAILED
    assert failed_state.events[-1].payload == {"terminal_code": "execution_failed"}

    second_session = app.create_session()
    interrupted = app.create_run(_request(second_session.session_id, key="request-2"))
    app.interrupt_run(second_session.session_id, interrupted.run_id, 1)
    interrupted_state = app.read_run_state(second_session.session_id, interrupted.run_id)
    assert interrupted_state.run.status is RunStatus.INTERRUPTED
    assert interrupted_state.checkpoint.next_action.action_kind is ActionKind.MODEL
    assert interrupted_state.events[-1].event_kind is EventKind.RUN_INTERRUPTED
    with pytest.raises(RunError) as second_terminal:
        app.fail_run(second_session.session_id, interrupted.run_id, 2)
    assert second_terminal.value.code is RunErrorCode.INVALID_TRANSITION


def test_stale_checkpoint_and_cross_session_reads_are_rejected(tmp_path) -> None:
    _store, app = _app(tmp_path)
    owner = app.create_session()
    other = app.create_session()
    run = app.create_run(_request(owner.session_id))

    with pytest.raises(RunError) as missing:
        app.read_run_state(other.session_id, run.run_id)
    assert missing.value.code is RunErrorCode.RUN_NOT_FOUND
    with pytest.raises(RunError) as stale:
        app.commit_model_response(owner.session_id, run.run_id, 0, _response())
    assert stale.value.code is RunErrorCode.INVALID_REQUEST

    app.commit_model_response(owner.session_id, run.run_id, 1, _response())
    with pytest.raises(RunError) as stale_again:
        app.commit_model_response(owner.session_id, run.run_id, 1, _response())
    assert stale_again.value.code is RunErrorCode.STALE_CHECKPOINT
    state = app.read_run_state(owner.session_id, run.run_id)
    assert len(state.records) == 2
    assert state.checkpoint.revision == 2


def test_two_sqlite_writers_racing_on_the_same_revision_commit_only_one_record(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    other_app = RunCoordinator(FiguraRunStore(tmp_path), _factory())
    barrier = Barrier(2)

    def commit(coordinator: RunCoordinator):
        barrier.wait()
        try:
            return coordinator.commit_model_response(
                session.session_id, run.run_id, 1, _response()
            )
        except RunError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(commit, (app, other_app)))

    assert sum(not isinstance(result, RunErrorCode) for result in results) == 1
    assert sum(result is RunErrorCode.STALE_CHECKPOINT for result in results) == 1
    state = app.read_run_state(session.session_id, run.run_id)
    assert len(state.records) == 2
    assert state.checkpoint.revision == 2
    assert len(state.events) == 1


def test_cross_run_response_reference_is_rejected_without_partial_completion(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    first = app.create_run(_request(session.session_id, key="first"))
    second = app.create_run(_request(session.session_id, key="second"))
    app.commit_model_response(session.session_id, first.run_id, 1, _response())
    second_response = app.commit_model_response(session.session_id, second.run_id, 1, _response())
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TRIGGER immutable_run_record_update")
        connection.execute(
            "UPDATE run_execution_checkpoints SET next_action_json = ? WHERE run_id = ?",
            ('{"action_kind":"final","response_record_id":"' + second_response.record_id + '"}', first.run_id),
        )

    with pytest.raises(RunError) as invalid_reference:
        app.complete_run(session.session_id, first.run_id, 2)

    assert invalid_reference.value.code is RunErrorCode.INTEGRITY_ERROR
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute(
            "SELECT status FROM runs WHERE run_id = ?", (first.run_id,)
        ).fetchone()[0] == "running"
        assert connection.execute(
            "SELECT COUNT(*) FROM run_execution_records WHERE run_id = ?", (first.run_id,)
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM run_stream_events WHERE run_id = ?", (first.run_id,)
        ).fetchone()[0] == 1


def test_unknown_checkpoint_schema_version_fails_closed(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE run_execution_checkpoints SET schema_version = 2 WHERE run_id = ?",
            (run.run_id,),
        )

    with pytest.raises(RunError) as unsupported:
        app.read_run_state(session.session_id, run.run_id)
    assert unsupported.value.code is RunErrorCode.UNSUPPORTED_VERSION


def test_record_sequence_gap_fails_closed(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    response_record = app.commit_model_response(
        session.session_id, run.run_id, 1, _response()
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TRIGGER immutable_run_record_delete")
        connection.execute(
            "DELETE FROM run_execution_records WHERE record_id = ?", (response_record.record_id,)
        )

    with pytest.raises(RunError) as gap:
        app.read_run_state(session.session_id, run.run_id)
    assert gap.value.code is RunErrorCode.INTEGRITY_ERROR


def test_unknown_execution_record_schema_version_fails_closed(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TRIGGER immutable_run_record_update")
        connection.execute(
            "UPDATE run_execution_records SET schema_version = 2 WHERE run_id = ?",
            (run.run_id,),
        )

    with pytest.raises(RunError) as unsupported:
        app.read_run_state(session.session_id, run.run_id)
    assert unsupported.value.code is RunErrorCode.UNSUPPORTED_VERSION


def test_reopened_store_reconstructs_committed_state_without_provider_work(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    app.commit_model_response(session.session_id, run.run_id, 1, _response())

    reopened = RunCoordinator(FiguraRunStore(tmp_path), _factory())
    state = reopened.read_run_state(session.session_id, run.run_id)

    assert state.run.run_id == run.run_id
    assert [record.record_sequence for record in state.records] == [1, 2]
    assert state.checkpoint.revision == 2
    assert state.checkpoint.next_action.action_kind is ActionKind.FINAL
    assert "图表显示数值" not in repr([event.to_public_dict() for event in state.events])
    assert store.database_path.exists()


def test_corrupt_checkpoint_cursor_fails_closed(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE run_execution_checkpoints SET last_committed_record_sequence = 2 WHERE run_id = ?",
            (run.run_id,),
        )

    with pytest.raises(RunError) as corrupt:
        app.read_run_state(session.session_id, run.run_id)
    assert corrupt.value.code is RunErrorCode.INTEGRITY_ERROR


def test_untrusted_session_cannot_read_records_even_if_run_id_is_known(tmp_path) -> None:
    _store, app = _app(tmp_path)
    first = app.create_session()
    second = app.create_session()
    run = app.create_run(_request(first.session_id))

    with pytest.raises(RunError) as error:
        app.read_run_state(second.session_id, run.run_id)

    assert error.value.code is RunErrorCode.RUN_NOT_FOUND
