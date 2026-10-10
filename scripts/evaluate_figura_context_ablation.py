"""Paired synthetic-history experiment using production requests and history tools.

This is an intervention on request projection, not a test of automatic threshold
triggering or a full durable Agent/Gateway run. Real summaries are never replaced
with handwritten summaries. Only generated fixtures are sent to the provider.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import time

from dotenv import load_dotenv

from figura.agent.context_compaction import (
    calculate_context_history_budgets,
    eligible_compaction_runs,
    select_compaction_coverage,
    validate_summary_response,
)
from figura.agent.request import AgentRequestBuilder
from figura.bootstrap import create_application
from figura.memory.retrieval import SessionHistorySearch
from figura.providers import (
    FinishReason, MODEL_IDS, MessageRole, ProviderFactory, ProviderId,
    ProviderMessage, ProviderResponse, ProviderToolCall,
)
from figura.providers.config import ProviderSettings
from figura.providers.errors import ProviderCallError
from figura.providers.token_estimation import estimate_text_tokens
from figura.runtime.models import RunCreateRequest
from figura.runtime.records import SessionContextCheckpoint
from figura.runtime.tool_execution import DurableToolExecutor
from figura.shared.source_refs import MessageSourceRef, ToolResultSourceRef
from figura.shared.json_schema import canonical_json_dumps
from figura.tools import ReplayEffect, ToolDefinition, ToolInvocation, ToolRegistry, ToolRuntime
from figura.tools.contracts import ToolContext


ROOT = Path(__file__).resolve().parents[1]
CASE_NAMES = ("repeated_requirements", "dense_observations", "iterative_revisions")


@dataclass(frozen=True)
class Fact:
    id: str
    question: str
    expected: str
    query: str
    round: int
    source: str = "user"
    pointer: str | None = None


def fixture(case: str) -> tuple[list[dict], list[Fact]]:
    """Gold labels are fixed before any summary/model inference."""
    if case not in CASE_NAMES:
        raise ValueError("unknown fixture")
    offset = CASE_NAMES.index(case) * 1000
    facts = [
        Fact("unit", "最终采用的金额单位是什么？只填单位。", "万元", "金额单位", 7),
        Fact("color", "最终指定给华北系列的颜色代码是什么？只填十六进制代码。", "#2F6B9A", "华北 配色", 8),
        Fact("precision", "展示数值最终保留几位小数？只填整数。", "1", "小数位", 9),
        Fact("mode", "最终确定柱状图采用分组还是堆叠？只填分组或堆叠。", "分组", "柱状图 方案", 9),
        Fact("correction", "D004-074 记录更正后的销售额是多少？只填数值。", "417.3", "D004-074", 8),
        Fact("detail", "历史数据记录 D004-068 的数值是多少？只填数值。", str(offset + 256.8), "D004-068", 4, "tool", "/result/rows/68/value"),
        Fact("unknown", "D005-019 缺失值应记为什么？只填 null 或 0。", "null", "D005-019", 5),
        Fact("pending", "交互版图表的制作是否已经完成？只填已完成或未完成。", "未完成", "交互版", 6),
        Fact("period", "用户最终确认对比的是哪个季度？只填季度代码。", "2026Q1", "对比季度", 7),
        Fact("proposal", "用户是否接受了助手提出的平滑曲线建议？只填已接受或未接受。", "未接受", "平滑曲线", 9),
    ]
    updates = {
        0: "项目目标是分析地区销售差异并制作静态报告。初始金额单位为元。",
        1: "初始华北配色设想为 #996633，等待后续确认。",
        2: "最初讨论保留两位小数，并考虑堆叠柱状图。当前都只是候选。",
        3: "对比应沿用数据中的区域与季度，不能把累计销售额解释成季度销售额。",
        4: "读取本批结构化数据；D004-074 的旧值暂记为 399.0，后续有更正时以更正为准。",
        5: "D005-019 没有可靠观测，缺失值必须写 null，不能补成 0。",
        6: "交互版图表是用户明确要求的待办，目前未完成；静态草稿完成不等于交互版完成。",
        7: "确认：金额单位改为万元；对比季度最终采用 2026Q1。",
        8: "确认：华北配色改为 #2F6B9A；D004-074 的销售额更正为 417.3 万元，撤销 399.0。",
        9: "最终确认：展示小数位为 1；柱状图方案采用分组。平滑曲线只是助手建议，用户未接受。",
        10: "继续整理报告中的事实与来源；沿用已确认要求，详细数据保持可追溯。",
        11: "保留最近一轮原文：下一步准备交付静态报告，但不宣称交互版已经完成。",
    }
    rounds = []
    for index in range(12):
        count = 80 if case == "dense_observations" else 72
        rows = [{"id": f"D{index:03d}-{j:03d}", "region": ("华北", "华东", "华南")[j % 3],
                 "category": f"渠道{j % 8 + 1}", "value": round(offset + 100 + index * 22.2 + j, 1),
                 "note": "工具候选观察，不等于已审核事实"} for j in range(count)]
        if index == 4:
            rows[68]["value"] = offset + 256.8
        discussion = []
        for j in range(12 if case == "repeated_requirements" else 5):
            item = rows[j]
            discussion.append(
                f"讨论{j+1}：{item['region']}的{item['category']}候选观测为{item['value']}；"
                "需要区分工具观察和用户确认，沿用当前有效单位，标签不应遮挡数据，"
                "未知值不补零；有后续更正时回查来源，不将旧方案当作最终决定。"
            )
        if case == "iterative_revisions":
            discussion.append("多轮修订时须核对决定的时间顺序；旧颜色、旧精度和旧值均不是最终版本。")
        rounds.append({"user": updates[index], "rows": rows,
                       "assistant": "本轮整理：" + updates[index] + "\n" + "\n".join(discussion)})
    return rounds, facts


def _json(value) -> str:
    return canonical_json_dumps(value)


def reduction(before: int, after: int) -> float:
    if before <= 0:
        raise ValueError("baseline must be positive")
    return (before - after) / before * 100


def answer_value(text: str) -> str | None:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or set(value) != {"answer"} or not isinstance(value["answer"], str):
        return None
    return value["answer"].strip()


def correct_answer(answer: str | None, expected: str) -> bool:
    if answer is None:
        return False
    if answer.startswith("#") or expected.startswith("#"):
        return answer.upper() == expected.upper()
    try:
        return float(answer) == float(expected)
    except ValueError:
        return answer == expected


def content_answer(text: str) -> str | None:
    """Auxiliary value audit: last answer JSON, permitting preamble/numeric types.

    Does not evaluate arbitrary prose or summary entailment. Strict output-format
    scoring remains separate in answer_value/model_answer.
    """
    decoder = json.JSONDecoder()
    candidates = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, dict) and set(value) == {"answer"}:
            candidates.append(value["answer"])
    if not candidates:
        return None
    value = candidates[-1]
    if value is None:
        return "null"
    return str(value).strip() if type(value) in (str, int, float) else None


def commit(coordinator, session_id, run_id, response, registry_version=None):
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(session_id, run_id, state.checkpoint.revision)
    claimed = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(session_id, run_id, claimed.checkpoint.revision,
        response, provider_attempt_id=attempt.attempt_id, registry_version=registry_version)
    return coordinator.read_run_state(session_id, run_id)


def seed(application, case: str, provider: ProviderId):
    coordinator = application.coordinator
    store = coordinator._store  # Experiment-only fixture seeding, not an application API.
    session = coordinator.create_session()
    rounds, facts = fixture(case)
    states = []
    for index, item in enumerate(rounds):
        run = coordinator.create_run(RunCreateRequest(session.session_id, item["user"],
            provider.value, MODEL_IDS[provider], f"fixture-{case}-{index}"))
        # This tool produces synthetic tabular observations, not image measurements.
        definition = ToolDefinition("fixture_table_observation", "合成历史中的表格观察。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            {"type": "object", "properties": {"rows": {"type": "array", "items": {"type": "object"}}},
             "required": ["rows"], "additionalProperties": False},
            ReplayEffect.REPLAY_SAFE, lambda _c, _a, rows=item["rows"]: {"rows": rows})
        fixture_registry = ToolRegistry("context-ablation-fixtures-v1", (definition,))
        call_id = f"fixture-table-{index}"
        commit(coordinator, session.session_id, run.run_id,
            ProviderResponse(provider, MODEL_IDS[provider], "读取候选数据。",
                (ProviderToolCall(call_id, definition.name, "{}"),), FinishReason.TOOL_CALLS),
            fixture_registry.version)
        DurableToolExecutor(store, fixture_registry).execute_pending(session.session_id, run.run_id)
        state = commit(coordinator, session.session_id, run.run_id,
            ProviderResponse(provider, MODEL_IDS[provider], item["assistant"], (), FinishReason.STOP))
        coordinator.complete_run(session.session_id, run.run_id, state.checkpoint.revision)
        states.append(coordinator.read_run_state(session.session_id, run.run_id))
    target = coordinator.create_run(RunCreateRequest(session.session_id,
        "继续核对历史事实。", provider.value, MODEL_IDS[provider], "experiment-target"))
    target_state = coordinator.read_run_state(session.session_id, target.run_id)
    refs = {fact.id: (ToolResultSourceRef(states[fact.round].run.run_id, f"fixture-table-{fact.round}")
            if fact.source == "tool" else MessageSourceRef(states[fact.round].run.run_id,
                states[fact.round].run.input_record_id)).to_dict() for fact in facts}
    return target_state, tuple(states), facts, refs, sha256(_json(rounds).encode()).hexdigest()


def source_recovery(history, state, facts, refs):
    results = []
    for fact in facts:
        cursor = None
        rank = 0
        found = None
        while True:
            page = history.search(state.run.session_id, state.run.run_id, fact.query,
                                  cursor=cursor, page_size=20)
            for match in page["matches"]:
                rank += 1
                if match["reference"] == refs[fact.id]:
                    found = match["reference"]
                    break
            if found is not None or not page["has_more"]:
                break
            cursor = page["next_cursor"]
        content = None
        if found is not None:
            selector = {"field_path": fact.pointer} if fact.pointer else None
            content = history.read(state.run.session_id, state.run.run_id, found, selector=selector)["content"]
        recovered = (str(content) == fact.expected if fact.pointer else
                     content is not None and fact.expected in _json(content))
        results.append({"id": fact.id, "query": fact.query, "source_found": found is not None,
                        "source_rank": rank if found else None, "recovered": recovered})
    return results


def usage_dict(response):
    return asdict(response.usage) if response.usage is not None else None


def tool_source_recovery(runtime, state, facts, refs):
    """Probe the real model-facing contract, including object-read fallback."""
    results = []
    for fact in facts:
        call_id = f"probe-{fact.id}"
        context = ToolContext(state.run.run_id, state.run.session_id, call_id)
        arguments = {"reference": refs[fact.id]}
        if fact.pointer:
            arguments["selector"] = {"field_path": fact.pointer}
        execution = runtime.invoke(ToolInvocation(call_id, "read_history", _json(arguments)), context)
        result = {"id": fact.id, "initial_outcome": execution.outcome.value,
                  "initial_error": execution.error.code if execution.error else None, "fallback_used": False}
        if execution.result is None and fact.pointer:
            parent, _slash, leaf = fact.pointer.rpartition("/")
            arguments["selector"] = {"field_path": parent}
            fallback = runtime.invoke(ToolInvocation(call_id, "read_history", _json(arguments)), context)
            result["fallback_used"] = True
            value = fallback.result["content"].get(leaf) if fallback.result else None
            result["recovered"] = value is not None and str(value) == fact.expected
        else:
            value = execution.result["content"] if execution.result else None
            result["recovered"] = value is not None and fact.expected in _json(value)
        results.append(result)
    return results


def question_state(state, fact):
    question = fact.question + '\n根据历史作答，需要时可使用历史工具。只输出 JSON：{"answer":"答案"}。'
    return replace(state, records=tuple(replace(record, payload=replace(record.payload, text=question))
        if record.record_id == state.run.input_record_id else record for record in state.records))


def model_answer(client, runtime, state, request, fact, max_rounds):
    """Independent model-led read-only loop; no forced calls or gold answers injected."""
    start = time.monotonic()
    rounds = []
    tool_calls = []
    for index in range(max_rounds):
        try:
            prepared = client.prepare(request)
            response = client.dispatch(prepared)
        except ProviderCallError as error:
            return {"id": fact.id, "correct": False, "status": "provider_failure",
                    "failure_code": error.failure.failure_code.value,
                    "http_status": error.failure.http_status, "rounds": rounds,
                    "tool_calls": tool_calls, "seconds": time.monotonic() - start}
        rounds.append({"estimated_input_tokens": prepared.context_estimate.input_tokens,
                       "usage": usage_dict(response), "finish_reason": response.finish_reason.value})
        if not response.tool_calls:
            answer = answer_value(response.assistant_content)
            return {"id": fact.id, "expected": fact.expected, "answer": answer,
                    "correct": response.finish_reason is FinishReason.STOP and correct_answer(answer, fact.expected),
                    "raw_answer": response.assistant_content,
                    "status": "answered" if response.finish_reason is FinishReason.STOP else "incomplete",
                    "rounds": rounds, "tool_calls": tool_calls, "seconds": time.monotonic() - start}
        messages = list(request.messages)
        messages.append(ProviderMessage(MessageRole.ASSISTANT, response.assistant_content,
                                       response.tool_calls, continuation=response.continuation))
        for call in response.tool_calls:
            if call.name not in {"search_history", "read_history"}:
                result = {"outcome": "failed", "error": {"code": "experiment_read_only",
                          "message": "本实验仅执行历史搜索与精确读取；请回答事实问题。"}}
            else:
                execution = runtime.invoke(ToolInvocation(call.call_id, call.name, call.arguments),
                    ToolContext(state.run.run_id, state.run.session_id, call.call_id))
                result = {"outcome": execution.outcome.value, "result": execution.result,
                          "error": asdict(execution.error) if execution.error else None}
            tool_calls.append({"name": call.name, "arguments": json.loads(call.arguments),
                               "outcome": result["outcome"]})
            messages.append(ProviderMessage(MessageRole.TOOL, _json(result), tool_call_id=call.call_id))
        request = replace(request, messages=tuple(messages))
    return {"id": fact.id, "expected": fact.expected, "answer": None, "correct": False,
            "status": "round_limit", "rounds": rounds, "tool_calls": tool_calls,
            "seconds": time.monotonic() - start}


def aggregate(report):
    pairs = [pair for case in report["cases"] for repetition in case["repetitions"]
             for pair in repetition.get("questions", [])]
    before = sum(pair["full_input_tokens"] for pair in pairs)
    after = sum(pair["summary_input_tokens"] for pair in pairs)
    results = {"paired_questions": len(pairs), "full_initial_input_tokens": before,
               "summary_initial_input_tokens": after,
               "weighted_initial_reduction_percent": reduction(before, after) if before else None}
    for arm in ("full", "summary"):
        answers = [pair[arm] for pair in pairs if arm in pair]
        usages = [round_["usage"] for answer in answers for round_ in answer["rounds"]]
        results[arm] = {"questions": len(answers), "correct": sum(a["correct"] for a in answers),
            "content_correct": sum(a.get("status") == "answered" and correct_answer(
                content_answer(a.get("raw_answer", "")), a.get("expected", "")) for a in answers),
            "failed_requests": sum(a["status"] == "provider_failure" for a in answers),
            "retrieval_questions": sum(bool(a["tool_calls"]) for a in answers),
            "tool_calls": sum(len(a["tool_calls"]) for a in answers),
            "estimated_input_tokens_all_rounds": sum(r["estimated_input_tokens"] for a in answers for r in a["rounds"]),
            "provider_prompt_tokens": sum(u["prompt_tokens"] or 0 for u in usages if u),
            "provider_completion_tokens": sum(u["completion_tokens"] or 0 for u in usages if u),
            "usage_complete": bool(usages) and all(u is not None and u["prompt_tokens"] is not None
                                  and u["completion_tokens"] is not None for u in usages)}
    results["source_recovery"] = {"facts": sum(len(c["source_recovery"]) for c in report["cases"]),
        "recovered": sum(r["recovered"] for c in report["cases"] for r in c["source_recovery"])}
    tool_probes = [probe for case in report["cases"] for probe in case.get("tool_source_recovery", [])]
    results["tool_source_recovery"] = {"facts": len(tool_probes),
        "recovered": sum(p["recovered"] for p in tool_probes),
        "fallback_reads": sum(p["fallback_used"] for p in tool_probes)}
    repetitions = [r for c in report["cases"] for r in c["repetitions"]]
    summary_usages = [r["summary_usage"] for r in repetitions
                      if r.get("summary_usage") is not None]
    results["summary_generation"] = {"attempts": len(repetitions),
        "validated": sum(r.get("summary_status") == "validated" for r in repetitions),
        "contract_rejections": sum(r.get("summary_status") == "invalid_contract" for r in repetitions),
        "provider_failures": sum(r.get("summary_status") == "provider_failure" for r in repetitions),
        "provider_prompt_tokens": sum(u["prompt_tokens"] or 0 for u in summary_usages),
        "provider_completion_tokens": sum(u["completion_tokens"] or 0 for u in summary_usages)}
    all_usages = [usage_dict for arm in ("full", "summary")
                  for answer in [pair[arm] for pair in pairs if arm in pair]
                  for usage_dict in (round_["usage"] for round_ in answer["rounds"])
                  if usage_dict is not None]
    all_usages.extend(summary_usages)
    results["cumulative_provider_usage_including_summary_generation"] = {
        "prompt_tokens": sum(item["prompt_tokens"] or 0 for item in all_usages),
        "completion_tokens": sum(item["completion_tokens"] or 0 for item in all_usages),
        "total_tokens": sum(item["total_tokens"] or 0 for item in all_usages),
        "usage_complete": bool(all_usages) and all(
            item["prompt_tokens"] is not None and item["completion_tokens"] is not None
            for item in all_usages
        ),
    }
    successful_pairs = [p for r in repetitions if r.get("summary_status") == "validated" for p in r["questions"]]
    valid_before = sum(p["full_input_tokens"] for p in successful_pairs)
    valid_after = sum(p["summary_input_tokens"] for p in successful_pairs)
    results["validated_summary_initial_reduction_percent"] = reduction(valid_before, valid_after) if valid_before else None
    return results


def write_report(path, report):
    report["aggregate"] = aggregate(report)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=[p.value for p in ProviderId], default="deepseek")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--cases", nargs="+", choices=CASE_NAMES, default=list(CASE_NAMES))
    parser.add_argument("--question-limit", type=int, default=10)
    parser.add_argument(
        "--capacities", nargs="+", type=int,
        help="Evaluate production 10%%/10%% history budgets at these Provider capacities.",
    )
    parser.add_argument("--skip-answers", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Only source recovery and full request estimates; no invented summary")
    parser.add_argument("--analyze-existing", type=Path, help="Recalculate metrics from saved responses, without network requests")
    parser.add_argument("--output", type=Path, default=ROOT / ".figura/evaluation/context-ablation/report.json")
    args = parser.parse_args()
    if min(args.repetitions, args.workers, args.max_rounds, args.question_limit) < 1:
        parser.error("counts must be positive")
    if args.capacities is not None and any(value <= 0 for value in args.capacities):
        parser.error("capacities must be positive")
    if args.analyze_existing is not None:
        report = json.loads(args.analyze_existing.read_text(encoding="utf-8"))
        report["analysis"] = {"method": "strict format scoring plus last-answer JSON scalar-value audit",
                              "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_report(args.output, report)
        print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
        return
    load_dotenv(ROOT / ".env", override=False)
    provider = ProviderId(args.provider)
    settings = ProviderSettings.from_env()
    profiles = dict(settings.profiles)
    # Fixed non-thinking experiment conditions avoid synthetic history continuations.
    profiles[provider] = replace(profiles[provider], thinking_mode=False, reasoning_effort="none"
                                if provider is not ProviderId.MIMO else None,
                                max_completion_tokens=8192, timeout_seconds=60)
    if args.offline:
        profiles[provider] = replace(profiles[provider], api_key="offline-fixture",
                                    base_url="https://offline.example.test/v1", configuration_error=None)
    factory = ProviderFactory(ProviderSettings(profiles))
    path = args.output.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    application = create_application(ROOT, data_dir=path.parent / f"snapshot-{stamp}", provider_factory=factory)
    # Stop background recovery before any synthetic fixture is created.
    executor = application.dispatcher._executor
    registry = executor._tools.registry
    application.close()
    builder = AgentRequestBuilder(application.execution_state, application.execution_images)
    history = SessionHistorySearch(application.coordinator, application.execution_state)
    runtime = ToolRuntime(registry)
    evidence_files = [Path(__file__).resolve(), ROOT / "src/figura/agent/request.py",
        ROOT / "src/figura/agent/context_compaction.py", ROOT / "src/figura/memory/retrieval.py",
        ROOT / "src/figura/providers/token_estimation.py",
        *sorted((ROOT / "src/figura/agent/prompting/assets").glob("*.md"))]
    report = {"scope": "synthetic paired request projection and independent model-led read-only history loop; not full durable Agent/Gateway evaluation",
        "started_at": stamp, "python": platform.python_version(),
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "provider": provider.value, "model": MODEL_IDS[provider], "thinking_mode": False,
        "reasoning_effort": profiles[provider].reasoning_effort, "max_completion_tokens": 8192,
        "repetitions": args.repetitions, "max_rounds": args.max_rounds, "registry_version": registry.version,
        "estimator": "tiktoken/o200k_base", "images": 0, "automatic_threshold_tested": False,
        "source_sha256": {str(file.relative_to(ROOT)): sha256(file.read_bytes()).hexdigest() for file in evidence_files},
        "snapshot_directory": f"snapshot-{stamp}", "offline": args.offline, "cases": []}
    for name in args.cases:
        state, prior, facts, refs, fixture_digest = seed(application, name, provider)
        facts = facts[:args.question_limit]
        capacities = args.capacities or [None]
        for capacity in capacities:
            budgets = calculate_context_history_budgets(capacity) if capacity is not None else None
            if capacity is not None and budgets is None:
                raise RuntimeError(f"invalid selected context capacity: {capacity}")
            if budgets is None:
                # Preserve the original fixed-history ablation: summarize all but
                # the newest Run, independently of the production partial-Run selector.
                selected = eligible_compaction_runs(prior[:-1], 0)
                coverage = None
            else:
                coverage = select_compaction_coverage(
                    prior, None, budgets.raw_history_tokens
                )
                selected = coverage.selected_run_states if coverage is not None else ()
            for variant in ("production_dynamic_summary_target",):
                capacity_profiles = dict(profiles)
                if capacity is not None:
                    capacity_profiles[provider] = replace(
                        capacity_profiles[provider], context_window_tokens=capacity
                    )
                capacity_client = ProviderFactory(
                    ProviderSettings(capacity_profiles)
                ).create(provider, MODEL_IDS[provider])
                case = {
                    "name": name,
                    "capacity_tokens": capacity,
                    "raw_history_budget_tokens": budgets.raw_history_tokens if budgets else None,
                    "summary_budget_tokens": budgets.summary_tokens if budgets else None,
                    "prompt_variant": variant,
                    "fixture_sha256": fixture_digest,
                    "history_runs": len(prior),
                    "compacted_runs": len(selected),
                    "coverage": (None if coverage is None else {
                        "run_id": coverage.covered_run_id,
                        "run_ordinal": coverage.covered_run_ordinal,
                        "record_sequence": coverage.covered_record_sequence,
                        "tool_sequence": coverage.covered_tool_sequence,
                    }),
                    "gold_facts": [asdict(f) for f in facts],
                    "source_recovery": source_recovery(history, state, facts, refs),
                    "tool_source_recovery": tool_source_recovery(runtime, state, facts, refs),
                    "repetitions": [],
                }
                report["cases"].append(case)
                full_request = builder.build(state, registry, prior)
                full_prepared = capacity_client.prepare(full_request)
                if full_prepared.context_estimate is None:
                    raise RuntimeError("tiktoken encoding unavailable; no fallback estimate allowed")
                case["full_probe_input_tokens"] = full_prepared.context_estimate.input_tokens
                case["source_recovery_count"] = sum(
                    item["recovered"] for item in case["source_recovery"]
                )
                print(f"{name} capacity={capacity or 'configured'} variant={variant}: "
                      f"full={case['full_probe_input_tokens']} source_recovery="
                      f"{case['source_recovery_count']}/{len(facts)}", flush=True)
                write_report(path, report)
                if args.offline:
                    continue
                if not selected:
                    case["selection_status"] = "no_compaction_coverage"
                    continue
                summary_capacity = capacity_profiles[provider].context_window_tokens
                if type(summary_capacity) is not int or summary_capacity <= 0:
                    raise RuntimeError(
                        "summary generation requires a configured Provider context capacity "
                        "or an explicit --capacities value"
                    )
                summary_budget = summary_capacity // 10
                for rep in range(args.repetitions):
                    entry = {"repetition": rep + 1, "questions": []}
                    case["repetitions"].append(entry)
                    request, allowed = builder.build_summary_request(
                        state, selected, None, coverage=coverage,
                        context_capacity_tokens=summary_capacity,
                        summary_budget_tokens=summary_budget,
                    )
                    prepared = capacity_client.prepare(request)
                    entry["summary_estimated_input_tokens"] = prepared.context_estimate.input_tokens
                    start = time.monotonic()
                    checkpoint = None
                    try:
                        response = capacity_client.dispatch(prepared)
                        summary, source_refs = validate_summary_response(response, provider_id=provider.value,
                            model_id=MODEL_IDS[provider], allowed_refs=allowed, selected_runs=selected)
                    except ProviderCallError as error:
                        entry.update(summary_status="provider_failure", failure_code=error.failure.failure_code.value,
                                     http_status=error.failure.http_status)
                        print(f"{name} capacity={capacity} repeat={rep+1}: summary failed ({entry['failure_code']})", flush=True)
                    except ValueError as error:
                        entry.update(summary_status="invalid_contract", summary_usage=usage_dict(response),
                                     validation_error=str(error), raw_summary=response.assistant_content,
                                     finish_reason=response.finish_reason.value,
                                     continuation_present=response.continuation is not None)
                        print(f"{name} capacity={capacity} repeat={rep+1}: rejected summary, fallback to full ({error})", flush=True)
                    else:
                        summary_json = _json(summary)
                        entry.update(summary_status="validated", summary=summary,
                                     summary_output_estimated_tokens=estimate_text_tokens(summary_json),
                                     summary_usage=usage_dict(response))
                        checkpoint = SessionContextCheckpoint(
                            session_id=state.run.session_id,
                            revision=1,
                            covered_run_id=coverage.covered_run_id if coverage else selected[-1].run.run_id,
                            covered_run_ordinal=coverage.covered_run_ordinal if coverage else selected[-1].run.ordinal,
                            covered_record_sequence=coverage.covered_record_sequence if coverage else selected[-1].checkpoint.last_committed_record_sequence,
                            covered_tool_sequence=coverage.covered_tool_sequence if coverage else selected[-1].checkpoint.last_committed_tool_sequence,
                            summary_contract_version=2,
                            summary=summary,
                            source_refs=source_refs,
                        )
                    entry["summary_seconds"] = time.monotonic() - start
                    entry["source_recovery_after_summary"] = source_recovery(history, state, facts, refs)
                    write_report(path, report)
                    # The identical current Run is projected with/without this checkpoint.
                    jobs = []
                    with ThreadPoolExecutor(max_workers=args.workers) as pool:
                        for index, fact in enumerate(facts):
                            target = question_state(state, fact)
                            requests = {"full": builder.build(target, registry, prior),
                                        "summary": builder.build(target, registry, prior, context_checkpoint=checkpoint)}
                            estimates = {arm: capacity_client.prepare(req).context_estimate.input_tokens for arm, req in requests.items()}
                            pair = {"id": fact.id, "full_input_tokens": estimates["full"],
                                    "summary_input_tokens": estimates["summary"],
                                    "reduction_percent": reduction(estimates["full"], estimates["summary"])}
                            entry["questions"].append(pair)
                            if not args.skip_answers:
                                for arm in ("full", "summary") if (index + rep) % 2 == 0 else ("summary", "full"):
                                    jobs.append((pool.submit(model_answer, capacity_client, runtime, state, requests[arm], fact, args.max_rounds), pair, arm))
                        job_index = {future: (pair, arm) for future, pair, arm in jobs}
                        for future in as_completed(job_index):
                            pair, arm = job_index[future]
                            pair[arm] = future.result()
                            write_report(path, report)
                            result = pair[arm]
                            print(f"{name} capacity={capacity} repeat={rep+1} {pair['id']} {arm}: "
                                  f"correct={result['correct']} tools={len(result['tool_calls'])}", flush=True)
                    entry["status"] = "completed"
                    write_report(path, report)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_report(path, report)
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2), flush=True)
    print(f"Report: {path}", flush=True)


if __name__ == "__main__":
    main()
