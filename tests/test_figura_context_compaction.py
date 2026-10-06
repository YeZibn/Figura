from __future__ import annotations

from dataclasses import replace
import json

import pytest

from figura.providers import FinishReason, MODEL_IDS, ProviderId
from figura.providers.errors import ProviderCallError, ProviderFailure, ProviderFailureCode
from figura.providers.token_estimation import ContextEstimate
from figura.agent.context_compaction import eligible_compaction_runs
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.models import ActionKind, RunStatus
from figura.runtime.records import SessionContextCheckpoint
from figura.runtime.store import FiguraRunStore
from figura.shared.source_refs import MessageSourceRef
from tests.test_figura_agent_executor import (
    _FakeFactory,
    _agent,
    _app,
    _app_with_image,
    _complete_text_run,
    _create_followup_run,
    _image_runtime,
    _registry,
    _response,
)


def _history_with_target(coordinator):
    session = coordinator.create_session()
    first = _create_followup_run(coordinator, session.session_id, key="history-first", text="第一轮：分析销售趋势")
    _complete_text_run(coordinator, session.session_id, first.run_id)
    second = _create_followup_run(coordinator, session.session_id, key="history-second", text="第二轮：补充地区对比")
    _complete_text_run(coordinator, session.session_id, second.run_id)
    target = _create_followup_run(coordinator, session.session_id, key="history-target", text="继续完成结论")
    return session, first, second, target


def _set_capacity_and_estimates(monkeypatch, values, *, capacity=100):
    import figura.providers.config as config
    import figura.providers.client as provider_client

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


def _summary_response(state, summary="已确认需要对比销售趋势和地区差异"):
    ref = MessageSourceRef(state.run.run_id, state.run.input_record_id)
    return _response(content=json.dumps(_summary_v2({
        "text": summary,
        "source_refs": [ref.to_dict()],
    }), ensure_ascii=False))


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


def test_threshold_compacts_oldest_closed_run_and_reestimates_request(tmp_path, monkeypatch):
    store, coordinator, _unused_session, _unused_run = _app(tmp_path)
    session, first, second, target = _history_with_target(coordinator)
    first_state = coordinator.read_run_state(session.session_id, first.run_id)
    _set_capacity_and_estimates(monkeypatch, [81, 75, 45])
    factory = _FakeFactory([
        _summary_response(first_state),
        _response(content="综合结论"),
    ])

    state = _agent(store, coordinator, _registry(), factory).execute_slice(
        session.session_id, target.run_id
    )

    operation = coordinator.read_context_compaction_operation(
        state.provider_request_bindings[0].context_compaction_operation_id
    )
    checkpoint = coordinator.read_session_context_checkpoint(session.session_id)
    summary_request, ordinary_request = factory.client.requests
    assert summary_request.tools == ()
    assert len(summary_request.messages) == 1
    assert operation.status == "completed" and operation.attempt_count == 1
    assert checkpoint is not None and checkpoint.covered_run_id == first.run_id
    assert checkpoint.summary_contract_version == 2
    assert checkpoint.summary["facts"][0]["text"] == "已确认需要对比销售趋势和地区差异"
    assert operation.request_binding["summary_contract_version"] == 2
    assert state.provider_request_bindings[0].context_projection == "checkpoint"
    assert state.provider_request_bindings[0].context_checkpoint_revision == checkpoint.revision
    assert state.provider_request_bindings[0].context_estimate == ContextEstimate(45, 100)
    assert any("自动摘要" in instruction.content for instruction in ordinary_request.instructions)
    ordinary_text = json.dumps([message.content for message in ordinary_request.messages], ensure_ascii=False)
    assert "第一轮：分析销售趋势" not in ordinary_text
    assert "第二轮：补充地区对比" in ordinary_text
    assert state.run.status is RunStatus.RUNNING


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
    assert state.provider_request_bindings[0].context_projection == expected_projection
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

    binding = state.provider_request_bindings[0]
    operation = coordinator.read_context_compaction_operation(
        binding.context_compaction_operation_id
    )
    assert binding.context_projection == "fallback"
    assert operation.status == "fallback"
    assert coordinator.read_session_context_checkpoint(session.session_id) is None
    ordinary_text = json.dumps(
        [message.content for message in factory.client.requests[-1].messages],
        ensure_ascii=False,
    )
    assert "第一轮：分析销售趋势" in ordinary_text
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

    assert result.provider_request_bindings[0].context_projection == "fallback"
    assert coordinator.read_session_context_checkpoint(session.session_id) == previous
    full_request_text = json.dumps(
        [message.content for message in second_factory.client.requests[-1].messages],
        ensure_ascii=False,
    )
    assert "第一轮：分析销售趋势" in full_request_text
    if missing_asset:
        assert len(second_factory.client.requests) == 1
        operation = coordinator.read_context_compaction_operation(
            result.provider_request_bindings[0].context_compaction_operation_id
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
    assert operation_id.attempt_count == 1
    original_binding = operation_id.request_binding

    reopened = FiguraRunStore(tmp_path)
    restarted_coordinator = RunCoordinator(reopened, coordinator._provider_factory)
    if changed_asset:
        from figura.agent.prompting import loader
        original = loader._load_asset
        monkeypatch.setattr(loader, "_load_asset", lambda asset: original(asset) + "\n新增摘要指导" if asset == "compaction.md" else original(asset))
    restarted_factory = _FakeFactory(
        ([] if changed_asset else [_summary_response(first_state)]) + [_response(content="完成")]
    )
    result = _agent(reopened, restarted_coordinator, _registry(), restarted_factory).execute_slice(
        session.session_id, target.run_id
    )
    resumed_operation = restarted_coordinator.read_context_compaction_operation(
        operation_id.operation_id
    )

    assert resumed_operation.request_binding == original_binding
    if changed_asset:
        assert resumed_operation.status == "fallback"
        assert resumed_operation.failure_code == "summary_binding_mismatch"
        assert resumed_operation.attempt_count == 1
        assert result.provider_request_bindings[0].context_projection == "fallback"
        assert coordinator.read_session_context_checkpoint(session.session_id) is None
        assert len(restarted_factory.client.requests) == 1
    else:
        assert resumed_operation.status == "completed"
        assert resumed_operation.attempt_count == 2
        assert result.provider_request_bindings[0].context_projection == "checkpoint"


def _break_compaction_asset(monkeypatch):
    from figura.agent.prompting import loader
    original = loader._load_asset

    def load(asset):
        if asset == "compaction.md":
            raise loader.PromptAssetError("compaction.md unavailable")
        return original(asset)

    monkeypatch.setattr(loader, "_load_asset", load)


def test_unavailable_compaction_asset_falls_back_without_summary_dispatch(tmp_path, monkeypatch):
    store, coordinator, _session, _run = _app(tmp_path)
    session, _first, _second, target = _history_with_target(coordinator)
    _set_capacity_and_estimates(monkeypatch, [90, 80, 90])
    _break_compaction_asset(monkeypatch)
    factory = _FakeFactory([_response(content="完整历史回答")])
    state = _agent(store, coordinator, _registry(), factory).execute_slice(session.session_id, target.run_id)
    binding = state.provider_request_bindings[0]
    operation = coordinator.read_context_compaction_operation(binding.context_compaction_operation_id)
    assert operation.failure_code == "invalid_summary_input"
    assert operation.attempt_count == 0 and operation.request_binding is None
    assert len(factory.client.requests) == 1
    assert coordinator.read_session_context_checkpoint(session.session_id) is None


def test_compaction_asset_change_updates_request_prompt_digest(tmp_path, monkeypatch):
    from figura.agent.prompting import loader

    _store, coordinator, _session, _run = _app(tmp_path)
    session, first, _second, target = _history_with_target(coordinator)
    current = coordinator.read_run_state(session.session_id, target.run_id)
    sources = (coordinator.read_run_state(session.session_id, first.run_id),)
    builder = _agent(_store, coordinator, _registry(), _FakeFactory([]))._requests
    before, refs = builder.build_summary_request(current, sources, None)
    assert "previous_summary_contract_version" not in json.loads(before.messages[0].content)
    assert before.asset_contract["registry_version"] == "context-compaction-v2"
    original = loader._load_asset
    monkeypatch.setattr(loader, "_load_asset", lambda asset: original(asset) + "\n新增摘要指导")
    after, new_refs = builder.build_summary_request(current, sources, None)
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
    )
    payload = json.loads(request.messages[0].content)
    assert "previous_summary_contract_version" not in payload
    assert payload["previous_source_refs"] == [old_ref.to_dict()]
    assert payload["previous_summary"]["items"][0]["text"] == "旧摘要"
    assert [run["run_id"] for run in payload["source_runs"]] == [second.run_id]
    assert old_ref in allowed_refs
    assert MessageSourceRef(second.run_id, second.input_record_id) in allowed_refs


def test_transient_summary_failure_retries_the_same_internal_provider_request(tmp_path, monkeypatch):
    import figura.agent.executor as executor_module

    monkeypatch.setattr(
        executor_module,
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
        result.provider_request_bindings[0].context_compaction_operation_id
    )
    assert operation.status == "completed"
    assert operation.attempt_count == 2
    assert len(factory.client.requests) == 3
    assert factory.client.requests[0] == factory.client.requests[1]
    assert len(result.provider_attempts) == 1


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
    binding = waiting.provider_request_bindings[0]
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
        assert completed.provider_request_bindings == (binding,)
        assert retry_factory.client.requests == []
        operation = restarted_coordinator.read_context_compaction_operation(binding.context_compaction_operation_id)
        assert operation.attempt_count == 1
    else:
        assert completed.run.status is RunStatus.COMPLETED, {
            "terminal_code": completed.run.terminal_code,
            "attempts": [(item.status.value, item.failure_code) for item in completed.provider_attempts],
            "prepared": len(retry_factory.client.prepared_requests),
            "dispatched": len(retry_factory.client.requests),
        }
        assert completed.provider_request_bindings == (binding,)
        assert len(retry_factory.client.requests) == 1
        assert any("自动摘要" in item.content for item in retry_factory.client.requests[0].instructions)
        operation = restarted_coordinator.read_context_compaction_operation(
            binding.context_compaction_operation_id
        )
        assert operation.attempt_count == 1

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
