from __future__ import annotations

import pytest

from figura.agent.executor import AgentExecutor
from figura.providers import (
    MODEL_IDS,
    FinishReason,
    ProviderFactory,
    ProviderId,
    ProviderResponse,
    ProviderToolCall,
)
from figura.providers.errors import ProviderCallError, ProviderFailure, ProviderFailureCode
from figura.runtime import (
    ActionKind,
    DurableToolExecutor,
    FiguraRunStore,
    RunCoordinator,
    RunCreateRequest,
    RunStatus,
    TerminalCode,
)
from figura.runtime._run_lock import PerRunExecutionLock
from figura.tools import ReplayEffect, ToolDefinition, ToolFailure, ToolRegistry


def _registry(
    calls: list[str] | None = None,
    *,
    fail_values: tuple[int, ...] = (),
) -> ToolRegistry:
    def handler(context, arguments):
        if calls is not None:
            calls.append(context.call_id)
        if arguments["value"] in fail_values:
            raise ToolFailure("inspection_failed", "无法检查该值。", retryable=True)
        return {"value": arguments["value"]}

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
                replay_effect=ReplayEffect.REPLAY_SAFE,
                handler=handler,
            ),
        ),
    )


def _app(tmp_path):
    store = FiguraRunStore(tmp_path)
    real_factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )
    coordinator = RunCoordinator(store, real_factory)
    session = coordinator.create_session()
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="分析图表数据",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="agent-executor-test",
        )
    )
    return store, coordinator, session, run


def _response(
    *,
    content: str = "分析完成",
    calls: tuple[ProviderToolCall, ...] = (),
    reason: FinishReason = FinishReason.STOP,
) -> ProviderResponse:
    return ProviderResponse(
        provider_id=ProviderId.QWEN,
        model_id=MODEL_IDS[ProviderId.QWEN],
        assistant_content=content,
        tool_calls=calls,
        finish_reason=reason,
    )


class _FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self):
        return None


class _FakeFactory:
    def __init__(self, outcomes):
        self.client = _FakeClient(outcomes)
        self.selections = []

    def create(self, provider_id, model_id):
        self.selections.append((provider_id, model_id))
        return self.client


def _agent(store, coordinator, registry, provider_factory):
    tool_executor = DurableToolExecutor(store, registry)
    return AgentExecutor(
        coordinator,
        provider_factory,
        tool_executor,
        PerRunExecutionLock(store.data_root),
    )


def _commit_tool_response(coordinator, session_id, run_id, registry, response):
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        response,
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry.version,
    )


def test_agent_completes_a_text_only_run_and_terminal_runs_are_no_ops(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    registry = _registry()
    factory = _FakeFactory([_response(content="图表整体呈上升趋势。")])
    agent = _agent(store, coordinator, registry, factory)

    completed = agent.execute(session.session_id, run.run_id)
    calls_before = len(factory.client.requests)
    unchanged = agent.execute(session.session_id, run.run_id)

    assert completed.run.status is RunStatus.COMPLETED
    assert completed.run.terminal_code is None
    assert len(completed.provider_attempts) == 1
    assert len(completed.records) == 3
    assert len(factory.client.requests) == calls_before == 1
    assert unchanged == completed
    assert factory.selections == [(ProviderId.QWEN.value, MODEL_IDS[ProviderId.QWEN])]


def test_agent_runs_ordered_tool_round_then_uses_committed_observation(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    handler_calls: list[str] = []
    registry = _registry(handler_calls)
    factory = _FakeFactory(
        [
            _response(
                content="先检查两个值。",
                reason=FinishReason.TOOL_CALLS,
                calls=(
                    ProviderToolCall("call-1", "inspect", '{"value":1}'),
                    ProviderToolCall("call-2", "inspect", '{"value":2}'),
                ),
            ),
            _response(content="两个值分别为 1 和 2。"),
        ]
    )

    state = _agent(store, coordinator, registry, factory).execute(session.session_id, run.run_id)

    assert state.run.status is RunStatus.COMPLETED
    assert handler_calls == ["call-1", "call-2"]
    assert len(factory.client.requests) == 2
    second_request = factory.client.requests[1]
    assert [message.tool_call_id for message in second_request.messages[-2:]] == [
        "call-1",
        "call-2",
    ]
    assert [message.content for message in second_request.messages[-2:]] == [
        '{"outcome":"succeeded","result":{"value":1}}',
        '{"outcome":"succeeded","result":{"value":2}}',
    ]
    assert len(state.provider_attempts) == 2


@pytest.mark.parametrize("complete_tool_batch_before_agent", [False, True])
def test_agent_resumes_after_response_or_completed_tool_batch(
    tmp_path, complete_tool_batch_before_agent: bool
) -> None:
    store, coordinator, session, run = _app(tmp_path)
    handler_calls: list[str] = []
    registry = _registry(handler_calls)
    _commit_tool_response(
        coordinator,
        session.session_id,
        run.run_id,
        registry,
        _response(
            content="先检查数据。",
            reason=FinishReason.TOOL_CALLS,
            calls=(ProviderToolCall("call-resume", "inspect", '{"value":7}'),),
        ),
    )

    reopened_store = FiguraRunStore(store.data_root)
    reopened_factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )
    reopened_coordinator = RunCoordinator(reopened_store, reopened_factory)
    state_after_response = reopened_coordinator.read_run_state(session.session_id, run.run_id)
    assert state_after_response.checkpoint.next_action.action_kind is ActionKind.TOOL_EXECUTION

    if complete_tool_batch_before_agent:
        # Model a separate process finishing the durable tool batch before the Agent
        # owner is restarted at the next MODEL checkpoint.
        tool_state = DurableToolExecutor(reopened_store, registry).execute_pending(
            session.session_id, run.run_id, max_calls=1
        )
        assert tool_state.checkpoint.next_action.action_kind is ActionKind.MODEL
    factory = _FakeFactory([_response(content="数据检查结果为 7。")])

    completed = _agent(
        reopened_store, reopened_coordinator, registry, factory
    ).execute(session.session_id, run.run_id)

    assert completed.run.status is RunStatus.COMPLETED
    assert handler_calls == ["call-resume"]
    assert len(factory.client.requests) == 1
    assert factory.client.requests[0].messages[-1].tool_call_id == "call-resume"


def test_agent_passes_known_tool_failure_as_observation_without_repeating_call(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    handler_calls: list[str] = []
    registry = _registry(handler_calls, fail_values=(1,))
    factory = _FakeFactory(
        [
            _response(
                content="检查该值。",
                reason=FinishReason.TOOL_CALLS,
                calls=(ProviderToolCall("call-failed", "inspect", '{"value":1}'),),
            ),
            _response(content="工具检查失败，无法确认该值。"),
        ]
    )

    state = _agent(store, coordinator, registry, factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.COMPLETED
    assert handler_calls == ["call-failed"]
    observation = factory.client.requests[1].messages[-1]
    assert observation.tool_call_id == "call-failed"
    assert observation.content == (
        '{"error":{"code":"inspection_failed","message":"无法检查该值。",'
        '"retryable":true},"outcome":"failed"}'
    )


def test_unknown_provider_outcome_fails_once_without_fallback_or_resend(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    failure = ProviderCallError(
        ProviderFailure(
            failure_code=ProviderFailureCode.TIMEOUT,
            outcome_known=False,
            transient=True,
            safe_message="请求状态未知。",
        )
    )
    factory = _FakeFactory([failure])

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.PROVIDER_OUTCOME_UNKNOWN.value
    assert state.provider_attempts[0].failure_code == ProviderFailureCode.TIMEOUT.value
    assert len(factory.client.requests) == 1
    assert len(factory.selections) == 1


def test_known_provider_failure_is_persisted_without_provider_fallback(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    failure = ProviderCallError(
        ProviderFailure(
            failure_code=ProviderFailureCode.PROVIDER_REJECTED,
            outcome_known=True,
            transient=False,
            safe_message="服务商拒绝请求。",
        )
    )
    factory = _FakeFactory([failure])

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.EXECUTION_FAILED.value
    assert state.provider_attempts[0].status.value == "known_failure"
    assert state.provider_attempts[0].failure_code == ProviderFailureCode.PROVIDER_REJECTED.value
    assert len(factory.client.requests) == 1
    assert factory.selections == [(ProviderId.QWEN.value, MODEL_IDS[ProviderId.QWEN])]


def test_started_provider_attempt_is_resolved_unknown_without_dispatch(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    coordinator.begin_provider_attempt(session.session_id, run.run_id, 1)

    reopened_store = FiguraRunStore(store.data_root)
    reopened_factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )
    reopened_coordinator = RunCoordinator(reopened_store, reopened_factory)
    factory = _FakeFactory([])

    state = _agent(reopened_store, reopened_coordinator, _registry(), factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.PROVIDER_OUTCOME_UNKNOWN.value
    assert factory.client.requests == []
    assert factory.selections == []


def test_unexpected_provider_exception_after_claim_fails_unknown_without_resend(
    tmp_path,
) -> None:
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([RuntimeError("transport interrupted")])

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.PROVIDER_OUTCOME_UNKNOWN.value
    assert state.provider_attempts[0].status.value == "outcome_unknown"
    assert state.provider_attempts[0].failure_code is None
    assert len(factory.client.requests) == 1
    assert len(factory.selections) == 1


def test_unresolved_tool_attempt_returns_without_tool_recovery_or_provider_call(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    handler_calls: list[str] = []
    registry = _registry(handler_calls)
    state = coordinator.read_run_state(session.session_id, run.run_id)
    provider_attempt = coordinator.begin_provider_attempt(
        session.session_id, run.run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session.session_id, run.run_id)
    coordinator.commit_model_response(
        session.session_id,
        run.run_id,
        claimed.checkpoint.revision,
        _response(
            content="检查该值。",
            reason=FinishReason.TOOL_CALLS,
            calls=(ProviderToolCall("call-pending", "inspect", '{"value":1}'),),
        ),
        provider_attempt_id=provider_attempt.attempt_id,
        registry_version=registry.version,
    )
    pending = coordinator.read_run_state(session.session_id, run.run_id)
    store.begin_tool_attempt(
        session_id=session.session_id,
        run_id=run.run_id,
        expected_revision=pending.checkpoint.revision,
        tool_call_sequence=1,
        registry_version=registry.version,
        replay_effect=ReplayEffect.REPLAY_SAFE,
        attempt_id="attempt-pending",
    )
    unresolved = coordinator.read_run_state(session.session_id, run.run_id)
    factory = _FakeFactory([])

    result = _agent(store, coordinator, registry, factory).execute(
        session.session_id, run.run_id
    )

    assert result == unresolved
    assert result.checkpoint.next_action.action_kind is ActionKind.TOOL_ATTEMPT
    assert handler_calls == []
    assert factory.client.requests == []
    assert factory.selections == []


def test_agent_does_not_dispatch_when_run_lock_is_held(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response()])
    agent = _agent(store, coordinator, _registry(), factory)
    state_before = coordinator.read_run_state(session.session_id, run.run_id)

    with PerRunExecutionLock(store.data_root).acquire(run.run_id):
        state = agent.execute(session.session_id, run.run_id)

    assert state == state_before
    assert factory.client.requests == []


def test_agent_stops_at_tool_budget_without_running_thirty_third_call(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    handler_calls: list[str] = []
    registry = _registry(handler_calls)
    calls = tuple(
        ProviderToolCall(f"call-{index}", "inspect", f'{{"value":{index}}}')
        for index in range(33)
    )
    factory = _FakeFactory(
        [_response(content="批量检查。", reason=FinishReason.TOOL_CALLS, calls=calls)]
    )

    state = _agent(store, coordinator, registry, factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.EXECUTION_FAILED.value
    assert len(handler_calls) == 32
    assert len(factory.client.requests) == 1
    assert state.checkpoint.next_action.action_kind is ActionKind.TOOL_EXECUTION


def test_request_that_cannot_fit_fails_before_client_creation_or_attempt_claim(
    tmp_path, monkeypatch
) -> None:
    import figura.agent.request as request_module

    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response()])
    monkeypatch.setattr(request_module, "MAX_TOTAL_TEXT_BYTES", 1)

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.EXECUTION_FAILED.value
    assert state.provider_attempts == ()
    assert factory.selections == []
    assert factory.client.requests == []


def test_agent_accepts_exactly_eight_provider_attempts_without_sending_ninth(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    registry = _registry()
    responses = [
        _response(
            content=f"调用第 {index} 轮工具。",
            reason=FinishReason.TOOL_CALLS,
            calls=(ProviderToolCall(f"call-{index}", "inspect", f'{{"value":{index}}}'),),
        )
        for index in range(1, 9)
    ]
    factory = _FakeFactory(responses)

    state = _agent(store, coordinator, registry, factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.EXECUTION_FAILED.value
    assert len(state.provider_attempts) == 8
    assert len(factory.client.requests) == 8


def test_empty_stop_response_is_committed_then_fails_as_invalid_response(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response(content="   ")])

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.INVALID_RESPONSE.value
    assert state.provider_attempts[0].status.value == "response_committed"
    assert len(factory.client.requests) == 1


@pytest.mark.parametrize(
    "reason",
    [FinishReason.LENGTH, FinishReason.CONTENT_FILTER, FinishReason.OTHER],
)
def test_unsupported_provider_finish_reason_is_committed_then_fails(
    tmp_path, reason: FinishReason
) -> None:
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response(content="未完成内容", reason=reason)])

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.INVALID_RESPONSE.value
    assert state.provider_attempts[0].status.value == "response_committed"
    assert state.tool_facts == ()
    assert len(factory.client.requests) == 1
