from __future__ import annotations

from dataclasses import replace
import json
import multiprocessing
from threading import Event, Thread

import pytest

from tests.test_figura_agent_executor import (
    _app, _agent, _registry, _response, _FakeFactory, _create_followup_run,
    _commit_tool_response,
)
from figura.memory import project_session_history
from figura.providers import FinishReason, ProviderToolCall
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RunStatus
from figura.runtime.persistence.controls import RunStopRequested
from figura.runtime.run_lock import RunExecutionOwnership
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.tools import ReplayEffect


@pytest.mark.parametrize("value, expected", [(1, "committed_success"), (2, "committed_failure")])
def test_partial_terminal_batch_retains_observations_and_continues(tmp_path, value, expected):
    store, co, session, run = _app(tmp_path)
    registry = _registry(fail_values=(2,))
    _commit_tool_response(co, session.session_id, run.run_id, registry, _response(
        content="原始意图：读取后分析", reason=FinishReason.TOOL_CALLS,
        calls=tuple(ProviderToolCall(f"call-{i}", "inspect", json.dumps({"value": value})) for i in range(3)),
    ))
    state = DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id, max_calls=1)
    store.begin_tool_attempt(session_id=session.session_id, run_id=run.run_id,
        expected_revision=state.checkpoint.revision, tool_call_sequence=2,
        registry_version=registry.version, replay_effect=ReplayEffect.REPLAY_SAFE)
    state = co.read_run_state(session.session_id, run.run_id)
    co.interrupt_run(session.session_id, run.run_id, state.checkpoint.revision)
    prior = co.read_run_state(session.session_id, run.run_id)
    current = _create_followup_run(co, session.session_id)
    history = project_session_history(current, (prior,))
    calls = history.run_outcomes[0].incomplete_batches[0].calls
    assert [item.state for item in calls] == [expected, "outcome_unknown", "not_started"]
    assert calls[0].source_result_tool_sequence is not None
    assert json.loads(calls[0].observation_json)["outcome"] == ("succeeded" if value == 1 else "failed")
    assert calls[1].observation_json is None
    assert len(history.messages) == 1
    factory = _FakeFactory([_response()])
    result = _agent(store, co, registry, factory).execute(session.session_id, current.run_id)
    assert result.run.status is RunStatus.COMPLETED
    payload = json.loads(factory.client.requests[0].instructions[2].content.split("\n", 1)[1])
    assert payload["prior_run_outcomes"][0]["incomplete_batches"][0]["calls"][0]["state"] == expected
    assert not any(message.tool_calls for message in factory.client.requests[0].messages)
    corrupt = replace(prior, tool_facts=(*prior.tool_facts, prior.tool_facts[-1]))
    with pytest.raises(RunError):
        project_session_history(current, (corrupt,))


def test_stop_is_idempotent_survives_reopen_and_prevents_claim(tmp_path):
    store, co, session, run = _app(tmp_path)
    before = co.read_run_state(session.session_id, run.run_id)
    first = co.request_stop(session.session_id, run.run_id)
    assert co.request_stop(session.session_id, run.run_id) == first
    state = FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id)
    assert state.stop_request == first
    assert state.checkpoint == before.checkpoint
    assert len(state.events) == len(before.events) + 1
    with pytest.raises(RunStopRequested):
        co.begin_provider_attempt(session.session_id, run.run_id, state.checkpoint.revision)
    factory = _FakeFactory([])
    result = _agent(store, co, _registry(), factory).execute(session.session_id, run.run_id)
    assert result.run.status is RunStatus.INTERRUPTED
    assert not factory.client.requests
    assert len([event for event in result.events if event.event_kind.value == "run_interrupted"]) == 1
    assert co.request_stop(session.session_id, run.run_id) == first


def test_stop_during_provider_keeps_real_response_and_does_not_start_tools(tmp_path):
    store, co, session, run = _app(tmp_path)
    calls = []
    registry = _registry(calls)
    factory = _FakeFactory([_response(reason=FinishReason.TOOL_CALLS,
        calls=(ProviderToolCall("pending", "inspect", '{"value":1}'),))])
    entered, release = Event(), Event()
    def block_dispatch():
        entered.set()
        assert release.wait(5)
    factory.client.before_dispatch = block_dispatch
    results = []
    thread = Thread(target=lambda: results.append(_agent(store, co, registry, factory).execute(session.session_id, run.run_id)))
    thread.start()
    try:
        assert entered.wait(5)
        co.request_stop(session.session_id, run.run_id)
        with pytest.raises(RunError):
            co.interrupt_run(session.session_id, run.run_id, co.read_run_state(session.session_id, run.run_id).checkpoint.revision)
        assert co.read_run_state(session.session_id, run.run_id).run.status is RunStatus.RUNNING
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert results[0].run.status is RunStatus.INTERRUPTED
    assert results[0].provider_attempts[0].status.value == "response_committed"
    assert len(results[0].tool_facts) == 1
    assert calls == []


def _hold_owner(root, run_id, connection):
    with RunExecutionOwnership(root).acquire(run_id):
        connection.send(True)
        connection.recv()


@pytest.mark.parametrize("abrupt", [False, True])
def test_cross_process_owner_releases_after_exit(tmp_path, abrupt):
    store, co, session, run = _app(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=_hold_owner, args=(str(tmp_path), run.run_id, child))
    process.start()
    try:
        assert parent.poll(5) and parent.recv()
        factory = _FakeFactory([_response()])
        state = _agent(store, co, _registry(), factory).execute(session.session_id, run.run_id)
        assert state.run.status is RunStatus.RUNNING and not factory.client.requests
        if abrupt:
            process.terminate()
        else:
            parent.send(True)
        process.join(5)
        assert process.exitcode is not None and (process.exitcode != 0 if abrupt else process.exitcode == 0)
        state = _agent(store, co, _registry(), factory).execute(session.session_id, run.run_id)
        assert state.run.status is RunStatus.COMPLETED
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()
        child.close()


@pytest.mark.parametrize('mode, expected_code', [
    ('exhausted', 'tool_recovery_exhausted'),
    ('registry', 'tool_recovery_unavailable'),
    ('reconcile', 'tool_outcome_unknown'),
    ('stop', 'interrupted'),
])
def test_orphan_classification_never_invokes_unsafe_handler(tmp_path, mode, expected_code):
    from figura.tools import ToolRegistry
    store, co, session, run = _app(tmp_path)
    calls = []
    registry = _registry(calls)
    _commit_tool_response(co, session.session_id, run.run_id, registry, _response(
        reason=FinishReason.TOOL_CALLS,
        calls=(ProviderToolCall('orphan', 'inspect', '{"value":1}'),),
    ))
    state = co.read_run_state(session.session_id, run.run_id)
    effect = ReplayEffect.RECONCILE_REQUIRED if mode == 'reconcile' else ReplayEffect.REPLAY_SAFE
    attempt = store.begin_tool_attempt(session_id=session.session_id, run_id=run.run_id,
        expected_revision=state.checkpoint.revision, tool_call_sequence=1,
        registry_version=registry.version, replay_effect=effect)
    if mode == 'exhausted':
        for _ in range(2):
            state = co.read_run_state(session.session_id, run.run_id)
            attempt = store.begin_tool_replay_attempt(session_id=session.session_id, run_id=run.run_id,
                expected_revision=state.checkpoint.revision, tool_call_sequence=1,
                previous_attempt_id=attempt.payload.attempt_id, registry_version=registry.version)
    if mode == 'registry':
        registry = ToolRegistry('different-registry', registry.definitions)
    elif mode == 'reconcile':
        registry = ToolRegistry(registry.version, tuple(replace(d, replay_effect=effect) for d in registry.definitions))
    elif mode == 'stop':
        co.request_stop(session.session_id, run.run_id)
    factory = _FakeFactory([])
    result = _agent(store, co, registry, factory).execute(session.session_id, run.run_id)
    assert result.run.terminal_code == expected_code
    assert not calls and not factory.client.requests
    assert result.checkpoint.next_action.action_kind.value == 'tool_attempt'
    assert len([e for e in result.events if e.event_kind.value in {'run_failed', 'run_interrupted'}]) == 1
    assert _agent(store, co, registry, factory).execute(session.session_id, run.run_id) == result


def test_unknown_provider_with_stop_is_not_redispatched(tmp_path):
    store, co, session, run = _app(tmp_path)
    state = co.read_run_state(session.session_id, run.run_id)
    co.begin_provider_attempt(session.session_id, run.run_id, state.checkpoint.revision)
    co.request_stop(session.session_id, run.run_id)
    factory = _FakeFactory([])
    result = _agent(store, co, _registry(), factory).execute(session.session_id, run.run_id)
    assert result.run.status is RunStatus.INTERRUPTED
    assert result.provider_attempts[0].status.value == 'outcome_unknown'
    assert not factory.client.requests
    assert _create_followup_run(co, session.session_id).ordinal == 2


def test_stop_transaction_rolls_back_request_when_progress_insert_fails(tmp_path):
    store, co, session, run = _app(tmp_path)
    before = co.read_run_state(session.session_id, run.run_id)
    with store.database.write() as connection:
        connection.execute("CREATE TRIGGER reject_stop_progress BEFORE INSERT ON run_stream_events WHEN NEW.event_kind = 'run_progress' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(RunError):
        co.request_stop(session.session_id, run.run_id)
    assert co.read_run_state(session.session_id, run.run_id) == before


def test_stop_api_is_scoped_durable_and_separates_acceptance_from_terminal(tmp_path):
    from tests.test_figura_gateway import _application, _create_run, _json, ORIGIN
    app, store, co, _, _ = _application(tmp_path)
    try:
        session = co.create_session()
        run = _create_run(co, session.session_id)
        url = f'/api/v1/sessions/{session.session_id}/runs/{run.run_id}/stop'
        headers = {'Origin': ORIGIN}
        first = app.handle('POST', url, headers)
        assert first.status == 202
        payload = _json(first)
        assert payload['run']['status'] == 'running'
        assert payload['run']['executionState'] == 'stopping'
        assert payload['run']['availableActions'] == []
        assert _json(app.handle('POST', url, headers, b'{}')) == payload
        assert app.handle('POST', url, headers, b'{"reason":"anything"}').status == 400
        other = co.create_session()
        assert app.handle('POST', url.replace(session.session_id, other.session_id), headers).status == 404
        assert app.handle('POST', url, {}).status == 403
        assert FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id).stop_request is not None
        state = co.read_run_state(session.session_id, run.run_id)
        co.interrupt_run(session.session_id, run.run_id, state.checkpoint.revision)
        terminal = app.handle('POST', url, headers)
        assert terminal.status == 200
        assert _json(terminal)['run']['executionState'] == 'terminal'
        assert _json(terminal)['stopRequest'] == payload['stopRequest']
        assert _create_followup_run(co, session.session_id).ordinal == 2
    finally:
        app.close()


def test_periodic_scan_compensates_without_manual_resubmission(tmp_path):
    from time import monotonic, sleep
    from figura.gateway.dispatcher import RunDispatcher
    store, co, session, run = _app(tmp_path)
    co.request_stop(session.session_id, run.run_id)
    factory = _FakeFactory([])
    dispatcher = RunDispatcher(_agent(store, co, _registry(), factory), max_workers=1, max_queued=0, scan_interval=0.02)
    try:
        deadline = monotonic() + 5
        while co.read_run_state(session.session_id, run.run_id).run.status is RunStatus.RUNNING and monotonic() < deadline:
            sleep(0.02)
        assert co.read_run_state(session.session_id, run.run_id).run.status is RunStatus.INTERRUPTED
        assert not factory.client.requests
    finally:
        dispatcher.close()
    assert not dispatcher._scanner.is_alive()


def test_ocr_success_measurement_unknown_render_unstarted_continues_with_authorized_observation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tests.test_figura_bar_measurement_tool import _setup, _request_builder
    from tests.figura_sources_support import make_execution_image_reader
    from figura.sources.chart_renders import FiguraChartRenderService
    from figura.tools import ToolRegistry
    from figura.tools.implementations.extract_text import extract_text_definition
    from figura.tools.implementations.measure_bars import measure_bars_definition
    from figura.tools.implementations.render_chart_figure import render_chart_figure_definition
    from figura.agent.execution_resources import ToolResourceRef
    from figura.providers import ImageBlock
    import figura.tools.measurements.ocr as ocr_module
    store, co, session, run, attachments, panels, execution_state, _, _, attachment = _setup(tmp_path)
    monkeypatch.setattr(ocr_module, '_engine', lambda _image: SimpleNamespace(
        boxes=[[(30, 10), (80, 10), (80, 22), (30, 22)]], txts=['Sales'], scores=[0.95]))
    renders = FiguraChartRenderService(store.data_root)
    reader = make_execution_image_reader(attachments, panels, renders)
    registry = ToolRegistry('abnormal-observation-v1', (
        extract_text_definition(execution_state.for_run, reader),
        measure_bars_definition(execution_state.for_run, reader),
        render_chart_figure_definition(execution_state.for_run, renders),
    ))
    source = json.dumps({'source_kind': 'attachment', 'source_id': attachment.attachment_id})
    _commit_tool_response(co, session.session_id, run.run_id, registry, _response(
        content='读取文字，再测量，最后渲染。', reason=FinishReason.TOOL_CALLS,
        calls=(ProviderToolCall('ocr', 'extract_text', source),
               ProviderToolCall('measurement', 'measure_bars', source),
               ProviderToolCall('render', 'render_chart_figure', '{"figure_ref":{"run_id":"missing","call_id":"missing"}}'))))
    state = DurableToolExecutor(store, registry).execute_pending(session.session_id, run.run_id, max_calls=1)
    store.begin_tool_attempt(session_id=session.session_id, run_id=run.run_id,
        expected_revision=state.checkpoint.revision, tool_call_sequence=2,
        registry_version=registry.version, replay_effect=ReplayEffect.REPLAY_SAFE)
    state = co.read_run_state(session.session_id, run.run_id)
    co.interrupt_run(session.session_id, run.run_id, state.checkpoint.revision)
    next_run = _create_followup_run(co, session.session_id)
    projection = execution_state.for_run(session.session_id, next_run.run_id)
    assert [r.ref.call_id for r in projection.list('ocr')] == ['ocr']
    assert not projection.list('measurement') and not projection.list('chart_render')
    image = reader.read(session.session_id, projection, ToolResourceRef('ocr', run.run_id, 'ocr'))
    assert image is not None
    builder = _request_builder(store, attachments, panels, execution_state)
    factory = _FakeFactory([_response()])
    result = _agent(store, co, registry, factory, builder).execute(session.session_id, next_run.run_id)
    assert result.run.status is RunStatus.COMPLETED
    request = factory.client.requests[0]
    payload = json.loads(request.instructions[2].content.split('\n', 1)[1])
    calls = payload['prior_run_outcomes'][0]['incomplete_batches'][0]['calls']
    assert [c['state'] for c in calls] == ['committed_success', 'outcome_unknown', 'not_started']
    assert 'Sales' in calls[0]['observation_json']
    assert not any(isinstance(b, ImageBlock) for m in request.messages for b in (m.content if isinstance(m.content, tuple) else ()))


def test_stop_after_prepare_prevents_dispatch_and_attempt(tmp_path):
    store, co, session, run = _app(tmp_path)
    factory = _FakeFactory([_response()])
    factory.client.after_prepare = lambda: co.request_stop(session.session_id, run.run_id)
    result = _agent(store, co, _registry(), factory).execute(session.session_id, run.run_id)
    assert result.run.status is RunStatus.INTERRUPTED
    assert len(factory.client.prepared_requests) == 1
    assert not factory.client.requests and not result.provider_attempts


def test_completed_before_stop_remains_completed_without_control_event(tmp_path):
    store, co, session, run = _app(tmp_path)
    result = _agent(store, co, _registry(), _FakeFactory([_response()])).execute(session.session_id, run.run_id)
    assert co.request_stop(session.session_id, run.run_id) is None
    assert co.read_run_state(session.session_id, run.run_id) == result


def test_terminal_owner_blocks_new_run_and_session_deletion_until_release(tmp_path):
    from tests.test_figura_gateway import _application, _create_run, ORIGIN
    app, store, co, _, _ = _application(tmp_path)
    try:
        session = co.create_session()
        run = _create_run(co, session.session_id)
        state = co.read_run_state(session.session_id, run.run_id)
        co.interrupt_run(session.session_id, run.run_id, state.checkpoint.revision)
        with RunExecutionOwnership(store.data_root).acquire(run.run_id):
            assert _create_run(co, session.session_id).run_id == run.run_id
            with pytest.raises(RunError) as error:
                _create_followup_run(co, session.session_id)
            assert error.value.code is RunErrorCode.INVALID_TRANSITION
            assert app.handle('DELETE', f'/api/v1/sessions/{session.session_id}', {'Origin': ORIGIN}).status == 409
        assert app.handle('DELETE', f'/api/v1/sessions/{session.session_id}', {'Origin': ORIGIN}).status == 204
    finally:
        app.close()


def test_v9_migration_preserves_facts_and_adds_empty_stop_controls(tmp_path):
    import sqlite3
    store, co, session, run = _app(tmp_path)
    before = co.read_run_state(session.session_id, run.run_id)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute('DROP TRIGGER immutable_run_stop_request_update')
        connection.execute('DROP TRIGGER immutable_run_stop_request_delete')
        connection.execute('DROP TABLE run_stop_requests')
        connection.execute('PRAGMA user_version = 9')
    reopened = FiguraRunStore(tmp_path)
    assert reopened.read_run_state(session.session_id, run.run_id) == before
    with reopened.database.read() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 10
        assert not connection.execute('SELECT * FROM run_stop_requests').fetchall()
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()


def test_abnormal_outcome_limit_is_not_silently_trimmed(tmp_path, monkeypatch):
    import figura.providers.validation as validation
    store, co, session, run = _app(tmp_path)
    registry = _registry()
    _commit_tool_response(co, session.session_id, run.run_id, registry, _response(
        content='保留全部原始意图' * 100, reason=FinishReason.TOOL_CALLS,
        calls=(ProviderToolCall('pending', 'inspect', '{"value":1}'),)))
    state = co.read_run_state(session.session_id, run.run_id)
    co.interrupt_run(session.session_id, run.run_id, state.checkpoint.revision)
    next_run = _create_followup_run(co, session.session_id)
    monkeypatch.setattr(validation, 'MAX_TOTAL_TEXT_BYTES', 100)
    factory = _FakeFactory([])
    result = _agent(store, co, registry, factory).execute(session.session_id, next_run.run_id)
    assert result.run.status is RunStatus.FAILED
    assert not result.provider_attempts and not factory.client.requests
    assert '保留全部原始意图' * 100 in factory.client.prepared_requests[0].instructions[2].content


def test_queue_saturation_defers_durable_stop_until_worker_is_free(tmp_path):
    from time import monotonic, sleep
    from figura.gateway.dispatcher import RunDispatcher, DispatcherFull
    store, co, session, run = _app(tmp_path)
    second_session = co.create_session()
    second_run = _create_followup_run(co, second_session.session_id)
    entered, release = Event(), Event()
    factory = _FakeFactory([_response()])
    factory.client.before_dispatch = lambda: (entered.set(), release.wait(5))
    dispatcher = RunDispatcher(_agent(store, co, _registry(), factory), max_workers=1, max_queued=0, scan_interval=0.02)
    try:
        dispatcher.ensure_scheduled(run)
        assert entered.wait(5)
        co.request_stop(second_session.session_id, second_run.run_id)
        assert dispatcher.ensure_scheduled(run) is False
        with pytest.raises(DispatcherFull):
            dispatcher.ensure_scheduled(second_run)
        sleep(0.06)
        assert co.read_run_state(second_session.session_id, second_run.run_id).stop_request is not None
        assert co.read_run_state(second_session.session_id, second_run.run_id).run.status is RunStatus.RUNNING
        release.set()
        deadline = monotonic() + 5
        while co.read_run_state(second_session.session_id, second_run.run_id).run.status is RunStatus.RUNNING and monotonic() < deadline:
            sleep(0.02)
        assert co.read_run_state(second_session.session_id, second_run.run_id).run.status is RunStatus.INTERRUPTED
        assert len(factory.client.requests) == 1
    finally:
        release.set()
        dispatcher.close()


def test_periodic_recovery_budget_survives_failed_result_commits(tmp_path, monkeypatch):
    from time import monotonic, sleep
    from figura.gateway.dispatcher import RunDispatcher
    from figura.runtime.records import ToolAttemptStartedFact
    store, co, session, run = _app(tmp_path)
    calls = []
    registry = _registry(calls)
    _commit_tool_response(co, session.session_id, run.run_id, registry, _response(
        reason=FinishReason.TOOL_CALLS, calls=(ProviderToolCall('bounded', 'inspect', '{"value":1}'),)))
    def unavailable_commit(*args, **kwargs):
        raise RunError(RunErrorCode.STORAGE_ERROR)
    monkeypatch.setattr(FiguraRunStore, 'commit_tool_result', unavailable_commit)
    dispatcher = RunDispatcher(_agent(store, co, registry, _FakeFactory([])), scan_interval=0.02)
    try:
        deadline = monotonic() + 5
        while co.read_run_state(session.session_id, run.run_id).run.status is RunStatus.RUNNING and monotonic() < deadline:
            sleep(0.02)
        state = co.read_run_state(session.session_id, run.run_id)
        assert state.run.terminal_code == 'tool_recovery_exhausted'
        assert [f.payload.attempt_number for f in state.tool_facts if isinstance(f.payload, ToolAttemptStartedFact)] == [1, 2, 3]
        assert len(calls) == 3
    finally:
        dispatcher.close()


@pytest.mark.parametrize('known', [False, True])
def test_provider_failure_competes_with_stop_without_losing_outcome(tmp_path, known):
    from figura.providers.errors import ProviderCallError, ProviderFailure, ProviderFailureCode
    store, co, session, run = _app(tmp_path)
    failure = ProviderCallError(ProviderFailure(
        failure_code=ProviderFailureCode.PROVIDER_REJECTED if known else ProviderFailureCode.TIMEOUT,
        outcome_known=known, transient=False, safe_message='服务商执行失败。'))
    factory = _FakeFactory([failure])
    factory.client.before_dispatch = lambda: co.request_stop(session.session_id, run.run_id)
    result = _agent(store, co, _registry(), factory).execute(session.session_id, run.run_id)
    assert result.run.status is RunStatus.INTERRUPTED
    assert result.provider_attempts[0].status.value == ('known_failure' if known else 'outcome_unknown')
    assert len(factory.client.requests) == 1


@pytest.mark.parametrize('failed', [False, True])
def test_stop_from_started_tool_preserves_real_result_and_blocks_next_call(tmp_path, failed):
    from figura.tools import ToolRegistry, ToolFailure
    from figura.runtime.records import ToolResultFact
    store, co, session, run = _app(tmp_path)
    calls = []
    def handler(context, arguments):
        calls.append(context.call_id)
        co.request_stop(session.session_id, run.run_id)
        if failed:
            raise ToolFailure('inspection_failed', '无法检查该值。', retryable=True)
        return {'value': 1}
    base = _registry()
    registry = ToolRegistry(base.version, (replace(base.definitions[0], handler=handler),))
    _commit_tool_response(co, session.session_id, run.run_id, registry, _response(
        reason=FinishReason.TOOL_CALLS, calls=(ProviderToolCall('first', 'inspect', '{"value":1}'), ProviderToolCall('next', 'inspect', '{"value":2}'))))
    state = _agent(store, co, registry, _FakeFactory([])).execute(session.session_id, run.run_id)
    assert state.run.status is RunStatus.INTERRUPTED and calls == ['first']
    results = [f.payload for f in state.tool_facts if isinstance(f.payload, ToolResultFact)]
    assert len(results) == 1 and results[0].outcome.value == ('failed' if failed else 'succeeded')
    with pytest.raises(RunStopRequested):
        store.begin_tool_attempt(session_id=session.session_id, run_id=run.run_id,
            expected_revision=state.checkpoint.revision, tool_call_sequence=2,
            registry_version=registry.version, replay_effect=ReplayEffect.REPLAY_SAFE)


def test_orphan_render_recovery_reuses_png_written_before_result_commit(tmp_path, monkeypatch):
    from tests.test_figura_gateway import _application, _create_run, _commit_chart_render
    from figura.tools import ToolRegistry
    from figura.tools.implementations.assemble_chart_figure import assemble_chart_figure_definition
    from figura.tools.implementations.render_chart_figure import render_chart_figure_definition
    from figura.sources.chart_renders import FiguraChartRenderService
    app, store, co, _, _ = _application(tmp_path)
    try:
        session = co.create_session()
        run = _create_run(co, session.session_id)
        original = FiguraRunStore.commit_tool_result
        commits = []
        def lose_render_commit(self, **kwargs):
            commits.append(kwargs['attempt_id'])
            if len(commits) == 2:
                raise RunError(RunErrorCode.STORAGE_ERROR)
            return original(self, **kwargs)
        monkeypatch.setattr(FiguraRunStore, 'commit_tool_result', lose_render_commit)
        with pytest.raises(RunError):
            _commit_chart_render(app, store, session.session_id, run.run_id)
        files = list(tmp_path.rglob('*.png'))
        assert len(files) == 1
        before = files[0].read_bytes(), files[0].stat().st_mtime_ns
        assert not app.execution_state.for_run(session.session_id, run.run_id).list('chart_render')
        monkeypatch.setattr(FiguraRunStore, 'commit_tool_result', original)
        registry = ToolRegistry('figura-web-v6', (
            assemble_chart_figure_definition(app.execution_state.for_run),
            render_chart_figure_definition(app.execution_state.for_run, FiguraChartRenderService(store.data_root))))
        result = _agent(store, co, registry, _FakeFactory([_response()])).execute(session.session_id, run.run_id)
        assert result.run.status is RunStatus.COMPLETED
        assert list(tmp_path.rglob('*.png')) == files
        assert (files[0].read_bytes(), files[0].stat().st_mtime_ns) == before
        assert len(app.execution_state.for_run(session.session_id, run.run_id).list('chart_render')) == 1
    finally:
        app.close()


def test_stopped_session_aggregate_deletion_removes_control_facts(tmp_path):
    from tests.test_figura_gateway import _application, _create_run, ORIGIN
    app, store, co, _, _ = _application(tmp_path)
    try:
        session = co.create_session()
        run = _create_run(co, session.session_id)
        co.request_stop(session.session_id, run.run_id)
        state = co.read_run_state(session.session_id, run.run_id)
        co.interrupt_run(session.session_id, run.run_id, state.checkpoint.revision)
        assert app.handle('DELETE', f'/api/v1/sessions/{session.session_id}', {'Origin': ORIGIN}).status == 204
        with store.database.read() as connection:
            assert not connection.execute('SELECT * FROM run_stop_requests').fetchall()
            assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    finally:
        app.close()
