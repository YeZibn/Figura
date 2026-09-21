"""Project existing Gateway events into a bounded diagnostic timeline."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..trace import sanitize_payload, truncate_text
from .manifest import DiagnosticSample


STAGE_NAMES = (
    "input",
    "model",
    "decomposition",
    "panel_handoff",
    "measurement",
    "quality_review",
    "repair",
    "assembly",
    "render",
)
STAGE_STATUSES = ("completed", "needs_repair", "failed", "not_reached", "not_observed")
FAILURE_STATUSES = {
    "error",
    "failed",
    "failure",
    "rejected",
    "exhausted",
    "blocked",
    "timeout",
    "timed_out",
    "unavailable",
}
SUCCESS_STATUSES = {
    "accepted",
    "available",
    "completed",
    "complete",
    "ok",
    "passed",
    "published",
    "published_with_warning",
    "success",
}
MEASUREMENT_TOOLS = {
    "extract_text",
    "measure_bars",
    "extract_line_series",
    "extract_pie_slices",
    "extract_scatter_points",
}
STAGE_ORDER = {name: index for index, name in enumerate(STAGE_NAMES)}


@dataclass
class StageEvidence:
    """Evidence retained for one fixed stage, without raw images or prompts."""

    name: str
    status: str = "not_observed"
    sequences: list[int] = field(default_factory=list)
    event_kinds: list[str] = field(default_factory=list)
    panel_ids: list[str] = field(default_factory=list)
    attempt_ids: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    failure_sequences: list[int] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "sequences": self.sequences[:64],
            "event_kinds": self.event_kinds[:32],
            "panel_ids": self.panel_ids[:32],
            "attempt_ids": self.attempt_ids[:32],
            "artifact_ids": self.artifact_ids[:32],
            "observation_ids": self.observation_ids[:32],
        }
        if self.errors:
            result["errors"] = [truncate_text(item, 240) for item in self.errors[:8]]
        if self.notes:
            result["notes"] = [truncate_text(item, 240) for item in self.notes[:8]]
        return result


@dataclass
class DiagnosticTimeline:
    """All stage evidence and bounded anomalies inferred from a run history."""

    stages: tuple[StageEvidence, ...]
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    first_failure: dict[str, Any] | None = None
    final_references: dict[str, list[str]] = field(default_factory=dict)
    history_gap: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "stages": [stage.to_dict() for stage in self.stages],
            "anomalies": [sanitize_payload(item) for item in self.anomalies[:32]],
            "final_references": {
                key: list(values[:32]) for key, values in self.final_references.items()
            },
            "history_gap": self.history_gap,
        }
        if self.first_failure is not None:
            result["first_failure"] = sanitize_payload(self.first_failure)
        return result


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


def _event_stages(kind: str, payload: Mapping[str, Any]) -> list[str]:
    tool_name = _tool_name(payload)
    stages: list[str] = []
    if kind in {"run_started", "resume_started"}:
        stages.append("input")
    if kind in {"model_started", "model_completed"}:
        stages.append("model")
    if tool_name == "decompose_chart_image":
        stages.append("decomposition")
        if kind == "tool_result" and _contains_panels(payload):
            stages.append("panel_handoff")
    elif tool_name in MEASUREMENT_TOOLS:
        stages.append("measurement")
    elif tool_name == "assemble_spec":
        stages.append("assembly")
    elif tool_name == "render_chart":
        stages.append("render")
    if kind.startswith("measurement_"):
        stages.append("measurement")

    if kind in {
        "chart_review_required",
        "chart_review_started",
        "chart_review_completed",
        "generated_chart_rejected",
        "review_started",
        "review_completed",
        "review_repair_required",
        "review_failed",
        "review_gate_required",
        "review_gate_updated",
    }:
        stages.append("quality_review")
    if kind.startswith("measurement_repair_") or kind in {
        "measurement_focus_requested",
        "measurement_focus_failed",
        "measurement_decision_required",
        "chart_review_repair_required",
        "review_repair_required",
    }:
        stages.append("repair")
    if kind in {"generated_chart", "generated_chart_published"}:
        stages.append("render")
    if kind == "recovery_blocked":
        stages.append("repair")
    if kind == "operation_completed":
        operation_kind = str(payload.get("operationKind") or "").lower()
        if operation_kind == "review":
            stages.append("quality_review")
        elif operation_kind in {"render", "publication"}:
            stages.append("render")
    return _unique(stages)


def _add_event_evidence(stage: StageEvidence, sequence: int, kind: str, payload: Mapping[str, Any]) -> None:
    if sequence > 0 and sequence not in stage.sequences:
        stage.sequences.append(sequence)
    if kind not in stage.event_kinds:
        stage.event_kinds.append(kind)
    refs = _references(payload)
    for field in ("panel_ids", "attempt_ids", "artifact_ids", "observation_ids"):
        target = getattr(stage, field)
        for value in refs[field]:
            if value not in target:
                target.append(value)
    note = _event_note(kind, payload)
    if note and note not in stage.notes:
        stage.notes.append(note)


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
                "chart_review_required",
                "chart_review_started",
                "measurement_repair_required",
                "measurement_decision_required",
                "measurement_focus_requested",
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
        if _kind(event) in {"generated_chart_rejected", "chart_review_completed", "review_failed"}
        and _event_is_failure(_kind(event), _payload(event))
    ]
    repairs = [
        event
        for event in events
        if _kind(event).startswith("measurement_repair_")
        or _kind(event) in {
            "measurement_focus_requested",
            "measurement_focus_applied",
            "measurement_evidence_selected",
            "chart_review_repair_required",
            "review_repair_required",
        }
    ]
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


def _final_references(events: Iterable[tuple[int, Mapping[str, Any]]]) -> dict[str, list[str]]:
    result = {"artifact_ids": [], "observation_ids": [], "figure_ids": [], "collection_ids": []}
    for _, payload in events:
        refs = _references(payload)
        for field in result:
            for value in refs[field]:
                if value not in result[field]:
                    result[field].append(value)
    return result


def _references(value: Any) -> dict[str, list[str]]:
    refs = {
        "panel_ids": [],
        "attempt_ids": [],
        "artifact_ids": [],
        "observation_ids": [],
        "figure_ids": [],
        "collection_ids": [],
    }
    if isinstance(value, Mapping):
        for candidate in _mapping_candidates(value):
            _collect_references(candidate, refs, context="", depth=0)
        for text in _preview_texts(value):
            _extract_preview_references(text, refs)
    else:
        _collect_references(value, refs, context="", depth=0)
    return refs


def _collect_references(value: Any, refs: dict[str, list[str]], *, context: str, depth: int) -> None:
    if depth > 8:
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.replace("-", "_").lower()
            target = _reference_field(normalized)
            if target:
                for item in _as_reference_values(child):
                    _append_ref(refs[target], item)
            elif normalized == "id" and context in {"panel", "panels", "source", "source_panel"}:
                _append_ref(refs["panel_ids"], child)
            next_context = normalized if normalized in {"panel", "panels", "source", "source_panel"} else context
            if isinstance(child, str) and normalized in {
                "source",
                "measurement_reference",
            }:
                _extract_preview_references(child, refs)
            _collect_references(child, refs, context=next_context, depth=depth + 1)
    elif isinstance(value, list):
        for child in value[:64]:
            _collect_references(child, refs, context=context, depth=depth + 1)


def _reference_field(key: str) -> str | None:
    if key in {"panel_id", "panel_ids", "panelid", "panelids", "source_panel_id", "source_panel_ids"}:
        return "panel_ids"
    if key in {"attempt_id", "attempt_ids", "attemptid", "attemptids", "parent_attempt_id"}:
        return "attempt_ids"
    if key in {"artifact_id", "artifact_ids", "artifactid", "artifactids", "candidate_id", "candidate_ids", "candidateid", "candidateids"}:
        return "artifact_ids"
    if key in {"observation_id", "observation_ids", "observationid", "observationids"}:
        return "observation_ids"
    if key in {"figure_id", "figure_ids", "figureid", "figureids"}:
        return "figure_ids"
    if key in {"collection_id", "collection_ids", "collectionid", "collectionids"}:
        return "collection_ids"
    return None


def _as_reference_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value[:64]
    return [value]


def _append_ref(target: list[str], value: Any) -> None:
    if not isinstance(value, str):
        return
    value = value.strip()
    if not value or len(value) > 160 or value.startswith(("/", "data:")) or "\\" in value:
        return
    if value not in target:
        target.append(value)


def _contains_panels(payload: Mapping[str, Any]) -> bool:
    if any(isinstance(candidate.get("panels"), list) for candidate in _mapping_candidates(payload)):
        return True
    return any(re.search(r'"panels"\s*:\s*\[', text.replace('\\"', '"')) for text in _preview_texts(payload))


def _contains_reuse(payload: Mapping[str, Any]) -> bool:
    for candidate in _mapping_candidates(payload):
        if candidate.get("reuse") is True:
            return True
    return any(re.search(r'"reuse"\s*:\s*true', text.replace('\\"', '"')) for text in _preview_texts(payload))


def _mapping_candidates(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []
    seen: set[int] = set()

    def visit(value: Mapping[str, Any], depth: int) -> None:
        identity = id(value)
        if depth > 4 or identity in seen:
            return
        seen.add(identity)
        candidates.append(value)
        for key, child in value.items():
            if isinstance(child, Mapping):
                visit(child, depth + 1)
            elif key in {"preview", "payload"} and isinstance(child, str) and len(child) <= 100000:
                try:
                    parsed = json.loads(child)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(parsed, Mapping):
                    visit(parsed, depth + 1)

    visit(payload, 0)
    return candidates


def _payload_truncated(payload: Mapping[str, Any]) -> bool:
    return any(candidate.get("truncated") is True for candidate in _mapping_candidates(payload))


def _preview_texts(value: Any, *, depth: int = 0) -> list[str]:
    if depth > 5:
        return []
    texts: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "preview" and isinstance(child, str):
                texts.append(child)
            elif isinstance(child, (Mapping, list)):
                texts.extend(_preview_texts(child, depth=depth + 1))
    elif isinstance(value, list):
        for child in value[:64]:
            texts.extend(_preview_texts(child, depth=depth + 1))
    return texts


def _extract_preview_references(text: str, refs: dict[str, list[str]]) -> None:
    patterns = {
        "panel_ids": r"\bpanel_[A-Za-z0-9]+\b",
        "attempt_ids": r"\b(?:attempt|matt)_[A-Za-z0-9]+\b",
        "artifact_ids": r"\b(?:artifact|cand)_[A-Za-z0-9]+\b",
        "observation_ids": r"\bobs_[A-Za-z0-9]+\b",
        "figure_ids": r"\bfigure_[A-Za-z0-9]+\b",
        "collection_ids": r"\bcollection_[A-Za-z0-9]+\b",
    }
    for field, pattern in patterns.items():
        for value in re.findall(pattern, text):
            _append_ref(refs[field], value)


def _find_scope(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for candidate in _mapping_candidates(payload):
        scope = candidate.get("scope")
        if isinstance(scope, Mapping):
            return scope
    return None


def _tool_name(payload: Mapping[str, Any]) -> str | None:
    for candidate in _mapping_candidates(payload):
        for key in ("tool_name", "toolName", "name"):
            value = candidate.get(key)
            if isinstance(value, str) and value:
                return value
    for text in _preview_texts(payload):
        match = re.search(r'"tool_name"\s*:\s*"([^"]+)"', text)
        if match:
            return match.group(1)
    return None


def _event_is_failure(kind: str, payload: Mapping[str, Any]) -> bool:
    if kind in {"run_failed", "run_interrupted", "generated_chart_rejected", "measurement_repair_exhausted", "measurement_repair_rejected", "measurement_focus_failed", "review_failed"}:
        return True
    if kind in {"chart_review_repair_required", "review_repair_required", "review_gate_required", "recovery_blocked"}:
        return True
    statuses = _statuses(payload)
    return any(status in FAILURE_STATUSES for status in statuses)


def _event_needs_repair(kind: str, payload: Mapping[str, Any]) -> bool:
    """Identify quality-gate states distinct from tool execution failure."""
    if kind in {
        "measurement_repair_required",
        "measurement_decision_required",
        "measurement_focus_requested",
        "measurement_focus_failed",
        "chart_review_repair_required",
        "review_repair_required",
    }:
        return True
    statuses = _statuses(payload)
    return bool(statuses & {"remeasure_required", "partial"})


def _event_is_success(kind: str, payload: Mapping[str, Any]) -> bool:
    if kind in {"run_started", "resume_started", "generated_chart", "generated_chart_published", "operation_completed", "chart_review_completed", "review_completed", "measurement_focus_applied", "measurement_evidence_selected"}:
        return not _event_is_failure(kind, payload)
    if kind == "tool_result":
        statuses = _statuses(payload)
        return not statuses or any(status in SUCCESS_STATUSES for status in statuses)
    return any(status in SUCCESS_STATUSES for status in _statuses(payload))


def _statuses(payload: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for candidate in _mapping_candidates(payload):
        for key in ("status", "state", "tool_status", "review_status", "candidate_status", "publication_status"):
            value = candidate.get(key)
            if isinstance(value, str):
                values.add(value.strip().lower())
    return values


def _event_error(kind: str, payload: Mapping[str, Any]) -> str:
    for key in (
        "error",
        "message",
        "reason",
        "provider_error_message",
        "provider_error_code",
        "error_code",
        "code",
        "terminal_code",
        "terminalCode",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return truncate_text(value, 240)
    issues = payload.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, Mapping):
                message = issue.get("message")
                if isinstance(message, str) and message:
                    return truncate_text(message, 240)
    statuses = sorted(_statuses(payload) & FAILURE_STATUSES)
    return f"{kind}: {', '.join(statuses) if statuses else 'failed'}"


def _event_note(kind: str, payload: Mapping[str, Any]) -> str | None:
    if kind == "tool_result" and _contains_reuse(payload):
        return "拆解结果来自已保存的 panel handoff，未视为重复拆解"
    if kind == "history_gap":
        return "事件历史存在缺口"
    return None


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _kind(event: Mapping[str, Any]) -> str:
    value = event.get("kind")
    return value if isinstance(value, str) else "unknown"


def _sequence(event: Mapping[str, Any]) -> int:
    value = event.get("sequence")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _last_sequence(events: list[Mapping[str, Any]]) -> int:
    return max((_sequence(event) for event in events), default=0)


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
