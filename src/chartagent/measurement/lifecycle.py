"""Minimal measurement evidence state for one authorized source scope."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .evidence import (
    MAX_MEASUREMENT_REFS,
    MEASUREMENT_FOCUS_MODES,
    MEASUREMENT_REGION_KINDS,
    MEASUREMENT_STATUSES,
    _json_safe,
    _now,
    _text,
    _union_bboxes,
    normalize_evidence_refs,
)
from .quality import measurement_from_data
from .scope import measurement_target_fingerprint, normalize_measurement_target


def _invalid_reference(code: str, location: str, message: str, next_action: str) -> dict[str, Any]:
    return {
        "status": "invalid",
        "code": code,
        "location": location,
        "message": message,
        "next_action": next_action,
    }


@dataclass(frozen=True)
class MeasurementAttempt:
    """One tool result, including its source scope and candidate evidence."""

    attempt_id: str
    session_id: str
    run_id: str | None
    attachment_id: str | None
    panel_id: str | None
    parent_attempt_id: str | None
    tool: str
    status: str
    scope: dict[str, Any] | None = None
    effective_scope: dict[str, Any] | None = None
    observation_scope: dict[str, Any] | None = None
    target: dict[str, Any] | None = None
    target_fingerprint: str | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[dict[str, Any], ...] = ()
    series_metadata: tuple[dict[str, Any], ...] = ()
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_measurement(cls, value: Mapping[str, Any]) -> "MeasurementAttempt | None":
        reference = value.get("reference") if isinstance(value.get("reference"), Mapping) else {}
        attempt = value.get("attempt") if isinstance(value.get("attempt"), Mapping) else {}
        source = value.get("source") if isinstance(value.get("source"), Mapping) else {}
        attempt_id = _text(reference.get("attempt_id") or attempt.get("attempt_id"), 160)
        session_id = _text(reference.get("session_id") or attempt.get("session_id"), 160)
        if not attempt_id or not session_id:
            return None

        quality_value = _json_safe(value.get("quality") or {})
        evidence_value = _json_safe(value.get("evidence") or {})
        quality = quality_value if isinstance(quality_value, dict) else {}
        evidence = evidence_value if isinstance(evidence_value, dict) else {}
        raw_refs = evidence.get("refs")
        evidence_refs = _bounded_mappings(raw_refs)
        status = _text(value.get("status"), 32)
        if status not in MEASUREMENT_STATUSES:
            status = "provisional"

        scope = _safe_mapping(attempt.get("scope") or source.get("scope"))
        effective_scope = _safe_mapping(
            attempt.get("effective_scope")
            or source.get("effective_scope")
            or value.get("effective_scope")
            or scope
        )
        observation_scope = _safe_mapping(
            value.get("observation_scope")
            or attempt.get("observation_scope")
            or source.get("observation_scope")
        )
        target = _safe_mapping(value.get("target") or attempt.get("target"))
        series_metadata = tuple(
            dict(item)
            for item in evidence_refs
            if item.get("kind") == "series"
        )
        tool = _text(attempt.get("tool"), 80)

        return cls(
            attempt_id=attempt_id,
            session_id=session_id,
            run_id=_text(attempt.get("run_id"), 128) or None,
            attachment_id=_text(reference.get("attachment_id") or source.get("attachment_id"), 160) or None,
            panel_id=_text(reference.get("panel_id") or source.get("panel_id"), 160) or None,
            parent_attempt_id=_text(attempt.get("parent_attempt_id"), 160) or None,
            tool=tool,
            status=status,
            scope=scope,
            effective_scope=effective_scope,
            observation_scope=observation_scope,
            target=target,
            target_fingerprint=_text(attempt.get("target_fingerprint"), 80)
            or measurement_target_fingerprint(target, tool=tool),
            quality=quality,
            evidence=evidence,
            evidence_refs=tuple(evidence_refs),
            series_metadata=series_metadata,
            created_at=_text(attempt.get("created_at"), 64) or _now(),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MeasurementAttempt | None":
        if not isinstance(value, Mapping):
            return None
        reference = value.get("measurement_ref")
        reference = reference if isinstance(reference, Mapping) else {}
        attempt_id = _text(value.get("attempt_id") or reference.get("attempt_id"), 160)
        session_id = _text(value.get("session_id") or reference.get("session_id"), 160)
        if not attempt_id or not session_id:
            return None

        quality = _safe_mapping(value.get("quality")) or {}
        evidence = _safe_mapping(value.get("evidence")) or {}
        raw_refs = value.get("evidence_refs")
        if not isinstance(raw_refs, list):
            raw_refs = evidence.get("refs")
        evidence_refs = _bounded_mappings(raw_refs)
        raw_series = value.get("series_metadata")
        series_metadata = _bounded_mappings(raw_series) if isinstance(raw_series, list) else [
            dict(item) for item in evidence_refs if item.get("kind") == "series"
        ]
        status = _text(value.get("status"), 32)
        if status not in MEASUREMENT_STATUSES:
            status = "provisional"
        scope = _safe_mapping(value.get("scope"))
        effective_scope = _safe_mapping(value.get("effective_scope") or scope)
        observation_scope = _safe_mapping(value.get("observation_scope"))
        target = _safe_mapping(value.get("target"))
        tool = _text(value.get("tool"), 80)

        return cls(
            attempt_id=attempt_id,
            session_id=session_id,
            run_id=_text(value.get("run_id"), 128) or None,
            attachment_id=_text(value.get("attachment_id") or reference.get("attachment_id"), 160) or None,
            panel_id=_text(value.get("panel_id") or reference.get("panel_id"), 160) or None,
            parent_attempt_id=_text(value.get("parent_attempt_id"), 160) or None,
            tool=tool,
            status=status,
            scope=scope,
            effective_scope=effective_scope,
            observation_scope=observation_scope,
            target=target,
            target_fingerprint=_text(value.get("target_fingerprint"), 80)
            or measurement_target_fingerprint(target, tool=tool),
            quality=quality,
            evidence=evidence,
            evidence_refs=tuple(evidence_refs),
            series_metadata=tuple(series_metadata),
            created_at=_text(value.get("created_at"), 64) or _now(),
        )

    def measurement_ref(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "attempt_id": self.attempt_id,
            "attachment_id": self.attachment_id,
            "panel_id": self.panel_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "attachment_id": self.attachment_id,
            "panel_id": self.panel_id,
            "parent_attempt_id": self.parent_attempt_id,
            "tool": self.tool,
            "status": self.status,
            "measurement_ref": self.measurement_ref(),
            "scope": _json_safe(self.scope),
            "effective_scope": _json_safe(self.effective_scope),
            "observation_scope": _json_safe(self.observation_scope),
            "target": _json_safe(self.target),
            "target_fingerprint": self.target_fingerprint,
            "quality": _json_safe(self.quality),
            "evidence": _json_safe(self.evidence),
            "evidence_refs": _json_safe(list(self.evidence_refs)),
            "series_metadata": _json_safe(list(self.series_metadata)),
            "created_at": self.created_at,
        }


@dataclass
class MeasurementSession:
    """Recoverable state for a single attachment/panel and its latest result."""

    session_id: str
    run_id: str | None
    attachment_id: str | None
    panel_id: str | None
    current: MeasurementAttempt | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MeasurementSession | None":
        session_id = _text(value.get("session_id"), 160)
        if not session_id:
            return None
        raw_attempt = value.get("current_attempt")
        attempt = MeasurementAttempt.from_dict(raw_attempt) if isinstance(raw_attempt, Mapping) else None
        if attempt is not None and attempt.session_id != session_id:
            return None
        attachment_id = _text(value.get("attachment_id"), 160) or None
        panel_id = _text(value.get("panel_id"), 160) or None
        if attempt is not None and (
            attempt.attachment_id != attachment_id or attempt.panel_id != panel_id
        ):
            return None
        return cls(
            session_id=session_id,
            run_id=_text(value.get("run_id"), 128) or None,
            attachment_id=attachment_id,
            panel_id=panel_id,
            current=attempt,
        )

    def set_current_attempt(self, attempt: MeasurementAttempt) -> bool:
        if attempt.session_id != self.session_id:
            return False
        if attempt.attachment_id != self.attachment_id or attempt.panel_id != self.panel_id:
            return False
        if self.run_id and attempt.run_id and self.run_id != attempt.run_id:
            return False
        if self.current is not None:
            if self.current.attempt_id == attempt.attempt_id:
                return True
            if attempt.parent_attempt_id and attempt.parent_attempt_id != self.current.attempt_id:
                return False
        elif attempt.parent_attempt_id:
            return False
        self.current = attempt
        return True

    def current_attempt(self) -> MeasurementAttempt | None:
        return self.current

    def evidence_refs(self) -> tuple[dict[str, Any], ...]:
        return self.current.evidence_refs if self.current is not None else ()

    def resolve_refs(
        self,
        refs: object,
        *,
        mode: str = "include",
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        normalized_refs = normalize_evidence_refs(refs)
        if not normalized_refs:
            return [], _target_error("measurement_target_refs_empty", "measurement_target.refs must contain at least one known evidence ref")
        if mode not in MEASUREMENT_FOCUS_MODES:
            return [], _target_error("measurement_target_mode_invalid", "measurement_target.mode must be include or exclude")
        index = {str(item.get("ref")): dict(item) for item in self.evidence_refs() if item.get("ref")}
        missing = [ref for ref in normalized_refs if ref not in index]
        if missing:
            return [], {
                **_target_error("measurement_target_ref_unknown", "one or more target refs are not in the current measurement result"),
                "missing_refs": missing[:MAX_MEASUREMENT_REFS],
            }
        resolved = [index[ref] for ref in normalized_refs]
        if not any(isinstance(item.get("bbox_px"), list) for item in resolved):
            return [], _target_error("measurement_target_ref_unbounded", "the selected evidence refs have no bounded geometry")
        return resolved, None

    def validate_measurement_target(
        self,
        target: Mapping[str, Any] | None,
        *,
        parent_attempt_id: str | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        normalized = normalize_measurement_target(target)
        current = self.current
        if normalized is None:
            return None, _target_error("measurement_target_invalid", "measurement_target must identify a bounded region or evidence refs")
        if current is None:
            return None, _target_error("measurement_attempt_not_found", "targeted measurement requires a current measurement result")
        if normalized.get("panel_id") not in {None, self.panel_id}:
            return None, _target_error("measurement_panel_mismatch", "measurement target does not belong to the current panel")
        requested_parent = normalized.get("parent_attempt_id") or parent_attempt_id
        if requested_parent != current.attempt_id:
            return None, _target_error("measurement_parent_mismatch", "measurement target must refer to the current measurement result")

        refs = normalized.get("refs") if isinstance(normalized.get("refs"), list) else []
        if refs:
            resolved, ref_error = self.resolve_refs(refs, mode=str(normalized.get("mode") or "include"))
            if ref_error is not None:
                return None, ref_error
            regions = [item.get("bbox_px") for item in resolved if isinstance(item.get("bbox_px"), list)]
            normalized["resolved_refs"] = [str(item.get("ref")) for item in resolved]
            normalized["resolved_regions_px"] = regions[:MAX_MEASUREMENT_REFS]
            union = _union_bboxes(regions)
            if union is not None:
                normalized["bbox_px"] = union
            if normalized.get("region_kind") == "panel":
                kinds = [str(item.get("kind") or "") for item in resolved]
                normalized["region_kind"] = kinds[0] if kinds and kinds[0] in MEASUREMENT_REGION_KINDS else "geometry"
        normalized["panel_id"] = self.panel_id
        normalized["parent_attempt_id"] = current.attempt_id
        return normalized, None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "attachment_id": self.attachment_id,
            "panel_id": self.panel_id,
            "current_attempt": self.current.to_dict() if self.current is not None else None,
        }


def _safe_mapping(value: object) -> dict[str, Any] | None:
    safe = _json_safe(value) if isinstance(value, Mapping) else None
    return safe if isinstance(safe, dict) else None


def _bounded_mappings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:MAX_MEASUREMENT_REFS]:
        safe = _safe_mapping(item)
        if safe is not None:
            result.append(safe)
    return result


def _target_error(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "rejected",
        "code": code,
        "location": "measurement_target",
        "message": message,
        "next_action": "结合当前 panel 和工具结果重新指定一个有界测量区域",
    }


def sessions_from_state(value: object) -> dict[str, MeasurementSession]:
    result: dict[str, MeasurementSession] = {}
    if isinstance(value, Mapping):
        values = list(value.values())
    elif isinstance(value, list):
        values = value
    else:
        values = []
    for item in values[:32]:
        if not isinstance(item, Mapping):
            continue
        session = MeasurementSession.from_dict(item)
        if session is not None:
            result[session.session_id] = session
    return result


def sessions_to_state(sessions: Mapping[str, MeasurementSession]) -> dict[str, Any]:
    return {
        key: session.to_dict()
        for key, session in list(sessions.items())[:32]
        if isinstance(session, MeasurementSession)
    }


def register_measurement(sessions: dict[str, MeasurementSession], data: Mapping[str, Any]) -> MeasurementSession | None:
    measurement = measurement_from_data(data)
    if measurement is None:
        return None
    attempt = MeasurementAttempt.from_measurement(measurement)
    if attempt is None:
        return None
    session = sessions.get(attempt.session_id)
    if session is None:
        session = MeasurementSession(
            session_id=attempt.session_id,
            run_id=attempt.run_id,
            attachment_id=attempt.attachment_id,
            panel_id=attempt.panel_id,
        )
        sessions[session.session_id] = session
    if not session.set_current_attempt(attempt):
        return None
    while len(sessions) > 32:
        sessions.pop(next(iter(sessions)))
    return session


def validate_measurement_evidence(
    reference: object,
    context: Mapping[str, Any] | None,
    *,
    evidence_refs: object | None = None,
    expected_attachment_id: str | None = None,
    expected_panel_id: str | None = None,
    location: str = "measurement_ref",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate only the exact measurement result and evidence refs used downstream."""
    if not isinstance(reference, Mapping):
        return None, _invalid_reference(
            "measurement_reference_invalid", location,
            "measurement_ref must be a structured server-issued reference",
            "重新读取当前测量结果并使用其 measurement.reference",
        )
    required = ("session_id", "attempt_id", "attachment_id")
    if any(not isinstance(reference.get(key), str) or not str(reference.get(key)).strip() for key in required):
        return None, _invalid_reference(
            "measurement_reference_incomplete", location,
            "measurement_ref is missing a required source or attempt identity",
            "重新读取当前测量结果，不要手写 measurement_ref",
        )
    if expected_attachment_id and reference.get("attachment_id") != expected_attachment_id:
        return None, _invalid_reference(
            "measurement_source_mismatch", location,
            "measurement attachment does not match the assembled source",
            "使用同一 attachment 中的测量结果",
        )
    if expected_panel_id and reference.get("panel_id") != expected_panel_id:
        return None, _invalid_reference(
            "measurement_panel_mismatch", location,
            "measurement panel does not match the assembled source",
            "使用同一 panel 中的测量结果",
        )
    if not isinstance(context, Mapping):
        return None, _invalid_reference(
            "measurement_context_unavailable", location,
            "server-owned measurement session is unavailable in this run",
            "重新观察当前 panel 后再组装",
        )

    raw_session = context.get(str(reference["session_id"]))
    session = raw_session if isinstance(raw_session, MeasurementSession) else (
        MeasurementSession.from_dict(raw_session) if isinstance(raw_session, Mapping) else None
    )
    if session is None:
        return None, _invalid_reference(
            "measurement_session_not_found", location,
            "measurement session is not registered for the current run",
            "重新观察当前 panel 的测量结果",
        )
    attempt = session.current_attempt()
    if attempt is None or attempt.attempt_id != reference.get("attempt_id"):
        return None, _invalid_reference(
            "measurement_attempt_not_found", location,
            "measurement result is not the current result registered for this session",
            "重新读取当前测量结果并重试组装",
        )
    if (
        attempt.attachment_id != reference.get("attachment_id")
        or attempt.panel_id != reference.get("panel_id")
        or session.attachment_id != attempt.attachment_id
        or session.panel_id != attempt.panel_id
    ):
        return None, _invalid_reference(
            "measurement_lineage_mismatch", location,
            "measurement result does not match its authorized attachment and panel",
            "只使用当前 attachment/panel 下的测量结果",
        )

    requested_refs: tuple[str, ...] = ()
    if evidence_refs is not None:
        if not isinstance(evidence_refs, (list, tuple, set)):
            return None, _invalid_reference(
                "measurement_evidence_refs_invalid", f"{location}.evidence_refs",
                "evidence_refs must be an array of compact evidence references",
                "只提交当前 measurement result 返回的 evidence refs",
            )
        requested_refs = normalize_evidence_refs(evidence_refs)
        available_refs = {
            str(item.get("ref"))
            for item in attempt.evidence_refs
            if isinstance(item, Mapping) and item.get("ref")
        }
        missing_refs = [ref for ref in requested_refs if ref not in available_refs]
        if missing_refs:
            return None, {
                **_invalid_reference(
                    "measurement_evidence_ref_unknown", f"{location}.evidence_refs",
                    "one or more evidence_refs are not in the referenced measurement result",
                    "重新读取当前 measurement observation 后修正 evidence_refs",
                ),
                "missing_refs": missing_refs[:MAX_MEASUREMENT_REFS],
                "available_refs": sorted(available_refs)[:MAX_MEASUREMENT_REFS],
            }

    evidence_index = {
        str(item.get("ref")): item
        for item in attempt.evidence_refs
        if isinstance(item, Mapping) and item.get("ref")
    }
    empty_refs = [
        ref for ref in requested_refs
        if evidence_index[ref].get("kind") in {"bar", "point", "sector"}
        and evidence_index[ref].get("has_numeric_value") is False
    ]
    if empty_refs:
        return None, {
            **_invalid_reference(
                "measurement_evidence_ref_unusable", f"{location}.evidence_refs",
                "referenced candidates do not contain numeric values required for chart data",
                "移除没有数值的候选，或重新测量对应区域",
            ),
            "refs": empty_refs[:MAX_MEASUREMENT_REFS],
        }

    return {
        "status": "candidate",
        "measurement_status": attempt.status,
        "session_id": session.session_id,
        "attempt_id": attempt.attempt_id,
        "attachment_id": attempt.attachment_id,
        "panel_id": attempt.panel_id,
        "tool": attempt.tool,
        "scope": _json_safe(attempt.scope),
        "effective_scope": _json_safe(attempt.effective_scope),
        "observation_scope": _json_safe(attempt.observation_scope),
        "quality": _json_safe(attempt.quality),
        "evidence_refs": list(requested_refs),
        "series_metadata": _json_safe(list(attempt.series_metadata)),
    }, None
