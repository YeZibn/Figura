from __future__ import annotations
from tests.figura_sources_support import make_durable_tool_executor

from dataclasses import replace
import json

import pytest

from figura.providers import (
    FinishReason,
    MODEL_IDS,
    ProviderContinuation,
    ProviderId,
    ProviderToolCall,
)
from figura.shared.payloads import encode_json
from figura.providers.errors import ProviderCallError, ProviderFailure, ProviderFailureCode
from figura.providers.token_estimation import ContextEstimate
from figura.agent.context_accounting import RequestContextAccounting
from figura.agent.context_compaction import (
    calculate_context_history_budgets,
    eligible_compaction_runs,
    select_compaction_coverage,
    selection_for_coverage,
)
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import ActionKind, RunStatus
from figura.runtime.records import SessionContextCheckpoint
from figura.runtime.store import FiguraRunStore
from figura.shared.source_refs import MessageSourceRef, ToolResultSourceRef
from tests.test_figura_agent_executor import (
    _FakeFactory,
    _agent,
    _app,
    _app_with_image,
    _complete_text_run,
    _complete_provider_text_run,
    _commit_tool_response,
    _create_followup_run,
    _image_runtime,
    _registry,
    _response,
)


def _history_with_target(coordinator, *, target_provider=ProviderId.QWEN):
    session = coordinator.create_session()
    first = _create_followup_run(
        coordinator,
        session.session_id,
        key="history-first",
        text="第一轮：分析销售趋势",
        provider_id=target_provider,
    )
    if target_provider is ProviderId.DEEPSEEK:
        continuation = ProviderContinuation(ProviderId.DEEPSEEK, 1, "历史思考续文")
        _complete_provider_text_run(
            coordinator, session.session_id, first.run_id, ProviderId.DEEPSEEK,
            continuation,
        )
    else:
        _complete_text_run(coordinator, session.session_id, first.run_id)
    second = _create_followup_run(
        coordinator,
        session.session_id,
        key="history-second",
        text="第二轮：补充地区对比",
        provider_id=target_provider,
    )
    if target_provider is ProviderId.DEEPSEEK:
        continuation = ProviderContinuation(ProviderId.DEEPSEEK, 1, "历史思考续文")
        _complete_provider_text_run(
            coordinator, session.session_id, second.run_id, ProviderId.DEEPSEEK,
            continuation,
        )
    else:
        _complete_text_run(coordinator, session.session_id, second.run_id)
    target = _create_followup_run(
        coordinator,
        session.session_id,
        key="history-target",
        text="继续完成结论",
        provider_id=target_provider,
    )
    return session, first, second, target


def _set_capacity_and_estimates(monkeypatch, values, *, capacity=100):
    import figura.providers.config as config
    import figura.providers.client as provider_client
    import figura.agent.executor as agent_executor

    original_profile = config._profile_from_env
    monkeypatch.setattr(
        config,
        "_profile_from_env",
        lambda provider, environ: replace(
            original_profile(provider, environ), context_window_tokens=capacity
        ),
    )
    remaining = list(values)

    def estimate(_payload, selected_capacity, _encoding):
        count = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if count is None:
            return None
        return ContextEstimate(count, selected_capacity)

    monkeypatch.setattr(provider_client, "estimate_input", estimate)

    def accounting(_request, _projection, prepared_estimate):
        if prepared_estimate is None:
            return RequestContextAccounting(
                None, None, None, None, None, None, None, 0, 0,
                None, None, "estimate_unavailable",
            )
        return RequestContextAccounting(
            prepared_estimate.input_tokens,
            30,
            10,
            5,
            25,
            5,
            10,
            0,
            0,
            prepared_estimate.context_window_tokens,
            "test-estimator-v1",
            "history_reducible",
        )

    monkeypatch.setattr(agent_executor, "account_request_context", accounting)


def _summary_response(
    state,
    summary="已确认需要对比销售趋势和地区差异",
    *,
    provider_id=ProviderId.QWEN,
    continuation=None,
):
    ref = MessageSourceRef(state.run.run_id, state.run.input_record_id)
    return _response(content=json.dumps(_summary_v2({
        "text": summary,
        "source_refs": [ref.to_dict()],
    }), ensure_ascii=False), provider_id=provider_id, continuation=continuation)


def _summary_v2(fact=None):
    value = {
        "current_goal": [],
        "constraints": [],
        "decisions": [],
        "facts": [],
        "progress": {
            "completed": [],
            "in_progress": [],
            "pending": [],
            "blocked": [],
        },
        "open_questions": [],
        "resources": [],
        "proposals": [],
    }
    if fact is not None:
        value["facts"].append(fact)
    return value


def _agent_requests(state):
    return tuple(item for item in state.provider_requests if item.purpose == "agent_turn")


def _agent_request(state):
    requests = _agent_requests(state)
    assert requests
    return requests[0]


def _operation_attempt_count(coordinator, operation):
    if operation.provider_request_id is None:
        return 0
    state = coordinator.read_run_state(operation.session_id, operation.target_run_id)
    return sum(
        attempt.request_id == operation.provider_request_id
        for attempt in state.provider_attempts
    )


@pytest.mark.parametrize(
    "capacity,estimates,post_estimate",
    [(100, [81, 82, 75, 45], 45), (200, [161, 162, 150, 90], 90)],
)
def test_threshold_compacts_oldest_closed_run_and_reestimates_request(
    tmp_path, monkeypatch, capacity, estimates, post_estimate
):
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, second, target = _history_with_target(coordinator)
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    _set_capacity_and_estimates(monkeypatch, estimates, capacity=capacity)
    factory = _FakeFactory([
        _summary_response(first_state),
        _response(content="综合结论"),
    ])

    state = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )

    operation = coordinator.read_context_compaction_operation(
        _agent_request(state).context_checkpoint_operation_id
    )
    checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    summary_request, ordinary_request = factory.client.requests
    assert len(factory.client.requests) == 2
    assert summary_request.tools == ()
    assert len(summary_request.messages) == 1
    assert operation.status == "completed" and _operation_attempt_count(coordinator, operation) == 1
    assert checkpoint is not None and checkpoint.covered_run_id == first.run_id
    assert checkpoint.summary_contract_version == 3
    assert checkpoint.summary["facts"][0]["text"] == "已确认需要对比销售趋势和地区差异"
    assert operation.selection_plan["selection_plan_version"] == 2
    assert operation.selection_plan["context_capacity_tokens"] == capacity
    assert operation.selection_plan["summary_budget_tokens"] <= capacity // 10
    assert operation.selection_plan["coverage_version"] == 2
    assert operation.selection_plan["input_projection_version"] == 2
    assert operation.selection_plan["directory_projection_version"] == 2
    assert _agent_request(state).context_projection == "checkpoint"
    assert _agent_request(state).context_checkpoint_revision == checkpoint.revision
    assert _agent_request(state).context_estimate == ContextEstimate(
        post_estimate, capacity
    )
    assert any("自动摘要" in instruction.content for instruction in ordinary_request.instructions)
    historical_inputs = json.loads(ordinary_request.messages[0].content)
    assert [entry["text"] for entry in historical_inputs["entries"]] == [
        "第二轮：补充地区对比",
    ]
    raw_process_text = json.dumps(
        [message.content for message in ordinary_request.messages[1:]], ensure_ascii=False
    )
    assert "第一轮：分析销售趋势" not in raw_process_text
    assert "第二轮：补充地区对比" not in raw_process_text
    assert state.run.status is RunStatus.RUNNING


def test_valid_summary_longer_than_soft_summary_budget_is_preserved(tmp_path, monkeypatch):
    store, coordinator, _unused_session, _run = _app(tmp_path)
    session, first, _second, target = _history_with_target(coordinator)
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    long_summary = "来源支持的关键背景仍需保留。 " * 40
    _set_capacity_and_estimates(monkeypatch, [90, 80, 45], capacity=100)
    factory = _FakeFactory([
        _summary_response(first_state, long_summary),
        _response(content="继续完成分析"),
    ])

    result = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )

    checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    operation = coordinator.read_context_compaction_operation(
        _agent_request(result).context_checkpoint_operation_id
    )
    assert checkpoint is not None
    assert checkpoint.summary["facts"][0]["text"] == long_summary.strip()
    assert operation.status == "completed"
    assert operation.selection_plan["summary_budget_tokens"] == 10


def test_abnormal_run_blocks_compaction_frontier_instead_of_splitting_its_tail(tmp_path):
    _store, coordinator, session, abnormal = _app(tmp_path)
    initial = coordinator.read_run_state(session.session_id, abnormal.run_id)
    coordinator.fail_run(session.session_id, abnormal.run_id, initial.checkpoint.revision)
    complete = _create_followup_run(
        coordinator, session.session_id, key="after-abnormal", text="继续后续交互"
    )
    _complete_text_run(coordinator, session.session_id, complete.run_id)
    target = _create_followup_run(
        coordinator, session.session_id, key="after-complete", text="当前请求"
    )

    prior = coordinator.read_prior_run_states(session.session_id, target.run_id)

    assert eligible_compaction_runs(prior, 0) == ()


@pytest.mark.parametrize(
    "capacity,expected",
    [(200_000, 20_000), (1_000_000, 100_000), (9, 0)],
)
def test_context_history_budgets_follow_selected_capacity(capacity, expected):
    budget = calculate_context_history_budgets(capacity)
    assert budget is not None
    assert budget.raw_history_tokens == expected
    assert budget.summary_tokens == expected
    assert budget.context_capacity_tokens == capacity


def test_accounting_aware_budget_reserves_protected_raw_and_mandatory_directory_once():
    accounting = RequestContextAccounting(
        full_input_tokens=800,
        history_input_tokens=300,
        current_input_tokens=100,
        summary_tokens=40,
        raw_history_tokens=120,
        resource_directory_tokens=180,
        policy_tools_state_tokens=200,
        selected_image_count=1,
        image_tokens=1024,
        context_capacity_tokens=1000,
        estimator_version="test-v1",
        pressure_reason="history_reducible",
    )

    budgets = calculate_context_history_budgets(
        1000,
        accounting=accounting,
        mandatory_directory_tokens=50,
        protected_raw_tokens=30,
    )

    # P=800; B+M consumes 200 policy + 100 current + 30 protected + 50
    # mandatory = 380, leaving A=420. U=70, S=100, optional directory=250.
    assert budgets == type(budgets)(
        context_capacity_tokens=1000,
        raw_history_tokens=100,
        summary_tokens=100,
        protected_raw_tokens=30,
        mandatory_directory_tokens=50,
        directory_tokens=300,
        accounting_version=2,
    )


@pytest.mark.parametrize("capacity", [None, 0, -1, True, 1.5, "200000"])
def test_context_history_budgets_reject_missing_or_invalid_capacity(capacity):
    assert calculate_context_history_budgets(capacity) is None


def test_frozen_selection_plan_v1_remains_exact_while_v2_requires_all_new_fields():
    from figura.agent.executor import _validated_compaction_plan

    legacy = {
        "context_capacity_tokens": 200_000,
        "raw_history_budget_tokens": 20_000,
        "summary_budget_tokens": 20_000,
        "coverage_version": 1,
    }
    assert _validated_compaction_plan(legacy) == {
        **legacy,
        "summary_contract_version": 2,
        "reconciliation": False,
    }
    assert _validated_compaction_plan({**legacy, "raw_history_budget_tokens": 1}) is None

    current = {
        "selection_plan_version": 2,
        "context_capacity_tokens": 200_000,
        "raw_history_budget_tokens": 25_000,
        "summary_budget_tokens": 20_000,
        "protected_raw_tokens": 5_000,
        "mandatory_directory_tokens": 700,
        "directory_budget_tokens": 12_000,
        "accounting_basis": {
            "policy_tools_state_tokens": 20_000,
            "current_input_tokens": 5_000,
        },
        "coverage_version": 2,
        "input_projection_version": 2,
        "directory_projection_version": 2,
        "accounting_version": 1,
        "summary_contract_version": 3,
        "reconciliation": True,
    }
    assert _validated_compaction_plan(current) == current
    assert _validated_compaction_plan({**current, "future_field": 1}) is None


def _complete_two_interaction_run(coordinator, store, session_id, *, key="two-interactions"):
    from figura.runtime.tool_execution import DurableToolExecutor

    registry = _registry()
    run = _create_followup_run(
        coordinator, session_id, key=key, text="先执行早期交互，再完成最终结论。"
    )
    _commit_tool_response(
        coordinator,
        session_id,
        run.run_id,
        registry,
        _response(
            content="较早交互：读取候选数值。",
            calls=(ProviderToolCall("early-call", "inspect", '{"value":7}'),),
            reason=FinishReason.TOOL_CALLS,
        ),
    )
    make_durable_tool_executor(store, registry).execute_pending(session_id, run.run_id)
    _complete_text_run(coordinator, session_id, run.run_id, registry=registry)
    return run


def _active_two_interaction_run(
    coordinator, store, session_id, *, key="active-two-interactions", run=None
):
    from figura.runtime.tool_execution import DurableToolExecutor

    registry = _registry()
    if run is None:
        run = _create_followup_run(
            coordinator, session_id, key=key, text="当前任务：完成两次有依据的观察。"
        )
    executor = make_durable_tool_executor(store, registry)
    for call_id, observation in (
        ("active-early-call", "活动 Run 较早交互：识别第一组数据。"),
        ("active-recent-call", "活动 Run 近期交互：核对第二组数据。"),
    ):
        _commit_tool_response(
            coordinator,
            session_id,
            run.run_id,
            registry,
            _response(
                content=observation,
                calls=(ProviderToolCall(call_id, "inspect", '{"value":7}'),),
                reason=FinishReason.TOOL_CALLS,
            ),
        )
        executor.execute_pending(session_id, run.run_id)
    return run


def test_selector_can_split_one_run_only_between_complete_interactions(tmp_path):
    store, coordinator, _unused_session, _run = _app(tmp_path)
    session = coordinator.create_session()
    run = _complete_two_interaction_run(coordinator, store, session.session_id)
    state = coordinator.read_run_state(session.session_id, run.run_id)
    estimates = []

    def estimate(text):
        estimates.append(text)
        return 7 if "较早交互" in text else 5

    selected = select_compaction_coverage((state,), None, 5, estimate_tokens=estimate)

    assert selected is not None
    assert selected.selected_run_states == (state,)
    assert selected.covered_run_id == run.run_id
    assert selected.covered_record_sequence < state.checkpoint.last_committed_record_sequence
    assert selected.covered_tool_sequence > 0
    assert len(estimates) == 5
    assert '"text":"先执行早期交互，再完成最终结论。"' in estimates[1]
    assert all("historical_run_context" in text for text in estimates[2::2])


def test_selector_preserves_single_oversized_newest_interaction_whole(tmp_path):
    store, coordinator, _unused_session, _run = _app(tmp_path)
    session = coordinator.create_session()
    run = _complete_two_interaction_run(coordinator, store, session.session_id)
    state = coordinator.read_run_state(session.session_id, run.run_id)

    selected = select_compaction_coverage(
        (state,), None, 2,
        estimate_tokens=lambda text: 1 if "较早交互" in text else 8,
    )

    assert selected is not None
    assert selected.covered_record_sequence < state.checkpoint.last_committed_record_sequence
    # The newer interaction is retained as a whole, so summary coverage ends at the tool batch.
    assert selected.covered_tool_sequence == state.checkpoint.last_committed_tool_sequence


def test_selector_compacts_only_the_older_complete_active_run_interaction(tmp_path):
    store, coordinator, session, initial = _app(tmp_path)
    run = _active_two_interaction_run(
        coordinator, store, session.session_id, run=initial
    )
    state = coordinator.read_run_state(session.session_id, run.run_id)

    selected = select_compaction_coverage(
        (),
        None,
        5,
        active_run_state=state,
        estimate_tokens=lambda text: 7 if "较早交互" in text else 5,
    )

    assert selected is not None
    assert selected.selected_run_states == (state,)
    assert selected.covered_run_id == run.run_id
    assert selected.covered_record_sequence < state.checkpoint.last_committed_record_sequence
    assert selected.covered_tool_sequence < state.checkpoint.last_committed_tool_sequence


def test_selector_shares_one_raw_tail_across_prior_and_active_run(tmp_path):
    store, coordinator, session, initial = _app(tmp_path)
    prior = _active_two_interaction_run(
        coordinator, store, session.session_id, key="mixed-prior", run=initial
    )
    _complete_text_run(coordinator, session.session_id, prior.run_id, registry=_registry())
    active = _active_two_interaction_run(
        coordinator, store, session.session_id, key="mixed-active"
    )
    prior_state = coordinator.read_run_state(session.session_id, prior.run_id)
    active_state = coordinator.read_run_state(session.session_id, active.run_id)

    selected = select_compaction_coverage(
        (prior_state,),
        None,
        5,
        active_run_state=active_state,
        estimate_tokens=lambda text: (
            0 if "historical_run_context" in text
            else 5 if "活动 Run 近期交互" in text
            else 7
        ),
    )

    assert selected is not None
    assert selected.selected_run_states == (prior_state, active_state)
    assert selected.covered_run_id == active.run_id
    assert selected.covered_record_sequence < active_state.checkpoint.last_committed_record_sequence


def test_selector_does_not_include_active_incomplete_tool_batch(tmp_path):
    store, coordinator, session, run = _app(tmp_path)
    registry = _registry()
    _commit_tool_response(
        coordinator,
        session.session_id,
        run.run_id,
        registry,
        _response(
            content="这个工具批次尚未结束。",
            calls=(ProviderToolCall("unfinished-active", "inspect", '{"value":1}'),),
            reason=FinishReason.TOOL_CALLS,
        ),
    )
    state = coordinator.read_run_state(session.session_id, run.run_id)

    selected = select_compaction_coverage(
        (), None, 0, active_run_state=state, estimate_tokens=lambda _text: 1
    )

    assert state.checkpoint.next_action.action_kind is ActionKind.TOOL_EXECUTION
    assert selected is None


def test_runtime_requires_provider_attempt_for_summary_checkpoint_commit(tmp_path):
    store, coordinator, session, initial = _app(tmp_path)
    run = _active_two_interaction_run(
        coordinator, store, session.session_id, run=initial
    )
    state = coordinator.read_run_state(session.session_id, run.run_id)
    selected = select_compaction_coverage(
        (), None, 5,
        active_run_state=state,
        estimate_tokens=lambda text: 7 if "较早交互" in text else 5,
    )
    assert selected is not None
    operation_args = {
        "session_id": session.session_id,
        "target_run_id": run.run_id,
        "base_record_sequence": state.checkpoint.last_committed_record_sequence,
        "base_tool_sequence": state.checkpoint.last_committed_tool_sequence,
        "input_checkpoint_revision": 0,
        "covered_run_id": run.run_id,
        "covered_run_ordinal": run.ordinal,
        "covered_record_sequence": selected.covered_record_sequence,
        "covered_tool_sequence": selected.covered_tool_sequence,
    }

    with pytest.raises(RunError) as error:
        coordinator.get_or_create_context_compaction_operation(
            **{
                **operation_args,
                "covered_record_sequence": state.checkpoint.last_committed_record_sequence + 1,
            }
        )
    assert error.value.code in {RunErrorCode.STALE_CHECKPOINT, RunErrorCode.UNSUPPORTED_PAYLOAD}

    unbound = SessionContextCheckpoint(
        session_id=session.session_id,
        revision=1,
        covered_run_id=run.run_id,
        covered_run_ordinal=run.ordinal,
        covered_record_sequence=selected.covered_record_sequence,
        covered_tool_sequence=selected.covered_tool_sequence,
        summary_contract_version=2,
        summary=_summary_v2(),
        source_refs=(MessageSourceRef(run.run_id, run.input_record_id),),
    )
    with pytest.raises(RunError) as error:
        coordinator.replace_session_context_checkpoint(unbound, expected_revision=0)
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD

    operation = coordinator.get_or_create_context_compaction_operation(**operation_args)
    checkpoint = replace(unbound, compaction_operation_id=operation.operation_id)
    with pytest.raises(RunError) as error:
        coordinator.replace_session_context_checkpoint(checkpoint, expected_revision=0)
    assert error.value.code is RunErrorCode.INVALID_TRANSITION
    assert coordinator.read_session_context_checkpoint(session.session_id) is None


def test_active_summary_receives_full_input_text_attachment_ids_and_source_ref(tmp_path):
    store, coordinator, session, initial, attachments, image_bytes, _image_path = _app_with_image(
        tmp_path
    )
    run = _active_two_interaction_run(
        coordinator, store, session.session_id, run=initial
    )
    state = coordinator.read_run_state(session.session_id, run.run_id)
    attachment_id = attachments.list(session.session_id)[0].attachment_id
    selection = select_compaction_coverage(
        (), None, 5,
        active_run_state=state,
        estimate_tokens=lambda text: 7 if "较早交互" in text else 5,
    )
    assert selection is not None
    builder = _agent(store, coordinator, _registry(), _FakeFactory([]))._requests

    request, refs = builder.build_summary_request(
        state,
        selection.selected_run_states,
        None,
        coverage=selection,
        context_capacity_tokens=100,
        summary_budget_tokens=10,
    )
    payload = json.loads(request.messages[0].content)
    source_input = payload["source_runs"][0]["input"]

    assert source_input["text"] == "请分析图表。"
    assert source_input["attachment_ids"] == [attachment_id]
    assert source_input["reference"] == MessageSourceRef(
        run.run_id, run.input_record_id
    ).to_dict()
    assert MessageSourceRef(run.run_id, run.input_record_id) in refs
    assert image_bytes.decode("latin1") not in request.messages[0].content


@pytest.mark.parametrize("provider_id", [ProviderId.QWEN, ProviderId.DEEPSEEK])
def test_summary_request_uses_provider_scoped_reasoning_options(tmp_path, provider_id):
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, second, target = _history_with_target(
        coordinator, target_provider=provider_id
    )
    source_state = coordinator.read_run_state(session.session_id, first.run_id)
    second_state = coordinator.read_run_state(session.session_id, second.run_id)
    target_state = coordinator.read_run_state(session.session_id, target.run_id)
    factory = _FakeFactory([])
    builder = _agent(store, coordinator, _registry(), factory)._requests

    summary_request, _refs = builder.build_summary_request(
        target_state,
        (source_state, second_state),
        None,
        context_capacity_tokens=100,
        summary_budget_tokens=10,
    )
    ordinary_request = builder.build(
        target_state,
        _registry(),
        (source_state, second_state),
    )

    if provider_id is ProviderId.DEEPSEEK:
        assert summary_request.options.thinking_mode is True
        assert summary_request.options.reasoning_effort == "medium"
    else:
        assert summary_request.options.thinking_mode is None
        assert summary_request.options.reasoning_effort is None
    assert ordinary_request.options.thinking_mode is None
    assert ordinary_request.options.reasoning_effort is None

    client = factory.create(provider_id, MODEL_IDS[provider_id])
    prepared = client.prepare(summary_request)
    ordinary_prepared = client.prepare(ordinary_request)
    assert prepared.descriptor["options"]["thinking_mode"] is True
    assert prepared.descriptor["options"]["reasoning_effort"] == (
        "medium" if provider_id is ProviderId.DEEPSEEK else None
    )
    if provider_id is ProviderId.DEEPSEEK:
        assert ordinary_prepared.descriptor["options"]["reasoning_effort"] != "medium"


def test_agent_compacts_active_prefix_and_reuses_checkpoint_in_same_run(tmp_path, monkeypatch):
    store, coordinator, session, initial = _app(tmp_path)
    run = _active_two_interaction_run(
        coordinator, store, session.session_id, run=initial
    )
    source_state = coordinator.read_run_state(session.session_id, run.run_id)
    _set_capacity_and_estimates(monkeypatch, [90, 85, 75, 50])
    factory = _FakeFactory([
        _summary_response(source_state, "较早的观察已纳入活动 Run 摘要。"),
        _response(
            content="摘要后继续：请求补测。",
            calls=(ProviderToolCall("post-summary-call", "inspect", '{"value":8}'),),
            reason=FinishReason.TOOL_CALLS,
        ),
        _response(content="结合保留的近期过程完成分析。"),
    ])
    agent = _agent(store, coordinator, _registry(), factory)

    after_summary = agent.execute_slice(session.session_id, run.run_id)
    checkpoint = coordinator.read_session_context_checkpoint(session.session_id)

    assert checkpoint is not None
    assert checkpoint.covered_run_id == run.run_id
    assert checkpoint.covered_record_sequence < source_state.checkpoint.last_committed_record_sequence
    summary_payload = json.loads(factory.client.requests[0].messages[0].content)
    assert summary_payload["source_runs"][0]["status"] == "running"
    assert summary_payload["source_runs"][0]["input"]["text"] == "分析图表数据"
    assert "不得把摘要覆盖边界当作 Run 的结束" in (
        factory.client.requests[0].instructions[0].content
    )
    summary_messages = json.dumps(summary_payload["source_runs"][0]["messages"])
    assert "active-early-call" in summary_messages
    assert "active-recent-call" not in summary_messages

    ordinary_request = factory.client.requests[1]
    ordinary_message_text = json.dumps(
        [message.content for message in ordinary_request.messages], ensure_ascii=False
    )
    assert "分析图表数据" in ordinary_message_text
    assert "活动 Run 较早交互" not in ordinary_message_text
    assert "活动 Run 近期交互" in ordinary_message_text
    assert after_summary.checkpoint.next_action.action_kind is ActionKind.TOOL_EXECUTION

    after_tool = agent.execute_slice(session.session_id, run.run_id)
    assert after_tool.checkpoint.next_action.action_kind is ActionKind.MODEL
    after_continuation = agent.execute_slice(session.session_id, run.run_id)
    continuation_text = json.dumps(
        [message.content for message in factory.client.requests[-1].messages],
        ensure_ascii=False,
    )
    assert "分析图表数据" in continuation_text
    assert "活动 Run 较早交互" not in continuation_text
    assert "活动 Run 近期交互" in continuation_text
    assert "摘要后继续：请求补测。" in continuation_text
    assert after_continuation.checkpoint.next_action.action_kind is ActionKind.FINAL

    completed = agent.execute_slice(session.session_id, run.run_id)
    assert completed.run.status is RunStatus.COMPLETED
    assert coordinator.read_session_context_checkpoint(session.session_id) == checkpoint

    followup = _create_followup_run(
        coordinator,
        session.session_id,
        key="after-active-compaction",
        text="沿用刚才的分析继续回答。",
    )
    followup_state = coordinator.read_run_state(session.session_id, followup.run_id)
    prior_states = coordinator.read_prior_run_states(session.session_id, followup.run_id)
    projected = agent._requests.build(
        followup_state,
        _registry(),
        prior_states,
        context_checkpoint=checkpoint,
    )
    projected_text = json.dumps([message.content for message in projected.messages], ensure_ascii=False)
    summary_instruction = next(
        item.content for item in projected.instructions if "旧历史的自动摘要" in item.content
    )
    assert "分析图表数据" not in projected_text
    assert run.input_record_id in summary_instruction
    assert "活动 Run 较早交互" not in projected_text
    assert "活动 Run 近期交互" in projected_text
    assert '"status":"completed"' in summary_instruction


def test_active_run_incremental_compaction_adds_only_new_process_after_checkpoint(
    tmp_path, monkeypatch
):
    store, coordinator, session, initial = _app(tmp_path)
    run = _active_two_interaction_run(
        coordinator, store, session.session_id, run=initial
    )
    _set_capacity_and_estimates(monkeypatch, [90, 85, 75, 90, 85, 90, 80, 45])
    factory = _FakeFactory([
        _summary_response(
            coordinator.read_run_state(session.session_id, run.run_id),
            "活动 Run 的较早观察已摘要。",
        ),
        _response(
            content="摘要后继续：请求补测。",
            calls=(ProviderToolCall("incremental-active-call", "inspect", '{"value":8}'),),
            reason=FinishReason.TOOL_CALLS,
        ),
        _summary_response(
            coordinator.read_run_state(session.session_id, run.run_id),
            "活动 Run 的近期观察也已摘要。",
        ),
        _response(content="增量压缩后完成分析。"),
    ])
    agent = _agent(store, coordinator, _registry(), factory)

    after_first_model = agent.execute_slice(session.session_id, run.run_id)
    first_checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    assert first_checkpoint is not None and first_checkpoint.revision == 1
    after_tool = agent.execute_slice(session.session_id, run.run_id)
    assert after_tool.checkpoint.next_action.action_kind is ActionKind.MODEL
    after_second_model = agent.execute_slice(session.session_id, run.run_id)

    second_checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    assert second_checkpoint is not None and second_checkpoint.revision == 2
    assert second_checkpoint.covered_run_id == run.run_id
    assert second_checkpoint.covered_record_sequence > first_checkpoint.covered_record_sequence
    assert second_checkpoint.covered_record_sequence < after_tool.checkpoint.last_committed_record_sequence
    second_summary = json.loads(factory.client.requests[2].messages[0].content)
    assert second_summary["previous_summary"] is not None
    assert second_summary["previous_source_refs"] == [
        item.to_dict() for item in first_checkpoint.source_refs
    ]
    incremental_messages = json.dumps(
        second_summary["source_runs"][0]["messages"], ensure_ascii=False
    )
    assert "active-early-call" not in incremental_messages
    assert "active-recent-call" in incremental_messages
    assert "incremental-active-call" not in incremental_messages

    second_ordinary_text = json.dumps(
        [message.content for message in factory.client.requests[3].messages],
        ensure_ascii=False,
    )
    assert "分析图表数据" in second_ordinary_text
    assert "活动 Run 较早交互" not in second_ordinary_text
    assert "活动 Run 近期交互" not in second_ordinary_text
    assert "摘要后继续：请求补测。" in second_ordinary_text
    assert after_second_model.checkpoint.next_action.action_kind is ActionKind.FINAL

    completed = agent.execute_slice(session.session_id, run.run_id)
    assert completed.run.status is RunStatus.COMPLETED


def test_interrupted_active_run_summary_reconstructs_the_frozen_prefix_after_restart(
    tmp_path, monkeypatch
):
    store, coordinator, session, initial = _app(tmp_path)
    run = _active_two_interaction_run(
        coordinator, store, session.session_id, run=initial
    )
    active_state = coordinator.read_run_state(session.session_id, run.run_id)
    _set_capacity_and_estimates(monkeypatch, [90, 80, 90, 45])
    factory = _FakeFactory([
        _summary_response(active_state, "活動 Run 的早期觀察。"),
        _response(content="完成"),
    ])

    def interrupt_before_checkpoint(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        coordinator, "replace_session_context_checkpoint", interrupt_before_checkpoint
    )
    with pytest.raises(KeyboardInterrupt):
        _agent(store, coordinator, _registry(), factory).execute_slice(
            session.session_id, run.run_id
        )

    operation = coordinator.find_context_compaction_operation(
        session.session_id,
        run.run_id,
        active_state.checkpoint.last_committed_record_sequence,
        active_state.checkpoint.last_committed_tool_sequence,
    )
    assert operation is not None and _operation_attempt_count(coordinator, operation) == 1
    orphaned_state = coordinator.read_run_state(session.session_id, run.run_id)
    original_request = next(
        item for item in orphaned_state.provider_requests
        if item.request_id == operation.provider_request_id
    )
    original_summary_request = factory.client.requests[0]

    reopened = FiguraRunStore(tmp_path)
    restarted_coordinator = RunCoordinator(reopened, coordinator._provider_factory)
    restarted_factory = _FakeFactory([
        _summary_response(active_state, "活动 Run 的早期觀察。"),
        _response(content="恢复后继续完成。"),
    ])
    result = _agent(reopened, restarted_coordinator, _registry(), restarted_factory).execute_slice(
        session.session_id, run.run_id
    )
    resumed = restarted_coordinator.read_context_compaction_operation(operation.operation_id)

    assert resumed.status == "completed", resumed.failure_code
    assert _operation_attempt_count(restarted_coordinator, resumed) == 2
    resumed_state = restarted_coordinator.read_run_state(session.session_id, run.run_id)
    assert next(
        item for item in resumed_state.provider_requests
        if item.request_id == resumed.provider_request_id
    ) == original_request
    assert restarted_factory.client.requests[0] == original_summary_request
    assert _agent_requests(result)[-1].context_projection == "checkpoint"
    checkpoint = restarted_coordinator.read_session_context_checkpoint(session.session_id)
    assert checkpoint is not None and checkpoint.covered_run_id == run.run_id


def test_active_run_checkpoint_survives_later_failure_and_refreshes_terminal_projection(
    tmp_path, monkeypatch
):
    store, coordinator, session, initial = _app(tmp_path)
    run = _active_two_interaction_run(
        coordinator, store, session.session_id, run=initial
    )
    active_state = coordinator.read_run_state(session.session_id, run.run_id)
    _set_capacity_and_estimates(monkeypatch, [90, 85, 75])
    factory = _FakeFactory([
        _summary_response(active_state, "早期观察已压缩。"),
        _response(content="Run 尚有后续工作。"),
    ])
    agent = _agent(store, coordinator, _registry(), factory)
    after_compaction = agent.execute_slice(session.session_id, run.run_id)
    checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    assert checkpoint is not None and checkpoint.covered_run_id == run.run_id

    failed = coordinator.fail_run(
        session.session_id,
        run.run_id,
        after_compaction.checkpoint.revision,
    )
    assert failed.status is RunStatus.FAILED
    assert coordinator.read_session_context_checkpoint(session.session_id) == checkpoint

    followup = _create_followup_run(
        coordinator,
        session.session_id,
        key="after-active-failure",
        text="继续处理尚未完成的工作。",
    )
    followup_state = coordinator.read_run_state(session.session_id, followup.run_id)
    prior_states = coordinator.read_prior_run_states(session.session_id, followup.run_id)
    projected = agent._requests.build(
        followup_state,
        _registry(),
        prior_states,
        context_checkpoint=checkpoint,
    )
    projected_text = json.dumps(
        [message.content for message in projected.messages], ensure_ascii=False
    )
    summary_instruction = next(
        item.content for item in projected.instructions if "旧历史的自动摘要" in item.content
    )
    execution_instruction = next(
        item.content for item in projected.instructions if "本次请求的运行资源目录" in item.content
    )

    assert "活动 Run 较早交互" not in projected_text
    assert "活动 Run 近期交互" in projected_text
    assert "Run 尚有后续工作。" in projected_text
    assert '"status":"failed"' in summary_instruction
    assert '"status":"failed"' in execution_instruction


def test_selector_aborts_instead_of_skipping_an_unestimated_history_run(tmp_path):
    _store, coordinator, _unused_session, _run = _app(tmp_path)
    session, first, second, _target = _history_with_target(coordinator)
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    second_state = coordinator.read_run_state(session.session_id, second.run_id)

    selected = select_compaction_coverage(
        (first_state, second_state),
        None,
        0,
        estimate_tokens=lambda text: None if first.run_id in text else 1,
    )

    assert selected is None


def test_agent_compacts_early_interaction_of_latest_run_and_keeps_its_recent_suffix(
    tmp_path, monkeypatch
):
    store, coordinator, _unused_session, _run = _app(tmp_path)
    session = coordinator.create_session()
    latest = _complete_two_interaction_run(coordinator, store, session.session_id)
    target = _create_followup_run(
        coordinator, session.session_id, key="partial-latest-target", text="继续上一轮。"
    )
    latest_state = coordinator.read_run_state(session.session_id, latest.run_id)
    _set_capacity_and_estimates(monkeypatch, [81, 85, 75])
    factory = _FakeFactory([
        _summary_response(latest_state, "早期工具观察已经纳入摘要。"),
        _response(content="基于保留的近期交互继续完成。"),
    ])

    result = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )

    checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    assert checkpoint is not None
    assert checkpoint.covered_run_id == latest.run_id
    assert checkpoint.covered_record_sequence < latest_state.checkpoint.last_committed_record_sequence
    assert checkpoint.covered_tool_sequence == latest_state.checkpoint.last_committed_tool_sequence
    assert _agent_request(result).context_projection == "checkpoint"
    summary_payload = json.loads(factory.client.requests[0].messages[0].content)
    assert summary_payload["source_runs"][0]["run_id"] == latest.run_id
    assert summary_payload["source_runs"][0]["input"]["text"] == "先执行早期交互，再完成最终结论。"
    assert "较早交互" in json.dumps(summary_payload["source_runs"], ensure_ascii=False)
    assert "分析完成" not in json.dumps(summary_payload["source_runs"], ensure_ascii=False)
    ordinary_request_messages = factory.client.requests[1].messages
    run_locator = json.loads(ordinary_request_messages[0].content)
    assert run_locator == {
        "figura_context_type": "historical_run_context",
        "run_id": latest.run_id,
        "run_ordinal": latest.ordinal,
        "input_ref": summary_payload["source_runs"][0]["input"]["reference"],
    }
    ordinary_messages = json.dumps(
        [message.content for message in ordinary_request_messages],
        ensure_ascii=False,
    )
    assert "较早交互" not in ordinary_messages
    assert "分析完成" in ordinary_messages
    assert result.run.status is RunStatus.RUNNING


def test_incremental_compaction_reads_only_newly_covered_slice_of_same_run(
    tmp_path, monkeypatch
):
    store, coordinator, _unused_session, _run = _app(tmp_path)
    session = coordinator.create_session()
    latest = _complete_two_interaction_run(coordinator, store, session.session_id)
    latest_state = coordinator.read_run_state(session.session_id, latest.run_id)
    _set_capacity_and_estimates(monkeypatch, [81, 85, 75])
    first_factory = _FakeFactory([
        _summary_response(latest_state, "早期工具观察已经纳入摘要。"),
        _response(content="近期交互已处理。"),
    ])
    first_target = _create_followup_run(
        coordinator, session.session_id, key="partial-first-target", text="继续上一轮。"
    )
    first_result = _agent(store, coordinator, _registry(), first_factory).execute_slice(
        session.session_id, first_target.run_id
    )
    coordinator.complete_run(
        session.session_id, first_target.run_id, first_result.checkpoint.revision
    )
    first_checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    assert first_checkpoint is not None
    assert first_checkpoint.covered_run_ordinal == latest.ordinal
    assert first_checkpoint.covered_record_sequence < latest_state.checkpoint.last_committed_record_sequence

    _set_capacity_and_estimates(monkeypatch, [81, 85, 75])
    second_factory = _FakeFactory([
        _summary_response(latest_state, "后续交互也已纳入摘要。"),
        _response(content="继续完成。"),
    ])
    second_target = _create_followup_run(
        coordinator, session.session_id, key="partial-second-target", text="继续整理历史。"
    )
    second_result = _agent(store, coordinator, _registry(), second_factory).execute_slice(
        session.session_id, second_target.run_id
    )
    assert second_result.provider_requests, {
        "run_status": second_result.run.status,
        "terminal_code": second_result.run.terminal_code,
        "next_action": second_result.checkpoint.next_action,
        "provider_attempts": second_result.provider_attempts,
        "requests": len(second_factory.client.requests),
    }
    compaction_binding = _agent_request(second_result)
    compaction_operation = coordinator.read_context_compaction_operation(
        compaction_binding.context_checkpoint_operation_id
    )
    assert len(second_factory.client.requests) == 2, {
        "run_status": second_result.run.status,
        "terminal_code": second_result.run.terminal_code,
        "projection": compaction_binding.context_projection,
        "failure_code": compaction_operation.failure_code,
        "requests": len(second_factory.client.requests),
    }

    second_checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    assert second_checkpoint is not None
    assert second_checkpoint.revision == first_checkpoint.revision + 1
    assert second_checkpoint.covered_run_id == latest.run_id
    assert second_checkpoint.covered_record_sequence == latest_state.checkpoint.last_committed_record_sequence
    payload = json.loads(second_factory.client.requests[0].messages[0].content)
    assert payload["previous_summary"] is not None
    assert payload["previous_source_refs"] == [
        reference.to_dict() for reference in first_checkpoint.source_refs
    ]
    assert [item["run_id"] for item in payload["source_runs"]] == [latest.run_id]
    messages = payload["source_runs"][0]["messages"]
    assert any(item.get("text") == "分析完成" for item in messages)
    assert all(item.get("role") != "user" for item in messages)
    assert all(item.get("tool_call_id") != "early-call" for item in messages)
    assert _agent_request(second_result).context_checkpoint_revision == 2


def test_partial_checkpoint_accepts_only_complete_tool_batch_boundaries(tmp_path):
    store, coordinator, _unused_session, _run = _app(tmp_path)
    session = coordinator.create_session()
    latest = _complete_two_interaction_run(coordinator, store, session.session_id)
    latest_state = coordinator.read_run_state(session.session_id, latest.run_id)
    selected = select_compaction_coverage(
        (latest_state,), None, 5,
        estimate_tokens=lambda text: 7 if "较早交互" in text else 5,
    )
    assert selected is not None
    valid = SessionContextCheckpoint(
        session_id=session.session_id,
        revision=1,
        covered_run_id=selected.covered_run_id,
        covered_run_ordinal=selected.covered_run_ordinal,
        covered_record_sequence=selected.covered_record_sequence,
        covered_tool_sequence=selected.covered_tool_sequence,
        summary_contract_version=2,
        summary=_summary_v2(),
        source_refs=(
            MessageSourceRef(latest.run_id, latest.input_record_id),
            ToolResultSourceRef(latest.run_id, "early-call"),
        ),
    )
    coordinator.replace_session_context_checkpoint(valid, expected_revision=0)

    invalid_input_only = replace(
        valid,
        revision=2,
        covered_record_sequence=1,
        covered_tool_sequence=0,
        source_refs=(MessageSourceRef(latest.run_id, latest.input_record_id),),
    )
    with pytest.raises(RunError) as error:
        coordinator.replace_session_context_checkpoint(
            invalid_input_only, expected_revision=1
        )
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD

    call_sequence = next(
        fact.tool_sequence for fact in latest_state.tool_facts
        if fact.fact_kind.value == "tool_call"
    )
    invalid_inside_batch = replace(valid, revision=2, covered_tool_sequence=call_sequence)
    with pytest.raises(RunError) as error:
        coordinator.replace_session_context_checkpoint(
            invalid_inside_batch, expected_revision=1
        )
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD

    final_response_id = next(
        record.record_id for record in latest_state.records
        if record.record_kind.value == "model_response"
        and record.payload.finish_reason == "stop"
    )
    after_cutoff_ref = replace(
        valid,
        revision=2,
        source_refs=(MessageSourceRef(latest.run_id, final_response_id),),
    )
    with pytest.raises(RunError) as error:
        coordinator.replace_session_context_checkpoint(after_cutoff_ref, expected_revision=1)
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD


def test_compaction_operation_rejects_cutoff_inside_tool_call_batch(tmp_path):
    store, coordinator, _unused_session, _run = _app(tmp_path)
    session = coordinator.create_session()
    latest = _complete_two_interaction_run(coordinator, store, session.session_id)
    target = _create_followup_run(
        coordinator, session.session_id, key="invalid-boundary-target", text="继续分析。"
    )
    target_state = coordinator.read_run_state(session.session_id, target.run_id)
    latest_state = coordinator.read_run_state(session.session_id, latest.run_id)
    response = next(
        record for record in latest_state.records
        if record.record_kind.value == "model_response"
        and record.payload.finish_reason == "tool_calls"
    )
    call_sequence = next(
        fact.tool_sequence for fact in latest_state.tool_facts
        if fact.fact_kind.value == "tool_call"
    )

    with pytest.raises(RunError) as error:
        coordinator.get_or_create_context_compaction_operation(
            session_id=session.session_id,
            target_run_id=target.run_id,
            base_record_sequence=target_state.checkpoint.last_committed_record_sequence,
            base_tool_sequence=target_state.checkpoint.last_committed_tool_sequence,
            input_checkpoint_revision=0,
            covered_run_id=latest.run_id,
            covered_run_ordinal=latest.ordinal,
            covered_record_sequence=response.record_sequence,
            covered_tool_sequence=call_sequence,
        )
    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD


def test_selector_keeps_incomplete_abnormal_run_tail_outside_summary(tmp_path):
    store, coordinator, _unused_session, _run = _app(tmp_path)
    session = coordinator.create_session()
    completed = _create_followup_run(
        coordinator, session.session_id, key="before-abnormal", text="已完成的历史交互。"
    )
    _complete_text_run(coordinator, session.session_id, completed.run_id)
    abnormal = _create_followup_run(
        coordinator, session.session_id, key="abnormal-tool-tail", text="执行一个会中断的观察。"
    )
    registry = _registry()
    _commit_tool_response(
        coordinator,
        session.session_id,
        abnormal.run_id,
        registry,
        _response(
            content="尚未完成的工具批次。",
            calls=(ProviderToolCall("unfinished-call", "inspect", '{"value":9}'),),
            reason=FinishReason.TOOL_CALLS,
        ),
    )
    abnormal_state = coordinator.read_run_state(session.session_id, abnormal.run_id)
    coordinator.fail_run(
        session.session_id, abnormal.run_id, abnormal_state.checkpoint.revision
    )
    target = _create_followup_run(
        coordinator, session.session_id, key="after-abnormal", text="继续分析。"
    )
    prior = coordinator.read_prior_run_states(session.session_id, target.run_id)

    selected = select_compaction_coverage(
        prior,
        None,
        0,
        estimate_tokens=lambda text: max(1, len(text.split())),
    )

    assert selected is not None
    assert selected.covered_run_id == completed.run_id
    assert all(state.run.run_id != abnormal.run_id for state in selected.selected_run_states)
    assert eligible_compaction_runs(prior, 0) == (prior[0],)


def test_partial_coverage_keeps_cited_and_newer_same_run_tool_resources(tmp_path):
    from figura.shared.resource_refs import ToolResourceRef
    from figura.agent.execution_resources import (ExecutionResource, OcrContent, RunExecutionState)
    from figura.agent.request import _prompt_resource_projection
    from figura.runtime.tool_execution import DurableToolExecutor
    from figura.tools import ToolOutcome
    from figura.tools.contracts import ToolExecutionError

    store, coordinator, _unused_session, _run = _app(tmp_path)
    session = coordinator.create_session()
    registry = _registry()
    run = _create_followup_run(
        coordinator, session.session_id, key="resource-slices", text="观察后继续整理。"
    )
    for call_id, text, value in (
        ("early-resource-call", "较早 OCR 观察", 1),
        ("late-resource-call", "近期 OCR 观察", 2),
    ):
        _commit_tool_response(
            coordinator,
            session.session_id,
            run.run_id,
            registry,
            _response(
                content=text,
                calls=(ProviderToolCall(call_id, "inspect", json.dumps({"value": value})),),
                reason=FinishReason.TOOL_CALLS,
            ),
        )
        make_durable_tool_executor(store, registry).execute_pending(session.session_id, run.run_id)
    _complete_text_run(coordinator, session.session_id, run.run_id, registry=registry)
    target = _create_followup_run(
        coordinator, session.session_id, key="resource-slice-target", text="继续整理。"
    )
    run_state = coordinator.read_run_state(session.session_id, run.run_id)
    target_state = coordinator.read_run_state(session.session_id, target.run_id)
    prior = coordinator.read_prior_run_states(session.session_id, target.run_id)
    selection = select_compaction_coverage(
        (run_state,),
        None,
        18,
        estimate_tokens=lambda text: (
            7 if "early-resource-call" in text
            else 8 if "late-resource-call" in text
            else 5
        ),
    )
    assert selection is not None
    assert selection.covered_record_sequence < run_state.checkpoint.last_committed_record_sequence

    def resource(call_id):
        return ExecutionResource(
            ToolResourceRef("ocr", run.run_id, call_id),
            OcrContent(
                attempt_id=f"attempt-{call_id}",
                source_ref=None,
                observation_scope=None,
                outcome=ToolOutcome.FAILED,
                error=ToolExecutionError("ocr_unavailable", "OCR 结果不可用。", False),
            ),
        )

    checkpoint = SessionContextCheckpoint(
        session_id=session.session_id,
        revision=1,
        covered_run_id=selection.covered_run_id,
        covered_run_ordinal=selection.covered_run_ordinal,
        covered_record_sequence=selection.covered_record_sequence,
        covered_tool_sequence=selection.covered_tool_sequence,
        summary_contract_version=2,
        summary=_summary_v2(),
        source_refs=(ToolResultSourceRef(run.run_id, "early-resource-call"),),
    )
    projected = _prompt_resource_projection(
        RunExecutionState(target.run_id, (resource("early-resource-call"), resource("late-resource-call"))),
        target_state,
        prior,
        checkpoint,
    )

    assert {item.ref.call_id for item in projected.resources} == {
        "early-resource-call",
        "late-resource-call",
    }


@pytest.mark.parametrize(
    "capacity,estimate,expected_projection",
    [(None, 95, "full"), (100, None, "full"), (100, 79, "full")],
)
def test_unknown_or_low_context_does_not_trigger_summary(
    tmp_path, monkeypatch, capacity, estimate, expected_projection
):
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, _first, _second, target = _history_with_target(coordinator)
    _set_capacity_and_estimates(monkeypatch, [estimate], capacity=capacity)
    factory = _FakeFactory([_response(content="普通请求")])

    state = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )

    assert len(factory.client.requests) == 1
    assert _agent_request(state).context_projection == expected_projection
    assert coordinator.read_session_context_checkpoint(session.session_id) is None


def test_invalid_summary_falls_back_to_full_history_and_pins_fallback(tmp_path, monkeypatch):
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, _second, target = _history_with_target(coordinator)
    _set_capacity_and_estimates(monkeypatch, [90, 80, 90])
    factory = _FakeFactory([
        _response(content="not JSON"),
        _response(content="未压缩完成"),
    ])

    state = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )

    binding = _agent_request(state)
    operation = coordinator.read_context_compaction_operation(
        binding.context_checkpoint_operation_id
    )
    assert binding.context_projection == "fallback"
    assert operation.status == "fallback"
    assert operation.failure_code == "summary_invalid_json"
    assert coordinator.read_session_context_checkpoint(session.session_id) is None
    ordinary_text = json.dumps(
        [message.content for message in factory.client.requests[-1].messages],
        ensure_ascii=False,
    )
    assert "第一轮：分析销售趋势" in ordinary_text
    assert first.run_id != target.run_id


def test_summary_request_over_capacity_falls_back_without_provider_dispatch(tmp_path, monkeypatch):
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, _second, target = _history_with_target(coordinator)
    _set_capacity_and_estimates(monkeypatch, [90, 90, 101, 90])
    factory = _FakeFactory([_response(content="容量安全回退后回答")])

    state = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )

    binding = _agent_request(state)
    operation = coordinator.read_context_compaction_operation(
        binding.context_checkpoint_operation_id
    )
    assert binding.context_projection == "fallback"
    assert operation.status == "fallback"
    assert operation.failure_code == "summary_request_exceeds_capacity"
    assert _operation_attempt_count(coordinator, operation) == 0
    assert coordinator.read_session_context_checkpoint(session.session_id) is None
    assert len(factory.client.requests) == 1
    raw_request = json.dumps(
        [message.content for message in factory.client.requests[0].messages],
        ensure_ascii=False,
    )
    assert "第一轮：分析销售趋势" in raw_request
    assert first.run_id != target.run_id


@pytest.mark.parametrize("missing_asset", [False, True])
def test_invalid_incremental_summary_keeps_previous_checkpoint_unchanged(tmp_path, monkeypatch, missing_asset):
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, _second, target = _history_with_target(coordinator)
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    _set_capacity_and_estimates(monkeypatch, [90, 80, 45])
    first_factory = _FakeFactory([
        _summary_response(first_state),
        _response(content="第一阶段完成"),
    ])
    state = _agent(store, coordinator, _registry(), first_factory).execute_slice(
        session.session_id, target.run_id
    )
    coordinator.complete_run(session.session_id, target.run_id, state.checkpoint.revision)
    previous = coordinator.read_session_context_checkpoint(session.session_id)
    assert previous is not None

    next_target = _create_followup_run(
        coordinator, session.session_id, key="incremental-target", text="追加背景后继续"
    )
    _set_capacity_and_estimates(monkeypatch, [90, 80, 90])
    if missing_asset:
        _break_compaction_asset(monkeypatch)
    second_factory = _FakeFactory(
        ([] if missing_asset else [_response(content="invalid summary")])
        + [_response(content="完整历史下的回答")]
    )
    result = _agent(store, coordinator, _registry(), second_factory).execute_slice(
        session.session_id, next_target.run_id
    )

    assert _agent_request(result).context_projection == "fallback"
    assert coordinator.read_session_context_checkpoint(session.session_id) == previous
    full_request_text = json.dumps(
        [message.content for message in second_factory.client.requests[-1].messages],
        ensure_ascii=False,
    )
    assert "第一轮：分析销售趋势" in full_request_text
    if missing_asset:
        assert len(second_factory.client.requests) == 1
        operation = coordinator.read_context_compaction_operation(
            _agent_request(result).context_checkpoint_operation_id
        )
        assert operation.failure_code == "invalid_summary_input"


@pytest.mark.parametrize("changed_asset", [False, True])
def test_interrupted_summary_reuses_saved_request_identity_after_restart(tmp_path, monkeypatch, changed_asset):
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, _second, target = _history_with_target(coordinator)
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    _set_capacity_and_estimates(monkeypatch, [90, 80, 90, 45])
    factory = _FakeFactory([_summary_response(first_state), _response(content="完成")])

    def interrupt_before_checkpoint(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(coordinator, "replace_session_context_checkpoint", interrupt_before_checkpoint)
    with pytest.raises(KeyboardInterrupt):
        _agent(store, coordinator, _registry(), factory).execute_slice(
            session.session_id, target.run_id
        )

    target_state = coordinator.read_run_state(session.session_id, target.run_id)
    operation_id = coordinator.get_or_create_context_compaction_operation(
        session_id=session.session_id,
        target_run_id=target.run_id,
        base_record_sequence=target_state.checkpoint.last_committed_record_sequence,
        base_tool_sequence=target_state.checkpoint.last_committed_tool_sequence,
        input_checkpoint_revision=0,
        covered_run_id=first.run_id,
        covered_run_ordinal=first.ordinal,
        covered_record_sequence=first_state.checkpoint.last_committed_record_sequence,
        covered_tool_sequence=first_state.checkpoint.last_committed_tool_sequence,
    )
    assert _operation_attempt_count(coordinator, operation_id) == 1
    interrupted_state = coordinator.read_run_state(session.session_id, target.run_id)
    original_request = next(
        item for item in interrupted_state.provider_requests
        if item.request_id == operation_id.provider_request_id
    )

    reopened = FiguraRunStore(tmp_path)
    restarted_coordinator = RunCoordinator(reopened, coordinator._provider_factory)
    if changed_asset:
        from figura.agent.prompting import loader
        original = loader._load_asset
        monkeypatch.setattr(loader, "_load_asset", lambda asset: original(asset) + "\n新增摘要指导" if asset == "compaction-v3.md" else original(asset))
    restarted_factory = _FakeFactory(
        ([] if changed_asset else [_summary_response(first_state)]) + [_response(content="完成")]
    )
    result = _agent(reopened, restarted_coordinator, _registry(), restarted_factory).execute_slice(
        session.session_id, target.run_id
    )
    resumed_operation = restarted_coordinator.read_context_compaction_operation(
        operation_id.operation_id
    )

    if changed_asset:
        assert resumed_operation.status == "fallback"
        assert resumed_operation.failure_code == "summary_request_invalid"
        assert _operation_attempt_count(restarted_coordinator, resumed_operation) == 1
        assert _agent_request(result).context_projection == "fallback"
        assert coordinator.read_session_context_checkpoint(session.session_id) is None
        assert len(restarted_factory.client.requests) == 1
    else:
        assert resumed_operation.status == "completed"
        assert _operation_attempt_count(restarted_coordinator, resumed_operation) == 2
        assert _agent_request(result).context_projection == "checkpoint"
    resumed_state = restarted_coordinator.read_run_state(session.session_id, target.run_id)
    assert next(
        item for item in resumed_state.provider_requests
        if item.request_id == resumed_operation.provider_request_id
    ) == original_request


def test_interrupted_summary_reuses_frozen_budget_when_provider_capacity_changes(
    tmp_path, monkeypatch
):
    import figura.providers.config as config

    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, _second, target = _history_with_target(coordinator)
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    _set_capacity_and_estimates(monkeypatch, [90, 80, 90, 45])
    first_factory = _FakeFactory([_summary_response(first_state), _response(content="完成")])

    def interrupt_before_checkpoint(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(coordinator, "replace_session_context_checkpoint", interrupt_before_checkpoint)
    with pytest.raises(KeyboardInterrupt):
        _agent(store, coordinator, _registry(), first_factory).execute_slice(
            session.session_id, target.run_id
        )

    target_state = coordinator.read_run_state(session.session_id, target.run_id)
    operation = coordinator.find_context_compaction_operation(
        session.session_id,
        target.run_id,
        target_state.checkpoint.last_committed_record_sequence,
        target_state.checkpoint.last_committed_tool_sequence,
    )
    assert operation is not None
    assert operation.selection_plan["context_capacity_tokens"] == 100
    interrupted_state = coordinator.read_run_state(session.session_id, target.run_id)
    original_request = next(
        item for item in interrupted_state.provider_requests
        if item.request_id == operation.provider_request_id
    )
    original_summary_request = first_factory.client.requests[0]

    original_profile = config._profile_from_env
    monkeypatch.setattr(
        config,
        "_profile_from_env",
        lambda provider, environ: replace(
            original_profile(provider, environ), context_window_tokens=250
        ),
    )
    reopened = FiguraRunStore(tmp_path)
    restarted_coordinator = RunCoordinator(reopened, coordinator._provider_factory)
    restarted_factory = _FakeFactory([
        _summary_response(first_state), _response(content="容量变化后继续完成")
    ])
    result = _agent(reopened, restarted_coordinator, _registry(), restarted_factory).execute_slice(
        session.session_id, target.run_id
    )
    resumed = restarted_coordinator.read_context_compaction_operation(operation.operation_id)

    assert resumed.status == "completed"
    resumed_state = restarted_coordinator.read_run_state(session.session_id, target.run_id)
    assert next(
        item for item in resumed_state.provider_requests
        if item.request_id == resumed.provider_request_id
    ) == original_request
    assert restarted_factory.client.requests[0] == original_summary_request
    assert _agent_request(result).context_checkpoint_revision == 1


def _break_compaction_asset(monkeypatch):
    from figura.agent.prompting import loader
    original = loader._load_asset

    def load(asset):
        if asset == "compaction-v3.md":
            raise loader.PromptAssetError("compaction-v3.md unavailable")
        return original(asset)

    monkeypatch.setattr(loader, "_load_asset", load)


def test_unavailable_compaction_asset_falls_back_without_summary_dispatch(tmp_path, monkeypatch):
    store, coordinator, _session, _run = _app(tmp_path)
    session, _first, _second, target = _history_with_target(coordinator)
    _set_capacity_and_estimates(monkeypatch, [90, 80, 90])
    _break_compaction_asset(monkeypatch)
    factory = _FakeFactory([_response(content="完整历史回答")])
    state = _agent(store, coordinator, _registry(), factory).execute_slice(session.session_id, target.run_id)
    binding = _agent_request(state)
    operation = coordinator.read_context_compaction_operation(binding.context_checkpoint_operation_id)
    assert operation.failure_code == "invalid_summary_input"
    assert _operation_attempt_count(coordinator, operation) == 0
    assert operation.selection_plan["context_capacity_tokens"] == 100
    assert len(factory.client.requests) == 1
    assert coordinator.read_session_context_checkpoint(session.session_id) is None


def test_compaction_asset_change_updates_request_prompt_digest(tmp_path, monkeypatch):
    from figura.agent.prompting import loader

    _store, coordinator, _session, _run = _app(tmp_path)
    session, first, _second, target = _history_with_target(coordinator)
    current = coordinator.read_run_state(session.session_id, target.run_id)
    sources = (coordinator.read_run_state(session.session_id, first.run_id),)
    builder = _agent(_store, coordinator, _registry(), _FakeFactory([]))._requests
    before, refs = builder.build_summary_request(
        current, sources, None,
        context_capacity_tokens=200_000,
        summary_budget_tokens=20_000,
    )
    assert "previous_summary_contract_version" not in json.loads(before.messages[0].content)
    assert before.asset_contract["registry_version"] == "context-compaction-v3"
    original = loader._load_asset
    monkeypatch.setattr(loader, "_load_asset", lambda asset: original(asset) + "\n新增摘要指导" if asset == "compaction-v3.md" else original(asset))
    after, new_refs = builder.build_summary_request(
        current, sources, None,
        context_capacity_tokens=200_000,
        summary_budget_tokens=20_000,
    )
    assert before.asset_contract["prompt_digest"] != after.asset_contract["prompt_digest"]
    assert before.messages == after.messages and refs == new_refs
    assert before.tools == after.tools == ()
    assert isinstance(before.messages[0].content, str)


@pytest.mark.parametrize("citation", ["message", "tool_result", "duplicate", "foreign", "empty"])
def test_summary_contract_authorizes_both_citation_shapes(tmp_path, citation):
    from figura.agent.context_compaction import validate_summary_response
    from figura.shared.source_refs import ToolResultSourceRef

    _store, coordinator, session, first = _app(tmp_path)
    source = coordinator.read_run_state(session.session_id, first.run_id)
    message = MessageSourceRef(first.run_id, source.run.input_record_id)
    tool = ToolResultSourceRef(first.run_id, "authorized-call")
    citations = {
        "message": [message.to_dict()], "tool_result": [tool.to_dict()],
        "duplicate": [tool.to_dict(), tool.to_dict()],
        "foreign": [ToolResultSourceRef("foreign-run", "foreign-call").to_dict()], "empty": [],
    }[citation]
    value = _summary_v2({"text": "事实摘要", "source_refs": citations})
    response = _response(content=json.dumps(value))
    arguments = dict(provider_id=ProviderId.QWEN.value, model_id=MODEL_IDS[ProviderId.QWEN],
        allowed_refs=(message, tool), selected_runs=(source,))
    if citation in {"duplicate", "foreign", "empty"}:
        with pytest.raises(ValueError):
            validate_summary_response(response, **arguments)
    else:
        summary, refs = validate_summary_response(response, **arguments)
        assert summary["facts"][0]["source_refs"] == citations
        assert summary["trust"] == "untrusted_history"
        assert message in refs


def test_summary_v2_keeps_goal_and_user_accepted_progress_in_separate_fields(tmp_path):
    from figura.agent.context_compaction import validate_summary_response

    _store, coordinator, session, first = _app(tmp_path)
    source = coordinator.read_run_state(session.session_id, first.run_id)
    ref = MessageSourceRef(first.run_id, source.run.input_record_id).to_dict()
    value = _summary_v2()
    value["current_goal"] = [{"text": "完成地区对比", "source_refs": [ref]}]
    value["progress"]["pending"] = [{"text": "补充地区对比", "source_refs": [ref]}]
    value["proposals"] = [{"text": "可以补充季节性分析", "source_refs": [ref]}]
    summary, _refs = validate_summary_response(
        _response(content=json.dumps(value)),
        provider_id=ProviderId.QWEN.value,
        model_id=MODEL_IDS[ProviderId.QWEN],
        allowed_refs=(MessageSourceRef(first.run_id, source.run.input_record_id),),
        selected_runs=(source,),
    )

    assert summary["current_goal"][0]["text"] == "完成地区对比"
    assert summary["progress"]["pending"][0]["text"] == "补充地区对比"
    assert summary["proposals"][0]["text"] == "可以补充季节性分析"
    assert "run_outcomes" in summary


@pytest.mark.parametrize(
    "mutation", ["missing_field", "extra_field", "invalid_progress", "item_extra_field"]
)
def test_summary_v2_rejects_incomplete_or_unexpected_fields(tmp_path, mutation):
    from figura.agent.context_compaction import validate_summary_response

    _store, coordinator, session, first = _app(tmp_path)
    source = coordinator.read_run_state(session.session_id, first.run_id)
    ref = MessageSourceRef(first.run_id, source.run.input_record_id).to_dict()
    value = _summary_v2()
    if mutation == "missing_field":
        del value["facts"]
    elif mutation == "extra_field":
        value["summary_contract_version"] = 2
    elif mutation == "invalid_progress":
        del value["progress"]["blocked"]
    else:
        value["facts"] = [{"text": "摘要", "source_refs": [ref], "status": "fact"}]
    with pytest.raises(ValueError):
        validate_summary_response(
            _response(content=json.dumps(value)),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            allowed_refs=(MessageSourceRef(first.run_id, source.run.input_record_id),),
            selected_runs=(source,),
        )


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        ("not JSON", "summary_invalid_json"),
        ('{"current_goal":[],"current_goal":[]}', "summary_duplicate_json_key"),
        (json.dumps({**_summary_v2(), "unexpected": []}), "summary_top_level_fields"),
        (
            json.dumps({
                **_summary_v2(),
                "facts": [{
                    "text": "有来源引用的数据",
                    "source_refs": [{"kind": "message", "run_id": "foreign", "record_id": "foreign"}],
                }],
            }),
            "summary_source_ref_unauthorized",
        ),
        (
            json.dumps({
                **_summary_v2(),
                "facts": [{
                    "text": "格式错误的引用",
                    "source_refs": [{"kind": "message", "run_id": "missing-record-id"}],
                }],
            }),
            "summary_source_ref_shape",
        ),
    ],
)
def test_summary_validation_emits_safe_failure_categories(tmp_path, content, expected_code):
    from figura.agent.context_compaction import SummaryValidationError, validate_summary_response

    _store, coordinator, session, first = _app(tmp_path)
    source = coordinator.read_run_state(session.session_id, first.run_id)
    with pytest.raises(SummaryValidationError) as error:
        validate_summary_response(
            _response(content=content),
            provider_id=ProviderId.QWEN.value,
            model_id=MODEL_IDS[ProviderId.QWEN],
            allowed_refs=(MessageSourceRef(first.run_id, source.run.input_record_id),),
            selected_runs=(source,),
        )
    assert error.value.failure_code == expected_code


@pytest.mark.parametrize(
    ("response_provider", "continuation_provider", "content", "expected_code"),
    [
        (ProviderId.DEEPSEEK, ProviderId.DEEPSEEK, "valid", None),
        (
            ProviderId.DEEPSEEK,
            ProviderId.QWEN,
            "valid",
            "summary_response_contract",
        ),
        (
            ProviderId.QWEN,
            ProviderId.QWEN,
            "valid",
            "summary_response_contract",
        ),
        (
            ProviderId.DEEPSEEK,
            ProviderId.DEEPSEEK,
            "invalid",
            "summary_invalid_json",
        ),
    ],
)
def test_summary_response_continuation_is_deepseek_private_and_final_content_is_validated(
    tmp_path, response_provider, continuation_provider, content, expected_code
):
    from figura.agent.context_compaction import SummaryValidationError, validate_summary_response

    _store, coordinator, session, first = _app(tmp_path)
    source = coordinator.read_run_state(session.session_id, first.run_id)
    ref = MessageSourceRef(first.run_id, source.run.input_record_id)
    summary_content = (
        json.dumps(
            _summary_v2({"text": "受来源支持的摘要", "source_refs": [ref.to_dict()]}),
            ensure_ascii=False,
        )
        if content == "valid"
        else "not JSON"
    )
    response = _response(
        content=summary_content,
        provider_id=response_provider,
        continuation=ProviderContinuation(
            continuation_provider, 1, "private-continuation-marker"
        ),
    )
    arguments = dict(
        provider_id=response_provider.value,
        model_id=MODEL_IDS[response_provider],
        allowed_refs=(ref,),
        selected_runs=(source,),
    )

    if expected_code is not None:
        with pytest.raises(SummaryValidationError) as error:
            validate_summary_response(response, **arguments)
        assert error.value.failure_code == expected_code
    else:
        summary, _refs = validate_summary_response(response, **arguments)
        assert summary["facts"][0]["text"] == "受来源支持的摘要"
        assert "private-continuation-marker" not in json.dumps(summary, ensure_ascii=False)


def test_incremental_summary_request_keeps_prior_summary_and_new_source_identity(tmp_path):
    store, coordinator, _session, _run = _app(tmp_path)
    session, first, second, target = _history_with_target(coordinator)
    old_state = coordinator.read_run_state(session.session_id, first.run_id)
    new_state = coordinator.read_run_state(session.session_id, second.run_id)
    old_ref = MessageSourceRef(first.run_id, first.input_record_id)
    previous = SessionContextCheckpoint(
        session_id=session.session_id, revision=1, covered_run_id=first.run_id,
        covered_run_ordinal=first.ordinal,
        covered_record_sequence=old_state.checkpoint.last_committed_record_sequence,
        covered_tool_sequence=old_state.checkpoint.last_committed_tool_sequence,
        summary_contract_version=1,
        summary={"items": [{"text": "旧摘要", "source_refs": [old_ref.to_dict()]}], "run_outcomes": []},
        source_refs=(old_ref,),
    )
    builder = _agent(store, coordinator, _registry(), _FakeFactory([]))._requests
    request, allowed_refs = builder.build_summary_request(
        coordinator.read_run_state(session.session_id, target.run_id), (new_state,), previous,
        context_capacity_tokens=200_000,
        summary_budget_tokens=20_000,
    )
    payload = json.loads(request.messages[0].content)
    assert "previous_summary_contract_version" not in payload
    assert payload["previous_source_refs"] == [old_ref.to_dict()]
    assert payload["previous_summary"]["items"][0]["text"] == "旧摘要"
    assert [run["run_id"] for run in payload["source_runs"]] == [second.run_id]
    source_run = payload["source_runs"][0]
    assert source_run["input"] == {
        "reference": MessageSourceRef(second.run_id, second.input_record_id).to_dict(),
        "text": "第二轮：补充地区对比",
        "attachment_ids": [],
    }
    assert all(message.get("role") != "user" for message in source_run["messages"])
    assert old_ref in allowed_refs
    assert MessageSourceRef(second.run_id, second.input_record_id) in allowed_refs


def test_context_summary_prompt_keeps_storage_version_private_from_model(tmp_path):
    from figura.agent.prompting.execution import build_context_summary_instruction

    _store, coordinator, session, first, *_rest = _app(tmp_path)
    state = coordinator.read_run_state(session.session_id, first.run_id)
    reference = MessageSourceRef(first.run_id, first.input_record_id)
    legacy = SessionContextCheckpoint(
        session_id=session.session_id,
        revision=1,
        covered_run_id=first.run_id,
        covered_run_ordinal=first.ordinal,
        covered_record_sequence=state.checkpoint.last_committed_record_sequence,
        covered_tool_sequence=state.checkpoint.last_committed_tool_sequence,
        summary_contract_version=2,
        summary={"items": [], "run_outcomes": []},
        source_refs=(reference,),
    )

    legacy_payload = json.loads(
        build_context_summary_instruction(legacy).content.split("\n", 1)[1]
    )
    current_payload = json.loads(
        build_context_summary_instruction(
            replace(legacy, summary_contract_version=3)
        ).content.split("\n", 1)[1]
    )

    assert legacy_payload["summary_contract_version"] == 2
    assert "summary_contract_version" not in current_payload


@pytest.mark.parametrize("summary_valid", [True, False])
def test_legacy_checkpoint_reconciles_covered_user_inputs_before_omitting_them(
    tmp_path, monkeypatch, summary_valid
):
    import figura.agent.executor as agent_executor
    import figura.agent.request as request_module

    monkeypatch.setattr(
        request_module,
        "estimate_json_tokens",
        lambda value: len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")),
    )
    monkeypatch.setattr(agent_executor, "estimate_protected_raw_history_tokens", lambda *_args: 0)
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, second, target = _history_with_target(coordinator)
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    second_state = coordinator.read_run_state(session.session_id, second.run_id)
    old_input_ref = MessageSourceRef(first.run_id, first.input_record_id)
    previous = SessionContextCheckpoint(
        session_id=session.session_id,
        revision=1,
        covered_run_id=first.run_id,
        covered_run_ordinal=first.ordinal,
        covered_record_sequence=first_state.checkpoint.last_committed_record_sequence,
        covered_tool_sequence=first_state.checkpoint.last_committed_tool_sequence,
        summary_contract_version=2,
        summary={
            "items": [{"text": "旧摘要", "source_refs": [old_input_ref.to_dict()]}],
            "run_outcomes": [],
        },
        source_refs=(old_input_ref,),
    )
    coordinator.replace_session_context_checkpoint(previous, expected_revision=0)
    _set_capacity_and_estimates(
        monkeypatch, [161_000, 162_000, 70_000, 45_000], capacity=200_000
    )
    if summary_valid:
        fact = {"text": "保留第一轮用户要求", "source_refs": [old_input_ref.to_dict()]}
        summary_response = _response(
            content=json.dumps(_summary_v2(fact), ensure_ascii=False)
        )
    else:
        summary_response = _response(content="not a summary")
    factory = _FakeFactory([summary_response, _response(content="完成兼容恢复")])

    result = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )
    assert len(factory.client.requests) == 2, {
        "status": result.run.status.value,
        "terminal_code": result.run.terminal_code,
        "attempts": [(item.status.value, item.failure_code) for item in result.provider_attempts],
        "prepared": len(factory.client.prepared_requests),
        "records": [(item.record_kind.value, item.record_sequence) for item in result.records],
    }
    summary_payload = json.loads(factory.client.requests[0].messages[0].content)
    assert [item["run_id"] for item in summary_payload["source_runs"]] == [first.run_id]
    assert summary_payload["source_runs"][0]["input"]["text"] == "第一轮：分析销售趋势"
    assert summary_payload["source_runs"][0]["messages"] == []
    agent_request = factory.client.requests[1]
    historical_payload = json.loads(agent_request.messages[0].content)
    historical_texts = [entry["text"] for entry in historical_payload["entries"]]
    current_native_inputs = [
        message.content for message in agent_request.messages
        if message.role.value == "user"
        and isinstance(message.content, str)
        and "继续完成结论" in message.content
    ]
    assert len(current_native_inputs) == 1
    assert "继续完成结论" not in historical_texts

    operation = coordinator.read_context_compaction_operation(
        _agent_request(result).context_checkpoint_operation_id
    )
    assert operation.selection_plan["reconciliation"] is True
    checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    if summary_valid:
        assert operation.status == "completed"
        assert checkpoint is not None and checkpoint.summary_contract_version == 3
        assert checkpoint.covered_run_id == first.run_id
        assert checkpoint.covered_record_sequence == previous.covered_record_sequence
        assert old_input_ref in checkpoint.source_refs
        assert historical_texts == ["第二轮：补充地区对比"]
    else:
        assert operation.status == "fallback"
        assert checkpoint is not None
        assert checkpoint.revision == previous.revision
        assert checkpoint.summary_contract_version == previous.summary_contract_version
        assert checkpoint.covered_run_id == previous.covered_run_id
        assert checkpoint.covered_record_sequence == previous.covered_record_sequence
        assert checkpoint.source_refs == previous.source_refs
        assert encode_json(checkpoint.summary) == encode_json(previous.summary)
        assert historical_texts == [
            "第一轮：分析销售趋势",
            "第二轮：补充地区对比",
        ]
    assert second_state.run.status is RunStatus.COMPLETED


def test_transient_summary_failure_retries_the_same_internal_provider_request(tmp_path, monkeypatch):
    import figura.runtime.persistence.providers as provider_persistence

    monkeypatch.setattr(
        provider_persistence,
        "retry_deadline",
        lambda *_args: "2000-01-01T00:00:00Z",
    )
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, _second, target = _history_with_target(coordinator)
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    _set_capacity_and_estimates(monkeypatch, [90, 80, 45])
    factory = _FakeFactory([
        ProviderCallError(ProviderFailure(
            ProviderFailureCode.PROVIDER_UNAVAILABLE,
            outcome_known=False,
            transient=True,
            safe_message="临时不可用",
        )),
        _summary_response(first_state),
        _response(content="摘要重试后完成"),
    ])

    result = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )

    operation = coordinator.read_context_compaction_operation(
        _agent_request(result).context_checkpoint_operation_id
    )
    assert operation.status == "completed"
    assert _operation_attempt_count(coordinator, operation) == 2
    assert len(factory.client.requests) == 3
    assert factory.client.requests[0] == factory.client.requests[1]
    assert len(result.provider_attempts) == 3
    assert sum(
        item.request_id == operation.provider_request_id
        for item in result.provider_attempts
    ) == 2


def test_deepseek_summary_retry_reuses_medium_reasoning_descriptor(tmp_path, monkeypatch):
    import figura.runtime.persistence.providers as provider_persistence

    monkeypatch.setattr(
        provider_persistence,
        "retry_deadline",
        lambda *_args: "2000-01-01T00:00:00Z",
    )
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, _second, target = _history_with_target(
        coordinator, target_provider=ProviderId.DEEPSEEK
    )
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    _set_capacity_and_estimates(monkeypatch, [90, 80, 45])
    factory = _FakeFactory([
        ProviderCallError(ProviderFailure(
            ProviderFailureCode.PROVIDER_UNAVAILABLE,
            outcome_known=False,
            transient=True,
            safe_message="临时不可用",
        )),
        _summary_response(
            first_state,
            provider_id=ProviderId.DEEPSEEK,
            continuation=ProviderContinuation(
                ProviderId.DEEPSEEK, 1, "summary-private-marker"
            ),
        ),
        _response(content="摘要重试后完成", provider_id=ProviderId.DEEPSEEK),
    ])

    result = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )

    assert result.provider_requests, (
        result.run.status,
        result.run.terminal_code,
        tuple((item.failure_code, item.status.value) for item in result.provider_attempts),
        len(factory.client.requests),
        len(factory.client.prepared_requests),
    )
    operation = coordinator.read_context_compaction_operation(
        _agent_request(result).context_checkpoint_operation_id
    )
    summary_request_record = next(
        item for item in result.provider_requests
        if item.request_id == operation.provider_request_id
    )
    descriptor_options = summary_request_record.options
    assert operation.status == "completed"
    assert _operation_attempt_count(coordinator, operation) == 2
    assert descriptor_options["thinking_mode"] is True
    assert descriptor_options["reasoning_effort"] == "medium"
    assert factory.client.requests[0] == factory.client.requests[1]
    checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    assert checkpoint is not None
    assert "summary-private-marker" not in encode_json(checkpoint.summary)
    ordinary_text = json.dumps(
        [message.content for message in factory.client.requests[-1].messages],
        ensure_ascii=False,
    )
    assert "summary-private-marker" not in ordinary_text


@pytest.mark.parametrize("registry_changed", [False, True])
def test_ordinary_provider_retry_reuses_compaction_checkpoint_without_new_summary(
    tmp_path, monkeypatch, registry_changed
):
    import figura.runtime.persistence.providers as provider_persistence

    monkeypatch.setattr(
        provider_persistence,
        "retry_deadline",
        lambda *_args: "2000-01-01T00:00:00Z",
    )
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, _second, target = _history_with_target(coordinator)
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    _set_capacity_and_estimates(monkeypatch, [90, 80, 45])
    factory = _FakeFactory([
        _summary_response(first_state),
        ProviderCallError(ProviderFailure(
            ProviderFailureCode.PROVIDER_UNAVAILABLE,
            outcome_known=True,
            transient=True,
            safe_message="临时不可用",
            http_status=503,
        )),
    ])
    waiting = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )
    binding = _agent_request(waiting)
    assert waiting.checkpoint.next_action.action_kind is ActionKind.PROVIDER_RETRY
    assert binding.context_projection == "checkpoint"

    reopened = FiguraRunStore(tmp_path)
    restarted_coordinator = RunCoordinator(reopened, coordinator._provider_factory)
    retry_factory = _FakeFactory([_response(content="重试完成")])
    from figura.tools import ToolRegistry
    retry_registry = ToolRegistry("figura-web-v9", _registry().definitions) if registry_changed else _registry()
    completed = _agent(reopened, restarted_coordinator, retry_registry, retry_factory).execute(
        session.session_id, target.run_id
    )

    if registry_changed:
        assert completed.run.status is RunStatus.FAILED
        assert completed.provider_requests == waiting.provider_requests
        assert retry_factory.client.requests == []
        operation = restarted_coordinator.read_context_compaction_operation(binding.context_checkpoint_operation_id)
        assert _operation_attempt_count(restarted_coordinator, operation) == 1
    else:
        assert completed.run.status is RunStatus.COMPLETED, {
            "terminal_code": completed.run.terminal_code,
            "attempts": [(item.status.value, item.failure_code) for item in completed.provider_attempts],
            "prepared": len(retry_factory.client.prepared_requests),
            "dispatched": len(retry_factory.client.requests),
        }
        assert completed.provider_requests == waiting.provider_requests
        assert len(retry_factory.client.requests) == 1
        assert any("自动摘要" in item.content for item in retry_factory.client.requests[0].instructions)
        operation = restarted_coordinator.read_context_compaction_operation(
            binding.context_checkpoint_operation_id
        )
        assert _operation_attempt_count(restarted_coordinator, operation) == 1


def test_legacy_ordinary_retry_rebuilds_manifest_without_new_context_policy_fields(
    tmp_path, monkeypatch
):
    from figura.agent.request import AgentRequestBuilder
    from tests.test_figura_execution_policy import _temporary

    monkeypatch.setattr(
        "figura.runtime.persistence.providers.retry_deadline",
        lambda *_: "2000-01-01T00:00:00Z",
    )
    store, coordinator, session, run = _app(tmp_path)
    original_build = AgentRequestBuilder.build_with_projection

    def legacy_policy_builder(self, *args, **kwargs):
        kwargs["context_policy_version"] = 1
        kwargs.pop("directory_budget_tokens", None)
        return original_build(self, *args, **kwargs)

    monkeypatch.setattr(AgentRequestBuilder, "build_with_projection", legacy_policy_builder)
    factory = _FakeFactory([_temporary(), _response(content="legacy retry completed")])
    agent = _agent(store, coordinator, _registry(), factory)
    waiting = agent.execute_slice(session.session_id, run.run_id)
    frozen_request = _agent_request(waiting)
    assert waiting.checkpoint.next_action.action_kind is ActionKind.PROVIDER_RETRY
    assert not {
        "context_policy_version", "directory_projection_version", "directory_budget_tokens"
    } & set(frozen_request.asset_manifest)

    monkeypatch.setattr(AgentRequestBuilder, "build_with_projection", original_build)
    completed = agent.execute(session.session_id, run.run_id)

    assert completed.run.status is RunStatus.COMPLETED
    assert completed.provider_requests == (frozen_request,)
    assert len(factory.client.requests) == 2
    assert factory.client.requests[0] == factory.client.requests[1]

def test_prompt_resource_directory_is_compact_while_server_catalog_stays_complete(tmp_path):
    from tests.test_figura_agent_executor import _execution_inventory

    store, coordinator, session, first, attachments, _image_bytes, _image_path = _app_with_image(
        tmp_path
    )
    _complete_text_run(coordinator, session.session_id, first.run_id)
    second = _create_followup_run(
        coordinator, session.session_id, key="resource-second", text="补充第二轮背景"
    )
    _complete_text_run(coordinator, session.session_id, second.run_id)
    target = _create_followup_run(
        coordinator, session.session_id, key="resource-target", text="继续分析"
    )
    registry, builder = _image_runtime(store, coordinator, attachments)
    target_state = coordinator.read_run_state(session.session_id, target.run_id)
    prior = coordinator.read_prior_run_states(session.session_id, target.run_id)
    full_catalog = builder._execution_state.build(target_state, prior)
    assert any(
        getattr(resource.ref, "id", None) == attachments.list(session.session_id)[0].attachment_id
        for resource in full_catalog.resources
    )

    checkpoint = SessionContextCheckpoint(
        session_id=session.session_id,
        revision=1,
        covered_run_id=second.run_id,
        covered_run_ordinal=second.ordinal,
        covered_record_sequence=coordinator.read_run_state(session.session_id, second.run_id).checkpoint.last_committed_record_sequence,
        covered_tool_sequence=coordinator.read_run_state(session.session_id, second.run_id).checkpoint.last_committed_tool_sequence,
        summary_contract_version=1,
        summary={"items": [], "run_outcomes": []},
        source_refs=(MessageSourceRef(second.run_id, second.input_record_id),),
    )
    request = builder.build(
        target_state, registry, prior, context_checkpoint=checkpoint
    )
    inventory_instruction = next(
        item.content for item in request.instructions if "运行资源目录" in item.content
    )
    prompt_catalog = json.loads(inventory_instruction.split("\n", 1)[1])
    attachment_id = attachments.list(session.session_id)[0].attachment_id
    assert all(
        resource.get("ref", {}).get("id") != attachment_id
        for resource in prompt_catalog["resources"]
    )
    assert builder._execution_state.build(target_state, prior) == full_catalog


def test_resource_budget_without_checkpoint_keeps_current_attachment_and_drops_optional_panel(
    tmp_path, monkeypatch
):
    from tests.test_figura_agent_request import _commit_tool_calls
    from figura.agent.request import mandatory_resource_directory_tokens
    from figura.shared.resource_refs import ImageResourceRef

    # Keep this selection test deterministic even when the optional offline
    # tokenizer cache is unavailable in a test environment.
    import figura.agent.request as request_module
    monkeypatch.setattr(
        request_module,
        "estimate_json_tokens",
        lambda value: len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")),
    )
    store, coordinator, session, run, attachments, _image_bytes, _image_path = _app_with_image(
        tmp_path
    )
    registry, builder = _image_runtime(store, coordinator, attachments)
    attachment_id = attachments.list(session.session_id)[0].attachment_id
    _commit_tool_calls(
        store,
        coordinator,
        session,
        run,
        registry,
        [ProviderToolCall(
            "decompose-current-panel",
            "decompose_chart_image",
            json.dumps({
                "attachment_id": attachment_id,
                "panels": [{
                    "name": "可选局部 Panel",
                    "points": [
                        {"x": 0, "y": 0}, {"x": 1000, "y": 0},
                        {"x": 1000, "y": 1000}, {"x": 0, "y": 1000},
                    ],
                }],
            }),
        )],
    )
    target_state = coordinator.read_run_state(session.session_id, run.run_id)
    full_catalog = builder._execution_state.build(target_state, ())
    attachment_ref = ImageResourceRef("attachment", attachment_id)
    panel_refs = {
        resource.ref for resource in full_catalog.resources
        if isinstance(resource.ref, ImageResourceRef) and resource.ref.kind == "panel"
    }
    assert len(panel_refs) == 1

    mandatory_budget = mandatory_resource_directory_tokens(
        full_catalog, target_state, (), None
    )
    assert mandatory_budget is not None
    request, projection = builder.build_with_projection(
        target_state,
        registry,
        (),
        directory_budget_tokens=mandatory_budget,
    )
    repeated_request, repeated_projection = builder.build_with_projection(
        target_state,
        registry,
        (),
        directory_budget_tokens=mandatory_budget,
    )
    inventory = json.loads(request.instructions[-1].content.split("\n", 1)[1])
    projected_refs = {entry["ref"].get("id") for entry in inventory["resources"]}

    assert request == repeated_request
    assert projection.resource_entries == repeated_projection.resource_entries
    assert attachment_ref.id in projected_refs
    assert not any(ref.id in projected_refs for ref in panel_refs)
    assert "未列出不表示资源不存在" in request.instructions[-1].content
    assert builder._execution_state.build(target_state, ()) == full_catalog

    overshoot_request = builder.build(
        target_state, registry, (), directory_budget_tokens=0
    )
    overshoot_inventory = json.loads(overshoot_request.instructions[-1].content.split("\n", 1)[1])
    overshoot_refs = {entry["ref"].get("id") for entry in overshoot_inventory["resources"]}
    assert overshoot_refs == {attachment_ref.id}
    assert any(resource.ref in panel_refs for resource in builder._execution_state.build(target_state, ()).resources)


def test_pending_visual_batch_is_raw_and_summary_sources_only_include_descriptors(tmp_path):
    from tests.test_figura_agent_request import _app_with_attachments, _image_registry, _commit_tool_calls, _image_bytes, _builder
    from figura.runtime.records import ContextCompactionOperation
    from figura.agent.prompting.observations import pending_visual_results
    store, coordinator, session, run, attachments = _app_with_attachments(tmp_path, (_image_bytes('red'),))
    _panels, _service, registry = _image_registry(store, coordinator, attachments)
    attachment = attachments.list(session.session_id)[0]
    _commit_tool_calls(store, coordinator, session, run, registry, [ProviderToolCall('early', 'inspect', '{"value":1}')])
    state = _commit_tool_calls(store, coordinator, session, run, registry, [ProviderToolCall('load', 'load_image', json.dumps({'source_kind':'attachment', 'source_id':attachment.attachment_id}))])
    assert pending_visual_results(state)
    selected = select_compaction_coverage((), None, 0, active_run_state=state, estimate_tokens=lambda _: 100)
    assert selected.covered_tool_sequence < state.checkpoint.last_committed_tool_sequence
    operation = ContextCompactionOperation('op', session.session_id, run.run_id,
        state.checkpoint.last_committed_record_sequence, state.checkpoint.last_committed_tool_sequence,
        0, run.run_id, run.ordinal, state.checkpoint.last_committed_record_sequence,
        state.checkpoint.last_committed_tool_sequence, 'preparing')
    assert selection_for_coverage((), None, operation, active_run_state=state) is None
    # A later ordinary response consumes the picture. It can then be summarized by reference.
    newer = _commit_tool_calls(store, coordinator, session, run, registry, [ProviderToolCall('later', 'inspect', '{"value":2}')])
    assert not pending_visual_results(newer)
    selected = select_compaction_coverage((), None, 0, active_run_state=newer, estimate_tokens=lambda _: 100)
    request, _refs = _builder(store, coordinator, attachments).build_summary_request(newer,
        selected.selected_run_states, None, coverage=selected, context_capacity_tokens=1000, summary_budget_tokens=100)
    content = request.messages[0].content
    assert 'attachments' in content and attachment.attachment_id in content
    assert 'images_loaded' not in content and '系统观察提醒' not in content and 'base64' not in content
    assert request.tools == ()
