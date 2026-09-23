"""Event parsing and bounded evidence-reference extraction."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..trace import truncate_text
from .timeline_model import (
    FAILURE_STATUSES,
    MEASUREMENT_TOOLS,
    SUCCESS_STATUSES,
    StageEvidence,
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
    if kind in {
        "generated_chart_rejected",
        "review_started",
        "review_completed",
        "review_repair_required",
        "review_failed",
        "review_gate_required",
        "review_gate_updated",
    }:
        stages.append("quality_review")
    if kind in {
        "assembly_validation_failure",
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
    if kind in {"run_failed", "run_interrupted", "generated_chart_rejected", "assembly_validation_failure", "review_failed"}:
        return True
    if kind in {"review_repair_required", "review_gate_required", "recovery_blocked"}:
        return True
    statuses = _statuses(payload)
    return any(status in FAILURE_STATUSES for status in statuses)


def _event_needs_repair(kind: str, payload: Mapping[str, Any]) -> bool:
    """Identify quality-gate states distinct from tool execution failure."""
    if kind in {"assembly_validation_failure", "review_repair_required"}:
        return True
    return False


def _event_is_success(kind: str, payload: Mapping[str, Any]) -> bool:
    if kind in {"run_started", "resume_started", "generated_chart", "generated_chart_published", "operation_completed", "review_completed"}:
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
