"""Offline checks for paired history experiments; never invoke a real Provider."""
from dataclasses import replace
import json

import pytest

from scripts.evaluate_figura_context_ablation import (
    CASE_NAMES, ROOT, aggregate, answer_value, content_answer, correct_answer,
    model_answer, question_state, seed, source_recovery, tool_source_recovery,
)
from figura.agent.request import AgentRequestBuilder
from figura.bootstrap import create_application
from figura.memory.retrieval import SessionHistorySearch
from figura.providers import (
    FinishReason, MODEL_IDS, MessageRole, ProviderFactory, ProviderId,
    ProviderResponse, ProviderToolCall,
)
from figura.runtime.records import SessionContextCheckpoint
from figura.tools import ToolRuntime


@pytest.fixture
def application(tmp_path):
    factory = ProviderFactory.from_env({
        "FIGURA_DEEPSEEK_API_KEY": "offline-fixture",
        "FIGURA_DEEPSEEK_THINKING_MODE": "false",
        "FIGURA_DEEPSEEK_REASONING_EFFORT": "none",
    })
    app = create_application(ROOT, data_dir=tmp_path, provider_factory=factory)
    app.close()  # Stop scanning before fixtures create a running Run.
    return app


@pytest.mark.parametrize("case", CASE_NAMES)
def test_gold_sources_recover_latest_decisions_and_detail_without_reexecution(application, case):
    state, prior, facts, refs, _digest = seed(application, case, ProviderId.DEEPSEEK)
    history = SessionHistorySearch(application.coordinator, application.execution_state)
    before = application.coordinator.read_run_state(state.run.session_id, state.run.run_id)
    result = source_recovery(history, state, facts, refs)
    assert len(result) == 10 and all(item["recovered"] for item in result)
    registry = application.dispatcher._executor._tools.registry
    tool_result = tool_source_recovery(ToolRuntime(registry), state, facts, refs)
    assert all(item["recovered"] for item in tool_result)
    assert sum(item["fallback_used"] for item in tool_result) == 1
    assert application.coordinator.read_run_state(state.run.session_id, state.run.run_id) == before
    detail = next(f for f in facts if f.id == "detail")
    assert refs[detail.id]["run_id"] == prior[4].run.run_id
    assert float(detail.expected) != 399.0  # Historical detail differs from the explicitly corrected record.


def test_paired_projection_keeps_question_identical_and_hides_old_detail(application):
    state, prior, facts, refs, _digest = seed(application, "dense_observations", ProviderId.DEEPSEEK)
    fact = next(f for f in facts if f.id == "detail")
    target = question_state(state, fact)
    registry = application.dispatcher._executor._tools.registry
    builder = AgentRequestBuilder(application.execution_state, application.execution_images)
    last = prior[-2]
    checkpoint = SessionContextCheckpoint(state.run.session_id, 1, last.run.run_id, last.run.ordinal,
        last.checkpoint.last_committed_record_sequence, last.checkpoint.last_committed_tool_sequence, 2,
        {"facts": [{"text": "详细数据可按来源读取。", "source_refs": [refs[fact.id]]}]})
    full = builder.build(target, registry, prior)
    compact = builder.build(target, registry, prior, context_checkpoint=checkpoint)
    assert full.tools == compact.tools
    assert full.options == compact.options
    assert full.messages[-1] == compact.messages[-1]
    assert fact.question in full.messages[-1].content
    assert full.instructions[0:2] == compact.instructions[0:2]
    full_text = json.dumps([m.content for m in full.messages], ensure_ascii=False)
    compact_text = json.dumps([m.content for m in compact.messages], ensure_ascii=False)
    assert 'D004-068' in full_text
    assert fact.expected in full_text
    assert fact.expected not in compact_text
    assert prior[-1].run.ordinal > checkpoint.covered_run_ordinal


def test_model_loop_reads_detail_and_counts_each_actual_request(application):
    state, prior, facts, refs, _digest = seed(application, "dense_observations", ProviderId.DEEPSEEK)
    fact = next(f for f in facts if f.id == "detail")
    registry = application.dispatcher._executor._tools.registry
    builder = AgentRequestBuilder(application.execution_state, application.execution_images)
    request = builder.build(question_state(state, fact), registry, prior)
    real_client = application.providers.create(ProviderId.DEEPSEEK, MODEL_IDS[ProviderId.DEEPSEEK])
    prepared_messages = []

    class OfflineClient:
        def prepare(self, request):
            prepared_messages.append(request.messages)
            return real_client.prepare(request)

        def dispatch(self, prepared):
            if len(prepared_messages) == 1:
                call = ProviderToolCall("read-detail", "read_history", json.dumps({
                    "reference": refs[fact.id], "selector": {"field_path": fact.pointer}}))
                return ProviderResponse(ProviderId.DEEPSEEK, real_client.model_id, "", (call,), FinishReason.TOOL_CALLS)
            observation = json.loads(prepared.request.messages[-1].content)
            if len(prepared_messages) == 2:
                assert observation["outcome"] == "failed"  # Existing read tool schema rejects scalar numbers.
                call = ProviderToolCall("read-detail-row", "read_history", json.dumps({
                    "reference": refs[fact.id], "selector": {"field_path": "/result/rows/68"}}))
                return ProviderResponse(ProviderId.DEEPSEEK, real_client.model_id, "", (call,), FinishReason.TOOL_CALLS)
            value = observation["result"]["content"]["value"]
            return ProviderResponse(ProviderId.DEEPSEEK, real_client.model_id,
                json.dumps({"answer": str(value)}), (), FinishReason.STOP)

    result = model_answer(OfflineClient(), ToolRuntime(registry), state, request, fact, 3)
    assert result["correct"] and len(result["rounds"]) == 3
    assert result["tool_calls"][0]["name"] == "read_history"
    assert [call["outcome"] for call in result["tool_calls"]] == ["failed", "succeeded"]
    assert prepared_messages[-1][-1].role is MessageRole.TOOL
    assert result["rounds"][1]["estimated_input_tokens"] > result["rounds"][0]["estimated_input_tokens"]
    assert application.coordinator.read_run_state(state.run.session_id, state.run.run_id).tool_facts == ()


def test_aggregate_keeps_missing_answer_and_usage_unmeasured():
    report = {"cases": [{"source_recovery": [], "repetitions": [{"questions": [
        {"full_input_tokens": 100, "summary_input_tokens": 30}]}]}]}
    summary = aggregate(report)
    assert summary["weighted_initial_reduction_percent"] == 70
    assert summary["full"]["questions"] == 0
    assert summary["summary"]["usage_complete"] is False


def test_summary_rejection_is_counted_as_zero_saving_fallback():
    report = {"cases": [{"source_recovery": [], "repetitions": [
        {"summary_status": "validated", "questions": [{"full_input_tokens": 100, "summary_input_tokens": 30}]},
        {"summary_status": "invalid_contract", "questions": [{"full_input_tokens": 100, "summary_input_tokens": 100}]},
    ]}]}
    summary = aggregate(report)
    assert summary["weighted_initial_reduction_percent"] == 35
    assert summary["validated_summary_initial_reduction_percent"] == 70
    assert summary["summary_generation"]["validated"] == 1
    assert summary["summary_generation"]["contract_rejections"] == 1


def test_cumulative_provider_usage_includes_summary_generation():
    usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    report = {"cases": [{"source_recovery": [], "repetitions": [{
        "summary_status": "validated",
        "summary_usage": usage,
        "questions": [{
            "full_input_tokens": 100,
            "summary_input_tokens": 40,
            "full": {"correct": True, "status": "answered", "tool_calls": [], "rounds": [
                {"estimated_input_tokens": 100, "usage": usage}], "raw_answer": '{"answer":"x"}'},
            "summary": {"correct": True, "status": "answered", "tool_calls": [], "rounds": [
                {"estimated_input_tokens": 40, "usage": usage}], "raw_answer": '{"answer":"x"}'},
        }],
    }]}]}

    summary = aggregate(report)

    assert summary["cumulative_provider_usage_including_summary_generation"] == {
        "prompt_tokens": 30,
        "completion_tokens": 6,
        "total_tokens": 36,
        "usage_complete": True,
    }


def test_dynamic_summary_target_is_rendered_and_bound_to_prompt_digest(application):
    state, prior, _facts, _refs, _digest = seed(
        application, "repeated_requirements", ProviderId.DEEPSEEK
    )
    registry = application.dispatcher._executor._tools.registry
    builder = AgentRequestBuilder(application.execution_state, application.execution_images)
    selected = prior[:-1]
    request, _allowed = builder.build_summary_request(
        state, selected, None,
        context_capacity_tokens=200_000,
        summary_budget_tokens=20_000,
    )
    larger, _larger_allowed = builder.build_summary_request(
        state, selected, None,
        context_capacity_tokens=1_000_000,
        summary_budget_tokens=100_000,
    )

    assert request.asset_contract["prompt_digest"] != larger.asset_contract["prompt_digest"]
    assert request.asset_contract["registry_digest"] == larger.asset_contract["registry_digest"]
    assert request.messages == larger.messages
    assert "200000 tokens" in request.instructions[-1].content
    assert "20000 tokens" in request.instructions[-1].content
    assert "1000000 tokens" in larger.instructions[-1].content
    assert "100000 tokens" in larger.instructions[-1].content
    assert "不要为接近目标而重复或扩写" in request.instructions[-1].content


def test_content_audit_distinguishes_format_violations_from_wrong_facts():
    numeric = '{"answer":1}'
    preamble = '较晚确认采用分组。\n{"answer":"分组"}'
    assert answer_value(numeric) is None
    assert correct_answer(content_answer(numeric), "1")
    assert answer_value(preamble) is None
    assert correct_answer(content_answer(preamble), "分组")
    assert not correct_answer(content_answer('{"answer":"堆叠"}'), "分组")
    assert content_answer('{"answer":true}') is None
