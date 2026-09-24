"""Observation-resource and artifact projections used by the Agent loop."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..trace import summarize_result
from ..tools.core.result import DispatchedObservation


def attach_visual_observation_refs(
    observation: DispatchedObservation,
    references: Sequence[dict[str, Any]],
) -> DispatchedObservation:
    """Attach managed visual-resource refs to decomposition crop records."""
    if not references or not observation.images:
        return observation
    try:
        payload = json.loads(observation.content)
    except (TypeError, json.JSONDecodeError):
        return observation
    if not isinstance(payload, dict):
        return observation
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("panels"), list):
        return observation
    by_key = {
        str(reference.get("resourceKey")): reference
        for reference in references
        if isinstance(reference, dict) and isinstance(reference.get("resourceKey"), str)
    }
    ordered_refs = [reference for reference in references if isinstance(reference, dict)]
    for image_index, image in enumerate(observation.images):
        metadata = image.metadata if isinstance(image.metadata, Mapping) else {}
        panel_id = metadata.get("panel_id")
        resource_key = metadata.get("resource_key")
        if not isinstance(panel_id, str):
            continue
        panel = next((item for item in data["panels"] if isinstance(item, dict) and item.get("id") == panel_id), None)
        if panel is None or not isinstance(panel.get("crop"), dict):
            continue
        reference = by_key.get(resource_key) if isinstance(resource_key, str) else None
        if reference is None and len(ordered_refs) == len(observation.images):
            reference = ordered_refs[image_index]
        crop = dict(panel["crop"])
        crop["resource_ref"] = dict(reference) if isinstance(reference, dict) else None
        crop["status"] = "persisted" if reference is not None else "unavailable"
        panel["crop"] = crop
        layout_context = panel.get("layout_context")
        if isinstance(layout_context, dict):
            panel_context = dict(layout_context.get("panel") or {})
            panel_context["crop_ref"] = crop["resource_ref"]
            layout_context["panel"] = panel_context
    payload["data"] = data
    return DispatchedObservation(content=json.dumps(payload, ensure_ascii=False), images=observation.images)


def artifact_records_from_observation(
    tool_name: str,
    call_id: str,
    content: str,
    source_attachment_ids: Sequence[str],
    references: Sequence[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Create a bounded attribution index while retaining the native result."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    warnings = payload.get("warnings", [])
    if isinstance(data, dict) and isinstance(data.get("warnings"), list):
        warnings = data["warnings"]
    warnings = [str(item)[:240] for item in warnings[:12]] if isinstance(warnings, list) else []
    panels = data.get("panels") if isinstance(data, dict) else None
    panel_ids = [str(item.get("id"))[:96] for item in panels if isinstance(item, dict) and item.get("id")] if isinstance(panels, list) else []
    measurement = data.get("measurement") if isinstance(data, dict) else None
    status = "failed" if payload.get("error") else "observed"
    if isinstance(measurement, dict):
        status = str(measurement.get("status") or status)[:64]
        reference = measurement.get("reference")
        if isinstance(reference, dict) and isinstance(reference.get("panel_id"), str):
            panel_ids = [reference["panel_id"]]
    measurement_quality = measurement.get("quality") if isinstance(measurement, dict) else None
    measurement_issues = measurement_quality.get("issues", []) if isinstance(measurement_quality, dict) else []
    measurement_evidence = measurement.get("evidence") if isinstance(measurement, dict) and isinstance(measurement.get("evidence"), dict) else {}
    records: list[dict[str, Any]] = [{
        "artifact_id": f"observation:{call_id}"[:160],
        "kind": "observation",
        "status": status,
        "source_attachment_ids": list(source_attachment_ids[:16]),
        "panel_ids": panel_ids[:16],
        "lineage": [tool_name],
        "confidence": data.get("confidence") if isinstance(data, dict) else None,
        "warnings": warnings,
        "resource_refs": list(references[:16]),
    }]
    if isinstance(measurement, dict):
        attempt = measurement.get("attempt") if isinstance(measurement.get("attempt"), dict) else {}
        records[0].update({
            "measurement_status": status,
            "measurement_reference": dict(measurement.get("reference") or {}) if isinstance(measurement.get("reference"), dict) else None,
            "measurement_issues": [item for item in measurement_issues[:8] if isinstance(item, dict)],
            "measurement_evidence_refs": list(measurement_evidence.get("refs") or [])[:64] if isinstance(measurement_evidence.get("refs"), list) else [],
            "measurement_series_metadata": [item for item in measurement_evidence.get("refs", [])[:64] if isinstance(item, dict) and item.get("kind") == "series"] if isinstance(measurement_evidence.get("refs"), list) else [],
            "measurement_scope": dict(attempt.get("scope") or {}) if isinstance(attempt.get("scope"), Mapping) else None,
            "measurement_observation_scope": dict(measurement.get("observation_scope") or {}) if isinstance(measurement.get("observation_scope"), Mapping) else None,
            "measurement_effective_scope": dict(measurement.get("effective_scope") or {}) if isinstance(measurement.get("effective_scope"), Mapping) else None,
        })
    context_fields = chart_context_trace_fields(content)
    if context_fields:
        records[0].update({key: value for key, value in context_fields.items() if key in {"source_scope", "coverage"}})
    if tool_name == "assemble_spec" and not payload.get("error"):
        kind = data.get("kind") if isinstance(data, dict) else None
        if kind in {"chart_figure", "chart_spec_collection"}:
            artifact_kind = "ChartFigure" if kind == "chart_figure" else "ChartSpecCollection"
            artifact_id = data.get("figure_id" if kind == "chart_figure" else "collection_id") or call_id
            records.append({
                "artifact_id": f"{artifact_kind}:{artifact_id}"[:160],
                "kind": artifact_kind,
                "status": "validated",
                "source_attachment_ids": list(source_attachment_ids[:16]),
                "panel_ids": panel_ids[:16],
                "lineage": [f"observation:{call_id}"],
                "warnings": warnings,
                "generation_context": data.get("generation_context"),
                "coverage": data.get("coverage"),
                "child_chart_ids": [item.get("chart_id") for item in data.get("charts", []) if isinstance(item, dict)] if kind == "chart_figure" else [],
            })
        else:
            records.append({
                "artifact_id": f"ChartSpec:{call_id}"[:160],
                "kind": "ChartSpec",
                "status": "validated",
                "source_attachment_ids": list(source_attachment_ids[:16]),
                "panel_ids": panel_ids[:16],
                "lineage": [f"observation:{call_id}"],
                "generation_context": data.get("generation_context"),
                "coverage": data.get("coverage"),
            })
    if isinstance(panels, list):
        for item in panels[:16]:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            crop = item.get("crop") if isinstance(item.get("crop"), dict) else {}
            crop_refs = [crop.get("resource_ref")] if isinstance(crop.get("resource_ref"), dict) else []
            records.append({
                "artifact_id": f"panel:{item['id']}"[:160],
                "kind": "panel",
                "status": item.get("status", "observed"),
                "source_attachment_ids": list(source_attachment_ids[:16]),
                "panel_ids": [str(item["id"])],
                "lineage": [f"observation:{call_id}"],
                "confidence": item.get("confidence"),
                "warnings": item.get("warnings", []),
                "resource_refs": crop_refs or list(references[:16]),
            })
    verification_items = data.get("chartVerification") if isinstance(data, dict) else None
    if isinstance(verification_items, list):
        for item in verification_items[:16]:
            if not isinstance(item, Mapping):
                continue
            verification = item.get("verification")
            if not isinstance(verification, Mapping):
                continue
            staged_ref = item.get("stagedRef")
            records.append({
                "artifact_id": item.get("artifactId") or staged_ref or f"chart:{call_id}",
                "kind": "generated_chart",
                "status": verification.get("status", "unavailable"),
                "staged_ref": staged_ref,
                "artifact_id_published": item.get("artifactId"),
                "verification": dict(verification),
                "lineage": [f"observation:{call_id}"],
            })
    return records[:48]


def trace_result_summary(content: str) -> Any:
    """Keep tool-result traces useful without duplicating image data."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return summarize_result(content)
    if isinstance(payload, dict):
        payload = dict(payload)
        payload.pop("chartVerification", None)
        data = payload.get("data")
        if isinstance(data, dict) and "measurement" in data:
            payload["data"] = dict(data)
            payload["data"].pop("measurement", None)
        if isinstance(payload.get("data"), dict):
            payload["data"].pop("chartVerification", None)
        content = json.dumps(payload, ensure_ascii=False)
    return summarize_result(content)


def chart_context_trace_fields(content: str) -> dict[str, Any]:
    """Project bounded source-scope and coverage facts beside trace summaries."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    if not isinstance(data, Mapping):
        return {}
    fields: dict[str, Any] = {}
    context = data.get("generation_context") or data.get("generationContext")
    if isinstance(context, Mapping):
        source_scope = context.get("source_scope") or context.get("sourceScope")
        coverage = context.get("coverage")
        if isinstance(source_scope, Mapping):
            fields["source_scope"] = {key: source_scope.get(key) for key in ("attachment_id", "attachmentId", "panel_ids", "panelIds", "revision") if source_scope.get(key) is not None}
        if isinstance(coverage, Mapping):
            fields["coverage"] = {key: coverage.get(key) for key in ("basis", "source_series", "sourceSeries", "represented_series", "representedSeries", "intentionally_omitted_series", "intentionallyOmittedSeries", "status") if coverage.get(key) is not None}
    measurement = data.get("measurement")
    if isinstance(measurement, Mapping):
        reference = measurement.get("reference") if isinstance(measurement.get("reference"), Mapping) else {}
        fields["source_scope"] = {
            "attachment_id": reference.get("attachment_id"),
            "panel_ids": [reference.get("panel_id")] if reference.get("panel_id") else [],
        }
    return {key: value for key, value in fields.items() if value not in (None, {}, [], "")}


__all__ = [
    "artifact_records_from_observation",
    "attach_visual_observation_refs",
    "chart_context_trace_fields",
    "trace_result_summary",
]
