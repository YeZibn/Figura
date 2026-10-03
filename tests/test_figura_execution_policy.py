"""Durable policy integration; all external calls use deterministic transports."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import json
import sqlite3
import threading
import time

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from figura.providers.errors import ProviderCallError, ProviderFailure, ProviderFailureCode
from figura.providers.models import ProviderOptions, ProviderToolCall, FinishReason
from figura.providers.retries import classify_failure, retry_after
from figura.runtime.errors import RunError
from figura.runtime.models import ActionKind, RunStatus, RecordKind, TerminalCode
from figura.runtime.records import ProviderRequestBinding
from figura.runtime.store import FiguraRunStore
from figura.runtime.run_lock import RunExecutionOwnership
from figura.shared.payloads import ExecutionPayloadLimits
from figura.tools.contracts import ToolOutcomeUnknown, ReplayEffect
from figura.gateway.dispatcher import RunDispatcher
from figura.storage.database import _utc_now
from tests.test_figura_agent_executor import _app, _agent, _registry, _FakeFactory, _response


def _temporary(*, known=False, status=None):
    return ProviderCallError(ProviderFailure(ProviderFailureCode.TIMEOUT, known, True, "临时故障。", status))


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr("figura.runtime.persistence.providers.retry_deadline", lambda *_: _utc_now())


def _binding(agent, state):
    request = agent._requests.build(state, agent._tools.registry)
    prepared = agent._provider_factory.create(state.run.provider, state.run.model).prepare(request)
    return ProviderRequestBinding(operation_id="operation-1", run_id=state.run.run_id,
        base_record_sequence=state.checkpoint.last_committed_record_sequence,
        base_tool_sequence=state.checkpoint.last_committed_tool_sequence,
        created_at=_utc_now(), **prepared.descriptor)


@pytest.mark.parametrize("known", [False, True])
def test_retry_success_preserves_unknown_or_failed_fact(tmp_path, no_backoff, known):
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_temporary(known=known), _response()])
    state = _agent(store, coordinator, _registry(), factory).execute(session.session_id, run.run_id)
    assert state.run.status is RunStatus.COMPLETED
    first, second = state.provider_attempts
    assert first.status.value == ("known_failure" if known else "outcome_unknown")
    assert second.retry_of_attempt_id == first.attempt_id
    assert [a.operation_attempt_number for a in state.provider_attempts] == [1, 2]
    assert len(state.provider_request_bindings) == 1
    assert len([r for r in state.records if r.record_kind is RecordKind.MODEL_RESPONSE]) == 1
    assert factory.client.requests[0] == factory.client.requests[1]


def test_four_attempts_exhaust_without_reset_after_reopen(tmp_path, no_backoff):
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_temporary()] * 4)
    agent = _agent(store, coordinator, _registry(), factory)
    for index in range(4):
        state = agent.execute_slice(session.session_id, run.run_id)
        assert len(state.provider_attempts) == index + 1
        assert FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id) == state
    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.PROVIDER_OUTCOME_UNKNOWN.value
    assert state.provider_attempts[-1].next_eligible_at is None
    assert len({a.operation_id for a in state.provider_attempts}) == 1


def test_durable_wait_rejects_early_claim_and_stop_bypasses_due(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([ProviderCallError(ProviderFailure(ProviderFailureCode.PROVIDER_REJECTED, True, True, "限流。", 429, 3600))])
    agent = _agent(store, coordinator, _registry(), factory)
    waiting = agent.execute_slice(session.session_id, run.run_id)
    assert waiting.checkpoint.next_action.action_kind is ActionKind.PROVIDER_RETRY
    assert agent.retry_delay(waiting) > 3500
    binding = waiting.provider_request_bindings[0]
    with pytest.raises(RunError):
        coordinator.begin_provider_attempt(session.session_id, run.run_id, waiting.checkpoint.revision, binding=binding)
    with RunDispatcher(agent, max_workers=1, max_queued=0, scan_interval=60) as dispatcher:
        assert dispatcher.ensure_scheduled(run) is False
        assert dispatcher.activity(run.run_id) is None
        coordinator.request_stop(session.session_id, run.run_id)
        assert dispatcher.ensure_scheduled(run)
        deadline = time.monotonic() + 3
        while coordinator.read_run_state(session.session_id, run.run_id).run.status is RunStatus.RUNNING:
            assert time.monotonic() < deadline
            time.sleep(.01)
    stopped = coordinator.read_run_state(session.session_id, run.run_id)
    assert stopped.run.status is RunStatus.INTERRUPTED
    assert len(factory.client.requests) == 1
    assert stopped.provider_attempts[0].status.value == "known_failure"


def test_orphan_claim_consumes_attempt_and_late_response_rejected(tmp_path, no_backoff):
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response()])
    agent = _agent(store, coordinator, _registry(), factory)
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    binding = _binding(agent, initial)
    first = coordinator.begin_provider_attempt(session.session_id, run.run_id, initial.checkpoint.revision, binding=binding)
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    with RunExecutionOwnership(tmp_path).acquire(run.run_id):
        unchanged = agent.execute_slice(session.session_id, run.run_id)
        assert unchanged == claimed
        with pytest.raises(RunError):
            coordinator.resolve_orphaned_provider_attempt(session.session_id, run.run_id)
    coordinator.resolve_orphaned_provider_attempt(session.session_id, run.run_id)
    closed = coordinator.read_run_state(session.session_id, run.run_id)
    assert closed.provider_attempts[0].status.value == "outcome_unknown"
    completed = agent.execute(session.session_id, run.run_id)
    assert completed.run.status is RunStatus.COMPLETED
    with pytest.raises(RunError):
        coordinator.commit_model_response(session.session_id, run.run_id, claimed.checkpoint.revision,
            _response(), provider_attempt_id=first.attempt_id)
    assert coordinator.read_run_state(session.session_id, run.run_id) == completed


def test_claim_race_has_one_winner_and_binding_is_immutable(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    binding = _binding(agent, initial)
    def claim(_):
        try:
            return coordinator.begin_provider_attempt(session.session_id, run.run_id, 1, binding=binding)
        except RunError:
            return None
    with ThreadPoolExecutor(2) as pool:
        assert sum(a is not None for a in pool.map(claim, range(2))) == 1
    with sqlite3.connect(store.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE run_provider_request_bindings SET payload_json = '{}' WHERE operation_id = ?", (binding.operation_id,))


def test_full_transition_guard_rejects_atomically_and_history_read_ceiling(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    agent = _agent(store, coordinator, _registry(), _FakeFactory([]))
    initial = coordinator.read_run_state(session.session_id, run.run_id)
    attempt = coordinator.begin_provider_attempt(session.session_id, run.run_id, 1, binding=_binding(agent, initial))
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    low = FiguraRunStore(tmp_path, payload_limits=ExecutionPayloadLimits(2500))
    calls = tuple(ProviderToolCall("长" * 100 + str(index), "inspect", json.dumps({"x": "x" * 300})) for index in range(3))
    limited = type(coordinator)(low, coordinator._provider_factory)
    with pytest.raises(RunError):
        limited.commit_model_response(session.session_id, run.run_id, claimed.checkpoint.revision,
            _response(calls=calls, reason=FinishReason.TOOL_CALLS), provider_attempt_id=attempt.attempt_id,
            registry_version="registry-v1")
    assert coordinator.read_run_state(session.session_id, run.run_id) == claimed
    coordinator.commit_model_response(session.session_id, run.run_id, claimed.checkpoint.revision,
        _response(content="界" * 100_000), provider_attempt_id=attempt.attempt_id)
    accepted = coordinator.read_run_state(session.session_id, run.run_id)
    assert low.read_run_state(session.session_id, run.run_id) == accepted


def test_partial_write_unknown_has_no_fabricated_observation_and_replay_cap(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response(calls=(ProviderToolCall("未知" * 150, "inspect", '{"value":1}'),), reason=FinishReason.TOOL_CALLS)])
    keys = []
    base = _registry().get("inspect")
    def partial(context, args):
        keys.append(context.idempotency_key)
        raise ToolOutcomeUnknown()
    from figura.tools import ToolRegistry
    registry = ToolRegistry("registry-v1", (replace(base, handler=partial, replay_effect=ReplayEffect.IDEMPOTENT_LOCAL_WRITE),))
    agent = _agent(store, coordinator, registry, factory)
    state = agent.execute(session.session_id, run.run_id)
    assert state.run.terminal_code == TerminalCode.TOOL_RECOVERY_EXHAUSTED.value
    assert len(keys) == 3 and len(set(keys)) == 1
    assert not any(f.fact_kind.value == "tool_result" for f in state.tool_facts)
    # The repository rejects further claims even outside Agent.
    last = state.tool_facts[-1].payload
    with pytest.raises(RunError):
        store.begin_tool_replay_attempt(session_id=session.session_id, run_id=run.run_id,
            expected_revision=state.checkpoint.revision, tool_call_sequence=1,
            previous_attempt_id=last.attempt_id, registry_version="registry-v1")


@pytest.mark.parametrize("status, expected", [(408, True), (429, True), (500, True), (502, True), (503, True), (504, True), (501, False), (401, False), (403, False), (413, False)])
def test_http_retry_classification_is_narrow(status, expected):
    response = httpx.Response(status, headers={"retry-after": "45"}, request=httpx.Request("POST", "https://provider.test"))
    failure = classify_failure(APIStatusError("secret body", response=response, body={"error": {"code": "temporary"}}))
    assert failure.transient is expected
    assert failure.retry_after_seconds == (45 if expected else None)
    assert "secret" not in repr(failure)


def test_quota_tls_dns_and_internal_errors_do_not_retry():
    import socket
    import ssl
    response = httpx.Response(429, request=httpx.Request("POST", "https://provider.test"))
    quota = APIStatusError("private", response=response, body={"error": {"code": "insufficient_quota"}})
    assert not classify_failure(quota).transient
    for cause in (ssl.SSLError(), socket.gaierror(socket.EAI_NONAME, "bad host")):
        error = APIConnectionError(request=response.request)
        error.__cause__ = cause
        assert not classify_failure(error).transient
    error = APIConnectionError(request=response.request)
    error.__cause__ = httpx.ConnectTimeout("private")
    assert classify_failure(error).outcome_known and classify_failure(error).transient
    assert not classify_failure(RuntimeError("private")).transient
    assert retry_after({"retry-after": "nan"}) is None
    assert retry_after({"retry-after": "-2"}) is None


def test_fourteen_sessions_receive_action_quanta_without_starvation(tmp_path, no_backoff):
    store, coordinator, session, run = _app(tmp_path)
    from figura.runtime.models import RunCreateRequest
    from figura.providers.models import ProviderId, MODEL_IDS
    runs = [run]
    for index in range(13):
        other = coordinator.create_session()
        runs.append(coordinator.create_run(RunCreateRequest(other.session_id, "测试", "qwen", MODEL_IDS[ProviderId.QWEN], str(index))))
    # Share one thread-safe fake response source. Every first model response creates one tool.
    class ConcurrentFactory:
        def create(self, provider_id, model_id):
            local = _FakeFactory([_response(calls=(ProviderToolCall("call-1", "inspect", '{"value":1}'),), reason=FinishReason.TOOL_CALLS), _response()])
            # Infer first vs later requests from the durable history.
            client = local.create(provider_id, model_id)
            def dispatch(prepared):
                return _response() if any(m.role.value == "tool" for m in prepared.request.messages) else local.client.outcomes[0]
            client.dispatch = dispatch
            return client
    agent = _agent(store, coordinator, _registry(), ConcurrentFactory())
    with RunDispatcher(agent, max_workers=1, max_queued=1, scan_interval=.05) as dispatcher:
        dispatcher.scan_ready()
        deadline = time.monotonic() + 8
        while any(coordinator.read_run_state(r.session_id, r.run_id).run.status is RunStatus.RUNNING for r in runs):
            assert time.monotonic() < deadline
            time.sleep(.02)
    assert all(coordinator.read_run_state(r.session_id, r.run_id).run.status is RunStatus.COMPLETED for r in runs)


@pytest.mark.parametrize("content", [b'{"choices":[],"choices":[]}', b'{"x":NaN}', b'{"x":"' + b'x' * 1024 + b'"}'])
def test_sdk_body_is_bounded_and_strict_before_normalization(content):
    from figura.providers.transport import OpenAISDKTransport, _bound_response
    from tests.test_figura_provider import _environment
    from figura.providers.config import ProviderSettings
    limits = ExecutionPayloadLimits(1024)
    profile = ProviderSettings.from_env(_environment()).profiles[next(iter(ProviderSettings.from_env(_environment()).profiles))]
    transport = OpenAISDKTransport(profile)
    from openai import OpenAI
    transport._client.close()
    sends = []
    def respond(request):
        sends.append(request)
        return httpx.Response(200, content=content)
    transport._client = OpenAI(api_key="test", base_url="https://provider.test/v1", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond), event_hooks={"response": [_bound_response]}))
    from figura.shared.payloads import use_payload_limits
    from figura.providers.errors import ProviderProtocolError
    with use_payload_limits(limits), pytest.raises(ProviderProtocolError):
        transport.create(model="test", messages=[{"role": "user", "content": "test"}])
    assert len(sends) == 1
    transport.close()


def test_frozen_options_survive_default_changes_and_endpoint_drift_is_detectable():
    from tests.test_figura_provider import _factory, _request, FakeTransport, _environment
    from figura.providers.models import ProviderId
    original_request = replace(_request(ProviderId.QWEN), options=ProviderOptions())
    first_client = _factory(FakeTransport()).create(ProviderId.QWEN, original_request.model_id)
    first = first_client.prepare(original_request)
    assert "max_completion_tokens" not in first.payload
    new_factory = _factory(FakeTransport(), {**_environment(), "FIGURA_QWEN_MAX_COMPLETION_TOKENS": "900000", "FIGURA_QWEN_TIMEOUT_SECONDS": "900", "FIGURA_QWEN_REASONING_EFFORT": "high"})
    same = new_factory.create(ProviderId.QWEN, original_request.model_id).prepare(first.request, frozen_options=True, frozen_timeout_seconds=first.descriptor["options"]["timeout_seconds"])
    assert same.descriptor == first.descriptor
    changed = _factory(FakeTransport(), {**_environment(), "FIGURA_QWEN_BASE_URL": "https://other.test/v1"}).create(ProviderId.QWEN, original_request.model_id).prepare(first.request, frozen_options=True, frozen_timeout_seconds=first.descriptor["options"]["timeout_seconds"])
    assert changed.descriptor["endpoint_binding"] != first.descriptor["endpoint_binding"]
    with pytest.raises(TypeError):
        first.payload["messages"][0]["content"] = "tampered"
    with pytest.raises(TypeError):
        first.descriptor["options"]["stream"] = True


def test_long_call_identity_roundtrips_failure_then_model_redecision(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    first_id, second_id = "调用" * 300, "修正" * 300
    calls = []
    factory = _FakeFactory([
        _response(calls=(ProviderToolCall(first_id, "inspect", '{"value":1}'),), reason=FinishReason.TOOL_CALLS),
        _response(calls=(ProviderToolCall(second_id, "inspect", '{"value":2}'),), reason=FinishReason.TOOL_CALLS),
        _response(),
    ])
    state = _agent(store, coordinator, _registry(calls, fail_values=(1,)), factory).execute(session.session_id, run.run_id)
    assert state.run.status is RunStatus.COMPLETED and calls == [first_id, second_id]
    results = [fact.payload for fact in state.tool_facts if fact.fact_kind.value == "tool_result"]
    assert results[0].error.retryable is True and results[0].call_id == first_id
    assert results[1].call_id == second_id
    assert factory.client.requests[-1].messages[2].tool_call_id == first_id


def test_payload_read_ceiling_increases_monotonically_and_new_writes_use_lower_guard(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    raised = FiguraRunStore(tmp_path, payload_limits=ExecutionPayloadLimits(40 * 1024 * 1024))
    from figura.runtime.coordinator import RunCoordinator
    writer = RunCoordinator(raised, coordinator._provider_factory)
    attempt = writer.begin_provider_attempt(session.session_id, run.run_id, 1)
    writer.commit_model_response(session.session_id, run.run_id, 2, _response(content="x" * (33 * 1024 * 1024)), provider_attempt_id=attempt.attempt_id)
    lowered = FiguraRunStore(tmp_path, payload_limits=ExecutionPayloadLimits(1024))
    state = lowered.read_run_state(session.session_id, run.run_id)
    assert len(state.records[-1].payload.assistant_content) == 33 * 1024 * 1024
    with lowered.database.read() as connection:
        assert connection.execute("SELECT read_ceiling FROM execution_payload_metadata").fetchone()[0] == 40 * 1024 * 1024


def test_schema10_upgrade_is_atomic_and_preserves_legacy_rows(tmp_path, monkeypatch):
    from figura.storage import schema
    store, coordinator, session, run = _app(tmp_path)
    before = store.read_run_state(session.session_id, run.run_id)
    # Restore actual v10 bounded DDL, not just its version number.
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        triggers = connection.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'").fetchall()
        for name, _ in triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute("DROP TABLE run_provider_request_bindings")
        connection.execute("DROP TABLE execution_payload_metadata")
        for table, ddl in (
            ("run_execution_records", schema._CORE_SCHEMA[2]),
            ("run_tool_execution_facts", schema._TOOL_SCHEMA[0]),
            ("run_provider_continuations", schema._CONTINUATION_SCHEMA[0]),
            ("run_provider_attempts", schema._PROVIDER_ATTEMPT_SCHEMA[0]),
        ):
            connection.execute(ddl.replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}_old"))
            columns = ", ".join(row[1] for row in connection.execute(f"PRAGMA table_info({table}_old)"))
            connection.execute(f"INSERT INTO {table}_old ({columns}) SELECT {columns} FROM {table}")
            connection.execute(f"DROP TABLE {table}")
            connection.execute(f"ALTER TABLE {table}_old RENAME TO {table}")
        for name, ddl in triggers:
            if name not in {"immutable_provider_binding_update", "immutable_provider_binding_delete", "provider_attempt_matches_binding"}:
                # v10 transition triggers do not reference the new attempt columns.
                if name == "provider_attempt_has_one_terminal_transition":
                    ddl = next(sql for sql in schema._PROVIDER_ATTEMPT_SCHEMA if "CREATE TRIGGER provider_attempt_has_one_terminal_transition" in sql)
                connection.execute(ddl)
        connection.execute("PRAGMA user_version = 10")
    validate = schema._validate_migration
    def fail(connection):
        validate(connection)
        raise RuntimeError("injected migration failure")
    monkeypatch.setattr(schema, "_validate_migration", fail)
    with pytest.raises(RuntimeError):
        FiguraRunStore(tmp_path)
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 10
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'execution_payload_metadata'").fetchone() is None
    monkeypatch.setattr(schema, "_validate_migration", validate)
    upgraded = FiguraRunStore(tmp_path)
    assert upgraded.read_run_state(session.session_id, run.run_id) == before


def test_concurrent_first_open_and_migration_has_consistent_schema(tmp_path):
    with ThreadPoolExecutor(4) as pool:
        stores = list(pool.map(lambda _: FiguraRunStore(tmp_path), range(4)))
    for store in stores:
        with store.database.read() as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 11
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_recovery_claim_limit_applies_directly_before_terminal(tmp_path):
    from tests.test_figura_durable_tool_execution import _commit_response, _tool_response
    store, coordinator, session, run = _app(tmp_path)
    _commit_response(coordinator, session.session_id, run.run_id, 1,
        _tool_response(ProviderToolCall("call-1", "inspect", '{"value":1}')), registry_version="registry-v1")
    first = store.begin_tool_attempt(session_id=session.session_id, run_id=run.run_id, expected_revision=3,
        tool_call_sequence=1, registry_version="registry-v1", replay_effect=ReplayEffect.REPLAY_SAFE)
    previous = first.payload.attempt_id
    for revision in (4, 5):
        fact = store.begin_tool_replay_attempt(session_id=session.session_id, run_id=run.run_id,
            expected_revision=revision, tool_call_sequence=1, previous_attempt_id=previous, registry_version="registry-v1")
        previous = fact.payload.attempt_id
    with pytest.raises(RunError):
        store.begin_tool_replay_attempt(session_id=session.session_id, run_id=run.run_id,
            expected_revision=6, tool_call_sequence=1, previous_attempt_id=previous, registry_version="registry-v1")
    assert len(store.read_run_state(session.session_id, run.run_id).tool_facts) == 4


def test_stop_orphan_binding_closes_unknown_with_valid_metadata(tmp_path):
    store, co, session, run = _app(tmp_path)
    agent = _agent(store, co, _registry(), _FakeFactory([]))
    initial = co.read_run_state(session.session_id, run.run_id)
    co.begin_provider_attempt(session.session_id, run.run_id, 1, binding=_binding(agent, initial))
    co.request_stop(session.session_id, run.run_id)
    stopped = agent.execute_slice(session.session_id, run.run_id)
    assert stopped.run.status is RunStatus.INTERRUPTED
    assert stopped.provider_attempts[0].status.value == "outcome_unknown"
    assert stopped.provider_attempts[0].failure_category == "permanent"


def test_cancellation_storage_failure_propagates_without_dispatch_or_fake_result(tmp_path, monkeypatch):
    from figura.runtime.errors import RunErrorCode
    from figura.runtime.tool_execution import _RunCancellation
    store, co, session, run = _app(tmp_path)
    calls = []
    factory = _FakeFactory([_response(calls=(ProviderToolCall("call-1", "inspect", '{"value":1}'),), reason=FinishReason.TOOL_CALLS)])
    agent = _agent(store, co, _registry(calls), factory)
    agent.execute_slice(session.session_id, run.run_id)
    def unavailable(_):
        raise RunError(RunErrorCode.STORAGE_ERROR)
    monkeypatch.setattr(_RunCancellation, "is_cancelled", unavailable)
    with pytest.raises(RunError):
        agent.execute_slice(session.session_id, run.run_id)
    state = co.read_run_state(session.session_id, run.run_id)
    assert not calls and state.checkpoint.next_action.action_kind is ActionKind.TOOL_ATTEMPT
    assert not any(f.fact_kind.value == "tool_result" for f in state.tool_facts)


def test_long_run_network_recovery_model_redecision_restart_stop_and_delete(tmp_path, no_backoff):
    from figura.runtime.coordinator import RunCoordinator
    from figura.providers.models import ProviderContinuation, ProviderId
    from tests.test_figura_agent_executor import _create_followup_run
    store, co, session, run = _app(tmp_path)
    call_ids = []
    registry = _registry(call_ids, fail_values=(1,))
    continuation = ProviderContinuation(ProviderId.QWEN, 1, "private continuation")
    decisions = [_response(calls=(ProviderToolCall(f"decision-{i}", "inspect", json.dumps({"value":i})),), reason=FinishReason.TOOL_CALLS, continuation=continuation) for i in range(1, 12)]
    factory = _FakeFactory([_temporary(), *decisions, _temporary()])
    agent = _agent(store, co, registry, factory)
    first = agent.execute_slice(session.session_id, run.run_id)
    assert first.checkpoint.next_action.action_kind is ActionKind.PROVIDER_RETRY
    reopened = FiguraRunStore(tmp_path)
    co = RunCoordinator(reopened, co._provider_factory)
    agent = _agent(reopened, co, registry, factory)
    for _ in range(30):
        state = agent.execute_slice(session.session_id, run.run_id)
        if len(call_ids) == 11:
            break
    assert len(call_ids) == 11
    waiting = agent.execute_slice(session.session_id, run.run_id)
    assert len(waiting.provider_continuations) == 11
    assert len(waiting.provider_attempts) == 13
    assert len({r.record_id for r in waiting.records}) == len(waiting.records)
    co.request_stop(session.session_id, run.run_id)
    stopped = agent.execute_slice(session.session_id, run.run_id)
    assert stopped.run.status is RunStatus.INTERRUPTED
    followup = _create_followup_run(co, session.session_id)
    next_factory = _FakeFactory([_response()])
    completed = _agent(reopened, co, registry, next_factory).execute(session.session_id, followup.run_id)
    assert completed.run.status is RunStatus.COMPLETED
    request = next_factory.client.requests[0]
    assert any('"retryable":true' in m.content for m in request.messages if isinstance(m.content, str))
    assert "interrupted" in request.instructions[2].content
    assert call_ids == [f"decision-{i}" for i in range(1, 12)]
    with reopened.database.write() as connection:
        reopened.begin_session_deletion(connection, session.session_id)
        reopened.delete_session_run_facts(connection, session.session_id)
        reopened.delete_session_runs(connection, session.session_id)
        reopened.complete_session_deletion(connection, session.session_id)
    with reopened.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_provider_request_bindings").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_raw_stream_cumulative_limit_is_checked_before_event_json_parse():
    from figura.providers.transport import OpenAISDKTransport, _bound_response
    from tests.test_figura_provider import _environment
    from figura.providers.config import ProviderSettings
    from figura.providers.models import ProviderId
    from figura.providers.errors import ProviderProtocolError
    from figura.shared.payloads import use_payload_limits
    from openai import OpenAI
    transport = OpenAISDKTransport(ProviderSettings.from_env(_environment()).profiles[ProviderId.QWEN])
    transport._client.close()
    yielded = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for i in range(100):
                yielded.append(i)
                yield b'data: {"choices":[]}\n\n'
    transport._client = OpenAI(api_key="test", base_url="https://provider.test", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream())), event_hooks={"response": [_bound_response]}))
    with use_payload_limits(ExecutionPayloadLimits(64)), pytest.raises(ProviderProtocolError):
        list(transport.create(model="test", messages=[], stream=True))
    assert len(yielded) < 100
    transport.close()


def _open_store_process(root):
    store = FiguraRunStore(root)
    with store.database.read() as connection:
        return connection.execute("PRAGMA user_version").fetchone()[0], connection.execute("PRAGMA foreign_key_check").fetchall()


def test_multiple_processes_first_open_share_one_atomic_migration(tmp_path):
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(3, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(_open_store_process, [str(tmp_path)] * 3))
    assert results == [(11, [])] * 3


def test_multiple_retry_waiters_use_no_queue_capacity_and_ready_run_completes(tmp_path):
    from figura.runtime.models import RunCreateRequest
    from figura.providers.models import ProviderId, MODEL_IDS
    store, co, session, run = _app(tmp_path)
    runs = [run]
    for i in range(3):
        other = co.create_session()
        runs.append(co.create_run(RunCreateRequest(other.session_id, "测试", "qwen", MODEL_IDS[ProviderId.QWEN], str(i))))
    factory = _FakeFactory([ProviderCallError(ProviderFailure(ProviderFailureCode.PROVIDER_REJECTED, True, True, "限流。", 429, 3600))] * 3 + [_response()])
    agent = _agent(store, co, _registry(), factory)
    for waiter in runs[:3]:
        agent.execute_slice(waiter.session_id, waiter.run_id)
    with RunDispatcher(agent, max_workers=1, max_queued=0, scan_interval=.02) as dispatcher:
        for waiter in runs[:3]:
            assert not dispatcher.ensure_scheduled(waiter)
            assert dispatcher.activity(waiter.run_id) is None
        dispatcher.scan_ready()
        deadline = time.monotonic() + 3
        while co.read_run_state(runs[3].session_id, runs[3].run_id).run.status is RunStatus.RUNNING:
            assert time.monotonic() < deadline
            time.sleep(.01)
    assert len(factory.client.requests) == 4
    assert all(len(co.read_run_state(r.session_id, r.run_id).provider_attempts) == 1 for r in runs[:3])


def test_bound_image_digest_and_identity_detect_content_or_source_changes():
    from tests.test_figura_provider import _factory, _request, FakeTransport
    from figura.providers.models import ProviderId, ProviderMessage, MessageRole, ImageBlock
    from figura.runtime.codecs.bindings import encode_binding, decode_binding
    from types import MappingProxyType
    client = _factory(FakeTransport()).create(ProviderId.QWEN, "qwen3.8-flash")
    image = ImageBlock("image/png", b"image bytes", MappingProxyType({"kind": "attachment", "id": "attachment-1"}))
    request = replace(_request(ProviderId.QWEN), messages=(ProviderMessage(MessageRole.USER, (image,)),))
    prepared = client.prepare(request)
    binding = ProviderRequestBinding(operation_id="operation-1", run_id="run-1", base_record_sequence=1,
        base_tool_sequence=0, created_at=_utc_now(), **prepared.descriptor)
    assert decode_binding(encode_binding(binding)) == binding
    changed_bytes = client.prepare(replace(request, messages=(ProviderMessage(MessageRole.USER, (replace(image, image_bytes=b"different bytes"),)),)))
    changed_ref = client.prepare(replace(request, messages=(ProviderMessage(MessageRole.USER, (replace(image, source_ref={"kind": "attachment", "id": "attachment-2"}),)),)))
    assert changed_bytes.descriptor["request_fingerprint"] != prepared.descriptor["request_fingerprint"]
    assert changed_ref.descriptor["request_fingerprint"] == prepared.descriptor["request_fingerprint"]
    assert changed_ref.descriptor["asset_manifest"] != prepared.descriptor["asset_manifest"]


def test_native_tool_stop_keeps_owner_and_rejects_takeover_until_result(tmp_path):
    from threading import Event, Thread
    from figura.tools import ToolRegistry
    from figura.runtime.tool_execution import DurableToolExecutor
    from tests.test_figura_agent_executor import _commit_tool_response
    store, co, session, run = _app(tmp_path)
    entered, release = Event(), Event()
    calls = []
    base = _registry(calls).get("inspect")
    def native(context, args):
        entered.set()
        assert release.wait(5)
        # The actual result remains observable even after stop.
        return base.handler(context, args)
    registry = ToolRegistry("registry-v1", (replace(base, handler=native),))
    _commit_tool_response(co, session.session_id, run.run_id, registry,
        _response(calls=(ProviderToolCall("call-1", "inspect", '{"value":1}'),), reason=FinishReason.TOOL_CALLS))
    agent = _agent(store, co, registry, _FakeFactory([]))
    results = []
    worker = Thread(target=lambda: results.append(agent.execute(session.session_id, run.run_id)))
    worker.start()
    try:
        assert entered.wait(5)
        co.request_stop(session.session_id, run.run_id)
        with pytest.raises(RunError):
            DurableToolExecutor(store, registry).recover_unknown_attempt(session.session_id, run.run_id)
        with pytest.raises(RunError):
            with store.database.write() as connection:
                store.begin_session_deletion(connection, session.session_id)
        assert agent.execute_slice(session.session_id, run.run_id).run.status is RunStatus.RUNNING
        assert not calls
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and results[0].run.status is RunStatus.INTERRUPTED
    assert calls == ["call-1"]
    assert len([f for f in results[0].tool_facts if f.fact_kind.value == "tool_result"]) == 1


def test_gateway_read_routes_do_not_schedule_or_recover_started_attempt(tmp_path, monkeypatch):
    from tests.test_figura_gateway import _application, _create_run, _json
    from figura.gateway.server import FiguraHTTPServer
    from http.client import HTTPConnection
    from threading import Thread
    app, _, co, _, passive = _application(tmp_path)
    session = co.create_session()
    run = _create_run(co, session.session_id)
    co.begin_provider_attempt(session.session_id, run.run_id, 1)
    before = co.read_run_state(session.session_id, run.run_id)
    scheduled = []
    monkeypatch.setattr(app.dispatcher, "ensure_scheduled", lambda *a, **kw: scheduled.append(a))
    server = FiguraHTTPServer(("127.0.0.1", 0), app)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        prefix = f"/api/v1/sessions/{session.session_id}"
        for path in ("/api/v1/health", prefix, prefix + "/runs", prefix + f"/runs/{run.run_id}/history", prefix + f"/runs/{run.run_id}/timeline", prefix + f"/runs/{run.run_id}/timeline/missing"):
            assert app.handle("GET", path, {}).status in {200, 404}
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request("GET", prefix + f"/runs/{run.run_id}/events?afterSequence=0")
        response = connection.getresponse()
        assert response.status == 200
        assert response.readline().decode().startswith(f"id: {run.run_id}:1")
        connection.close()
        assert not scheduled and not passive.calls
        assert co.read_run_state(session.session_id, run.run_id) == before
    finally:
        server.shutdown()
        server.server_close()
        app.close()


def test_sdk_transport_disables_hidden_retries_and_rejects_invalid_utf8_stream():
    from figura.providers.transport import OpenAISDKTransport, _bound_response
    from tests.test_figura_provider import _environment
    from figura.providers.config import ProviderSettings
    from figura.providers.models import ProviderId
    from figura.providers.errors import ProviderProtocolError
    from openai import OpenAI
    transport = OpenAISDKTransport(ProviderSettings.from_env(_environment()).profiles[ProviderId.QWEN])
    assert transport._client.max_retries == 0
    assert transport._client._client._transport._pool._retries == 0
    transport._client.close()
    transport._client = OpenAI(api_key="test", base_url="https://provider.test", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b'data: {"content":"\xff"}\n\n')), event_hooks={"response": [_bound_response]}))
    try:
        with pytest.raises(ProviderProtocolError):
            list(transport.create(model="test", messages=[], stream=True))
    finally:
        transport.close()
