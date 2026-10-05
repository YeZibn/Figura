from __future__ import annotations

import sqlite3

import pytest

from figura.providers.models import MODEL_IDS, ProviderId
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.records import ModelResponseFact, RunInput, SessionContextCheckpoint
from figura.runtime.store import FiguraRunStore
from figura.shared.source_refs import MessageSourceRef


def _completed_run(store: FiguraRunStore, session_id: str):
    model_id = MODEL_IDS[ProviderId.QWEN]
    run = store.create_initial_run(
        session_id=session_id,
        provider_id=ProviderId.QWEN.value,
        model_id=model_id,
        input_payload=RunInput("旧问题", (), ProviderId.QWEN.value, model_id),
        key_digest="a" * 64,
        request_fingerprint="b" * 64,
    )
    attempt = store.begin_provider_attempt(
        session_id=session_id,
        run_id=run.run_id,
        expected_revision=1,
        attempt_id=f"attempt-{run.run_id}",
    )
    state = store.read_run_state(session_id, run.run_id)
    store.commit_model_response(
        session_id=session_id,
        run_id=run.run_id,
        expected_revision=state.checkpoint.revision,
        provider_attempt_id=attempt.attempt_id,
        payload=ModelResponseFact(
            ProviderId.QWEN.value,
            model_id,
            "旧回答",
            "stop",
        ),
        record_id=f"response-{run.run_id}",
    )
    state = store.read_run_state(session_id, run.run_id)
    store.complete_run(
        session_id=session_id,
        run_id=run.run_id,
        expected_revision=state.checkpoint.revision,
    )
    return store.read_run_state(session_id, run.run_id)


def _context_checkpoint(session_id: str, state, *, revision: int = 1):
    return SessionContextCheckpoint(
        session_id=session_id,
        revision=revision,
        covered_run_id=state.run.run_id,
        covered_run_ordinal=state.run.ordinal,
        covered_record_sequence=state.checkpoint.last_committed_record_sequence,
        covered_tool_sequence=state.checkpoint.last_committed_tool_sequence,
        summary_contract_version=1,
        summary={"summary": "用户询问了旧问题，助手给出了旧回答。"},
        source_refs=(
            MessageSourceRef(state.run.run_id, state.records[0].record_id),
            MessageSourceRef(state.run.run_id, state.records[1].record_id),
        ),
    )


def test_context_checkpoint_round_trips_after_restart_and_rejects_stale_replace(tmp_path):
    store = FiguraRunStore(tmp_path)
    session = store.create_session()
    state = _completed_run(store, session.session_id)

    first = store.replace_session_context_checkpoint(
        _context_checkpoint(session.session_id, state), expected_revision=0
    )
    restarted = FiguraRunStore(tmp_path)
    assert restarted.read_session_context_checkpoint(session.session_id) == first

    with pytest.raises(RunError) as error:
        restarted.replace_session_context_checkpoint(
            _context_checkpoint(session.session_id, state), expected_revision=0
        )
    assert error.value.code is RunErrorCode.STALE_CHECKPOINT
    assert restarted.read_session_context_checkpoint(session.session_id) == first


def test_context_checkpoint_rejects_cross_session_source_and_bad_frontier(tmp_path):
    store = FiguraRunStore(tmp_path)
    session = store.create_session()
    other_session = store.create_session()
    state = _completed_run(store, session.session_id)
    other_state = _completed_run(store, other_session.session_id)

    cross_session = _context_checkpoint(session.session_id, state)
    cross_session = SessionContextCheckpoint(
        **{
            **cross_session.__dict__,
            "source_refs": (
                MessageSourceRef(other_state.run.run_id, other_state.records[0].record_id),
            ),
        }
    )
    with pytest.raises(RunError) as error:
        store.replace_session_context_checkpoint(cross_session, expected_revision=0)
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
    assert store.read_session_context_checkpoint(session.session_id) is None

    bad_frontier = SessionContextCheckpoint(
        **{
            **_context_checkpoint(session.session_id, state).__dict__,
            "covered_record_sequence": state.checkpoint.last_committed_record_sequence + 1,
        }
    )
    with pytest.raises(RunError) as error:
        store.replace_session_context_checkpoint(bad_frontier, expected_revision=0)
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD


def test_session_deletion_cascades_context_checkpoint(tmp_path):
    store = FiguraRunStore(tmp_path)
    session = store.create_session()
    state = _completed_run(store, session.session_id)
    store.replace_session_context_checkpoint(
        _context_checkpoint(session.session_id, state), expected_revision=0
    )

    with store.database.write() as connection:
        store.begin_session_deletion(connection, session.session_id)
        store.delete_session_run_facts(connection, session.session_id)
        store.delete_session_runs(connection, session.session_id)
        store.complete_session_deletion(connection, session.session_id)

    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute(
            "SELECT 1 FROM session_context_checkpoints WHERE session_id = ?",
            (session.session_id,),
        ).fetchone() is None
    assert not store.session_exists(session.session_id)


def test_schema_v11_migrates_additive_context_checkpoint_table(tmp_path):
    store = FiguraRunStore(tmp_path)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TABLE session_context_checkpoints")
        connection.execute("PRAGMA user_version = 11")

    upgraded = FiguraRunStore(tmp_path)
    with sqlite3.connect(upgraded.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 12
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'session_context_checkpoints'"
        ).fetchone() == ("session_context_checkpoints",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_compaction_operation_binding_and_attempt_count_survive_restart(tmp_path):
    store = FiguraRunStore(tmp_path)
    session = store.create_session()
    source = _completed_run(store, session.session_id)
    model_id = MODEL_IDS[ProviderId.QWEN]
    target = store.create_initial_run(
        session_id=session.session_id,
        provider_id=ProviderId.QWEN.value,
        model_id=model_id,
        input_payload=RunInput("当前问题", (), ProviderId.QWEN.value, model_id),
        key_digest="c" * 64,
        request_fingerprint="d" * 64,
    )
    target_state = store.read_run_state(session.session_id, target.run_id)
    source_checkpoint = store.read_run_state(session.session_id, source.run.run_id)
    operation_args = {
        "session_id": session.session_id,
        "target_run_id": target.run_id,
        "base_record_sequence": target_state.checkpoint.last_committed_record_sequence,
        "base_tool_sequence": target_state.checkpoint.last_committed_tool_sequence,
        "input_checkpoint_revision": 0,
        "covered_run_id": source.run.run_id,
        "covered_run_ordinal": source.run.ordinal,
        "covered_record_sequence": source_checkpoint.checkpoint.last_committed_record_sequence,
        "covered_tool_sequence": source_checkpoint.checkpoint.last_committed_tool_sequence,
    }

    operation = store.get_or_create_context_compaction_operation(**operation_args)
    binding = {"request_fingerprint": "e" * 64, "provider_id": "qwen"}
    store.bind_context_compaction_request(operation.operation_id, binding)
    assert store.begin_context_compaction_attempt(operation.operation_id) == 1

    restarted = FiguraRunStore(tmp_path)
    resumed = restarted.get_or_create_context_compaction_operation(**operation_args)
    assert resumed.operation_id == operation.operation_id
    assert resumed.attempt_count == 1
    assert resumed.request_binding == binding


def test_compaction_operation_and_summary_checkpoint_commit_atomically(tmp_path):
    store = FiguraRunStore(tmp_path)
    session = store.create_session()
    source = _completed_run(store, session.session_id)
    model_id = MODEL_IDS[ProviderId.QWEN]
    target = store.create_initial_run(
        session_id=session.session_id,
        provider_id=ProviderId.QWEN.value,
        model_id=model_id,
        input_payload=RunInput("当前问题", (), ProviderId.QWEN.value, model_id),
        key_digest="c" * 64,
        request_fingerprint="d" * 64,
    )
    target_state = store.read_run_state(session.session_id, target.run_id)
    source_checkpoint = store.read_run_state(session.session_id, source.run.run_id)
    operation = store.get_or_create_context_compaction_operation(
        session_id=session.session_id,
        target_run_id=target.run_id,
        base_record_sequence=target_state.checkpoint.last_committed_record_sequence,
        base_tool_sequence=target_state.checkpoint.last_committed_tool_sequence,
        input_checkpoint_revision=0,
        covered_run_id=source.run.run_id,
        covered_run_ordinal=source.run.ordinal,
        covered_record_sequence=source_checkpoint.checkpoint.last_committed_record_sequence,
        covered_tool_sequence=source_checkpoint.checkpoint.last_committed_tool_sequence,
    )
    store.bind_context_compaction_request(
        operation.operation_id,
        {"request_fingerprint": "f" * 64, "provider_id": "qwen"},
    )
    checkpoint = SessionContextCheckpoint(
        **{
            **_context_checkpoint(session.session_id, source_checkpoint).__dict__,
            "compaction_operation_id": operation.operation_id,
        }
    )

    stored = store.replace_session_context_checkpoint(checkpoint, expected_revision=0)
    persisted_operation = store.read_context_compaction_operation(operation.operation_id)

    assert stored.revision == 1
    assert stored.compaction_operation_id == operation.operation_id
    assert persisted_operation.status == "completed"
    assert persisted_operation.result_checkpoint_revision == stored.revision
