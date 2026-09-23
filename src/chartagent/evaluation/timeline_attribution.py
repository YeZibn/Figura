"""Failure attribution and stage-status reduction rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .timeline_evidence import (
    _contains_reuse,
    _event_is_failure,
    _event_is_success,
    _event_needs_repair,
    _find_scope,
    _kind,
    _mapping_candidates,
    _payload,
    _payload_truncated,
    _references,
    _sequence,
    _statuses,
    _tool_name,
)
from .timeline_model import STAGE_NAMES, STAGE_ORDER, StageEvidence

def _apply_stage_statuses(
    stages: Mapping[str, StageEvidence],
    *,
    buckets: Mapping[str, list[tuple[int, str, Mapping[str, Any]]]],
    events: list[Mapping[str, Any]],
    anomalies: list[dict[str, Any]],
) -> None:
    terminal_failure_sequence = min(
        (_sequence(event) for event in events if _kind(event) in {"run_failed", "run_interrupted"}),
        default=None,
    )
    observed_stage_indices = [
        STAGE_ORDER[name]
        for name in STAGE_NAMES
        if buckets[name]
    ]
    last_observed_stage = max(observed_stage_indices, default=-1)
    for stage_name in STAGE_NAMES:
        stage = stages[stage_name]
        bucket = buckets[stage_name]
        if not bucket:
            if terminal_failure_sequence is not None and STAGE_ORDER[stage_name] > last_observed_stage:
                stage.status = "not_reached"
            else:
                stage.status = "not_observed"
            continue
        has_failure = any(_event_is_failure(kind, payload) for _, kind, payload in bucket)
        stage.failure_sequences = [
            sequence
            for sequence, kind, payload in bucket
            if _event_is_failure(kind, payload)
        ][:64]
        has_success = any(_event_is_success(kind, payload) for _, kind, payload in bucket)
        needs_repair = any(_event_needs_repair(kind, payload) for _, kind, payload in bucket)
        pending_only = all(
            kind in {
                "tool_call",
                "assembly_validation_failure",
            }
            for _, kind, _ in bucket
        )
        if has_failure:
            stage.status = "failed"
        elif needs_repair:
            stage.status = "needs_repair"
        elif has_success:
            stage.status = "completed"
        elif pending_only:
            stage.status = "not_observed"
        else:
            stage.status = "completed"

    for anomaly in anomalies:
        stage_name = anomaly.get("stage")
        if stage_name in stages and anomaly.get("code") in {"panel_handoff_missing", "panel_count_mismatch", "unscoped_measurement"}:
            stages[stage_name].notes.append(str(anomaly.get("message", "存在诊断异常")))


def _detect_repeated_decomposition(
    results: list[tuple[int, Mapping[str, Any]]],
    anomalies: list[dict[str, Any]],
) -> None:
    non_reused = [item for item in results if not _contains_reuse(item[1])]
    if len(non_reused) > 1:
        anomalies.append(
            {
                "code": "repeated_decomposition",
                "category": "decomposition",
                "stage": "decomposition",
                "sequence": non_reused[1][0],
                "evidence_sequences": [sequence for sequence, _ in non_reused[:8]],
                "message": "同一运行中出现多次非复用的图像拆解结果",
            }
        )


def _detect_panel_handoff_gap(
    results: list[tuple[int, Mapping[str, Any]]],
    *,
    panel_count: int,
    expected_panel_count: int | None,
    anomalies: list[dict[str, Any]],
) -> None:
    if not results:
        return
    latest_sequence, latest_payload = results[-1]
    panel_ids = _references(latest_payload)["panel_ids"]
    evidence_truncated = any(_payload_truncated(payload) for _, payload in results)
    observed = panel_count or (len(panel_ids) if not evidence_truncated else 0)
    if expected_panel_count and observed != expected_panel_count and not (evidence_truncated and observed == 0):
        relation = "少于" if observed < expected_panel_count else "多于"
        anomalies.append(
            {
                "code": "panel_count_mismatch",
                "category": "panel_routing",
                "stage": "panel_handoff",
                "sequence": latest_sequence,
                "expected_panel_count": expected_panel_count,
                "observed_panel_count": observed,
                "message": f"拆解结果的 panel 数量{relation}清单预期",
            }
        )
    elif observed == 0 and not evidence_truncated:
        anomalies.append(
            {
                "code": "panel_handoff_missing",
                "category": "panel_routing",
                "stage": "panel_handoff",
                "sequence": latest_sequence,
                "message": "观察到拆解调用，但没有可识别的 panel 引用",
            }
        )


def _detect_unscoped_measurement(
    measurement_events: list[tuple[int, Mapping[str, Any]]],
    *,
    panel_count: int | None,
    anomalies: list[dict[str, Any]],
) -> None:
    if not panel_count or panel_count <= 1:
        return
    for sequence, payload in measurement_events:
        refs = _references(payload)
        scope = _find_scope(payload)
        mode = str(scope.get("mode") or "").lower() if scope else ""
        explicit_unscoped = bool(payload.get("unscoped")) or mode in {"unscoped", "whole_image", "source"}
        if not refs["panel_ids"] or explicit_unscoped:
            anomalies.append(
                {
                    "code": "unscoped_measurement",
                    "category": "panel_routing",
                    "stage": "measurement",
                    "sequence": sequence,
                    "tool_name": _tool_name(payload),
                    "message": "多 panel 样本的测量没有携带 panel 作用域",
                }
            )


def _detect_review_without_repair(
    events: list[Mapping[str, Any]],
    anomalies: list[dict[str, Any]],
) -> None:
    review_failures = [
        (_sequence(event), _kind(event))
        for event in events
        if _kind(event) in {"generated_chart_rejected", "review_failed"}
        and _event_is_failure(_kind(event), _payload(event))
    ]
    repairs = [
        event
        for event in events
        if _kind(event) == "review_repair_required"
        or (
            _kind(event) == "tool_call"
            and _sequence(event) > review_failures[0][0]
        )
    ] if review_failures else []
    if review_failures and not repairs:
        sequence, kind = review_failures[0]
        anomalies.append(
            {
                "code": "review_failed_without_repair",
                "category": "repair",
                "stage": "repair",
                "sequence": sequence,
                "message": f"审核事件 {kind} 失败后没有观察到修复动作",
            }
        )


def _detect_assembly_omission(
    measurement_events: list[tuple[int, Mapping[str, Any]]],
    final_events: list[tuple[int, Mapping[str, Any]]],
    *,
    panel_count: int | None,
    anomalies: list[dict[str, Any]],
) -> None:
    measured: set[str] = set()
    for _, payload in measurement_events:
        if _event_is_success("tool_result", payload):
            measured.update(_references(payload)["panel_ids"])
    final: set[str] = set()
    for _, payload in final_events:
        final.update(_references(payload)["panel_ids"])
    if len(measured) > 1 and final and not measured.issubset(final):
        missing = sorted(measured - final)
        anomalies.append(
            {
                "code": "assembly_missing_panels",
                "category": "assembly_render",
                "stage": "assembly",
                "sequence": min(sequence for sequence, _ in final_events),
                "missing_panel_ids": missing[:16],
                "message": "最终组装引用的 panel 少于已成功测量的 panel",
            }
        )
    elif panel_count and panel_count > 1 and final_events and not measured and not final:
        # There is a final artifact but no source-panel evidence. This is not
        # enough to claim an omission, so preserve it as a weaker observation.
        anomalies.append(
            {
                "code": "assembly_source_unobserved",
                "category": "unknown",
                "stage": "assembly",
                "sequence": min(sequence for sequence, _ in final_events),
                "message": "多 panel 样本已生成最终结果，但事件中没有可核对的 source panel 引用",
            }
        )


def _first_failure(
    anomalies: list[dict[str, Any]],
    stages: Mapping[str, StageEvidence],
    *,
    hard_failure_events: list[tuple[int, str, str]],
) -> dict[str, Any] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for anomaly in anomalies:
        sequence = anomaly.get("sequence")
        if isinstance(sequence, int):
            candidates.append((sequence, dict(anomaly)))
    for sequence, category, code in hard_failure_events:
        candidates.append(
            (
                sequence,
                {
                    "category": category,
                    "stage": "transport_runtime" if category == "transport_runtime" else category,
                    "sequence": sequence,
                    "code": code,
                    "message": "运行在该阶段终止或历史不完整",
                },
            )
        )
    for stage_name, stage in stages.items():
        if stage.status == "failed" and stage.sequences:
            category = _category_for_stage(stage_name)
            failure_sequence = min(stage.failure_sequences or stage.sequences)
            candidates.append(
                (
                    failure_sequence,
                    {
                        "category": category,
                        "stage": stage_name,
                        "sequence": failure_sequence,
                        "code": "stage_failed",
                        "message": stage.errors[0] if stage.errors else f"阶段 {stage_name} 失败",
                    },
                )
            )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], _failure_priority(item[1].get("category"))))
    return candidates[0][1]


def _category_for_stage(stage_name: str) -> str:
    if stage_name in {"decomposition"}:
        return "decomposition"
    if stage_name == "panel_handoff":
        return "panel_routing"
    if stage_name == "measurement":
        return "measurement"
    if stage_name == "model":
        return "transport_runtime"
    if stage_name in {"quality_review", "repair"}:
        return "repair"
    if stage_name in {"assembly", "render"}:
        return "assembly_render"
    return "unknown"


def _failure_priority(category: Any) -> int:
    return {
        "decomposition": 0,
        "panel_routing": 1,
        "measurement": 2,
        "repair": 3,
        "assembly_render": 4,
        "transport_runtime": 5,
        "unknown": 6,
    }.get(category, 99)


def _observed_panel_count(results: list[tuple[int, Mapping[str, Any]]]) -> int:
    count = 0
    for _, payload in results:
        for candidate in _mapping_candidates(payload):
            panels = candidate.get("panels")
            if isinstance(panels, list):
                count = max(count, len(panels))
        if not _payload_truncated(payload):
            count = max(count, len(_references(payload)["panel_ids"]))
    return count
