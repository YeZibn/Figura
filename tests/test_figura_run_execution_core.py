from __future__ import annotations

from tests.figura_sources_support import make_attachment_service

import io
import sqlite3
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from PIL import Image

from figura.providers import (
    MODEL_IDS,
    FinishReason,
    MessageRole,
    ProviderContinuation,
    ProviderFactory,
    ProviderId,
    ProviderMessage,
    ProviderOptions,
    ProviderRequest,
    ProviderResponse,
    ProviderToolCall,
    ProviderUsage,
)
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import (
    ActionKind,
    EventKind,
    RecordKind,
    RunCreateRequest,
    RunStatus,
    TerminalCode,
)
from figura.runtime.records import ModelResponseFact, RunInput
from figura.runtime.store import FiguraRunStore
from figura.runtime.codecs.records import (
    decode_payload,
    encode_payload,
)
from figura.runtime.codecs.events import decode_event_payload, encode_event_payload


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


def _commit_response(
    coordinator: RunCoordinator,
    session_id: str,
    run_id: str,
    _legacy_revision: int,
    response: ProviderResponse,
    **kwargs,
):
    if type(_legacy_revision) is not int or _legacy_revision < 1:
        return coordinator.begin_provider_attempt(session_id, run_id, _legacy_revision)
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    return coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        response,
        provider_attempt_id=attempt.attempt_id,
        **kwargs,
    )


def _request(
    session_id: str,
    *,
    text: str = "请分析这张图表。",
    key: str = "request-1",
    attachment_ids: tuple[str, ...] = (),
) -> RunCreateRequest:
    return RunCreateRequest(
        session_id=session_id,
        text=text,
        provider_id=ProviderId.QWEN.value,
        model_id=MODEL_IDS[ProviderId.QWEN],
        idempotency_key=key,
        attachment_ids=attachment_ids,
    )


def _png_bytes() -> bytes:
    content = io.BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(content, format="PNG")
    return content.getvalue()


def test_run_progress_event_payload_is_bounded_to_checkpoint_revision() -> None:
    payload = {"checkpoint_revision": 4}
    encoded = encode_event_payload(EventKind.RUN_PROGRESS, payload)

    assert decode_event_payload(EventKind.RUN_PROGRESS, encoded) == payload
    for invalid in (
        {},
        {"checkpoint_revision": 0},
        {"checkpoint_revision": True},
        {"checkpoint_revision": 1, "tool_name": "secret"},
    ):
        with pytest.raises(RunError):
            encode_event_payload(EventKind.RUN_PROGRESS, invalid)


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


def test_run_input_codec_round_trips_ordered_attachment_ids() -> None:
    payload = RunInput(
        text="查看这些图片。",
        attachment_ids=("a" * 32, "b" * 32),
        requested_provider=ProviderId.QWEN.value,
        requested_model=MODEL_IDS[ProviderId.QWEN],
    )

    encoded = encode_payload(RecordKind.INPUT, payload)
    decoded = decode_payload(RecordKind.INPUT, encoded, expected_schema_version=1)

    assert decoded == payload


@pytest.mark.parametrize(
    "attachment_ids",
    [
        ("duplicate", "duplicate"),
        tuple(f"attachment-{index}" for index in range(17)),
        ("",),
        ("x" * 129,),
    ],
)
def test_run_input_codec_rejects_invalid_attachment_id_lists(attachment_ids) -> None:
    payload = RunInput(
        text="查看图片。",
        attachment_ids=attachment_ids,
        requested_provider=ProviderId.QWEN.value,
        requested_model=MODEL_IDS[ProviderId.QWEN],
    )

    with pytest.raises(RunError) as error:
        encode_payload(RecordKind.INPUT, payload)

    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD


def test_v4_migration_adds_attachment_table_without_changing_run_state(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    before = app.read_run_state(session.session_id, run.run_id)

    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP INDEX panels_by_session")
        connection.execute("DROP TRIGGER immutable_panel_update")
        connection.execute("DROP TRIGGER immutable_panel_delete")
        connection.execute("DROP TABLE panels")
        connection.execute("DROP INDEX attachments_by_session_created")
        connection.execute("DROP TABLE attachments")
        connection.execute("PRAGMA user_version = 4")

    migrated_store = FiguraRunStore(tmp_path)
    after = migrated_store.read_run_state(session.session_id, run.run_id)

    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'attachments'"
        ).fetchone() == ("attachments",)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'panels'"
        ).fetchone() == ("panels",)

    assert after == before


def test_v5_migration_preserves_attachments_and_adds_panels(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    before = app.read_run_state(session.session_id, run.run_id)
    attachment_id = "a" * 32

    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "INSERT INTO attachments(attachment_id, session_id, filename, media_type, byte_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (attachment_id, session.session_id, "source.png", "image/png", 1, run.created_at),
        )
        connection.execute("DROP INDEX panels_by_session")
        connection.execute("DROP TRIGGER immutable_panel_update")
        connection.execute("DROP TRIGGER immutable_panel_delete")
        connection.execute("DROP TABLE panels")
        connection.execute("PRAGMA user_version = 5")

    migrated_store = FiguraRunStore(tmp_path)
    after = migrated_store.read_run_state(session.session_id, run.run_id)

    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT attachment_id, session_id, filename FROM attachments"
        ).fetchone() == (attachment_id, session.session_id, "source.png")
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'panels'"
        ).fetchone() == ("panels",)

    assert after == before


def test_v7_migration_adds_scoped_deletion_without_changing_run_facts(tmp_path) -> None:
    store, coordinator = _app(tmp_path)
    session = coordinator.create_session("保留记录")
    run = coordinator.create_run(_request(session.session_id))
    before = coordinator.read_run_state(session.session_id, run.run_id)

    with sqlite3.connect(store.database_path) as connection:
        for trigger_name in (
            "immutable_run_event_delete",
            "immutable_run_record_delete",
            "immutable_run_tool_fact_delete",
            "immutable_run_provider_continuation_delete",
            "immutable_run_provider_attempt_delete",
            "immutable_panel_delete",
        ):
            connection.execute(f"DROP TRIGGER {trigger_name}")
        connection.execute("DROP TABLE session_deletion_scopes")
        connection.execute("PRAGMA user_version = 7")

    migrated_store = FiguraRunStore(tmp_path)
    after = migrated_store.read_run_state(session.session_id, run.run_id)

    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert connection.execute(
            "SELECT session_id FROM session_deletion_scopes"
        ).fetchall() == []
        with pytest.raises(sqlite3.IntegrityError, match="immutable execution record"):
            connection.execute(
                "UPDATE run_execution_records SET payload_json = payload_json WHERE record_id = ?",
                (before.records[0].record_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable execution record"):
            connection.execute(
                "DELETE FROM run_execution_records WHERE record_id = ?",
                (before.records[0].record_id,),
            )

    assert after == before


def test_create_run_persists_authorized_attachment_ids_and_includes_them_in_idempotency(
    tmp_path,
) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    attachments = make_attachment_service(store)
    first = attachments.upload(session.session_id, "first.png", _png_bytes())
    second = attachments.upload(session.session_id, "second.png", _png_bytes())
    request = _request(
        session.session_id,
        key="attachment-run",
        attachment_ids=(second.attachment_id, first.attachment_id),
    )

    run = app.create_run(request)
    state = app.read_run_state(session.session_id, run.run_id)
    repeated = app.create_run(request)

    assert state.records[0].payload.attachment_ids == (
        second.attachment_id,
        first.attachment_id,
    )
    assert repeated.run_id == run.run_id
    assert state.events[0].payload == {"ordinal": 1, "session_id": session.session_id}
    with pytest.raises(RunError) as reordered:
        app.create_run(
            _request(
                session.session_id,
                key="attachment-run",
                attachment_ids=(first.attachment_id, second.attachment_id),
            )
        )
    assert reordered.value.code is RunErrorCode.IDEMPOTENCY_CONFLICT


def test_run_creation_rejects_missing_duplicate_and_cross_session_attachments_atomically(
    tmp_path,
) -> None:
    store, app = _app(tmp_path)
    owner = app.create_session()
    other = app.create_session()
    attachments = make_attachment_service(store)
    metadata = attachments.upload(owner.session_id, "chart.png", _png_bytes())

    requests = (
        _request(owner.session_id, key="missing", attachment_ids=("f" * 32,)),
        _request(owner.session_id, key="duplicate", attachment_ids=(metadata.attachment_id,) * 2),
        _request(other.session_id, key="cross-session", attachment_ids=(metadata.attachment_id,)),
    )
    for request in requests:
        with pytest.raises(RunError):
            app.create_run(request)

    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM run_execution_records").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM run_execution_checkpoints").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM run_idempotency").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM run_stream_events").fetchone()[0] == 0


def test_referenced_attachment_cannot_be_deleted_and_remains_resolvable(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    attachments = make_attachment_service(store)
    metadata = attachments.upload(session.session_id, "chart.png", _png_bytes())
    content = attachments.resolve(session.session_id, metadata.attachment_id).image_bytes
    run = app.create_run(
        _request(
            session.session_id,
            key="retained-attachment",
            attachment_ids=(metadata.attachment_id,),
        )
    )

    with pytest.raises(RunError) as deletion:
        attachments.delete(session.session_id, metadata.attachment_id)

    assert deletion.value.code is RunErrorCode.INVALID_TRANSITION
    assert app.read_run_state(session.session_id, run.run_id).records[0].payload.attachment_ids == (
        metadata.attachment_id,
    )
    assert attachments.resolve(session.session_id, metadata.attachment_id).image_bytes == content


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


def test_read_prior_run_states_returns_terminal_same_session_runs_in_ordinal_order(tmp_path) -> None:
    _store, app = _app(tmp_path)
    session = app.create_session()
    other_session = app.create_session()

    first = app.create_run(_request(session.session_id, key="history-first"))
    _commit_response(app, session.session_id, first.run_id, 1, _response(content="第一轮回答。"))
    app.complete_run(session.session_id, first.run_id, 3)

    other = app.create_run(_request(other_session.session_id, key="history-other"))
    second = app.create_run(_request(session.session_id, key="history-second"))
    _commit_response(app, session.session_id, second.run_id, 1, _response(content="第二轮回答。"))
    app.complete_run(session.session_id, second.run_id, 3)

    target = app.create_run(_request(session.session_id, key="history-target"))
    prior = app.read_prior_run_states(session.session_id, target.run_id)

    assert [state.run.run_id for state in prior] == [first.run_id, second.run_id]
    assert [state.run.ordinal for state in prior] == [1, 2]
    assert all(state.run.status is RunStatus.COMPLETED for state in prior)
    assert app.read_prior_run_states(other_session.session_id, other.run_id) == ()


def test_read_prior_run_states_rejects_wrong_session_and_nonterminal_history(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    other_session = app.create_session()
    first = app.create_run(_request(session.session_id, key="history-prior"))
    _commit_response(app, session.session_id, first.run_id, 1, _response())
    app.complete_run(session.session_id, first.run_id, 3)
    target = app.create_run(_request(session.session_id, key="history-current"))

    with pytest.raises(RunError) as wrong_session:
        app.read_prior_run_states(other_session.session_id, target.run_id)
    assert wrong_session.value.code is RunErrorCode.RUN_NOT_FOUND

    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE runs SET status = 'running' WHERE run_id = ?", (first.run_id,)
        )
    with pytest.raises(RunError) as nonterminal:
        app.read_prior_run_states(session.session_id, target.run_id)
    assert nonterminal.value.code is RunErrorCode.INVALID_TRANSITION


def test_session_rejects_distinct_active_run_but_allows_idempotent_replay(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    request = _request(session.session_id, key="active-run")
    run = app.create_run(request)

    assert app.create_run(request).run_id == run.run_id
    with pytest.raises(RunError) as overlapping:
        app.create_run(_request(session.session_id, key="overlapping-run"))

    assert overlapping.value.code is RunErrorCode.INVALID_TRANSITION
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM runs WHERE session_id = ?", (session.session_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM run_execution_records WHERE run_id != ?", (run.run_id,)
        ).fetchone()[0] == 0


def test_concurrent_distinct_run_creates_in_one_session_only_commit_one(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    competing_app = RunCoordinator(FiguraRunStore(tmp_path), _factory())
    barrier = Barrier(2)

    def create(coordinator: RunCoordinator, key: str):
        barrier.wait()
        try:
            return coordinator.create_run(_request(session.session_id, key=key))
        except RunError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda args: create(*args),
                ((app, "concurrent-first"), (competing_app, "concurrent-second")),
            )
        )

    assert sum(not isinstance(outcome, RunErrorCode) for outcome in outcomes) == 1
    assert outcomes.count(RunErrorCode.INVALID_TRANSITION) == 1
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM runs WHERE session_id = ?", (session.session_id,)
        ).fetchone()[0] == 1


def test_text_response_commit_advances_checkpoint_and_rejects_tool_payloads(tmp_path) -> None:
    _store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))

    attempt = app.begin_provider_attempt(session.session_id, run.run_id, 1)
    claimed = app.read_run_state(session.session_id, run.run_id)
    with pytest.raises(RunError) as error:
        app.commit_model_response(
            session.session_id,
            run.run_id,
            claimed.checkpoint.revision,
            _response(tool_calls=(ProviderToolCall("tool-1", "inspect", "{}"),)),
            provider_attempt_id=attempt.attempt_id,
        )
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD

    state = app.read_run_state(session.session_id, run.run_id)
    assert len(state.records) == 1
    assert state.checkpoint.revision == 2
    assert state.provider_attempts[0].status.value == "started"
    assert len(state.events) == 1

    valid_session = app.create_session()
    valid_run = app.create_run(_request(valid_session.session_id, key="valid-response"))
    record = _commit_response(app, valid_session.session_id, valid_run.run_id, 1, _response())
    state = app.read_run_state(valid_session.session_id, valid_run.run_id)
    assert record.record_sequence == 2
    assert state.checkpoint.revision == 3
    assert state.checkpoint.last_committed_record_sequence == 2
    assert state.checkpoint.next_action.action_kind is ActionKind.FINAL
    assert state.checkpoint.next_action.response_record_id == record.record_id
    assert [event.event_sequence for event in state.events] == [1]
    assert state.records[-1].payload.schema_version == 2
    assert state.records[-1].payload.continuation_ref is None


@pytest.mark.parametrize(
    "with_tools, with_continuation",
    [(False, False), (False, True), (True, False), (True, True)],
    ids=["text-no-continuation", "text-with-continuation", "tools-no-continuation", "tools-with-continuation"],
)
def test_model_response_round_trips_optional_continuation_for_text_and_tools(
    tmp_path,
    with_tools: bool,
    with_continuation: bool,
) -> None:
    _store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    continuation = (
        ProviderContinuation(ProviderId.QWEN, 1, "exact private continuation")
        if with_continuation
        else None
    )
    calls = (ProviderToolCall("call-1", "inspect", '{"value":1}'),) if with_tools else ()
    response = _response(
        content="" if with_tools else "已完成分析",
        finish_reason=FinishReason.TOOL_CALLS if with_tools else FinishReason.STOP,
        tool_calls=calls,
        continuation=continuation,
    )

    record = _commit_response(app,
        session.session_id,
        run.run_id,
        1,
        response,
        registry_version="registry-v1" if with_tools else None,
    )
    state = app.read_run_state(session.session_id, run.run_id)
    response_fact = state.records[-1].payload

    assert isinstance(response_fact, ModelResponseFact)
    assert response_fact.schema_version == 2
    assert (response_fact.continuation_ref is not None) is with_continuation
    assert len(state.provider_continuations) == int(with_continuation)
    assert len(state.tool_facts) == int(with_tools)
    if with_continuation:
        persisted = state.provider_continuations[0]
        assert persisted.run_id == run.run_id
        assert persisted.response_record_id == record.record_id
        assert persisted.provider_id == ProviderId.QWEN.value
        assert persisted.format_version == 1
        assert persisted.schema_version == 1
        assert persisted.reasoning_content == "exact private continuation"
        assert persisted.created_at == record.created_at
        assert response_fact.continuation_ref == persisted.continuation_id
    else:
        assert response_fact.continuation_ref is None


def test_v1_model_response_remains_readable_and_non_response_facts_stay_v1(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    response = _response()
    record = _commit_response(app, session.session_id, run.run_id, 1, response)
    legacy_fact = ModelResponseFact(
        provider_id=ProviderId.QWEN.value,
        model_id=MODEL_IDS[ProviderId.QWEN],
        assistant_content=response.assistant_content,
        finish_reason=FinishReason.STOP.value,
        usage=response.usage,
        provider_response_id=response.provider_response_id,
        schema_version=1,
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TRIGGER immutable_run_record_update")
        connection.execute(
            "UPDATE run_execution_records SET schema_version = 1, payload_json = ? WHERE record_id = ?",
            (encode_payload(RecordKind.MODEL_RESPONSE, legacy_fact), record.record_id),
        )

    legacy_state = app.read_run_state(session.session_id, run.run_id)
    legacy_response = legacy_state.records[-1].payload
    assert isinstance(legacy_response, ModelResponseFact)
    assert legacy_response == legacy_fact
    assert legacy_response.continuation_ref is None

    fresh_store, fresh_app = _app(tmp_path / "new-store")
    fresh_session = fresh_app.create_session()
    fresh_run = fresh_app.create_run(_request(fresh_session.session_id))
    _commit_response(fresh_app, fresh_session.session_id, fresh_run.run_id, 1, _response())
    fresh_app.complete_run(fresh_session.session_id, fresh_run.run_id, 3)
    with sqlite3.connect(fresh_store.database_path) as connection:
        versions = connection.execute(
            "SELECT record_kind, schema_version FROM run_execution_records "
            "WHERE run_id = ? ORDER BY record_sequence",
            (fresh_run.run_id,),
        ).fetchall()
    assert versions == [("input", 1), ("model_response", 2), ("final_answer", 1)]


def test_unknown_model_response_version_fails_closed(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    response = _commit_response(app, session.session_id, run.run_id, 1, _response())
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TRIGGER immutable_run_record_update")
        connection.execute(
            "UPDATE run_execution_records SET schema_version = 9 WHERE record_id = ?",
            (response.record_id,),
        )

    with pytest.raises(RunError) as unsupported:
        app.read_run_state(session.session_id, run.run_id)
    assert unsupported.value.code is RunErrorCode.UNSUPPORTED_VERSION


def test_reopened_continuation_can_be_replayed_and_survives_terminal_run(tmp_path) -> None:
    _store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    payload = "persisted continuation used for the next provider request"
    _commit_response(app,
        session.session_id,
        run.run_id,
        1,
        _response(continuation=ProviderContinuation(ProviderId.QWEN, 1, payload)),
    )

    reopened = RunCoordinator(FiguraRunStore(tmp_path), _factory())
    recovered = reopened.read_run_state(session.session_id, run.run_id)
    assert len(recovered.provider_continuations) == 1
    persisted = recovered.provider_continuations[0]
    assert persisted.reasoning_content == payload
    checkpoint_before_replay = recovered.checkpoint

    captured_requests: list[dict[str, object]] = []

    class CapturingTransport:
        def create(self, **request_payload: object) -> object:
            captured_requests.append(request_payload)
            return SimpleNamespace(
                id="replayed-response",
                choices=(
                    SimpleNamespace(
                        index=0,
                        message=SimpleNamespace(
                            content="后续响应",
                            reasoning_content=None,
                            tool_calls=(),
                        ),
                        finish_reason="stop",
                    ),
                ),
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            )

    replay_factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: CapturingTransport(),
    )
    replay_request = ProviderRequest(
        provider_id=ProviderId.QWEN,
        model_id=MODEL_IDS[ProviderId.QWEN],
        instructions=(),
        messages=(
            ProviderMessage(MessageRole.USER, "原始问题"),
            ProviderMessage(
                MessageRole.ASSISTANT,
                "",
                continuation=ProviderContinuation(
                    ProviderId(persisted.provider_id),
                    persisted.format_version,
                    persisted.reasoning_content,
                ),
            ),
        ),
        options=ProviderOptions(max_completion_tokens=64),
    )
    replay_client = replay_factory.create(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN])
    replay_client.dispatch(replay_client.prepare(replay_request))

    assert captured_requests[0]["messages"][1]["reasoning_content"] == payload
    after_replay = reopened.read_run_state(session.session_id, run.run_id)
    assert after_replay.checkpoint == checkpoint_before_replay
    assert after_replay.provider_continuations == recovered.provider_continuations
    assert after_replay.tool_facts == ()

    reopened.complete_run(session.session_id, run.run_id, checkpoint_before_replay.revision)
    terminal_state = reopened.read_run_state(session.session_id, run.run_id)
    assert terminal_state.run.status is RunStatus.COMPLETED
    assert terminal_state.provider_continuations == recovered.provider_continuations
    restarted_again = RunCoordinator(FiguraRunStore(tmp_path), _factory())
    assert restarted_again.read_run_state(session.session_id, run.run_id).provider_continuations == recovered.provider_continuations


def test_continuation_is_absent_from_public_repr_logs_and_user_facing_errors(tmp_path, caplog) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    secret = "private continuation must never be projected"
    with caplog.at_level(logging.DEBUG):
        _commit_response(app,
            session.session_id,
            run.run_id,
            1,
            _response(continuation=ProviderContinuation(ProviderId.QWEN, 1, secret)),
        )
        state = app.read_run_state(session.session_id, run.run_id)

    response = state.records[-1].payload
    reference = response.continuation_ref
    assert reference is not None
    public_surfaces = repr(state.run.to_public_dict()) + repr(
        [event.to_public_dict() for event in state.events]
    )
    internal_reprs = repr(state) + repr(response) + repr(state.provider_continuations)
    assert secret not in public_surfaces + internal_reprs
    assert reference not in public_surfaces + internal_reprs
    assert secret not in caplog.text
    assert reference not in caplog.text

    failed_session = app.create_session()
    failed_run = app.create_run(_request(failed_session.session_id, key="error-run"))
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_private_continuation BEFORE INSERT ON run_provider_continuations "
            f"BEGIN SELECT RAISE(ABORT, '{secret}'); END"
        )
    with pytest.raises(RunError) as rejected:
        _commit_response(app,
            failed_session.session_id,
            failed_run.run_id,
            1,
            _response(continuation=ProviderContinuation(ProviderId.QWEN, 1, secret)),
        )
    assert secret not in str(rejected.value) + repr(rejected.value)
    assert secret not in caplog.text


@pytest.mark.parametrize(
    "corruption, expected_code",
    [
        ("missing", RunErrorCode.INTEGRITY_ERROR),
        ("wrong_provider", RunErrorCode.INTEGRITY_ERROR),
        ("unknown_schema", RunErrorCode.UNSUPPORTED_VERSION),
        ("unknown_format", RunErrorCode.UNSUPPORTED_VERSION),
    ],
)
def test_corrupt_continuation_rows_fail_closed(tmp_path, corruption, expected_code) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    _commit_response(app,
        session.session_id,
        run.run_id,
        1,
        _response(continuation=ProviderContinuation(ProviderId.QWEN, 1, "private")),
    )
    with sqlite3.connect(store.database_path) as connection:
        if corruption == "missing":
            connection.execute("DROP TRIGGER immutable_run_provider_continuation_delete")
            connection.execute(
                "DELETE FROM run_provider_continuations WHERE run_id = ?",
                (run.run_id,),
            )
        elif corruption == "wrong_provider":
            connection.execute("DROP TRIGGER immutable_run_provider_continuation_update")
            connection.execute(
                "UPDATE run_provider_continuations SET provider_id = 'deepseek' WHERE run_id = ?",
                (run.run_id,),
            )
        elif corruption == "unknown_schema":
            connection.execute("DROP TRIGGER immutable_run_provider_continuation_update")
            connection.execute(
                "UPDATE run_provider_continuations SET schema_version = 2 WHERE run_id = ?",
                (run.run_id,),
            )
        else:
            connection.execute("DROP TRIGGER immutable_run_provider_continuation_update")
            connection.execute(
                "UPDATE run_provider_continuations SET format_version = 2 WHERE run_id = ?",
                (run.run_id,),
            )

    with pytest.raises(RunError) as corrupt:
        app.read_run_state(session.session_id, run.run_id)
    assert corrupt.value.code is expected_code


def test_completion_commits_final_record_status_checkpoint_and_safe_event_together(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    _commit_response(app, session.session_id, run.run_id, 1, _response())

    final_record = app.complete_run(session.session_id, run.run_id, 3)
    state = app.read_run_state(session.session_id, run.run_id)

    assert final_record.record_kind.value == "final_answer"
    assert final_record.record_sequence == 3
    assert state.run.status is RunStatus.COMPLETED
    assert state.run.final_record_id == final_record.record_id
    assert state.checkpoint.revision == 4
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
        app.interrupt_run(session.session_id, run.run_id, 4)
    assert terminal.value.code is RunErrorCode.INVALID_TRANSITION


def test_invalid_finalization_rolls_back_final_record_and_terminal_event(tmp_path) -> None:
    _store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    _commit_response(app,
        session.session_id,
        run.run_id,
        1,
        _response(finish_reason=FinishReason.LENGTH),
    )

    with pytest.raises(RunError) as invalid:
        app.complete_run(session.session_id, run.run_id, 3)

    assert invalid.value.code is RunErrorCode.INVALID_TRANSITION
    state = app.read_run_state(session.session_id, run.run_id)
    assert [record.record_kind.value for record in state.records] == ["input", "model_response"]
    assert [event.event_kind for event in state.events] == [EventKind.RUN_CREATED]
    assert state.checkpoint.next_action.action_kind is ActionKind.FINAL


def test_failure_and_interruption_keep_checkpoint_and_are_terminal(tmp_path) -> None:
    _store, app = _app(tmp_path)
    first_session = app.create_session()
    failed = app.create_run(_request(first_session.session_id))
    _commit_response(app, first_session.session_id, failed.run_id, 1, _response())
    app.fail_run(first_session.session_id, failed.run_id, 3, TerminalCode.EXECUTION_FAILED)
    failed_state = app.read_run_state(first_session.session_id, failed.run_id)
    assert failed_state.run.status is RunStatus.FAILED
    assert failed_state.run.terminal_message == "Run 执行未能完成。"
    assert failed_state.checkpoint.revision == 4
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
        _commit_response(app, owner.session_id, run.run_id, 0, _response())
    assert stale.value.code is RunErrorCode.INVALID_REQUEST

    _commit_response(app, owner.session_id, run.run_id, 1, _response())
    with pytest.raises(RunError) as stale_again:
        _commit_response(app, owner.session_id, run.run_id, 1, _response())
    assert stale_again.value.code is RunErrorCode.INVALID_TRANSITION
    state = app.read_run_state(owner.session_id, run.run_id)
    assert len(state.records) == 2
    assert state.checkpoint.revision == 3


def test_two_sqlite_writers_racing_on_the_same_revision_commit_only_one_record(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    run = app.create_run(_request(session.session_id))
    other_app = RunCoordinator(FiguraRunStore(tmp_path), _factory())
    barrier = Barrier(2)

    def commit(coordinator: RunCoordinator):
        barrier.wait()
        try:
            return _commit_response(coordinator,
                session.session_id, run.run_id, 1, _response()
            )
        except RunError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(commit, (app, other_app)))

    assert sum(not isinstance(result, RunErrorCode) for result in results) == 1
    assert sum(
        result in {RunErrorCode.STALE_CHECKPOINT, RunErrorCode.INVALID_TRANSITION}
        for result in results
        if isinstance(result, RunErrorCode)
    ) == 1
    state = app.read_run_state(session.session_id, run.run_id)
    assert len(state.records) == 2
    assert state.checkpoint.revision == 3
    assert len(state.events) == 1


def test_cross_run_response_reference_is_rejected_without_partial_completion(tmp_path) -> None:
    store, app = _app(tmp_path)
    session = app.create_session()
    second_session = app.create_session()
    first = app.create_run(_request(session.session_id, key="first"))
    second = app.create_run(_request(second_session.session_id, key="second"))
    _commit_response(app, session.session_id, first.run_id, 1, _response())
    second_response = _commit_response(
        app, second_session.session_id, second.run_id, 1, _response()
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TRIGGER immutable_run_record_update")
        connection.execute(
            "UPDATE run_execution_checkpoints SET next_action_json = ? WHERE run_id = ?",
            ('{"action_kind":"final","response_record_id":"' + second_response.record_id + '"}', first.run_id),
        )

    with pytest.raises(RunError) as invalid_reference:
        app.complete_run(session.session_id, first.run_id, 3)

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
    response_record = _commit_response(app,
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
    _commit_response(app, session.session_id, run.run_id, 1, _response())

    reopened = RunCoordinator(FiguraRunStore(tmp_path), _factory())
    state = reopened.read_run_state(session.session_id, run.run_id)

    assert state.run.run_id == run.run_id
    assert [record.record_sequence for record in state.records] == [1, 2]
    assert state.checkpoint.revision == 3
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


def _make_schema8(store):
    from figura.storage.schema import _CONTINUATION_SCHEMA

    with sqlite3.connect(store.database_path) as connection:
        for name in ('continuation_matches_model_response', 'immutable_run_provider_continuation_update',
                     'immutable_run_provider_continuation_delete'):
            connection.execute(f'DROP TRIGGER {name}')
        old_table = _CONTINUATION_SCHEMA[0].replace('run_provider_continuations (', 'run_provider_continuations_old (').replace(
            "reasoning_content TEXT CHECK (\n            (provider_id = 'deepseek' OR (reasoning_content IS NOT NULL AND length(reasoning_content) > 0))\n            AND (reasoning_content IS NULL OR length(CAST(reasoning_content AS BLOB)) <= 524288)\n        )",
            'reasoning_content TEXT NOT NULL CHECK (length(reasoning_content) > 0 AND length(CAST(reasoning_content AS BLOB)) <= 524288)'
        )
        connection.execute(old_table)
        connection.execute('INSERT INTO run_provider_continuations_old SELECT * FROM run_provider_continuations')
        connection.execute('DROP TABLE run_provider_continuations')
        connection.execute('ALTER TABLE run_provider_continuations_old RENAME TO run_provider_continuations')
        for statement in _CONTINUATION_SCHEMA[1:]:
            connection.execute(statement)
        connection.execute('PRAGMA user_version = 8')


@pytest.mark.parametrize('reasoning', [None, '', 'private text'])
def test_schema9_preserves_explicit_deepseek_values_and_schema8_history(tmp_path, reasoning):
    from dataclasses import replace
    store, coordinator = _app(tmp_path)
    session = coordinator.create_session()
    run = coordinator.create_run(replace(_request(session.session_id),
        provider_id='deepseek', model_id=MODEL_IDS[ProviderId.DEEPSEEK]))
    response = ProviderResponse(ProviderId.DEEPSEEK, MODEL_IDS[ProviderId.DEEPSEEK], 'ok', (),
        FinishReason.STOP, continuation=ProviderContinuation(ProviderId.DEEPSEEK, 1, 'original'))
    _commit_response(coordinator, session.session_id, run.run_id, 1, response)
    state = coordinator.read_run_state(session.session_id, run.run_id)
    coordinator.complete_run(session.session_id, run.run_id, state.checkpoint.revision)
    before = coordinator.read_run_state(session.session_id, run.run_id)
    _make_schema8(store)
    store = FiguraRunStore(tmp_path)
    coordinator = RunCoordinator(store, _factory())
    assert coordinator.read_run_state(session.session_id, run.run_id) == before
    next_run = coordinator.create_run(replace(_request(session.session_id, key='next'),
        provider_id='deepseek', model_id=MODEL_IDS[ProviderId.DEEPSEEK]))
    _commit_response(coordinator, session.session_id, next_run.run_id, 1,
        replace(response, continuation=ProviderContinuation(ProviderId.DEEPSEEK, 1, reasoning)))
    restarted = FiguraRunStore(tmp_path)
    new_state = restarted.read_run_state(session.session_id, next_run.run_id)
    assert new_state.provider_continuations[0].reasoning_content == reasoning
    assert 'private text' not in repr(new_state)
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 9
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute('DELETE FROM run_provider_continuations')
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE run_provider_continuations SET reasoning_content='changed'")

    coordinator = RunCoordinator(restarted, _factory())
    coordinator.complete_run(session.session_id, next_run.run_id, new_state.checkpoint.revision)
    with restarted.database.write() as connection:
        restarted.begin_session_deletion(connection, session.session_id)
        restarted.delete_session_run_facts(connection, session.session_id)
        restarted.delete_session_runs(connection, session.session_id)
        restarted.complete_session_deletion(connection, session.session_id)
    assert not restarted.session_exists(session.session_id)


def test_schema9_migration_failure_rolls_back_table_and_version(tmp_path, monkeypatch):
    import figura.storage.schema as schema
    store, coordinator = _app(tmp_path)
    session = coordinator.create_session()
    run = coordinator.create_run(_request(session.session_id))
    before = coordinator.read_run_state(session.session_id, run.run_id)
    _make_schema8(store)
    def fail(_connection):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    monkeypatch.setattr(schema, '_validate_migration', fail)
    with pytest.raises(RunError):
        FiguraRunStore(tmp_path)
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 8
        assert 'NOT NULL' in connection.execute("SELECT sql FROM sqlite_master WHERE name='run_provider_continuations'").fetchone()[0]
    monkeypatch.undo()
    assert FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id) == before
