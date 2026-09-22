"""Measurement attempt and session lifecycle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from .evidence import (
    MAX_MEASUREMENT_ATTEMPTS,
    MAX_MEASUREMENT_REFS,
    MAX_MEASUREMENT_TARGET_FIELDS,
    MAX_REPAIR_ATTEMPTS,
    MEASUREMENT_FOCUS_MODES,
    MEASUREMENT_REGION_KINDS,
    MEASUREMENT_STATUSES,
    _json_safe,
    _now,
    _text,
    _union_bboxes,
    normalize_evidence_refs,
)
from .quality import _repair_error, _repair_limit, measurement_from_data
from .scope import measurement_target_fingerprint, normalize_measurement_target
@dataclass(frozen=True)
class MeasurementAttempt:
    attempt_id: str
    session_id: str
    run_id: str | None
    attachment_id: str | None
    panel_id: str | None
    parent_attempt_id: str | None
    tool: str
    status: str
    scope: dict[str, Any] | None = None
    observation_scope: dict[str, Any] | None = None
    target: dict[str, Any] | None = None
    target_fingerprint: str | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[dict[str, Any], ...] = ()
    selected_refs: tuple[str, ...] = ()
    discarded_refs: tuple[str, ...] = ()
    decision_status: str = "pending"
    series_map: dict[str, str] = field(default_factory=dict)
    evidence_basis: str | None = None
    focus_mode: str | None = None
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
        status = _text(value.get("status"), 32)
        if status not in MEASUREMENT_STATUSES:
            status = "provisional"
        quality = _json_safe(value.get("quality") or {})
        evidence = _json_safe(value.get("evidence") or {})
        raw_refs = evidence.get("refs") if isinstance(evidence, Mapping) else []
        if not raw_refs:
            raw_refs = value.get("evidence_refs")
        evidence_refs = tuple(item for item in raw_refs[:MAX_MEASUREMENT_REFS] if isinstance(item, Mapping)) if isinstance(raw_refs, list) else ()
        decision = value.get("decision") if isinstance(value.get("decision"), Mapping) else {}
        if not decision:
            decision = {
                "selected_refs": value.get("selected_refs"),
                "discarded_refs": value.get("discarded_refs"),
            }
        focus = evidence.get("focus") if isinstance(evidence, Mapping) else None
        scope = _json_safe(attempt.get("scope") or source.get("scope"))
        observation_scope = _json_safe(value.get("observation_scope") or attempt.get("observation_scope") or source.get("observation_scope"))
        observation_scope = observation_scope if isinstance(observation_scope, dict) else None
        target = _json_safe(value.get("target") or attempt.get("target"))
        target = target if isinstance(target, dict) else None
        return cls(
            attempt_id=attempt_id,
            session_id=session_id,
            run_id=_text(attempt.get("run_id"), 128) or None,
            attachment_id=_text(reference.get("attachment_id") or source.get("attachment_id"), 160) or None,
            panel_id=_text(reference.get("panel_id") or source.get("panel_id"), 160) or None,
            parent_attempt_id=_text(attempt.get("parent_attempt_id"), 160) or None,
            tool=_text(attempt.get("tool"), 80),
            status=status,
            scope=scope if isinstance(scope, dict) else None,
            observation_scope=observation_scope,
            target=target,
            target_fingerprint=_text(attempt.get("target_fingerprint"), 80) or measurement_target_fingerprint(target, tool=attempt.get("tool")),
            quality=quality if isinstance(quality, dict) else {},
            evidence=evidence if isinstance(evidence, dict) else {},
            evidence_refs=tuple(dict(item) for item in evidence_refs),
            selected_refs=normalize_evidence_refs(decision.get("selected_refs")),
            discarded_refs=normalize_evidence_refs(decision.get("discarded_refs")),
            decision_status=_text(decision.get("status"), 32) or "pending",
            series_map={
                _text(key, 80): _text(item, 120)
                for key, item in list((decision.get("series_map") or {}).items())[:MAX_MEASUREMENT_TARGET_FIELDS]
                if _text(key, 80) and _text(item, 120)
            } if isinstance(decision.get("series_map"), Mapping) else {},
            evidence_basis=_text(decision.get("evidence_basis"), 80) or None,
            focus_mode=_text(focus.get("mode"), 24) or None if isinstance(focus, Mapping) else None,
            created_at=_text(attempt.get("created_at"), 64) or _now(),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MeasurementAttempt | None":
        if not isinstance(value, Mapping):
            return None
        quality = _json_safe(value.get("quality") or {})
        evidence = _json_safe(value.get("evidence") or {})
        raw_refs = evidence.get("refs") if isinstance(evidence, Mapping) else []
        if not raw_refs:
            raw_refs = value.get("evidence_refs")
        evidence_refs = tuple(item for item in raw_refs[:MAX_MEASUREMENT_REFS] if isinstance(item, Mapping)) if isinstance(raw_refs, list) else ()
        decision = value.get("decision") if isinstance(value.get("decision"), Mapping) else {}
        if not decision:
            decision = {
                "selected_refs": value.get("selected_refs"),
                "discarded_refs": value.get("discarded_refs"),
            }
        focus = evidence.get("focus") if isinstance(evidence, Mapping) else None
        scope = _json_safe(value.get("scope"))
        observation_scope = _json_safe(value.get("observation_scope"))
        observation_scope = observation_scope if isinstance(observation_scope, dict) else None
        target = _json_safe(value.get("target"))
        target = target if isinstance(target, dict) else None
        attempt_id = _text(value.get("attempt_id"), 160)
        session_id = _text(value.get("session_id"), 160)
        if not attempt_id or not session_id:
            return None
        status = _text(value.get("status"), 32)
        if status not in MEASUREMENT_STATUSES:
            status = "provisional"
        return cls(
            attempt_id=attempt_id,
            session_id=session_id,
            run_id=_text(value.get("run_id"), 128) or None,
            attachment_id=_text(value.get("attachment_id"), 160) or None,
            panel_id=_text(value.get("panel_id"), 160) or None,
            parent_attempt_id=_text(value.get("parent_attempt_id"), 160) or None,
            tool=_text(value.get("tool"), 80),
            status=status,
            scope=scope if isinstance(scope, dict) else None,
            observation_scope=observation_scope,
            target=target,
            target_fingerprint=_text(value.get("target_fingerprint"), 80) or measurement_target_fingerprint(target, tool=value.get("tool")),
            quality=quality if isinstance(quality, dict) else {},
            evidence=evidence if isinstance(evidence, dict) else {},
            evidence_refs=tuple(dict(item) for item in evidence_refs),
            selected_refs=normalize_evidence_refs(decision.get("selected_refs")),
            discarded_refs=normalize_evidence_refs(decision.get("discarded_refs")),
            decision_status=_text(decision.get("status"), 32) or "pending",
            series_map={
                _text(key, 80): _text(item, 120)
                for key, item in list((decision.get("series_map") or {}).items())[:MAX_MEASUREMENT_TARGET_FIELDS]
                if _text(key, 80) and _text(item, 120)
            } if isinstance(decision.get("series_map"), Mapping) else {},
            evidence_basis=_text(decision.get("evidence_basis"), 80) or None,
            focus_mode=_text(focus.get("mode"), 24) or None if isinstance(focus, Mapping) else None,
            created_at=_text(value.get("created_at"), 64) or _now(),
        )

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
            "scope": _json_safe(self.scope),
            "observation_scope": _json_safe(self.observation_scope),
            "target": _json_safe(self.target),
            "target_fingerprint": self.target_fingerprint,
            "quality": _json_safe(self.quality),
            "evidence": _json_safe(self.evidence),
            "evidence_refs": _json_safe(list(self.evidence_refs)),
            "selected_refs": list(self.selected_refs),
            "discarded_refs": list(self.discarded_refs),
            "decision": {
                "status": self.decision_status,
                "selected_refs": list(self.selected_refs),
                "discarded_refs": list(self.discarded_refs),
                "series_map": _json_safe(self.series_map),
                "evidence_basis": self.evidence_basis,
            },
            "focus_mode": self.focus_mode,
            "created_at": self.created_at,
        }

    def reference(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "attempt_id": self.attempt_id,
            "attachment_id": self.attachment_id,
            "panel_id": self.panel_id,
        }


@dataclass
class MeasurementSession:
    session_id: str
    run_id: str | None
    attachment_id: str | None
    panel_id: str | None
    attempts: list[MeasurementAttempt] = field(default_factory=list)
    current_attempt_id: str | None = None
    max_repair_attempts: int = MAX_REPAIR_ATTEMPTS
    selected_refs: tuple[str, ...] = ()
    discarded_refs: tuple[str, ...] = ()
    decision_status: str = "pending"
    decision_attempt_id: str | None = None
    series_map: dict[str, str] = field(default_factory=dict)
    evidence_basis: str | None = None
    decision_fingerprint: str | None = None
    focus_mode: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MeasurementSession | None":
        session_id = _text(value.get("session_id"), 160)
        if not session_id:
            return None
        raw_attempts = value.get("attempts") if isinstance(value.get("attempts"), list) else []
        attempts: list[MeasurementAttempt] = []
        for raw in raw_attempts[:MAX_MEASUREMENT_ATTEMPTS]:
            if not isinstance(raw, Mapping):
                continue
            attempt = MeasurementAttempt.from_dict(raw)
            if attempt is not None and attempt.session_id == session_id:
                attempts.append(attempt)
        session = cls(
            session_id=session_id,
            run_id=_text(value.get("run_id"), 128) or None,
            attachment_id=_text(value.get("attachment_id"), 160) or None,
            panel_id=_text(value.get("panel_id"), 160) or None,
            attempts=attempts,
            current_attempt_id=_text(value.get("current_attempt_id"), 160) or None,
            max_repair_attempts=_repair_limit(value.get("max_repair_attempts", MAX_REPAIR_ATTEMPTS)),
            selected_refs=normalize_evidence_refs(value.get("selected_refs")),
            discarded_refs=normalize_evidence_refs(value.get("discarded_refs")),
            decision_status=_text(value.get("decision_status"), 32) or "pending",
            decision_attempt_id=_text(value.get("decision_attempt_id"), 160) or None,
            series_map={
                _text(key, 80): _text(item, 120)
                for key, item in list((value.get("series_map") or {}).items())[:MAX_MEASUREMENT_TARGET_FIELDS]
                if _text(key, 80) and _text(item, 120)
            } if isinstance(value.get("series_map"), Mapping) else {},
            evidence_basis=_text(value.get("evidence_basis"), 80) or None,
            decision_fingerprint=_text(value.get("decision_fingerprint"), 80) or None,
            focus_mode=_text(value.get("focus_mode"), 24) or None,
        )
        if session.current_attempt_id and not any(item.attempt_id == session.current_attempt_id for item in attempts):
            session.current_attempt_id = attempts[-1].attempt_id if attempts else None
        return session

    def add_attempt(self, attempt: MeasurementAttempt) -> bool:
        if attempt.session_id != self.session_id:
            return False
        if self.attachment_id and attempt.attachment_id and self.attachment_id != attempt.attachment_id:
            return False
        if self.panel_id and attempt.panel_id and self.panel_id != attempt.panel_id:
            return False
        if any(item.attempt_id == attempt.attempt_id for item in self.attempts):
            return False
        if attempt.target is not None:
            if self.repair_attempt_count >= self.max_repair_attempts:
                return False
            if self.has_target(attempt.target, tool=attempt.tool):
                return False
        self.attempts.append(attempt)
        self.attempts = self.attempts[-MAX_MEASUREMENT_ATTEMPTS:]
        self.current_attempt_id = attempt.attempt_id
        self.selected_refs = ()
        self.discarded_refs = ()
        self.decision_status = "pending"
        self.decision_attempt_id = None
        self.series_map = {}
        self.evidence_basis = None
        self.decision_fingerprint = None
        self.focus_mode = attempt.focus_mode
        return True

    @property
    def repair_attempt_count(self) -> int:
        return sum(1 for item in self.attempts if item.target is not None)

    @property
    def repair_budget_remaining(self) -> int:
        return max(0, self.max_repair_attempts - self.repair_attempt_count)

    def pending_repair_action(self) -> dict[str, Any] | None:
        current = next(
            (item for item in reversed(self.attempts) if item.attempt_id == self.current_attempt_id),
            None,
        )
        if current is None or not isinstance(current.quality, Mapping):
            return None
        action = current.quality.get("repair_action")
        if not isinstance(action, Mapping):
            return None
        result = dict(action)
        result["budget_remaining"] = self.repair_budget_remaining
        if self.repair_budget_remaining <= 0:
            result["status"] = "exhausted"
            result["next_action"] = "修复预算已用尽；保留当前失败证据，不得继续创建定向重测"
        return result

    def has_target(self, target: Mapping[str, Any] | None, *, tool: str | None = None) -> bool:
        fingerprint = measurement_target_fingerprint(target, tool=tool)
        return bool(fingerprint and any(item.target_fingerprint == fingerprint for item in self.attempts))

    def current_attempt(self) -> MeasurementAttempt | None:
        return next(
            (item for item in reversed(self.attempts) if item.attempt_id == self.current_attempt_id),
            None,
        )

    def evidence_refs(self) -> tuple[dict[str, Any], ...]:
        current = self.current_attempt()
        if current is None:
            return ()
        return current.evidence_refs

    def resolve_refs(
        self,
        refs: object,
        *,
        mode: str = "include",
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Resolve compact refs against the current attempt's bounded index."""
        normalized_refs = normalize_evidence_refs(refs)
        if not normalized_refs:
            return [], _repair_error("measurement_target_refs_empty", "measurement_target.refs must contain at least one known evidence ref")
        if mode not in MEASUREMENT_FOCUS_MODES:
            return [], _repair_error("measurement_target_mode_invalid", "measurement_target.mode must be include or exclude")
        index = {str(item.get("ref")): dict(item) for item in self.evidence_refs() if isinstance(item, Mapping)}
        missing = [ref for ref in normalized_refs if ref not in index]
        if missing:
            return [], {
                **_repair_error("measurement_target_ref_unknown", "one or more measurement target refs are not in the current attempt"),
                "missing_refs": missing[:MAX_MEASUREMENT_REFS],
            }
        resolved = [index[ref] for ref in normalized_refs]
        if not any(isinstance(item.get("bbox_px"), list) for item in resolved):
            return [], _repair_error("measurement_target_ref_unbounded", "the selected evidence refs have no bounded geometry")
        return resolved, None

    def record_decision(
        self,
        *,
        attempt_id: str,
        selected_refs: object = (),
        discarded_refs: object = (),
        status: str = "selected",
        series_map: Mapping[str, Any] | None = None,
        evidence_basis: str | None = None,
    ) -> bool:
        if attempt_id != self.current_attempt_id:
            return False
        selected = normalize_evidence_refs(selected_refs)
        discarded = normalize_evidence_refs(discarded_refs)
        available = {str(item.get("ref")) for item in self.evidence_refs() if isinstance(item, Mapping)}
        if any(ref not in available for ref in (*selected, *discarded)):
            return False
        if set(selected) & set(discarded):
            return False
        decision_status = _text(status, 32).lower() or "selected"
        if decision_status not in {"pending", "selected", "discarded", "abandoned"}:
            return False
        if not selected and decision_status not in {"pending", "discarded", "abandoned"}:
            return False
        normalized_series_map = {
            _text(key, 80): _text(value, 120)
            for key, value in list((series_map or {}).items())[:MAX_MEASUREMENT_TARGET_FIELDS]
            if _text(key, 80) and _text(value, 120)
        }
        normalized_basis = _text(evidence_basis, 80) or None
        fingerprint_payload = {
            "attempt_id": attempt_id,
            "selected_refs": list(selected),
            "discarded_refs": list(discarded),
            "status": decision_status,
            "series_map": normalized_series_map,
            "evidence_basis": normalized_basis,
        }
        decision_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        if self.decision_fingerprint == decision_fingerprint and self.decision_attempt_id == attempt_id:
            return True
        self.selected_refs = selected
        self.discarded_refs = discarded
        self.decision_status = decision_status
        self.decision_attempt_id = attempt_id
        self.series_map = normalized_series_map
        self.evidence_basis = normalized_basis
        self.decision_fingerprint = decision_fingerprint
        current_index = next(
            (index for index, item in enumerate(self.attempts) if item.attempt_id == attempt_id),
            None,
        )
        current = self.current_attempt()
        if current_index is not None and current is not None:
            self.attempts[current_index] = replace(
                current,
                selected_refs=selected,
                discarded_refs=discarded,
                decision_status=decision_status,
                series_map=normalized_series_map,
                evidence_basis=normalized_basis,
            )
        self.focus_mode = current.focus_mode if current else self.focus_mode
        return True

    def validate_repair_target(
        self,
        target: Mapping[str, Any] | None,
        *,
        tool: str,
        parent_attempt_id: str | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        normalized = normalize_measurement_target(target)
        if normalized is None:
            return None, _repair_error("measurement_target_invalid", "measurement_target is invalid")
        if self.panel_id and normalized.get("panel_id") not in {None, self.panel_id}:
            return None, _repair_error("measurement_panel_mismatch", "measurement target does not belong to the current panel")
        current_parent = parent_attempt_id or self.current_attempt_id
        requested_parent = normalized.get("parent_attempt_id") or current_parent
        if not requested_parent or requested_parent != self.current_attempt_id:
            return None, _repair_error("measurement_parent_mismatch", "measurement target parent attempt is not the current attempt")
        if self.repair_attempt_count >= self.max_repair_attempts:
            return None, _repair_error("measurement_repair_budget_exhausted", "measurement repair budget is exhausted", status="exhausted")
        if self.has_target(normalized, tool=tool):
            return None, _repair_error("measurement_target_duplicate", "equivalent measurement target was already attempted", status="rejected")
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
        normalized["panel_id"] = self.panel_id or normalized.get("panel_id")
        normalized["parent_attempt_id"] = requested_parent
        return normalized, None

    def accepted_attempt(self) -> MeasurementAttempt | None:
        for attempt in reversed(self.attempts):
            if attempt.attempt_id == self.current_attempt_id and attempt.status == "accepted":
                issues = attempt.quality.get("issues", []) if isinstance(attempt.quality, Mapping) else []
                if not any(isinstance(item, Mapping) and item.get("severity") == "blocking" for item in issues):
                    return attempt
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "attachment_id": self.attachment_id,
            "panel_id": self.panel_id,
            "current_attempt_id": self.current_attempt_id,
            "max_repair_attempts": self.max_repair_attempts,
            "selected_refs": list(self.selected_refs),
            "discarded_refs": list(self.discarded_refs),
            "decision_status": self.decision_status,
            "decision_attempt_id": self.decision_attempt_id,
            "series_map": _json_safe(self.series_map),
            "evidence_basis": self.evidence_basis,
            "decision_fingerprint": self.decision_fingerprint,
            "focus_mode": self.focus_mode,
            "attempts": [item.to_dict() for item in self.attempts[-MAX_MEASUREMENT_ATTEMPTS:]],
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
    session.add_attempt(attempt)
    while len(sessions) > 32:
        sessions.pop(next(iter(sessions)))
    return session


def measurement_gate(
    reference: object,
    context: Mapping[str, Any] | None,
    *,
    evidence_refs: object | None = None,
    expected_attachment_id: str | None = None,
    expected_panel_id: str | None = None,
    location: str = "measurement_ref",
    require_decision: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate a model-provided reference against code-owned session state."""
    if not isinstance(reference, Mapping):
        return None, {
            "status": "blocked",
            "code": "measurement_reference_invalid",
            "location": location,
            "message": "measurement_ref must be a structured server-issued reference",
            "next_action": "重新读取当前测量观察并使用其 measurement.reference",
        }
    required = ("session_id", "attempt_id", "attachment_id")
    if any(not isinstance(reference.get(key), str) or not str(reference.get(key)).strip() for key in required):
        return None, {
            "status": "blocked",
            "code": "measurement_reference_incomplete",
            "location": location,
            "message": "measurement_ref is missing a required source or attempt identity",
            "next_action": "重新读取当前测量观察，不要手写 measurement_ref",
        }
    if expected_attachment_id and reference.get("attachment_id") != expected_attachment_id:
        return None, {
            "status": "blocked",
            "code": "measurement_source_mismatch",
            "location": location,
            "message": "measurement attachment does not match the assembled source",
            "next_action": "恢复同一 attachment 的测量证据",
        }
    if expected_panel_id and reference.get("panel_id") != expected_panel_id:
        return None, {
            "status": "blocked",
            "code": "measurement_panel_mismatch",
            "location": location,
            "message": "measurement panel does not match the assembled source",
            "next_action": "恢复同一 panel 的测量证据",
        }
    if not isinstance(context, Mapping):
        return None, {
            "status": "blocked",
            "code": "measurement_context_unavailable",
            "location": location,
            "message": "server-owned measurement session is unavailable in this run",
            "next_action": "重新观察当前 panel 后再组装",
        }
    raw_session = context.get(str(reference["session_id"]))
    session = raw_session if isinstance(raw_session, MeasurementSession) else MeasurementSession.from_dict(raw_session) if isinstance(raw_session, Mapping) else None
    if session is None:
        return None, {
            "status": "blocked",
            "code": "measurement_session_not_found",
            "location": location,
            "message": "measurement session is not registered for the current run",
            "next_action": "重新观察当前 panel 的测量结果",
        }
    attempt = next((item for item in session.attempts if item.attempt_id == reference.get("attempt_id")), None)
    if attempt is None:
        return None, {
            "status": "blocked",
            "code": "measurement_attempt_not_found",
            "location": location,
            "message": "measurement attempt is not registered for the current session",
            "next_action": "重新读取当前测量观察并重试组装",
        }
    if attempt.attachment_id != reference.get("attachment_id") or attempt.panel_id != reference.get("panel_id"):
        return None, {
            "status": "blocked",
            "code": "measurement_lineage_mismatch",
            "location": location,
            "message": "measurement attempt lineage does not match its reference",
            "next_action": "只使用当前 attachment/panel 下的最新测量证据",
        }
    quality = attempt.quality if isinstance(attempt.quality, Mapping) else {}
    if attempt.status in {"failed", "unsupported"}:
        issues = list(quality.get("issues", []))[:4] if isinstance(quality.get("issues"), list) else []
        return None, {
            "status": "blocked",
            "code": "measurement_execution_unusable",
            "location": location,
            "message": f"measurement attempt execution status is {attempt.status}",
            "measurement_status": attempt.status,
            "issues": _json_safe(issues),
            "repair_action": _json_safe(quality.get("repair_action")) if isinstance(quality.get("repair_action"), Mapping) else None,
            "next_action": "改用可用的当前 observation，或由主 Agent 显式请求有界补充",
        }
    if require_decision and attempt.evidence_refs and any(
        isinstance(item, Mapping) and isinstance(item.get("bbox_px"), list)
        for item in attempt.evidence_refs
    ):
        if (
            session.decision_attempt_id != attempt.attempt_id
            or session.decision_status not in {"selected", "accepted", "discarded", "abandoned"}
            or (session.decision_status in {"selected", "accepted"} and not session.selected_refs)
        ):
            return None, {
                "status": "blocked",
                "code": "measurement_decision_required",
                "location": f"{location}.selected_refs",
                "message": "主 Agent 尚未明确选择当前 attempt 的测量证据",
                "measurement_status": attempt.status,
                "available_refs": [item.get("ref") for item in attempt.evidence_refs[:MAX_MEASUREMENT_REFS]],
                "next_action": "先根据 overlay 和 evidence.refs 提交 measurement_decision，再组装 ChartSpec",
            }
    requested_refs: tuple[str, ...] | None = None
    if evidence_refs is not None:
        if not isinstance(evidence_refs, (list, tuple, set)):
            return None, {
                "status": "blocked",
                "code": "measurement_evidence_refs_invalid",
                "location": f"{location}.evidence_refs",
                "message": "evidence_refs must be an array of compact evidence references",
                "next_action": "只提交当前 measurement attempt 返回的 evidence refs",
            }
        requested_refs = normalize_evidence_refs(evidence_refs)
        available_refs = {
            str(item.get("ref"))
            for item in attempt.evidence_refs
            if isinstance(item, Mapping) and item.get("ref")
        }
        missing_refs = [ref for ref in requested_refs if ref not in available_refs]
        if missing_refs:
            return None, {
                "status": "blocked",
                "code": "measurement_evidence_ref_unknown",
                "location": f"{location}.evidence_refs",
                "message": "one or more evidence_refs are not in the referenced measurement attempt",
                "missing_refs": missing_refs[:MAX_MEASUREMENT_REFS],
                "available_refs": sorted(available_refs)[:MAX_MEASUREMENT_REFS],
                "next_action": "重新读取当前 measurement observation 后修正 evidence_refs",
            }

    effective_refs = requested_refs if requested_refs is not None else session.selected_refs
    if effective_refs:
        selected_index = {
            str(item.get("ref")): item
            for item in attempt.evidence_refs
            if isinstance(item, Mapping)
        }
        empty_refs = [
            ref
            for ref in effective_refs
            if isinstance(selected_index.get(ref), Mapping)
            and selected_index[ref].get("kind") in {"bar", "point", "sector"}
            and selected_index[ref].get("has_numeric_value") is False
        ]
        if empty_refs:
            return None, {
                "status": "blocked",
                "code": "measurement_selected_ref_empty",
                "location": f"{location}.evidence_refs",
                "message": "selected measurement refs do not contain the numeric fields required by the assembled chart",
                "selected_refs": empty_refs[:MAX_MEASUREMENT_REFS],
                "next_action": "舍弃空值候选，或由主 Agent 对对应区域发起一次有界补充",
            }
    selected_status = (
        session.decision_status
        if requested_refs is None and session.decision_status in {"discarded", "abandoned"}
        else "accepted"
        if attempt.status == "accepted"
        else "selected"
    )
    return {
        "status": selected_status,
        "measurement_status": attempt.status,
        "session_id": session.session_id,
        "attempt_id": attempt.attempt_id,
        "attachment_id": attempt.attachment_id,
        "panel_id": attempt.panel_id,
        "tool": attempt.tool,
        "quality": _json_safe(attempt.quality),
        "observation_scope": _json_safe(attempt.observation_scope),
        "evidence_refs": list(effective_refs),
        # Compatibility fields for old readers. New callers use evidence_refs
        # and are not required to create a decision state.
        "selected_refs": list(effective_refs),
        "discarded_refs": list(session.discarded_refs) if requested_refs is None else [],
        "decision_status": session.decision_status if requested_refs is None else "inferred",
        "series_map": _json_safe(session.series_map),
        "evidence_basis": session.evidence_basis,
        "quality_warnings": list(quality.get("warnings") or [])[:12] if isinstance(quality.get("warnings"), list) else [],
    }, None
