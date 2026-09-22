"""Project Gateway events into a bounded diagnostic timeline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .manifest import DiagnosticSample
from .timeline_attribution import (
    _apply_stage_statuses,
    _detect_assembly_omission,
    _detect_panel_handoff_gap,
    _detect_repeated_decomposition,
    _detect_review_without_repair,
    _detect_unscoped_measurement,
    _first_failure,
    _observed_panel_count,
)
from .timeline_evidence import (
    _event_stages,
    _add_event_evidence,
    _event_error,
    _event_is_failure,
    _final_references,
    _kind,
    _sequence,
    _tool_name,
)
from .timeline_model import (
    MEASUREMENT_TOOLS,
    STAGE_NAMES,
    DiagnosticTimeline,
    StageEvidence,
)


def build_timeline(
    history: Mapping[str, Any],
    *,
    sample: DiagnosticSample | None = None,
    timed_out: bool = False,
) -> DiagnosticTimeline:
    """Build a stable stage projection from a Gateway history response."""

    raw_events = history.get("events")
    events = [event for event in raw_events if isinstance(event, Mapping)] if isinstance(raw_events, list) else []
    buckets = {name: [] for name in STAGE_NAMES}
    stage_evidence = {name: StageEvidence(name) for name in STAGE_NAMES}
    decomposition_results: list[tuple[int, Mapping[str, Any]]] = []
    measurement_events: list[tuple[int, Mapping[str, Any]]] = []
    final_events: list[tuple[int, Mapping[str, Any]]] = []
    hard_failure_events: list[tuple[int, str, str]] = []
    history_gap = bool(history.get("historyGap"))
    if history_gap:
        hard_failure_events.append((0, "transport_runtime", "history_gap"))

    for event in events:
        sequence = _sequence(event)
        kind = _kind(event)
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        stages = _event_stages(kind, payload)
        if kind == "tool_result" and _tool_name(payload) == "decompose_chart_image":
            decomposition_results.append((sequence, payload))
        if kind == "tool_result" and _tool_name(payload) in MEASUREMENT_TOOLS:
            measurement_events.append((sequence, payload))
        if any(stage in {"assembly", "render"} for stage in stages):
            final_events.append((sequence, payload))
        for stage_name in stages:
            buckets[stage_name].append((sequence, kind, payload))
            _add_event_evidence(stage_evidence[stage_name], sequence, kind, payload)
        for stage_name in stages:
            if _event_is_failure(kind, payload):
                stage_evidence[stage_name].errors.append(_event_error(kind, payload))
        if kind in {"run_failed", "run_interrupted"}:
            hard_failure_events.append((sequence, "transport_runtime", kind))

    anomalies: list[dict[str, Any]] = []
    _detect_repeated_decomposition(decomposition_results, anomalies)
    panel_count = _observed_panel_count(decomposition_results)
    expected_panel_count = sample.expected_panel_count if sample is not None else None
    _detect_panel_handoff_gap(
        decomposition_results,
        panel_count=panel_count,
        expected_panel_count=expected_panel_count,
        anomalies=anomalies,
    )
    _detect_unscoped_measurement(
        measurement_events,
        panel_count=panel_count or expected_panel_count,
        anomalies=anomalies,
    )
    _detect_review_without_repair(events, anomalies)
    final_references = _final_references(final_events)
    _detect_assembly_omission(
        measurement_events,
        final_events,
        panel_count=panel_count or expected_panel_count,
        anomalies=anomalies,
    )
    if timed_out:
        anomalies.append(
            {
                "code": "run_timeout",
                "category": "transport_runtime",
                "stage": "transport_runtime",
                "sequence": _last_sequence(events),
                "message": "在诊断等待窗口内未观察到终态",
            }
        )

    _apply_stage_statuses(
        stage_evidence,
        buckets=buckets,
        events=events,
        anomalies=anomalies,
    )
    if history_gap:
        stage_evidence["input"].notes.append("历史起点早于当前可读取事件")
    first_failure = _first_failure(
        anomalies,
        stage_evidence,
        hard_failure_events=hard_failure_events,
    )
    return DiagnosticTimeline(
        stages=tuple(stage_evidence[name] for name in STAGE_NAMES),
        anomalies=anomalies,
        first_failure=first_failure,
        final_references=final_references,
        history_gap=history_gap,
    )


__all__ = ["DiagnosticTimeline", "StageEvidence", "build_timeline"]
