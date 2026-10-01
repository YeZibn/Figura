from __future__ import annotations

from tests.figura_sources_support import make_attachment_service, make_panel_service, make_execution_image_reader

import json
import sqlite3
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

import figura.agent.prompting.observations as observation_module
from figura.agent.request import AgentRequestBuilder
from figura.agent.executor import AgentExecutor
from figura.sources.attachments import FiguraAttachmentService
from figura.sources.chart_renders import FiguraChartRenderService
from figura.agent.execution_state import RunExecutionStateService
from figura.providers import (
    MODEL_IDS,
    FinishReason,
    MessageRole,
    ProviderContinuation,
    ProviderFactory,
    ProviderId,
    ProviderResponse,
    ProviderToolCall,
)
from figura.providers.errors import ProviderCallError, ProviderFailure, ProviderFailureCode
from figura.providers.validation import validate_request
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.models import ActionKind, RunCreateRequest, RunStatus, TerminalCode, ToolFactKind
from figura.runtime.store import FiguraRunStore
from figura.runtime.tool_execution import DurableToolExecutor
from figura.runtime.run_lock import PerRunExecutionLock
from figura.shared.json_schema import canonical_json_dumps
from figura.tools import ReplayEffect, ToolDefinition, ToolFailure, ToolRegistry
from figura.tools.implementations.image import image_tool_definitions


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


def _app_with_image(tmp_path):
    store = FiguraRunStore(tmp_path)
    attachments = make_attachment_service(store)
    factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
        },
        transport_factory=lambda _profile: None,
    )
    coordinator = RunCoordinator(store, factory)
    session = coordinator.create_session()
    content = BytesIO()
    Image.new("RGB", (2, 2), color="purple").save(content, format="PNG")
    image_bytes = content.getvalue()
    metadata = attachments.upload(session.session_id, "chart.png", image_bytes)
    run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="请分析图表。",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="agent-executor-image-test",
            attachment_ids=(metadata.attachment_id,),
        )
    )
    image_path = tmp_path / "attachments" / f"{metadata.attachment_id}.bin"
    return store, coordinator, session, run, attachments, image_bytes, image_path


def _response(
    *,
    content: str = "分析完成",
    calls: tuple[ProviderToolCall, ...] = (),
    reason: FinishReason = FinishReason.STOP,
    continuation: ProviderContinuation | None = None,
    provider_id: ProviderId = ProviderId.QWEN,
) -> ProviderResponse:
    return ProviderResponse(
        provider_id=provider_id,
        model_id=MODEL_IDS[provider_id],
        assistant_content=content,
        tool_calls=calls,
        finish_reason=reason,
        continuation=continuation,
    )


class _PayloadTransport:
    def __init__(self):
        self.calls = []
        self.before_create = None

    def create(self, **payload):
        if self.before_create is not None:
            self.before_create()
        self.calls.append(payload)
        message = SimpleNamespace(
            content="分析完成",
            reasoning_content=None,
            tool_calls=None,
        )
        return SimpleNamespace(
            id="deepseek-response",
            choices=(
                SimpleNamespace(
                    index=0,
                    message=message,
                    finish_reason="stop",
                ),
            ),
            usage=None,
        )


class _FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.provider_id = None
        self.model_id = None
        self.prepared_requests = []
        self.requests = []
        self.after_prepare = None
        self.before_dispatch = None

    def prepare(self, request):
        self.prepared_requests.append(request)
        validate_request(request, self.provider_id)
        if request.model_id != self.model_id:
            raise ValueError("model mismatch")
        if self.after_prepare is not None:
            self.after_prepare()
        return request

    def dispatch(self, request):
        self.requests.append(request)
        if self.before_dispatch is not None:
            self.before_dispatch()
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
        self.client.provider_id = ProviderId(provider_id)
        self.client.model_id = model_id
        return self.client


def _agent(store, coordinator, registry, provider_factory, request_builder=None):
    if request_builder is None:
        attachments = make_attachment_service(store)
        panels = make_panel_service(store, attachments)
        execution_state = RunExecutionStateService(coordinator, panels)
        image_reader = make_execution_image_reader(
            attachments,
            panels,
            FiguraChartRenderService(store.data_root),
        )
        request_builder = AgentRequestBuilder(
            execution_state, image_reader
        )
    tool_executor = DurableToolExecutor(store, registry)
    return AgentExecutor(
        coordinator,
        provider_factory,
        tool_executor,
        PerRunExecutionLock(store.data_root),
        request_builder=request_builder,
    )


def _execution_inventory(request) -> dict[str, object]:
    return json.loads(request.instructions[2].content.split("\n", 1)[1])


def _image_runtime(store, coordinator, attachments):
    panels = make_panel_service(store, attachments)
    execution_state = RunExecutionStateService(coordinator, panels)
    image_reader = make_execution_image_reader(
        attachments,
        panels,
        FiguraChartRenderService(store.data_root),
    )
    registry = ToolRegistry(
        "registry-v1",
        (*image_tool_definitions(execution_state.for_run, image_reader, panels), *_registry().definitions),
    )
    return registry, AgentRequestBuilder(execution_state, image_reader)


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


def _create_followup_run(coordinator, session_id, *, key="agent-followup", text="继续分析"):
    return coordinator.create_run(
        RunCreateRequest(
            session_id=session_id,
            text=text,
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key=key,
        )
    )


def _complete_text_run(coordinator, session_id, run_id, *, registry=None):
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        _response(),
        provider_attempt_id=attempt.attempt_id,
        registry_version=registry.version if registry is not None else None,
    )
    committed = coordinator.read_run_state(session_id, run_id)
    coordinator.complete_run(session_id, run_id, committed.checkpoint.revision)


def _complete_provider_text_run(
    coordinator,
    session_id: str,
    run_id: str,
    provider_id: ProviderId,
    continuation: ProviderContinuation | None = None,
) -> None:
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(
        session_id, run_id, state.checkpoint.revision
    )
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id,
        run_id,
        claimed.checkpoint.revision,
        _response(
            content="上一轮的完整回答。",
            continuation=continuation,
            provider_id=provider_id,
        ),
        provider_attempt_id=attempt.attempt_id,
    )
    completed = coordinator.read_run_state(session_id, run_id)
    coordinator.complete_run(session_id, run_id, completed.checkpoint.revision)


def _multi_provider_runtime(tmp_path, transport):
    store = FiguraRunStore(tmp_path)
    factory = ProviderFactory.from_env(
        {
            "FIGURA_QWEN_API_KEY": "qwen-secret",
            "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/v1",
            "FIGURA_DEEPSEEK_API_KEY": "deepseek-secret",
            "FIGURA_DEEPSEEK_BASE_URL": "https://deepseek.example.test/v1",
            "FIGURA_DEEPSEEK_THINKING_MODE": "true",
            "FIGURA_DEEPSEEK_REASONING_EFFORT": "high",
        },
        transport_factory=lambda _profile: transport,
    )
    coordinator = RunCoordinator(store, factory)
    session = coordinator.create_session()
    return store, coordinator, session, factory


def _assert_request_rejected_before_claim(state, factory):
    assert state.run.status is RunStatus.FAILED
    assert state.provider_attempts == ()
    assert factory.client.requests == []


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


def test_provider_attempt_is_committed_before_dispatch(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response()])
    dispatched_states = []
    factory.client.before_dispatch = lambda: dispatched_states.append(
        coordinator.read_run_state(session.session_id, run.run_id)
    )

    completed = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, run.run_id
    )

    assert completed.run.status is RunStatus.COMPLETED
    assert len(dispatched_states) == 1
    dispatch_state = dispatched_states[0]
    assert dispatch_state.checkpoint.next_action.action_kind is ActionKind.PROVIDER_ATTEMPT
    assert dispatch_state.provider_attempts[0].status.value == "started"


def test_prepared_call_is_discarded_when_run_changes_before_claim(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response()])
    factory.client.after_prepare = lambda: coordinator.fail_run(
        session.session_id,
        run.run_id,
        1,
        TerminalCode.EXECUTION_FAILED,
    )

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.provider_attempts == ()
    assert factory.client.requests == []


def test_agent_does_not_send_attachment_bytes_without_an_explicit_load(tmp_path) -> None:
    store, coordinator, session, run, attachments, image_bytes, _image_path = _app_with_image(
        tmp_path
    )
    factory = _FakeFactory([_response(content="图表有两个明显峰值。")])
    registry, builder = _image_runtime(store, coordinator, attachments)
    agent = _agent(store, coordinator, registry, factory, builder)

    state = agent.execute(session.session_id, run.run_id)
    request = factory.client.requests[0]

    assert state.run.status is RunStatus.COMPLETED
    assert request.messages[0].content.endswith(attachments.list(session.session_id)[0].attachment_id)
    assert any(
        resource.get("filename") == "chart.png"
        for resource in _execution_inventory(request)["resources"]
    )
    assert all(not isinstance(message.content, tuple) for message in request.messages)
    assert len(state.provider_attempts) == 1
    with sqlite3.connect(store.database_path) as connection:
        payloads = connection.execute(
            "SELECT payload_json FROM run_execution_records"
        ).fetchall()
    assert all(image_bytes not in payload.encode("utf-8") for (payload,) in payloads)


@pytest.mark.parametrize("failure", ["missing", "unreadable", "malformed", "over-limit"])
def test_loaded_image_failure_stops_before_following_provider_attempt(
    tmp_path, monkeypatch, failure: str
) -> None:
    store, coordinator, session, run, attachments, image_bytes, image_path = _app_with_image(
        tmp_path
    )
    registry, builder = _image_runtime(store, coordinator, attachments)
    attachment_id = attachments.list(session.session_id)[0].attachment_id
    factory = _FakeFactory([
        _response(
            content="读取原图。",
            reason=FinishReason.TOOL_CALLS,
            calls=(ProviderToolCall(
                "load-image",
                "load_image",
                f'{{"source_kind":"attachment","source_id":"{attachment_id}"}}',
            ),),
        ),
        _response(content="完成。"),
    ])
    if failure == "over-limit":
        monkeypatch.setattr(observation_module, "MAX_IMAGE_BYTES", 1)
    else:
        original_resolve = FiguraAttachmentService.resolve

        def resolve_then_damage(service, session_id, source_id):
            image = original_resolve(service, session_id, source_id)
            if failure == "missing":
                image_path.unlink()
            elif failure == "unreadable":
                image_path.unlink()
                image_path.symlink_to(tmp_path / "outside.bin")
            else:
                image_path.write_bytes(b"x" * len(image_bytes))
            return image

        monkeypatch.setattr(FiguraAttachmentService, "resolve", resolve_then_damage)
    agent = _agent(store, coordinator, registry, factory, builder)

    state = agent.execute(session.session_id, run.run_id)

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.EXECUTION_FAILED.value
    assert len(state.provider_attempts) == 1
    assert len(factory.selections) == 1
    assert len(factory.client.requests) == 1


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
    tool_messages = [
        message for message in second_request.messages if message.role is MessageRole.TOOL
    ]
    assert [message.tool_call_id for message in tool_messages] == [
        "call-1",
        "call-2",
    ]
    assert [message.content for message in tool_messages] == [
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
    tool_messages = [
        message
        for message in factory.client.requests[0].messages
        if message.role is MessageRole.TOOL
    ]
    assert [message.tool_call_id for message in tool_messages] == ["call-resume"]


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
    observation = next(
        message
        for message in factory.client.requests[1].messages
        if message.role is MessageRole.TOOL
    )
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
    assert len(factory.client.prepared_requests) == 1
    assert factory.client.requests == []
    assert len(factory.selections) == 1


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


def test_request_that_cannot_fit_fails_during_preparation_before_attempt_claim(
    tmp_path, monkeypatch
) -> None:
    import figura.providers.validation as provider_validation

    store, coordinator, session, run = _app(tmp_path)
    factory = _FakeFactory([_response()])
    monkeypatch.setattr(provider_validation, "MAX_TOTAL_TEXT_BYTES", 1)

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.EXECUTION_FAILED.value
    assert state.provider_attempts == ()
    assert len(factory.selections) == 1
    assert len(factory.client.prepared_requests) == 1
    assert factory.client.requests == []


def test_complete_session_history_message_limit_fails_before_claim(tmp_path, monkeypatch) -> None:
    import figura.providers.validation as provider_validation

    _store, coordinator, session, prior = _app(tmp_path)
    _complete_text_run(coordinator, session.session_id, prior.run_id)
    current = _create_followup_run(coordinator, session.session_id)
    factory = _FakeFactory([_response()])
    monkeypatch.setattr(provider_validation, "MAX_MESSAGE_COUNT", 2)

    state = _agent(_store, coordinator, _registry(), factory).execute(
        session.session_id, current.run_id
    )

    _assert_request_rejected_before_claim(state, factory)


def test_deepseek_replays_prior_run_continuation_before_dispatch(tmp_path) -> None:
    transport = _PayloadTransport()
    store, coordinator, session, factory = _multi_provider_runtime(tmp_path, transport)
    prior_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="第一轮请求。",
            provider_id=ProviderId.DEEPSEEK.value,
            model_id=MODEL_IDS[ProviderId.DEEPSEEK],
            idempotency_key="deepseek-prior-run",
        )
    )
    continuation = ProviderContinuation(
        ProviderId.DEEPSEEK, 1, "private DeepSeek continuation"
    )
    _complete_provider_text_run(
        coordinator,
        session.session_id,
        prior_run.run_id,
        ProviderId.DEEPSEEK,
        continuation,
    )
    target_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="第二轮请求。",
            provider_id=ProviderId.DEEPSEEK.value,
            model_id=MODEL_IDS[ProviderId.DEEPSEEK],
            idempotency_key="deepseek-target-run",
        )
    )
    dispatch_states = []
    transport.before_create = lambda: dispatch_states.append(
        coordinator.read_run_state(session.session_id, target_run.run_id)
    )

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, target_run.run_id
    )

    assert state.run.status is RunStatus.COMPLETED
    assistant_messages = [
        message for message in transport.calls[0]["messages"]
        if message["role"] == "assistant"
    ]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["reasoning_content"] == continuation.reasoning_content
    assert len(dispatch_states) == 1
    assert dispatch_states[0].provider_attempts[0].status.value == "started"
    assert state.provider_attempts[0].status.value == "response_committed"


def test_cross_provider_history_fails_preparation_without_claim_or_dispatch(tmp_path) -> None:
    transport = _PayloadTransport()
    store, coordinator, session, factory = _multi_provider_runtime(tmp_path, transport)
    prior_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="Qwen 第一轮请求。",
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            idempotency_key="qwen-prior-run",
        )
    )
    _complete_provider_text_run(
        coordinator,
        session.session_id,
        prior_run.run_id,
        ProviderId.QWEN,
        ProviderContinuation(ProviderId.QWEN, 1, "private Qwen continuation"),
    )
    target_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="改用 DeepSeek 继续。",
            provider_id=ProviderId.DEEPSEEK.value,
            model_id=MODEL_IDS[ProviderId.DEEPSEEK],
            idempotency_key="deepseek-cross-provider-run",
        )
    )

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, target_run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.run.terminal_code == TerminalCode.EXECUTION_FAILED.value
    assert state.provider_attempts == ()
    assert transport.calls == []


def test_missing_deepseek_history_continuation_fails_before_claim(tmp_path) -> None:
    transport = _PayloadTransport()
    store, coordinator, session, factory = _multi_provider_runtime(tmp_path, transport)
    prior_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="DeepSeek 第一轮请求。",
            provider_id=ProviderId.DEEPSEEK.value,
            model_id=MODEL_IDS[ProviderId.DEEPSEEK],
            idempotency_key="deepseek-prior-without-continuation",
        )
    )
    _complete_provider_text_run(
        coordinator,
        session.session_id,
        prior_run.run_id,
        ProviderId.DEEPSEEK,
    )
    target_run = coordinator.create_run(
        RunCreateRequest(
            session_id=session.session_id,
            text="继续分析。",
            provider_id=ProviderId.DEEPSEEK.value,
            model_id=MODEL_IDS[ProviderId.DEEPSEEK],
            idempotency_key="deepseek-target-without-continuation",
        )
    )

    state = _agent(store, coordinator, _registry(), factory).execute(
        session.session_id, target_run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert state.provider_attempts == ()
    assert transport.calls == []


def test_complete_session_history_does_not_attach_unloaded_images(tmp_path, monkeypatch) -> None:
    import figura.providers.validation as provider_validation

    store, coordinator, session, prior, attachments, _image_bytes, _image_path = _app_with_image(
        tmp_path
    )
    _complete_text_run(coordinator, session.session_id, prior.run_id)
    current = _create_followup_run(coordinator, session.session_id)
    factory = _FakeFactory([_response()])
    monkeypatch.setattr(provider_validation, "MAX_IMAGE_COUNT", 0)

    registry, builder = _image_runtime(store, coordinator, attachments)
    state = _agent(
        store,
        coordinator,
        registry,
        factory,
        builder,
    ).execute(session.session_id, current.run_id)

    assert state.run.status is RunStatus.COMPLETED
    assert len(factory.client.requests) == 1
    assert all(not isinstance(message.content, tuple) for message in factory.client.requests[0].messages)


def test_tool_schema_limit_fails_before_claim(tmp_path, monkeypatch) -> None:
    import figura.providers.validation as provider_validation

    store, coordinator, session, current = _app(tmp_path)
    registry = _registry()
    attachments = make_attachment_service(store)
    panels = make_panel_service(store, attachments)
    execution_state = RunExecutionStateService(coordinator, panels)
    image_reader = make_execution_image_reader(
        attachments,
        panels,
        FiguraChartRenderService(store.data_root),
    )
    builder = AgentRequestBuilder(execution_state, image_reader)
    request = builder.build(
        coordinator.read_run_state(session.session_id, current.run_id), registry
    )
    request_without_schemas = (
        sum(len(instruction.content.encode("utf-8")) for instruction in request.instructions)
        + sum(
            len(message.content.encode("utf-8"))
            for message in request.messages
            if isinstance(message.content, str)
        )
        + sum(len(tool.description.encode("utf-8")) for tool in request.tools)
    )
    schema_bytes = sum(
        len(canonical_json_dumps(tool.parameters).encode("utf-8"))
        for tool in request.tools
    )
    factory = _FakeFactory([_response()])
    monkeypatch.setattr(
        provider_validation,
        "MAX_TOTAL_TEXT_BYTES",
        request_without_schemas + schema_bytes - 1,
    )

    state = _agent(store, coordinator, registry, factory, builder).execute(
        session.session_id, current.run_id
    )

    _assert_request_rejected_before_claim(state, factory)


def test_missing_historical_attachment_is_not_read_without_explicit_load(tmp_path) -> None:
    store, coordinator, session, prior, attachments, _image_bytes, image_path = _app_with_image(
        tmp_path
    )
    _complete_text_run(coordinator, session.session_id, prior.run_id)
    image_path.unlink()
    current = _create_followup_run(coordinator, session.session_id)
    factory = _FakeFactory([_response()])

    registry, builder = _image_runtime(store, coordinator, attachments)
    state = _agent(
        store,
        coordinator,
        registry,
        factory,
        builder,
    ).execute(session.session_id, current.run_id)

    assert state.run.status is RunStatus.COMPLETED
    assert len(factory.client.requests) == 1
    assert any(
        resource.get("filename") == "chart.png"
        for resource in _execution_inventory(factory.client.requests[0])["resources"]
    )


def test_historical_resolved_tool_registry_mismatch_is_kept_as_inert_history(tmp_path) -> None:
    store, coordinator, session, prior = _app(tmp_path)
    historical_registry = _registry()
    call_response = _response(
        content="执行历史检查。",
        reason=FinishReason.TOOL_CALLS,
        calls=(ProviderToolCall("prior-call", "inspect", '{"value":1}'),),
    )
    _commit_tool_response(
        coordinator, session.session_id, prior.run_id, historical_registry, call_response
    )
    DurableToolExecutor(store, historical_registry).execute_pending(
        session.session_id, prior.run_id
    )
    _commit_tool_response(
        coordinator,
        session.session_id,
        prior.run_id,
        historical_registry,
        _response(content="历史检查已完成。"),
    )
    completed_prior = coordinator.read_run_state(session.session_id, prior.run_id)
    coordinator.complete_run(
        session.session_id, prior.run_id, completed_prior.checkpoint.revision
    )
    current = _create_followup_run(coordinator, session.session_id)
    current_registry = ToolRegistry("registry-v2", historical_registry.definitions)
    factory = _FakeFactory([_response()])

    state = _agent(store, coordinator, current_registry, factory).execute(
        session.session_id, current.run_id
    )

    assert state.run.status is RunStatus.COMPLETED
    assert len(factory.client.requests) == 1
    request_messages = factory.client.requests[0].messages
    assert any(
        message.role is MessageRole.ASSISTANT
        and any(call.call_id == "prior-call" for call in message.tool_calls)
        for message in request_messages
    )
    assert any(
        message.role is MessageRole.TOOL and message.tool_call_id == "prior-call"
        for message in request_messages
    )


def test_unresolved_old_registry_call_is_not_executed_under_the_new_registry(tmp_path) -> None:
    store, coordinator, session, run = _app(tmp_path)
    old_registry = _registry()
    _commit_tool_response(
        coordinator,
        session.session_id,
        run.run_id,
        old_registry,
        _response(
            content="尚未解析的历史工具调用。",
            reason=FinishReason.TOOL_CALLS,
            calls=(ProviderToolCall("old-pending", "inspect", '{"value":1}'),),
        ),
    )
    active_registry = ToolRegistry("registry-v2", old_registry.definitions)
    factory = _FakeFactory([_response()])

    state = _agent(store, coordinator, active_registry, factory).execute(
        session.session_id, run.run_id
    )

    assert state.run.status is RunStatus.FAILED
    assert len(state.provider_attempts) == 1
    assert factory.selections == []
    assert factory.client.requests == []
    assert not any(
        fact.fact_kind is ToolFactKind.TOOL_RESULT
        and getattr(fact.payload, "call_id", None) == "old-pending"
        for fact in state.tool_facts
    )


def test_incomplete_prior_tool_work_fails_before_claim(tmp_path) -> None:
    _store, coordinator, session, prior = _app(tmp_path)
    registry = _registry()
    _commit_tool_response(
        coordinator,
        session.session_id,
        prior.run_id,
        registry,
        _response(
            content="待执行工具。",
            reason=FinishReason.TOOL_CALLS,
            calls=(ProviderToolCall("pending-call", "inspect", '{"value":1}'),),
        ),
    )
    pending = coordinator.read_run_state(session.session_id, prior.run_id)
    coordinator.fail_run(
        session.session_id,
        prior.run_id,
        pending.checkpoint.revision,
        TerminalCode.EXECUTION_FAILED,
    )
    current = _create_followup_run(coordinator, session.session_id)
    factory = _FakeFactory([_response()])

    state = _agent(_store, coordinator, registry, factory).execute(
        session.session_id, current.run_id
    )

    _assert_request_rejected_before_claim(state, factory)


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
