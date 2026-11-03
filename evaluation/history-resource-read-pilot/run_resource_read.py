"""Model-led probe for direct read_history calls using a compacted resource index."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from figura.agent.context_compaction import select_compaction_coverage, validate_summary_response
from figura.agent.request import AgentRequestBuilder
from figura.bootstrap import create_application
from figura.charts.chartfigure import parse_chart_figure
from figura.memory.retrieval import SessionHistorySearch, resource_ref_to_dict
from figura.providers import (
    FinishReason, MODEL_IDS, MessageRole, ProviderFactory, ProviderId,
    ProviderMessage, ProviderResponse, ProviderToolCall,
)
from figura.providers.config import ProviderSettings
from figura.providers.errors import ProviderCallError
from figura.runtime.models import RunCreateRequest
from figura.runtime.records import SessionContextCheckpoint
from figura.runtime.tool_execution import DurableToolExecutor
from figura.shared.json_schema import canonical_json_dumps
from figura.shared.source_refs import ToolResultSourceRef
from figura.tools import ReplayEffect, ToolDefinition, ToolInvocation, ToolOutput, ToolRegistry, ToolRuntime
from figura.tools.contracts import ToolContext
from figura.tools.implementations.assemble_chart_figure import assemble_chart_figure_definition
from figura.tools.implementations.extract_text import EXTRACT_TEXT_RESULT_SCHEMA
from figura.tools.implementations.measure_chart import MEASURE_CHART_PARAMETERS_SCHEMA
from figura.tools.implementations.measurement_schema import SOURCE_PARAMETERS
from figura.tools.measurements.contracts import MEASUREMENT_RESULT_SCHEMA
from figura_fixtures import bar_chart_figure, measurement_result


HERE = Path(__file__).resolve().parent
CAPACITY = 100_000
MAX_ROUNDS = 5


def _json(value):
    return canonical_json_dumps(value)


def _commit(coordinator, session_id, run_id, response, registry_version=None):
    state = coordinator.read_run_state(session_id, run_id)
    attempt = coordinator.begin_provider_attempt(session_id, run_id, state.checkpoint.revision)
    state = coordinator.read_run_state(session_id, run_id)
    coordinator.commit_model_response(
        session_id, run_id, state.checkpoint.revision, response,
        provider_attempt_id=attempt.attempt_id, registry_version=registry_version,
    )
    return coordinator.read_run_state(session_id, run_id)


def _seed(app, provider):
    coordinator = app.coordinator
    session = coordinator.create_session("resource direct read pilot")
    output = BytesIO()
    Image.new("RGB", (500, 500), "white").save(output, format="PNG")
    attachment = app.attachments.upload(session.session_id, "synthetic-chart.png", output.getvalue())
    source = coordinator.create_run(RunCreateRequest(
        session.session_id,
        "已对合成图表执行 OCR、测量并组装季度营收图。后续需要时按来源引用精确读取，不要在摘要里复制每条细节。",
        provider.value, MODEL_IDS[provider], "resource-pilot-source", (attachment.attachment_id,),
    ))
    snippets = [
        {"snippet_id": f"snippet-{i:03d}",
         "text": f"Observation {i:03d}: marker CODE-{(i * 7919) % 999983:06d}",
         "bbox_px": [i % 490, (i * 7) % 490, 1, 1], "confidence": 0.93}
        for i in range(1, 401)
    ]
    ocr_value = {
        "source_kind": "attachment", "source_id": attachment.attachment_id,
        "image_size": {"width": 500, "height": 500},
        "coordinate_system": "attachment_px", "available": True,
        "truncated": False, "snippets": snippets,
    }
    measurement_value = measurement_result(
        "bar", source_kind="attachment", source_id=attachment.attachment_id, status="no_evidence",
    )
    measurement_value["warnings"] = [
        "Preview warning one.", "Preview warning two.", "Preview warning three.",
        "Detailed warning token: WARN-7QK-491.",
        "Detailed warning token: WARN-3XM-826.",
    ]
    fixture_registry = ToolRegistry("resource-read-pilot-fixture-v1", (
        ToolDefinition(
            "extract_text", "Synthetic committed OCR result.", SOURCE_PARAMETERS,
            EXTRACT_TEXT_RESULT_SCHEMA, ReplayEffect.REPLAY_SAFE,
            lambda _context, _arguments: ToolOutput(ocr_value),
        ),
        ToolDefinition(
            "measure_chart", "Synthetic committed measurement result.",
            MEASURE_CHART_PARAMETERS_SCHEMA, MEASUREMENT_RESULT_SCHEMA,
            ReplayEffect.REPLAY_SAFE,
            lambda _context, _arguments: ToolOutput(measurement_value),
        ),
        assemble_chart_figure_definition(app.execution_state.for_run),
    ))
    tool_runtime = ToolRuntime(fixture_registry)
    durable_tools = DurableToolExecutor(coordinator._store, fixture_registry, tool_runtime)
    ocr_call, measure_call = "fixture-ocr-7QK491", "fixture-measure-3XM826"
    _commit(coordinator, session.session_id, source.run_id, ProviderResponse(
        provider, MODEL_IDS[provider], "记录合成 OCR 与测量观察。",
        (
            ProviderToolCall(ocr_call, "extract_text", _json({
                "source_kind": "attachment", "source_id": attachment.attachment_id,
            })),
            ProviderToolCall(measure_call, "measure_chart", _json({
                "source_kind": "attachment", "source_id": attachment.attachment_id, "chart_type": "bar",
            })),
        ),
        FinishReason.TOOL_CALLS,
    ), fixture_registry.version)
    durable_tools.execute_pending(session.session_id, source.run_id)
    state = _commit(coordinator, session.session_id, source.run_id, ProviderResponse(
        provider, MODEL_IDS[provider], "OCR 与测量结果已记录。", (), FinishReason.STOP,
    ))
    coordinator.complete_run(session.session_id, source.run_id, state.checkpoint.revision)
    source_state = coordinator.read_run_state(session.session_id, source.run_id)

    figure_run = coordinator.create_run(RunCreateRequest(
        session.session_id, "基于上一轮已记录的测量来源，装配季度营收 Figure。",
        provider.value, MODEL_IDS[provider], "resource-pilot-figure",
    ))
    figure = bar_chart_figure(measurement_ref={"run_id": source.run_id, "call_id": measure_call})
    figure["title"] = "Quarterly Revenue Detail"
    chart = figure["charts"][0]["chart_spec"]
    chart["metadata"]["title"] = "Regional Revenue Series"
    chart["dataset"]["categories"] = [
        {"id": f"period-{i:02d}", "label": f"Period {i:02d}"} for i in range(1, 13)
    ]
    values = [round(100 + i * 17.3, 1) for i in range(1, 13)]
    values[7], values[11] = 817.4, 129.6
    chart["dataset"]["series"][0]["values"] = values
    figure_call = "fixture-figure-9VA204"
    _commit(coordinator, session.session_id, figure_run.run_id, ProviderResponse(
        provider, MODEL_IDS[provider], "装配合成季度营收 Figure。",
        (ProviderToolCall(figure_call, "assemble_chart_figure", _json(figure)),),
        FinishReason.TOOL_CALLS,
    ), fixture_registry.version)
    durable_tools.execute_pending(session.session_id, figure_run.run_id)
    state = _commit(coordinator, session.session_id, figure_run.run_id, ProviderResponse(
        provider, MODEL_IDS[provider], "历史 Figure 已记录，可按引用读取。", (), FinishReason.STOP,
    ))
    coordinator.complete_run(session.session_id, figure_run.run_id, state.checkpoint.revision)
    figure_state = coordinator.read_run_state(session.session_id, figure_run.run_id)

    filler = coordinator.create_run(RunCreateRequest(
        session.session_id, "整理报告版式与交付顺序。",
        provider.value, MODEL_IDS[provider], "resource-pilot-filler",
    ))
    state = _commit(coordinator, session.session_id, filler.run_id, ProviderResponse(
        provider, MODEL_IDS[provider], ("版式整理完成。沿用已确认的交付顺序。 " * 5000),
        (), FinishReason.STOP,
    ))
    coordinator.complete_run(session.session_id, filler.run_id, state.checkpoint.revision)
    filler_state = coordinator.read_run_state(session.session_id, filler.run_id)
    target = coordinator.create_run(RunCreateRequest(
        session.session_id, "核对一项历史资源。",
        provider.value, MODEL_IDS[provider], "resource-pilot-target",
    ))
    target_state = coordinator.read_run_state(session.session_id, target.run_id)
    refs = {
        "ocr": {"kind": "ocr", "run_id": source.run_id, "call_id": ocr_call},
        "measurement": {"kind": "measurement", "run_id": source.run_id, "call_id": measure_call},
        "chart_figure": {"kind": "chart_figure", "run_id": figure_run.run_id, "call_id": figure_call},
    }
    facts = [
        {"id": "ocr-137", "query": "OCR 第137条 Observation marker code",
         "expected": snippets[136]["text"], "kind": "ocr"},
        {"id": "ocr-149", "query": "OCR 第149条 Observation marker code",
         "expected": snippets[148]["text"], "kind": "ocr"},
        {"id": "measurement-warning-4", "query": "measure_chart 第4条完整 warning",
         "expected": measurement_value["warnings"][3], "kind": "measurement"},
        {"id": "measurement-warning-5", "query": "measure_chart 第5条完整 warning",
         "expected": measurement_value["warnings"][4], "kind": "measurement"},
        {"id": "figure-period-08", "query": "Quarterly Revenue Detail 中 Period 08 的 Revenue 数值",
         "expected": str(values[7]), "kind": "chart_figure"},
        {"id": "figure-period-12", "query": "Quarterly Revenue Detail 中 Period 12 的 Revenue 数值",
         "expected": str(values[11]), "kind": "chart_figure"},
    ]
    return target_state, (source_state, figure_state, filler_state), facts, refs, fixture_registry.version


def _request_for(builder, target, registry, prior, checkpoint, fact, *, control=False):
    text = (
        f"请从历史资源中回答：{fact['query']}。请逐字给出目标字段的完整原文或精确数值，不要解释或补充来源。需要时按来源读取精确内容。"
        '只输出 JSON：{"answer":"答案"}。'
    )
    if control:
        text = (
            f"请从历史资源中回答：{fact['query']}。目标引用未列在资源目录时，"
            f"请先调用 search_history 并设置 source_kind 为 {fact['kind']}，"
            "再把返回引用交给 read_history 读取后回答。只输出 JSON：{\"answer\":\"答案\"}。"
        )
    records = tuple(
        replace(record, payload=replace(record.payload, text=text))
        if record.record_id == target.run.input_record_id else record
        for record in target.records
    )
    return builder.build(replace(target, records=records), registry, prior, context_checkpoint=checkpoint)


def _request_text(request):
    return "\n".join(
        [item.content for item in request.instructions]
        + [str(item.content) for item in request.messages]
    )


def _resource_refs_in_request(request):
    references = []
    for instruction in request.instructions:
        if "本次请求的运行资源目录" not in instruction.content:
            continue
        try:
            payload = json.loads(instruction.content.rsplit("\n", 1)[-1])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        resources = payload.get("resources", []) if isinstance(payload, dict) else []
        references.extend(
            item.get("ref") for item in resources
            if isinstance(item, dict) and isinstance(item.get("ref"), dict)
        )
    return references


def _answer(text):
    try:
        value = json.loads(text.strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if isinstance(value, dict) and set(value) == {"answer"}:
        return str(value["answer"]).strip()
    return None


def _run_model(client, runtime, state, request, fact):
    calls, rounds = [], []
    started = time.monotonic()
    for _ in range(MAX_ROUNDS):
        try:
            prepared = client.prepare(request)
            response = client.dispatch(prepared)
        except ProviderCallError as error:
            return {
                "status": "provider_failure", "failure_code": error.failure.failure_code.value,
                "http_status": error.failure.http_status, "calls": calls, "rounds": rounds,
            }
        rounds.append({
            "estimated_input_tokens": prepared.context_estimate.input_tokens if prepared.context_estimate else None,
            "usage": asdict(response.usage) if response.usage else None,
            "finish_reason": response.finish_reason.value,
        })
        if not response.tool_calls:
            answer = _answer(response.assistant_content)
            return {
                "status": "answered" if response.finish_reason is FinishReason.STOP else "incomplete",
                "answer": answer, "correct": answer == fact["expected"],
                "raw_answer": response.assistant_content, "calls": calls, "rounds": rounds,
                "seconds": round(time.monotonic() - started, 3),
            }
        messages = list(request.messages)
        messages.append(ProviderMessage(
            MessageRole.ASSISTANT, response.assistant_content,
            response.tool_calls, continuation=response.continuation,
        ))
        for call in response.tool_calls:
            if call.name not in {"read_history", "search_history"}:
                result = {"outcome": "failed", "error": {"code": "experiment_read_only"}}
            else:
                outcome = runtime.invoke(
                    ToolInvocation(call.call_id, call.name, call.arguments),
                    ToolContext(state.run.run_id, state.run.session_id, call.call_id),
                )
                result = {
                    "outcome": outcome.outcome.value,
                    "result": outcome.result,
                    "error": asdict(outcome.error) if outcome.error else None,
                }
            args = json.loads(call.arguments)
            calls.append({
                "name": call.name, "arguments": args, "outcome": result["outcome"],
                "result_contains_expected": fact["expected"] in _json(result.get("result")),
                "error": result.get("error"),
            })
            messages.append(ProviderMessage(MessageRole.TOOL, _json(result), tool_call_id=call.call_id))
        request = replace(request, messages=tuple(messages))
    return {
        "status": "round_limit", "correct": False, "calls": calls, "rounds": rounds,
        "seconds": round(time.monotonic() - started, 3),
    }


def _remove_ref(checkpoint, source_ref):
    raw = source_ref.to_dict()
    summary = deepcopy(dict(checkpoint.summary))

    def clean(items):
        output = []
        for item in items:
            refs = [ref for ref in item.get("source_refs", []) if ref != raw]
            if refs:
                output.append({**item, "source_refs": refs})
        return output

    for key in ("current_goal", "constraints", "decisions", "facts", "open_questions", "resources", "proposals"):
        summary[key] = clean(summary.get(key, []))
    progress = summary.get("progress", {})
    summary["progress"] = {
        key: clean(progress.get(key, [])) for key in ("completed", "in_progress", "pending", "blocked")
    }
    return replace(
        checkpoint,
        summary=summary,
        source_refs=tuple(ref for ref in checkpoint.source_refs if ref != source_ref),
    )


def _source_ref(kind, source_run_id):
    call_ids = {
        "ocr": "fixture-ocr-7QK491",
        "measurement": "fixture-measure-3XM826",
        "chart_figure": "fixture-figure-9VA204",
    }
    return ToolResultSourceRef(source_run_id, call_ids[kind])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--provider", choices=[item.value for item in ProviderId], default="deepseek")
    args = parser.parse_args()
    if not all(character.isalnum() or character in "._-" for character in args.batch_id):
        parser.error("batch-id contains unsupported characters")
    out_dir = HERE / "runs" / args.batch_id
    data_dir = ROOT / ".figura/evaluation" / f"resource-read-{args.batch_id}"
    if out_dir.exists() or data_dir.exists():
        parser.error("batch or runtime output already exists")
    load_dotenv(ROOT / ".env", override=False)
    provider = ProviderId(args.provider)
    settings = ProviderSettings.from_env()
    profile = settings.profiles[provider]
    if not profile.availability().available:
        parser.error(f"provider is not configured: {provider.value}")
    profiles = dict(settings.profiles)
    profiles[provider] = replace(
        profile, thinking_mode=False,
        reasoning_effort="none" if provider is not ProviderId.MIMO else None,
        max_completion_tokens=4096, context_window_tokens=CAPACITY,
        write_timeout_seconds=max(profile.write_timeout_seconds, 120.0),
    )
    factory = ProviderFactory(ProviderSettings(profiles))
    client = factory.create(provider, MODEL_IDS[provider])
    out_dir.mkdir(parents=True)
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    app = create_application(ROOT, data_dir=data_dir, provider_factory=factory)
    app.close()
    builder = AgentRequestBuilder(app.execution_state, app.execution_images)
    registry = app.dispatcher._executor._tools.registry
    history = SessionHistorySearch(app.coordinator, app.execution_state)
    runtime = ToolRuntime(registry)
    target, prior, facts, refs, fixture_registry_version = _seed(app, provider)
    before_resources = app.execution_state.build(target, prior).resources
    source_run_ids = {
        "ocr": prior[0].run.run_id,
        "measurement": prior[0].run.run_id,
        "chart_figure": prior[1].run.run_id,
    }

    coverage = select_compaction_coverage(prior, None, CAPACITY // 10)
    if coverage is None:
        raise RuntimeError("synthetic history did not select a compaction coverage window")
    selected = tuple(state for state in prior if state.run.ordinal <= coverage.covered_run_ordinal)
    summary_request, allowed_refs = builder.build_summary_request(
        target, selected, None, coverage=coverage,
        context_capacity_tokens=CAPACITY, summary_budget_tokens=CAPACITY // 10,
    )
    prepared_summary = client.prepare(summary_request)
    if prepared_summary.context_estimate.input_tokens + (
        prepared_summary.request.options.max_completion_tokens or 0
    ) > CAPACITY:
        raise RuntimeError("summary request exceeds the experimental capacity")
    summary_response = client.dispatch(prepared_summary)
    summary, model_source_refs = validate_summary_response(
        summary_response,
        provider_id=provider.value,
        model_id=MODEL_IDS[provider],
        allowed_refs=allowed_refs,
        selected_runs=selected,
    )
    natural_checkpoint = SessionContextCheckpoint(
        target.run.session_id, 1, coverage.covered_run_id, coverage.covered_run_ordinal,
        coverage.covered_record_sequence, coverage.covered_tool_sequence, 2,
        summary, model_source_refs,
    )
    # Controlled direct-read arm: retain the real model summary, and explicitly
    # link all three committed resource-producing tool results in the checkpoint.
    forced_refs = tuple(dict.fromkeys((
        *model_source_refs,
        *(_source_ref(kind, source_run_ids[kind]) for kind in ("ocr", "measurement", "chart_figure")),
    )))
    scrub_markers = {
        fact["expected"].split(": ")[-1].rstrip(".")
        if fact["kind"] == "measurement" else fact["expected"]
        for fact in facts
    }

    def scrub_items(items):
        return [
            item for item in items
            if not any(marker and marker in item.get("text", "") for marker in scrub_markers)
        ]

    controlled_summary = deepcopy(dict(summary))
    for key in ("current_goal", "constraints", "decisions", "facts", "open_questions", "resources", "proposals"):
        controlled_summary[key] = scrub_items(controlled_summary.get(key, []))
    controlled_summary["progress"] = {
        key: scrub_items(summary.get("progress", {}).get(key, []))
        for key in ("completed", "in_progress", "pending", "blocked")
    }
    removed_summary_items = sum(
        len(summary.get(key, [])) - len(controlled_summary.get(key, []))
        for key in ("current_goal", "constraints", "decisions", "facts", "open_questions", "resources", "proposals")
    ) + sum(
        len(summary.get("progress", {}).get(key, []))
        - len(controlled_summary.get("progress", {}).get(key, []))
        for key in ("completed", "in_progress", "pending", "blocked")
    )
    direct_checkpoint = replace(
        natural_checkpoint, summary=controlled_summary, source_refs=forced_refs,
    )

    report = {
        "scope": "synthetic canonical resources; real Provider compaction summary, with a controlled checkpoint that explicitly exposes resource refs and removes summary items containing target answers; model-led history tool loop uses production request builder/runtime retrieval; not image accuracy or full Gateway execution",
        "batch_id": args.batch_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider.value, "model": MODEL_IDS[provider],
        "thinking_mode": False, "context_capacity_tokens": CAPACITY,
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python": platform.python_version(), "fixture_registry_version": fixture_registry_version,
        "agent_registry_version": registry.version,
        "fixture_ids": {
            "session_id": target.run.session_id,
            "target_run_id": target.run.run_id,
            "source_run_id": prior[0].run.run_id,
            "figure_run_id": prior[1].run.run_id,
            "filler_run_id": prior[2].run.run_id,
        },
        "coverage": {
            "covered_run_id": coverage.covered_run_id,
            "covered_run_ordinal": coverage.covered_run_ordinal,
            "covered_record_sequence": coverage.covered_record_sequence,
            "covered_tool_sequence": coverage.covered_tool_sequence,
            "selected_run_ids": [state.run.run_id for state in selected],
        },
        "summary": {
            "estimated_input_tokens": prepared_summary.context_estimate.input_tokens,
            "usage": asdict(summary_response.usage) if summary_response.usage else None,
            "model_source_refs": [ref.to_dict() for ref in model_source_refs],
            "resource_refs_visible_in_natural_projection": {
                kind: any(
                    ref.to_dict() == _source_ref(kind, source_run_ids[kind]).to_dict()
                    for ref in model_source_refs
                )
                for kind in refs
            },
            "summary": summary,
            "controlled_summary_removed_items": removed_summary_items,
        },
        "catalog_before_projection": [resource_ref_to_dict(item.ref) for item in before_resources],
        "direct_cases": [],
        "omitted_reference_controls": [],
        "runtime_snapshot": str(data_dir.relative_to(ROOT)),
    }
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    direct_requests = {
        fact["id"]: _request_for(builder, target, registry, prior, direct_checkpoint, fact)
        for fact in facts
    }
    for fact in facts:
        request = direct_requests[fact["id"]]
        prompt_text = _request_text(request)
        ref_visible = refs[fact["kind"]] in _resource_refs_in_request(request)
        answer_leaked = fact["expected"] in prompt_text
        if not ref_visible or answer_leaked:
            report["direct_cases"].append({
                **fact,
                "status": "invalid_exposure" if not ref_visible else "answer_leaked",
                "resource_ref_visible": ref_visible,
                "answer_leaked_in_request": answer_leaked,
            })
            continue
        attempt = _run_model(client, runtime, target, request, fact)
        first = attempt.get("calls", [None])[0]
        first_read = next((item for item in attempt.get("calls", []) if item["name"] == "read_history"), None)
        attempt.update({
            "resource_ref_visible": True,
            "answer_leaked_in_request": False,
            "first_tool_is_read_history": bool(first and first["name"] == "read_history"),
            "first_read_ref_matches_directory": bool(
                first_read and first_read["arguments"].get("reference") == refs[fact["kind"]]
            ),
            "read_result_contains_answer": any(
                item["result_contains_expected"] for item in attempt.get("calls", [])
            ),
            "direct_read_pass": bool(
                attempt.get("correct")
                and first and first["name"] == "read_history"
                and first_read and first_read["arguments"].get("reference") == refs[fact["kind"]]
                and any(item["result_contains_expected"] for item in attempt.get("calls", []))
            ),
        })
        report["direct_cases"].append({**fact, "status": "run", "attempt": attempt})
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "event": "direct_case",
            "case": fact["id"],
            "pass": attempt.get("direct_read_pass"),
            "answer": attempt.get("answer"),
            "tools": [item["name"] for item in attempt.get("calls", [])],
        }, ensure_ascii=False), flush=True)

    controls = [next(item for item in facts if item["kind"] == kind) for kind in refs]
    source_refs_by_kind = {
        kind: _source_ref(kind, source_run_ids[kind]) for kind in refs
    }
    for fact in controls:
        control_checkpoint = _remove_ref(direct_checkpoint, source_refs_by_kind[fact["kind"]])
        request = _request_for(builder, target, registry, prior, control_checkpoint, fact, control=True)
        prompt_text = _request_text(request)
        ref_visible = refs[fact["kind"]] in _resource_refs_in_request(request)
        answer_leaked = fact["expected"] in prompt_text
        if ref_visible or answer_leaked:
            report["omitted_reference_controls"].append({
                **fact, "status": "invalid_control_projection",
                "resource_ref_visible": ref_visible, "answer_leaked_in_request": answer_leaked,
            })
            continue
        attempt = _run_model(client, runtime, target, request, fact)
        names = [item["name"] for item in attempt.get("calls", [])]
        first_read = next((item for item in attempt.get("calls", []) if item["name"] == "read_history"), None)
        attempt.update({
            "resource_ref_visible": False,
            "answer_leaked_in_request": False,
            "search_before_read": "search_history" in names and "read_history" in names
                and names.index("search_history") < names.index("read_history"),
            "read_ref_matches_resource": bool(
                first_read and first_read["arguments"].get("reference") == refs[fact["kind"]]
            ),
        })
        report["omitted_reference_controls"].append({**fact, "status": "run", "attempt": attempt})
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "event": "control_case", "case": fact["id"],
            "correct": attempt.get("correct"), "tools": names,
            "search_before_read": attempt.get("search_before_read"),
        }, ensure_ascii=False), flush=True)

    direct = [item["attempt"] for item in report["direct_cases"] if item.get("attempt")]
    control = [item["attempt"] for item in report["omitted_reference_controls"] if item.get("attempt")]
    report["aggregate"] = {
        "direct_total": len(report["direct_cases"]),
        "direct_executed": len(direct),
        "direct_passed": sum(item.get("direct_read_pass") is True for item in direct),
        "direct_answers_correct": sum(item.get("correct") is True for item in direct),
        "direct_first_read": sum(item.get("first_tool_is_read_history") is True for item in direct),
        "direct_reference_match": sum(item.get("first_read_ref_matches_directory") is True for item in direct),
        "control_total": len(report["omitted_reference_controls"]),
        "control_executed": len(control),
        "control_correct": sum(item.get("correct") is True for item in control),
        "control_search_then_read": sum(item.get("search_before_read") is True for item in control),
        "scope": "9 one-shot questions; descriptive pilot, not a reliability estimate",
    }
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2), flush=True)
    print(f"Report: {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
