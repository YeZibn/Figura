"""Controlled follow-up: require typed RunExecutionState resource refs."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

from dotenv import load_dotenv

from figura.agent.request import AgentRequestBuilder
from figura.bootstrap import create_application
from figura.providers import MODEL_IDS, ProviderFactory, ProviderId
from figura.providers.config import ProviderSettings
from figura.runtime.records import SessionContextCheckpoint, ToolCallFact
from figura.shared.source_refs import MessageSourceRef
from figura.tools import ToolRuntime


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_resource_read.py"
SPEC = importlib.util.spec_from_file_location("resource_read_runner", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-batch", required=True)
    args = parser.parse_args()
    source_dir = HERE / "runs" / args.source_batch
    report = json.loads((source_dir / "report.json").read_text(encoding="utf-8"))
    load_dotenv(ROOT / ".env", override=False)
    provider = ProviderId(report["provider"])
    settings = ProviderSettings.from_env()
    profiles = dict(settings.profiles)
    profiles[provider] = replace(
        profiles[provider], thinking_mode=False,
        reasoning_effort="none" if provider is not ProviderId.MIMO else None,
        max_completion_tokens=4096, context_window_tokens=100_000,
    )
    factory = ProviderFactory(ProviderSettings(profiles))
    client = factory.create(provider, MODEL_IDS[provider])
    data_dir = ROOT / report["runtime_snapshot"]
    app = create_application(ROOT, data_dir=data_dir, provider_factory=factory)
    app.close()
    coordinator = app.coordinator
    fixture_ids = report["fixture_ids"]
    target = coordinator.read_run_state(fixture_ids["session_id"], fixture_ids["target_run_id"])
    prior = coordinator.read_prior_run_states(fixture_ids["session_id"], fixture_ids["target_run_id"])
    registry = app.dispatcher._executor._tools.registry
    builder = AgentRequestBuilder(app.execution_state, app.execution_images)
    runtime = ToolRuntime(registry)

    call_ids = {
        "ocr": "fixture-ocr-7QK491",
        "measurement": "fixture-measure-3XM826",
        "chart_figure": "fixture-figure-9VA204",
    }
    message_refs = {}
    for state in prior:
        for fact in state.tool_facts:
            if isinstance(fact.payload, ToolCallFact) and fact.payload.call_id in call_ids.values():
                kind = next(key for key, value in call_ids.items() if value == fact.payload.call_id)
                message_refs[kind] = MessageSourceRef(state.run.run_id, fact.payload.response_record_id)

    # MessageSourceRefs make the compacted typed resources visible through the
    # production projection while withholding alternate tool_result references.
    summary = {
        "trust": "untrusted_history",
        "current_goal": [],
        "constraints": [],
        "decisions": [],
        "facts": [{
            "text": "历史 OCR、测量与 ChartFigure 资源可通过当前资源目录中的类型化引用按需读取。",
            "source_refs": [ref.to_dict() for ref in message_refs.values()],
        }],
        "progress": {"completed": [], "in_progress": [], "pending": [], "blocked": []},
        "open_questions": [],
        "resources": [],
        "proposals": [],
        "run_outcomes": [],
    }
    coverage = report["coverage"]
    checkpoint = SessionContextCheckpoint(
        target.run.session_id,
        2,
        coverage["covered_run_id"],
        coverage["covered_run_ordinal"],
        coverage["covered_record_sequence"],
        coverage["covered_tool_sequence"],
        2,
        summary,
        tuple(message_refs.values()),
    )
    all_resources = app.execution_state.build(target, prior).resources
    reference_map = {
        item.ref.kind: MODULE.resource_ref_to_dict(item.ref)
        for item in all_resources
    }
    answers = {
        "ocr": "CODE-084920",
        "measurement": "Detailed warning token: WARN-7QK-491.",
        "chart_figure": "817.4",
    }
    queries = {
        "ocr": "在 OCR 资源中查找第 137 条 Observation，提取 marker code。",
        "measurement": "在测量资源中找到第 4 条 warning，并完整复制该 warning。",
        "chart_figure": "在 Quarterly Revenue Detail 的 Revenue 系列中，Period 08 的数值是多少？",
    }
    selector = {
        "ocr": {"field_path": "/result/snippets", "start": 136, "end": 137},
        "measurement": {"field_path": "/result/warnings", "start": 3, "end": 4},
        "chart_figure": {
            "field_path": "/figure/charts/0/chart_spec/dataset/series/0/values",
            "start": 7,
            "end": 8,
        },
    }
    result_rows = []
    for kind in ("ocr", "measurement", "chart_figure"):
        fact = {
            "id": f"typed-{kind}",
            "query": queries[kind],
            "expected": answers[kind],
            "kind": kind,
        }
        question = (
            f"请从本次请求资源目录中复制 kind={kind} 的完整类型化引用，"
            "直接调用 read_history 并读取完整资源（只传 reference，不传 selector）。禁止 search_history，"
            "也不要使用 message 或 tool_result 引用。"
            f"目标：{fact['query']}"
            "只输出 JSON：{\"answer\":\"实际答案\"}，不要复述整个资源。"
        )
        current = replace(target, records=tuple(
            replace(record, payload=replace(record.payload, text=question))
            if record.record_id == target.run.input_record_id else record
            for record in target.records
        ))
        request = builder.build(current, registry, prior, context_checkpoint=checkpoint)
        request_text = MODULE._request_text(request)
        visible = reference_map[kind] in MODULE._resource_refs_in_request(request)
        leaked = fact["expected"] in request_text
        if not visible or leaked:
            result_rows.append({
                **fact, "status": "invalid_exposure",
                "resource_ref_visible": visible, "answer_leaked_in_request": leaked,
            })
            continue
        attempt = MODULE._run_model(client, runtime, target, request, fact)
        calls = attempt.get("calls", [])
        first = calls[0] if calls else None
        match = bool(
            first
            and first["name"] == "read_history"
            and first["arguments"].get("reference") == reference_map[kind]
        )
        has_result = any(call["result_contains_expected"] for call in calls)
        attempt.update({
            "typed_reference_match": match,
            "read_result_contains_answer": has_result,
            "typed_direct_pass": bool(attempt.get("correct") and match and has_result),
            "resource_ref_visible": visible,
            "answer_leaked_in_request": False,
        })
        result_rows.append({**fact, "status": "run", "attempt": attempt})
        print(json.dumps({
            "event": "typed_direct_case",
            "case": fact["id"],
            "pass": attempt.get("typed_direct_pass"),
            "answer": attempt.get("answer"),
            "tools": [call["name"] for call in calls],
        }, ensure_ascii=False), flush=True)

    output = {
        "scope": "Controlled model-led direct typed-resource read using a compacted request projection; source facts reused from the preceding isolated pilot; explicit tool-use instruction; not a spontaneous tool-choice estimate.",
        "source_batch": args.source_batch,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider.value,
        "model": MODEL_IDS[provider],
        "cases": result_rows,
        "aggregate": {
            "total": len(result_rows),
            "executed": sum(item.get("status") == "run" for item in result_rows),
            "typed_direct_passed": sum(item.get("attempt", {}).get("typed_direct_pass") is True for item in result_rows),
        },
    }
    output["finished_at"] = datetime.now(timezone.utc).isoformat()
    path = source_dir / "typed-resource-read-followup-v3.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output["aggregate"], ensure_ascii=False, indent=2), flush=True)
    print(f"Report: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
