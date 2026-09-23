"""Observation-resource and artifact projections used by the Agent loop.

The functions in this module deliberately keep the native tool observation
unchanged except for the managed resource references that belong in the
decomposition payload.  They are projection helpers, not an alternate tool
execution path.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..trace import summarize_result
from ..tools.core.result import DispatchedObservation, GeneratedImage


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
        metadata = image.metadata if hasattr(image.metadata, "get") else {}
        panel_id = metadata.get("panel_id") if isinstance(metadata, dict) else None
        resource_key = metadata.get("resource_key") if isinstance(metadata, dict) else None
        if not isinstance(panel_id, str):
            continue
        panel = next(
            (item for item in data["panels"] if isinstance(item, dict) and item.get("id") == panel_id),
            None,
        )
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
    return DispatchedObservation(
        content=json.dumps(payload, ensure_ascii=False),
        images=observation.images,
    )


def artifact_records_from_observation(
    tool_name: str,
    call_id: str,
    content: str,
    source_attachment_ids: Sequence[str],
    references: Sequence[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Create a small attributable index while retaining the native result."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    warnings = payload.get("warnings", [])
    if isinstance(data, dict) and isinstance(data.get("warnings"), list):
        warnings = data.get("warnings")
    warnings = [str(item)[:240] for item in warnings[:12]] if isinstance(warnings, list) else []
    panel_ids = []
    panels = data.get("panels") if isinstance(data, dict) else None
    if isinstance(panels, list):
        panel_ids = [str(item.get("id"))[:96] for item in panels if isinstance(item, dict) and item.get("id")]
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
    records: list[dict[str, Any]] = [
        {
            "artifact_id": f"observation:{call_id}"[:128],
            "kind": "observation",
            "status": status,
            "source_attachment_ids": list(source_attachment_ids),
            "panel_ids": panel_ids,
            "lineage": [tool_name],
            "confidence": data.get("confidence") if isinstance(data, dict) else None,
            "warnings": warnings,
            "resource_refs": list(references),
        }
    ]
    if isinstance(measurement, dict):
        records[0].update(
            {
                "measurement_status": status,
                "measurement_reference": dict(measurement.get("reference") or {}) if isinstance(measurement.get("reference"), dict) else None,
                "measurement_issues": [item for item in measurement_issues[:8] if isinstance(item, dict)],
                "measurement_evidence_refs": list(measurement_evidence.get("refs") or [])[:64] if isinstance(measurement_evidence.get("refs"), list) else [],
                "measurement_series_metadata": [
                    item for item in measurement_evidence.get("refs", [])[:64]
                    if isinstance(item, dict) and item.get("kind") == "series"
                ] if isinstance(measurement_evidence.get("refs"), list) else [],
                "measurement_scope": dict(measurement.get("attempt", {}).get("scope") or {})
                if isinstance(measurement.get("attempt"), dict) and isinstance(measurement.get("attempt", {}).get("scope"), Mapping) else None,
                "measurement_observation_scope": dict(measurement.get("observation_scope") or {}) if isinstance(measurement.get("observation_scope"), Mapping) else None,
                "measurement_effective_scope": dict(measurement.get("effective_scope") or {}) if isinstance(measurement.get("effective_scope"), Mapping) else None,
            }
        )
    lifecycle = lifecycle_trace_fields(content)
    if lifecycle:
        records[0].update(
            {
                key: lifecycle[key]
                for key in (
                    "candidate_id",
                    "review_id",
                    "collection_id",
                    "attempt",
                    "parent_attempt",
                    "candidate_status",
                    "review_status",
                    "publication_status",
                    "source_scope",
                    "coverage",
                    "repair_kind",
                )
                if key in lifecycle
            }
        )
    if tool_name == "assemble_spec" and not payload.get("error"):
        assembled_kind = data.get("kind") if isinstance(data, dict) else None
        if assembled_kind == "chart_figure":
            records.append(
                {
                    "artifact_id": f"figure:{data.get('figure_id') or call_id}"[:128],
                    "kind": "ChartFigure",
                    "status": "validated",
                    "source_attachment_ids": [data.get("source", {}).get("attachment_id")] if isinstance(data.get("source"), dict) else list(source_attachment_ids),
                    "panel_ids": [data.get("source", {}).get("panel_id")] if isinstance(data.get("source"), dict) else panel_ids,
                    "lineage": [f"observation:{call_id}"],
                    "warnings": warnings,
                    "provenance": data.get("provenance"),
                    "coverage": data.get("coverage"),
                    "generation_context": data.get("generation_context"),
                    "source_scope": lifecycle.get("source_scope"),
                    "repair_kind": lifecycle.get("repair_kind"),
                    "child_chart_ids": [item.get("chart_id") for item in data.get("charts", []) if isinstance(item, dict)],
                }
            )
        elif assembled_kind == "chart_spec_collection":
            records.append(
                {
                    "artifact_id": f"chartspec-collection:{data.get('collection_id') or call_id}"[:128],
                    "kind": "ChartSpecCollection",
                    "status": "validated",
                    "source_attachment_ids": list(source_attachment_ids),
                    "panel_ids": panel_ids,
                    "lineage": [f"observation:{call_id}"],
                    "warnings": warnings,
                    "provenance": data.get("provenance"),
                    "generation_context": data.get("generation_context"),
                    "source_scope": lifecycle.get("source_scope"),
                    "coverage": data.get("coverage"),
                    "figure_count": len(data.get("figures", [])) if isinstance(data.get("figures"), list) else 0,
                }
            )
        else:
            records.append(
                {
                    "artifact_id": f"chartspec:{call_id}"[:128],
                    "kind": "ChartSpec",
                    "status": "validated",
                    "source_attachment_ids": list(source_attachment_ids),
                    "panel_ids": panel_ids,
                    "lineage": [f"observation:{call_id}"],
                    "warnings": warnings,
                    "provenance": data.get("provenance"),
                    "generation_context": data.get("generation_context"),
                    "source_scope": lifecycle.get("source_scope"),
                    "coverage": data.get("coverage"),
                }
            )
    for item in panels or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        crop = item.get("crop") if isinstance(item.get("crop"), dict) else {}
        crop_refs = [crop.get("resource_ref")] if isinstance(crop.get("resource_ref"), dict) else []
        records.append(
            {
                "artifact_id": f"panel:{item['id']}"[:128],
                "kind": "panel",
                "status": item.get("status", "observed"),
                "source_attachment_ids": list(source_attachment_ids),
                "panel_ids": [str(item["id"])],
                "lineage": [f"observation:{call_id}"],
                "confidence": item.get("confidence"),
                "warnings": item.get("warnings", []),
                "resource_refs": crop_refs or list(references),
            }
        )
    review_items = data.get("review") if isinstance(data, dict) else None
    if not isinstance(review_items, list) and isinstance(data, dict) and isinstance(data.get("candidate"), dict):
        review_items = [data["candidate"]]
    if isinstance(review_items, list):
        for index, item in enumerate(review_items[:16], start=1):
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidateId") or f"{call_id}:{index}")[:128]
            candidate_status = str(item.get("candidateStatus") or item.get("status") or "candidate")[:64]
            records.append(
                {
                    "artifact_id": f"candidate:{candidate_id}"[:128],
                    "kind": "candidate",
                    "status": candidate_status,
                    "source_attachment_ids": item.get("sourceAttachmentIds", source_attachment_ids),
                    "panel_ids": item.get("panelIds", panel_ids),
                    "lineage": [f"observation:{call_id}"],
                    "warnings": warnings,
                    "resource_refs": list(references),
                    "candidate_id": candidate_id,
                    "attempt": item.get("candidateAttempt") or item.get("lineageAttempt"),
                    "parent_attempt": item.get("parentAttempt") or item.get("parentCandidateId"),
                    "source_scope": (item.get("generationContext") or {}).get("source_scope") if isinstance(item.get("generationContext"), Mapping) else None,
                    "coverage": item.get("coverage") or ((item.get("generationContext") or {}).get("coverage") if isinstance(item.get("generationContext"), Mapping) else None),
                    "repair_kind": (item.get("review") or {}).get("repairKind") if isinstance(item.get("review"), Mapping) else item.get("repairKind"),
                }
            )
            review = item.get("review")
            if isinstance(review, dict):
                records.append(
                    {
                        "artifact_id": f"review:{item.get('reviewId') or candidate_id}"[:128],
                        "kind": "review",
                        "status": review.get("status", item.get("reviewStatus", "unknown")),
                        "source_attachment_ids": item.get("sourceAttachmentIds", source_attachment_ids),
                        "panel_ids": item.get("panelIds", panel_ids),
                        "lineage": [f"candidate:{candidate_id}"],
                        "confidence": review.get("confidence"),
                        "warnings": [str(issue.get("message")) for issue in review.get("issues", []) if isinstance(issue, dict)],
                    }
                )
    return records[:48]


def trace_result_summary(content: str) -> Any:
    """Keep tool-result traces useful without duplicating the quality envelope."""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return summarize_result(content)
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and "measurement" in data:
            payload = dict(payload)
            payload["data"] = dict(data)
            payload["data"].pop("measurement", None)
        content = json.dumps(payload, ensure_ascii=False)
    return summarize_result(content)


def lifecycle_trace_fields(content: str) -> dict[str, Any]:
    """Project stable candidate/scope identity beside bounded result summaries."""
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
            fields["source_scope"] = {
                key: source_scope.get(key)
                for key in ("attachment_id", "attachmentId", "panel_ids", "panelIds", "revision")
                if source_scope.get(key) is not None
            }
        if isinstance(coverage, Mapping):
            fields["coverage"] = {
                key: coverage.get(key)
                for key in (
                    "basis",
                    "source_series",
                    "sourceSeries",
                    "represented_series",
                    "representedSeries",
                    "intentionally_omitted_series",
                    "intentionallyOmittedSeries",
                    "status",
                )
                if coverage.get(key) is not None
            }
    measurement = data.get("measurement")
    if isinstance(measurement, Mapping):
        reference = measurement.get("reference") if isinstance(measurement.get("reference"), Mapping) else {}
        attempt = measurement.get("attempt") if isinstance(measurement.get("attempt"), Mapping) else {}
        measurement_scope = {
            "attachment_id": reference.get("attachment_id"),
            "panel_ids": [reference.get("panel_id")] if reference.get("panel_id") else [],
        }
        if measurement_scope["attachment_id"] or measurement_scope["panel_ids"]:
            fields.setdefault("source_scope", measurement_scope)
        attempt_id = reference.get("attempt_id") or attempt.get("attempt_id")
        parent_attempt = attempt.get("parent_attempt_id")
        if attempt_id:
            fields["attempt_id"] = str(attempt_id)[:160]
        if parent_attempt:
            fields["parent_attempt"] = str(parent_attempt)[:160]
        target = measurement.get("target")
        if parent_attempt is None and isinstance(target, Mapping) and target.get("parent_attempt_id"):
            fields["parent_attempt"] = str(target["parent_attempt_id"])[:160]
    candidate_items = data.get("review")
    if not isinstance(candidate_items, list) and isinstance(data.get("candidate"), Mapping):
        candidate_items = [data.get("candidate")]
    if isinstance(candidate_items, list):
        item = next((value for value in candidate_items if isinstance(value, Mapping)), None)
        if item is not None:
            candidate_id = item.get("candidateId") or item.get("candidate_id")
            if candidate_id:
                fields["candidate_id"] = str(candidate_id)[:160]
            review_id = item.get("reviewId") or item.get("review_id")
            if review_id:
                fields["review_id"] = str(review_id)[:160]
            collection_id = item.get("collectionId") or item.get("collection_id")
            if collection_id:
                fields["collection_id"] = str(collection_id)[:160]
            for source_key, field_name in (
                ("candidateStatus", "candidate_status"),
                ("reviewStatus", "review_status"),
                ("publicationStatus", "publication_status"),
            ):
                if item.get(source_key) is not None:
                    fields[field_name] = str(item[source_key])[:64]
            attempt_value = item.get("candidateAttempt") or item.get("lineageAttempt") or item.get("attempt")
            if attempt_value is not None:
                try:
                    fields["attempt"] = max(1, min(int(attempt_value), 8))
                except (TypeError, ValueError):
                    pass
            parent_attempt = item.get("parentAttempt") or item.get("parent_attempt") or item.get("parentCandidateId")
            if parent_attempt:
                fields["parent_attempt"] = str(parent_attempt)[:160]
            candidate_context = item.get("generationContext") or item.get("generation_context")
            if isinstance(candidate_context, Mapping):
                candidate_scope = candidate_context.get("source_scope") or candidate_context.get("sourceScope")
                candidate_coverage = candidate_context.get("coverage")
                if isinstance(candidate_scope, Mapping):
                    fields["source_scope"] = dict(candidate_scope)
                if isinstance(candidate_coverage, Mapping):
                    fields["coverage"] = dict(candidate_coverage)
            review = item.get("review")
            if isinstance(review, Mapping) and review.get("repairKind"):
                fields["repair_kind"] = str(review["repairKind"])[:32]
            elif item.get("repairKind"):
                fields["repair_kind"] = str(item["repairKind"])[:32]
    direct_repair = data.get("repair_kind") or data.get("repairKind")
    if direct_repair:
        fields["repair_kind"] = str(direct_repair)[:32]
    return {
        key: value
        for key, value in fields.items()
        if value not in (None, {}, [], "")
    }


# Private aliases preserve the historical internal names for callers that
# imported them from ``agent.loop`` during the migration.
_attach_visual_observation_refs = attach_visual_observation_refs
_artifact_records_from_observation = artifact_records_from_observation
_trace_result_summary = trace_result_summary
_lifecycle_trace_fields = lifecycle_trace_fields
