"""Measurement result registration, scoped-call validation, and projections."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..measurement import (
    MeasurementSession,
    measurement_target_fingerprint,
    register_measurement,
)


def measurement_data_from_content(content: str) -> Mapping[str, Any] | None:
    """Return the tool result data containing a measurement envelope."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    data = payload.get("data")
    return data if isinstance(data, Mapping) and isinstance(data.get("measurement"), Mapping) else None


def register_measurement_observation(
    sessions: dict[str, MeasurementSession],
    content: str,
) -> MeasurementSession | None:
    """Store the latest result for the session represented by a tool call."""
    data = measurement_data_from_content(content)
    return register_measurement(sessions, data) if data is not None else None


def measurement_evidence_from_sessions(
    sessions: Mapping[str, MeasurementSession],
) -> list[dict[str, Any]]:
    """Project current candidate evidence for the model without a repair queue."""
    result: list[dict[str, Any]] = []
    for session in sessions.values():
        attempt = session.current_attempt()
        if attempt is None:
            continue
        quality = attempt.quality
        result.append(
            {
                "measurement_ref": attempt.measurement_ref(),
                "attachment_id": attempt.attachment_id,
                "panel_id": attempt.panel_id,
                "tool": attempt.tool,
                "status": attempt.status,
                "scope": attempt.scope,
                "effective_scope": attempt.effective_scope,
                "observation_scope": attempt.observation_scope,
                "evidence_refs": list(attempt.evidence_refs)[:64],
                "series_metadata": list(attempt.series_metadata)[:64],
                "warnings": list(quality.get("warnings") or [])[:12],
                "issues": list(quality.get("issues") or [])[:8],
            }
        )
    return result[:32]


def measurement_target_context(
    target: object,
    sessions: Mapping[str, MeasurementSession],
    *,
    source_attachment_id: str | None,
    source_panel_id: str | None,
    source_tool: str,
    parent_attempt_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate an explicit local measurement request against current source state."""
    if not isinstance(target, Mapping):
        return None, _target_error("measurement_target_invalid", "measurement_target must be an object")
    if not source_attachment_id:
        return None, _target_error("measurement_source_mismatch", "local measurement requires the authorized current attachment")
    if target.get("attachment_id") not in {None, source_attachment_id}:
        return None, _target_error("measurement_source_mismatch", "measurement target does not belong to the current attachment")
    if target.get("panel_id") not in {None, source_panel_id}:
        return None, _target_error("measurement_panel_mismatch", "measurement target does not belong to the current panel")

    session = next(
        (
            item for item in reversed(list(sessions.values()))
            if item.attachment_id == source_attachment_id and item.panel_id == source_panel_id
        ),
        None,
    )
    if session is None:
        return None, _target_error("measurement_session_not_found", "local measurement requires a current result for the same panel")
    normalized, error = session.validate_measurement_target(
        target,
        parent_attempt_id=parent_attempt_id,
    )
    if error is not None or normalized is None:
        return None, error or _target_error("measurement_target_invalid", "measurement target is invalid")

    normalized["attachment_id"] = source_attachment_id
    normalized["panel_id"] = source_panel_id
    normalized["target_fingerprint"] = measurement_target_fingerprint(normalized, tool=source_tool)
    return normalized, None


def measurement_trace_fields(content: str) -> dict[str, Any]:
    """Project bounded source, evidence, and quality facts for a tool result."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return {}
    data = payload.get("data") if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping) else payload
    measurement = data.get("measurement") if isinstance(data, Mapping) else None
    if not isinstance(measurement, Mapping):
        return {}
    reference = measurement.get("reference") if isinstance(measurement.get("reference"), Mapping) else {}
    attempt = measurement.get("attempt") if isinstance(measurement.get("attempt"), Mapping) else {}
    quality = measurement.get("quality") if isinstance(measurement.get("quality"), Mapping) else {}
    evidence = measurement.get("evidence") if isinstance(measurement.get("evidence"), Mapping) else {}
    effective_scope = measurement.get("effective_scope") or attempt.get("effective_scope")
    fields: dict[str, Any] = {
        "measurement_status": str(measurement.get("status") or "unknown")[:48],
        "measurement_reference": {
            key: reference.get(key)
            for key in ("session_id", "attempt_id", "attachment_id", "panel_id")
            if reference.get(key) is not None
        },
        "measurement_evidence_refs": list(evidence.get("refs") or [])[:64]
        if isinstance(evidence.get("refs"), list) else [],
        "measurement_series_metadata": [
            item for item in evidence.get("refs", [])[:64]
            if isinstance(item, Mapping) and item.get("kind") == "series"
        ] if isinstance(evidence.get("refs"), list) else [],
        "measurement_quality": {
            "blocking": bool(quality.get("blocking")),
            "warnings": list(quality.get("warnings") or [])[:12]
            if isinstance(quality.get("warnings"), list) else [],
            "issues": list(quality.get("issues") or [])[:8]
            if isinstance(quality.get("issues"), list) else [],
        },
    }
    scope = attempt.get("scope")
    if isinstance(scope, Mapping):
        fields["measurement_scope"] = dict(scope)
    if isinstance(effective_scope, Mapping):
        fields["measurement_effective_scope"] = dict(effective_scope)
    observation_scope = measurement.get("observation_scope")
    if isinstance(observation_scope, Mapping):
        fields["measurement_observation_scope"] = dict(observation_scope)
    target = measurement.get("target")
    if isinstance(target, Mapping):
        fields["measurement_target"] = {
            key: target.get(key)
            for key in (
                "target_id", "panel_id", "parent_attempt_id", "region_kind", "fields",
                "bbox_source_px", "source_image_size", "bbox_px", "local_image_size", "clipped",
            )
            if target.get(key) is not None
        }
    return fields


def _target_error(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "rejected",
        "code": code,
        "location": "measurement_target",
        "message": message,
        "next_action": "根据当前测量结果为同一 panel 指定一个有界区域",
    }
