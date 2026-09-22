"""Atomic ChartSpec assembly and internal validation helpers."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any
from uuid import uuid4

from ...spec import (
    Axes,
    Axis,
    ChartCoverage,
    ChartFigure,
    ChartFigureItem,
    ChartMetadata,
    ChartSpec,
    ChartSpecCollection,
    ChartType,
    DataPoint,
    FigureLayout,
    FigureSource,
    GenerationContext,
    MAX_COLLECTION_FIGURES,
    MAX_FIGURE_CHARTS,
    MAX_FIGURE_COLUMNS,
    ValidationIssue,
    generation_context_schema,
    normalize_generation_context,
)
from ...measurement import MeasurementSession, measurement_gate, normalize_evidence_refs
from ..core.definition import Tool
from .validation import MAX_GENERATION_POINTS, MAX_GENERATION_LABEL_LENGTH, validate_generation

_CARTESIAN_TYPES = frozenset({ChartType.BAR, ChartType.LINE, ChartType.SCATTER})


def _assembly_error(message: str, location: str) -> dict[str, Any]:
    bounded_message = str(message)[:240]
    return {
        "error": bounded_message,
        "issues": [{"location": location[:120], "message": bounded_message}],
    }


def _measurement_gate_error(gate: Mapping[str, Any], location: str) -> dict[str, Any]:
    bounded = {
        key: value
        for key, value in gate.items()
        if key in {
            "status",
            "code",
            "location",
            "message",
            "next_action",
            "measurement_status",
            "issues",
            "repair_action",
            "available_refs",
            "missing_refs",
            "evidence_refs",
            "selected_refs",
            "discarded_refs",
            "decision_status",
            "series_map",
            "evidence_basis",
        }
    }
    raw_location = str(bounded.get("location") or "measurement_ref")
    bounded["location"] = raw_location if raw_location.startswith(location) else f"{location}.{raw_location}"[:160]
    message = str(bounded.get("message") or "measurement evidence was not accepted")[:240]
    return {
        "error": "measurement evidence gate failed",
        "issues": [{"location": bounded["location"], "message": message}],
        "measurement_gate": bounded,
        "validation": {"status": "blocked", "checks": {"measurement": "blocked"}},
    }


def _generation_context_error(
    value: object,
    location: str,
    *,
    source_scope_hint: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Normalize and validate one model-provided generation context."""
    if value is None:
        return None
    context = (
        value
        if isinstance(value, GenerationContext)
        else normalize_generation_context(value, source_scope_hint=source_scope_hint)
    )
    if context is None:
        return _assembly_error("generation_context must be a structured object", location)
    issues = context.validate(location)
    if issues:
        return {
            "error": "generation_context validation failed",
            "issues": [
                {"location": item["location"], "message": item["message"]}
                for item in issues[:16]
            ],
        }
    return None


def _normalized_generation_context(
    value: object,
    *,
    source_scope_hint: Mapping[str, Any] | None = None,
) -> GenerationContext | None:
    if isinstance(value, GenerationContext):
        return value
    return normalize_generation_context(value, source_scope_hint=source_scope_hint)


def _source_scope_hint(
    expected_source: FigureSource | None,
    measurement_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    source = expected_source
    if source is not None:
        return {"attachment_id": source.attachment_id, "panel_ids": [source.panel_id]}
    if isinstance(measurement_ref, Mapping):
        attachment_id = measurement_ref.get("attachment_id")
        panel_id = measurement_ref.get("panel_id")
        if isinstance(attachment_id, str) and attachment_id.strip() and isinstance(panel_id, str) and panel_id.strip():
            return {"attachment_id": attachment_id, "panel_ids": [panel_id]}
    return None


def _context_scope_mismatch(
    context: GenerationContext,
    *,
    expected_source: FigureSource | None = None,
    measurement_ref: Mapping[str, Any] | None = None,
    location: str,
) -> dict[str, Any] | None:
    scope = context.source_scope
    if scope is None:
        return None
    if expected_source is not None:
        if scope.attachment_id != expected_source.attachment_id:
            return _assembly_error(
                "generation_context attachment does not match figure source",
                f"{location}.source_scope.attachment_id",
            )
        if expected_source.panel_id not in scope.panel_ids:
            return _assembly_error(
                "generation_context panel does not match figure source",
                f"{location}.source_scope.panel_ids",
            )
    if measurement_ref is not None:
        if measurement_ref.get("attachment_id") != scope.attachment_id:
            return _assembly_error(
                "measurement reference attachment does not match generation_context",
                f"{location}.attachment_id",
            )
        ref_panel = measurement_ref.get("panel_id")
        if ref_panel and ref_panel not in scope.panel_ids:
            return _assembly_error(
                "measurement reference panel is outside generation_context source scope",
                f"{location}.panel_id",
            )
    return None


def _record_measurement_decision(
    decision: Mapping[str, Any] | None,
    *,
    measurement_ref: Mapping[str, Any] | None,
    measurement_context: Mapping[str, Any] | None,
    location: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Record the main Agent's explicit ref selection before assembly."""
    if not isinstance(decision, Mapping):
        return None, None
    session_id = str(decision.get("session_id") or (measurement_ref or {}).get("session_id") or "").strip()
    attempt_id = str(decision.get("attempt_id") or (measurement_ref or {}).get("attempt_id") or "").strip()
    if not session_id or not attempt_id or not isinstance(measurement_context, Mapping):
        return None, {
            "status": "blocked",
            "code": "measurement_decision_invalid",
            "location": f"{location}.measurement_decision",
            "message": "measurement_decision must identify the current session and attempt",
            "next_action": "使用当前 measurement.reference 和 evidence.refs 提交选择",
        }
    raw_session = measurement_context.get(session_id)
    session = (
        raw_session
        if isinstance(raw_session, MeasurementSession)
        else MeasurementSession.from_dict(raw_session)
        if isinstance(raw_session, Mapping)
        else None
    )
    if session is None:
        return None, {
            "status": "blocked",
            "code": "measurement_session_not_found",
            "location": f"{location}.measurement_decision",
            "message": "measurement session is not registered for the current run",
            "next_action": "重新读取当前测量观察后再选择 evidence.refs",
        }
    if session.current_attempt_id != attempt_id:
        return None, {
            "status": "blocked",
            "code": "measurement_attempt_not_current",
            "location": f"{location}.measurement_decision.attempt_id",
            "message": "measurement decision must target the current attempt",
            "next_action": "只选择当前 measurement.reference 对应 attempt 的证据",
        }
    selected = normalize_evidence_refs(decision.get("selected_refs") or decision.get("refs"))
    discarded = normalize_evidence_refs(decision.get("discarded_refs"))
    raw_status = decision.get("status") or decision.get("decision_status")
    decision_status = str(raw_status or ("selected" if selected else "discarded")).strip().lower()
    if decision_status not in {"selected", "discarded", "abandoned"}:
        return None, {
            "status": "blocked",
            "code": "measurement_decision_status_invalid",
            "location": f"{location}.measurement_decision.status",
            "message": "measurement_decision.status 必须是 selected、discarded 或 abandoned",
            "next_action": "明确选择有效证据，或明确舍弃/放弃当前测量",
        }
    if decision_status == "selected" and not selected:
        return None, {
            "status": "blocked",
            "code": "measurement_decision_required",
            "location": f"{location}.measurement_decision.selected_refs",
            "message": "selected 决策至少需要一个 selected_refs",
            "next_action": "根据 overlay 选择要用于 ChartSpec 的证据引用，或将 status 改为 discarded/abandoned",
        }
    if decision_status in {"discarded", "abandoned"} and not selected and not discarded:
        # An explicit discard/abandon is meaningful even when the sensor did
        # not expose bounded refs; the assembled points may come from direct
        # visual reasoning or another source.
        discarded = normalize_evidence_refs(decision.get("discarded_refs") or [])
    if not session.record_decision(
        attempt_id=attempt_id,
        selected_refs=selected,
        discarded_refs=discarded,
        status=decision_status,
        series_map=decision.get("series_map") if isinstance(decision.get("series_map"), Mapping) else None,
        evidence_basis=str(decision.get("evidence_basis") or "")[:80] or None,
    ):
        return None, {
            "status": "blocked",
            "code": "measurement_decision_refs_invalid",
            "location": f"{location}.measurement_decision.selected_refs",
            "message": "selected_refs 或 discarded_refs 不属于当前 measurement attempt，或存在重叠",
            "next_action": "重新读取当前 attempt 的 evidence.refs，不要手写内部 ID",
        }
    return {
        "session_id": session.session_id,
        "attempt_id": attempt_id,
        "selected_refs": list(session.selected_refs),
        "discarded_refs": list(session.discarded_refs),
        "decision_status": session.decision_status,
        "series_map": dict(session.series_map),
        "evidence_basis": session.evidence_basis,
    }, None


def _reject_internal_series_labels(points: list[dict], location: str) -> dict[str, Any] | None:
    for index, point in enumerate(points):
        if not isinstance(point, Mapping):
            continue
        series = point.get("series")
        if isinstance(series, str) and re.fullmatch(r"(?:series_\d+|S\d+)", series.strip(), flags=re.IGNORECASE):
            return _assembly_error(
                "证据引用不能直接作为最终 series 标签；请使用图例文本或明确的业务名称",
                f"{location}[{index}].series",
            )
    return None


def _assemble_single_spec(
    chart_type: str,
    points: list[dict],
    title: str = "",
    x_label: str = "",
    y_label: str = "",
    source: str | None = None,
    x_categories: list[str] | None = None,
    measurement_ref: Mapping[str, Any] | None = None,
    evidence_refs: object | None = None,
    measurement_decision: Mapping[str, Any] | None = None,
    measurement_context: Mapping[str, Any] | None = None,
    generation_context: GenerationContext | Mapping[str, Any] | None = None,
    expected_source: FigureSource | None = None,
    location: str = "measurement_ref",
) -> dict:
    """Atomically construct and validate a serialization-ready ChartSpec."""
    try:
        kind = ChartType(chart_type)
    except (TypeError, ValueError):
        return _assembly_error(f"unknown chart_type: {chart_type!r}", "chart_type")

    context_error = _generation_context_error(
        generation_context,
        "generation_context",
        source_scope_hint=_source_scope_hint(expected_source, measurement_ref),
    )
    if context_error is not None:
        return context_error
    context = _normalized_generation_context(
        generation_context,
        source_scope_hint=_source_scope_hint(expected_source, measurement_ref),
    )
    if context is not None:
        scope_error = _context_scope_mismatch(
            context,
            expected_source=expected_source,
            measurement_ref=measurement_ref,
            location=location,
        )
        if scope_error is not None:
            return scope_error

    if not isinstance(points, list) or not points:
        return _assembly_error("points must be a non-empty array", "points")
    if evidence_refs is not None and measurement_ref is None:
        return _assembly_error(
            "evidence_refs requires the matching server-issued measurement_ref",
            f"{location}.evidence_refs",
        )

    provenance = None
    legacy_selected_refs = (
        normalize_evidence_refs(
            measurement_decision.get("selected_refs") or measurement_decision.get("refs")
        )
        if isinstance(measurement_decision, Mapping)
        else ()
    )
    resolved_evidence_refs = evidence_refs
    if evidence_refs is not None and legacy_selected_refs:
        normalized_evidence_refs = normalize_evidence_refs(evidence_refs)
        if normalized_evidence_refs != legacy_selected_refs:
            return _assembly_error(
                "evidence_refs conflicts with legacy measurement_decision.selected_refs",
                f"{location}.evidence_refs",
            )
        resolved_evidence_refs = normalized_evidence_refs
    elif evidence_refs is None and legacy_selected_refs:
        resolved_evidence_refs = legacy_selected_refs

    decision_payload, decision_error = _record_measurement_decision(
        measurement_decision,
        measurement_ref=measurement_ref,
        measurement_context=measurement_context,
        location=location,
    )
    if decision_error is not None:
        return _measurement_gate_error(decision_error, location)

    if measurement_ref is not None:
        provenance, gate_error = measurement_gate(
            measurement_ref,
            measurement_context,
            evidence_refs=resolved_evidence_refs,
            expected_attachment_id=expected_source.attachment_id if expected_source else None,
            expected_panel_id=(
                expected_source.panel_id
                if expected_source
                else context.source_scope.panel_ids[0]
                if context is not None and context.source_scope is not None and len(context.source_scope.panel_ids) == 1
                else None
            ),
            location=location,
        )
        if gate_error is not None:
            return _measurement_gate_error(gate_error, location)
    if kind in _CARTESIAN_TYPES and (
        not isinstance(x_label, str)
        or not x_label.strip()
        or not isinstance(y_label, str)
        or not y_label.strip()
    ):
        return _assembly_error(
            f"{kind.value} charts require non-empty x_label and y_label",
            "axes",
        )
    if x_categories is not None:
        if kind not in _CARTESIAN_TYPES:
            return _assembly_error("x_categories is only supported for cartesian charts", "x_categories")
        if not isinstance(x_categories, list):
            return _assembly_error("x_categories must be an array", "x_categories")
        if len(x_categories) > MAX_GENERATION_POINTS:
            return _assembly_error("x_categories exceeds the configured size limit", "x_categories")

    data_points: list[DataPoint] = []
    internal_label_error = _reject_internal_series_labels(points, "points")
    if internal_label_error is not None:
        return internal_label_error
    for index, raw in enumerate(points):
        if not isinstance(raw, Mapping):
            return _assembly_error(f"points[{index}] must be an object", f"points[{index}]")
        point = DataPoint.from_dict(raw)
        data_points.append(point)

    axes = None
    if kind in _CARTESIAN_TYPES:
        categories = (
            list(dict.fromkeys(
                point.category.strip()
                for point in data_points
                if isinstance(point.category, str)
            ))
            if kind is ChartType.BAR and x_categories is None
            else list(x_categories) if x_categories is not None else None
        )
        axes = Axes(
            x=Axis(label=x_label, categories=categories),
            y=Axis(label=y_label),
        )

    chart_spec = ChartSpec(
        metadata=ChartMetadata(chart_type=kind, title=title, source=source),
        axes=axes,
        dataset=data_points,
        provenance=provenance,
        generation_context=context,
    )
    if decision_payload is not None and isinstance(chart_spec.provenance, dict):
        chart_spec.provenance["selected_refs"] = decision_payload["selected_refs"]
        chart_spec.provenance["discarded_refs"] = decision_payload["discarded_refs"]
        chart_spec.provenance["decision_status"] = decision_payload["decision_status"]
        chart_spec.provenance["series_map"] = decision_payload["series_map"]
        chart_spec.provenance["evidence_basis"] = decision_payload["evidence_basis"]
        chart_spec.provenance["observation_scope"] = provenance.get("observation_scope")
    elif isinstance(chart_spec.provenance, dict) and isinstance(provenance, Mapping):
        chart_spec.provenance["evidence_refs"] = list(provenance.get("evidence_refs") or [])
    validation = validate_generation(chart_spec)
    if validation.blocking:
        issues = validation.legacy_issues()
        return {
            "error": issues[0]["message"] if issues else "ChartSpec validation failed",
            "issues": issues,
            "validation": validation.to_dict(),
        }
    assembled = chart_spec.to_dict()
    if decision_payload is not None:
        assembled["_measurement_decision"] = decision_payload
    elif measurement_ref is not None and isinstance(provenance, Mapping):
        assembled["_evidence_refs"] = list(provenance.get("evidence_refs") or [])
    return assembled


def _collection_error(message: str, location: str, *, validation: dict | None = None) -> dict[str, Any]:
    bounded_message = str(message)[:240]
    result: dict[str, Any] = {
        "error": bounded_message,
        "issues": [{"location": location[:160], "message": bounded_message}],
    }
    if validation is not None:
        result["validation"] = validation
    return result


def _figure_child_input(
    child: Mapping[str, Any],
    inherited_context: GenerationContext | None = None,
) -> dict[str, Any]:
    """Translate semantic child input to the legacy single-chart assembler."""
    return {
        "chart_type": child.get("chart_type"),
        "points": child.get("points"),
        "title": child.get("title", ""),
        "x_label": child.get("x_label", ""),
        "y_label": child.get("y_label", ""),
        "x_categories": child.get("x_categories"),
        "source": child.get("source"),
        "measurement_ref": child.get("measurement_ref"),
        "evidence_refs": child.get("evidence_refs"),
        "measurement_decision": child.get("measurement_decision"),
        "generation_context": child.get("generation_context", inherited_context),
    }


def _figure_measurement_decisions(
    figure: Mapping[str, Any],
    measurement_context: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Project validated child decisions so the Agent can release one gate."""
    charts = figure.get("charts")
    if not isinstance(charts, list) or not isinstance(measurement_context, Mapping):
        return []
    decisions: list[dict[str, Any]] = []
    for child in charts[:MAX_FIGURE_CHARTS]:
        if not isinstance(child, Mapping):
            continue
        reference = child.get("measurement_ref")
        if not isinstance(reference, Mapping):
            continue
        decision = child.get("measurement_decision")
        session_id = str(reference.get("session_id") or "").strip()
        attempt_id = str(reference.get("attempt_id") or "").strip()
        if not session_id or not attempt_id:
            continue
        session = measurement_context.get(session_id)
        if isinstance(session, Mapping):
            session = MeasurementSession.from_dict(session)
        if not isinstance(session, MeasurementSession):
            continue
        if session.current_attempt_id != attempt_id:
            continue
        explicit_refs = child.get("evidence_refs")
        selected = list(normalize_evidence_refs(explicit_refs)) if explicit_refs is not None else list(session.selected_refs)
        discarded = list(session.discarded_refs)
        decision_status = "inferred" if explicit_refs is not None else "legacy_accepted"
        series_map: dict[str, Any] = {}
        evidence_basis = None
        if isinstance(decision, Mapping):
            if explicit_refs is None:
                selected = list(normalize_evidence_refs(decision.get("selected_refs") or decision.get("refs")))
                discarded = list(normalize_evidence_refs(decision.get("discarded_refs")))
            decision_status = str(decision.get("status") or decision.get("decision_status") or session.decision_status or "selected")[:32]
            series_map = dict(decision.get("series_map") or {}) if isinstance(decision.get("series_map"), Mapping) else {}
            evidence_basis = str(decision.get("evidence_basis") or "")[:80] or None
        decisions.append(
            {
                "session_id": session_id,
                "attempt_id": attempt_id,
                "selected_refs": selected[:64],
                "discarded_refs": discarded[:64],
                "decision_status": decision_status,
                "series_map": series_map,
                "evidence_basis": evidence_basis,
            }
        )
    return decisions


def _assemble_figure(
    figure: Mapping[str, Any],
    *,
    location: str = "figure",
    measurement_context: Mapping[str, Any] | None = None,
) -> ChartFigure | dict[str, Any]:
    if not isinstance(figure, Mapping):
        return _collection_error("figure must be an object", location)
    source_raw = figure.get("source")
    if not isinstance(source_raw, Mapping):
        return _collection_error("figure source must include attachment_id and panel_id", f"{location}.source")
    source = FigureSource.from_dict(source_raw)
    raw_context = figure.get("generation_context")
    context_error = _generation_context_error(
        raw_context,
        f"{location}.generation_context",
        source_scope_hint=_source_scope_hint(source),
    )
    if context_error is not None:
        return context_error
    generation_context = _normalized_generation_context(
        raw_context,
        source_scope_hint=_source_scope_hint(source),
    )
    if generation_context is not None:
        scope_error = _context_scope_mismatch(
            generation_context,
            expected_source=source,
            location=f"{location}.generation_context",
        )
        if scope_error is not None:
            return scope_error
    raw_charts = figure.get("charts")
    if not isinstance(raw_charts, list) or not raw_charts:
        return _collection_error("figure charts must be a non-empty array", f"{location}.charts")
    if len(raw_charts) > MAX_FIGURE_CHARTS:
        return _collection_error("figure contains too many charts", f"{location}.charts")
    charts: list[ChartFigureItem] = []
    for index, raw_child in enumerate(raw_charts):
        child_location = f"{location}.charts[{index}]"
        if not isinstance(raw_child, Mapping):
            return _collection_error("chart item must be an object", child_location)
        chart_id = raw_child.get("chart_id")
        if not isinstance(chart_id, str) or not chart_id.strip():
            return _collection_error("chart_id must be a non-empty string", f"{child_location}.chart_id")
        child_result = _assemble_single_spec(
            **_figure_child_input(raw_child, generation_context),
            measurement_context=measurement_context,
            expected_source=source,
            location=f"{child_location}.measurement_ref",
        )
        if "error" in child_result:
            issues = [
                {
                    "location": f"{child_location}.{issue.get('location', 'spec')}",
                    "message": str(issue.get("message") or child_result.get("error"))[:240],
                }
                for issue in child_result.get("issues", [])
                if isinstance(issue, Mapping)
            ]
            return {
                "error": "ChartSpec figure assembly failed",
                "issues": issues or [{"location": child_location, "message": "child ChartSpec is invalid"}],
                "validation": child_result.get("validation", {"status": "failed"}),
            }
        try:
            child_spec = ChartSpec.from_dict(child_result)
        except (TypeError, ValueError, KeyError) as exc:
            return _collection_error(str(exc), f"{child_location}.spec")
        charts.append(
            ChartFigureItem(
                chart_id=chart_id.strip(),
                title=str(raw_child.get("display_title") or raw_child.get("title") or "")[:MAX_GENERATION_LABEL_LENGTH],
                spec=child_spec,
            )
        )
    layout_raw = figure.get("layout") or {"type": "grid", "columns": min(2, len(charts))}
    if not isinstance(layout_raw, Mapping):
        return _collection_error("figure layout must be an object", f"{location}.layout")
    layout = FigureLayout.from_dict(layout_raw)
    if layout.columns > MAX_FIGURE_COLUMNS:
        return _collection_error("figure layout columns exceed the configured limit", f"{location}.layout.columns")
    coverage_raw = figure.get("coverage")
    if not isinstance(coverage_raw, Mapping):
        return _collection_error("figure coverage is required", f"{location}.coverage")
    coverage = ChartCoverage.from_dict(coverage_raw)
    if generation_context is not None:
        expected_basis = generation_context.coverage.basis.value
        if "basis" not in coverage_raw:
            return _collection_error(
                "generation_context and figure coverage must explicitly declare the same basis",
                f"{location}.coverage.basis",
            )
        if coverage.basis != expected_basis:
            return _collection_error(
                "figure coverage basis does not match generation_context",
                f"{location}.coverage.basis",
            )
        context_coverage = generation_context.coverage
        if context_coverage.represented_series and set(context_coverage.represented_series) != set(coverage.represented_series):
            return _collection_error(
                "figure represented_series does not match generation_context",
                f"{location}.coverage.represented_series",
            )
        if context_coverage.intentionally_omitted_series and set(context_coverage.intentionally_omitted_series) != set(coverage.omitted_series):
            return _collection_error(
                "figure omitted_series does not match generation_context",
                f"{location}.coverage.omitted_series",
            )
    figure_id = figure.get("figure_id")
    if not isinstance(figure_id, str) or not figure_id.strip():
        return _collection_error("figure_id must be a non-empty string", f"{location}.figure_id")
    result = ChartFigure(
        figure_id=figure_id.strip(),
        source=source,
        layout=layout,
        charts=charts,
        coverage=coverage,
        generation_context=generation_context,
    )
    issues = result.validate()
    if not issues and result.coverage.status != "complete":
        issues.append(ValidationIssue("coverage.status", "figure coverage must be complete before generation"))
    if issues:
        return {
            "error": "ChartSpec figure assembly failed",
            "issues": [{"location": f"{location}.{issue.location}", "message": issue.message} for issue in issues[:32]],
            "validation": {"status": "failed", "checks": {"semantic": "failed"}},
        }
    return result


def assemble_spec(
    chart_type: str | None = None,
    points: list[dict] | None = None,
    title: str = "",
    x_label: str = "",
    y_label: str = "",
    source: str | None = None,
    x_categories: list[str] | None = None,
    measurement_ref: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    measurement_decision: dict[str, Any] | None = None,
    generation_context: dict[str, Any] | None = None,
    *,
    figure: dict[str, Any] | None = None,
    figures: list[dict[str, Any]] | None = None,
    collection_id: str | None = None,
    _measurement_context: Mapping[str, Any] | None = None,
) -> dict:
    """Atomically construct a single ChartSpec, figure, or collection."""
    if figure is not None and figures is not None:
        return _collection_error("provide either figure or figures, not both", "figure")
    if figures is not None:
        if not isinstance(figures, list) or not figures:
            return _collection_error("figures must be a non-empty array", "figures")
        if len(figures) > MAX_COLLECTION_FIGURES:
            return _collection_error("collection contains too many figures", "figures")
        built: list[ChartFigure] = []
        for index, item in enumerate(figures):
            result = _assemble_figure(
                item,
                location=f"figures[{index}]",
                measurement_context=_measurement_context,
            )
            if isinstance(result, dict):
                return result
            built.append(result)
        resolved_collection_id = collection_id or f"collection_{uuid4().hex}"
        collection = ChartSpecCollection(resolved_collection_id[:128], built)
        issues = collection.validate()
        if issues:
            return {
                "error": "ChartSpec collection assembly failed",
                "issues": [{"location": issue.location, "message": issue.message} for issue in issues[:32]],
                "validation": {"status": "failed", "checks": {"semantic": "failed"}},
            }
        payload = collection.to_dict()
        decisions = [
            decision
            for figure in figures
            if isinstance(figure, Mapping)
            for decision in _figure_measurement_decisions(figure, _measurement_context)
        ]
        if decisions:
            payload["_measurement_decisions"] = decisions[:MAX_COLLECTION_FIGURES * MAX_FIGURE_CHARTS]
        return payload
    if figure is not None:
        result = _assemble_figure(figure, measurement_context=_measurement_context)
        if not isinstance(result, ChartFigure):
            return result
        payload = result.to_dict()
        decisions = _figure_measurement_decisions(figure, _measurement_context)
        if decisions:
            payload["_measurement_decisions"] = decisions
        return payload
    if chart_type is None:
        return _assembly_error("chart_type is required unless figure or figures is provided", "chart_type")
    return _assemble_single_spec(
        chart_type,
        points or [],
        title,
        x_label,
        y_label,
        source,
        x_categories=x_categories,
        measurement_ref=measurement_ref,
        evidence_refs=evidence_refs,
        measurement_decision=measurement_decision,
        measurement_context=_measurement_context,
        generation_context=generation_context,
    )


def validate_spec(spec: dict) -> dict:
    """Run shared validation for internal callers and compatibility checks."""
    try:
        if isinstance(spec, Mapping) and spec.get("kind") == "chart_figure":
            issues = [
                {"location": issue.location, "message": issue.message}
                for issue in ChartFigure.from_dict(spec).validate()
            ]
        elif isinstance(spec, Mapping) and spec.get("kind") == "chart_spec_collection":
            issues = [
                {"location": issue.location, "message": issue.message}
                for issue in ChartSpecCollection.from_dict(spec).validate()
            ]
        else:
            chart_spec = ChartSpec.from_dict(spec)
            issues = validate_generation(chart_spec).legacy_issues()
    except Exception as exc:  # noqa: BLE001 - critic boundary
        issues = [{"location": "spec", "message": str(exc)}]
    return {"ok": not issues, "issues": issues}


POINT_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "description": "Category label for bar or pie data; required with value for categorical charts."},
        "value": {"type": "number", "description": "Finite numeric magnitude for bar or pie data; required with category for categorical charts."},
        "x": {"type": "number", "description": "Finite numeric x coordinate for line or scatter data; required with y for coordinate charts."},
        "y": {"type": "number", "description": "Finite numeric y coordinate for line or scatter data; required with x for coordinate charts."},
        "series": {"type": "string", "description": "Optional non-empty series label used to group multi-series line or scatter data."},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional extraction confidence in the inclusive range 0 to 1."},
    },
    "oneOf": [
        {"required": ["category", "value"]},
        {"required": ["x", "y"]},
    ],
    "additionalProperties": False,
}

AXIS_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "Displayed axis label; required and non-empty for cartesian charts."},
        "categories": {"type": "array", "items": {"type": "string", "description": "One non-empty categorical tick label."}, "maxItems": MAX_GENERATION_POINTS, "description": "Optional ordered category labels for a categorical x-axis."},
        "min_value": {"type": "number", "description": "Optional finite lower bound for a numeric axis; must be less than max_value."},
        "max_value": {"type": "number", "description": "Optional finite upper bound for a numeric axis; must be greater than min_value."},
    },
    "required": ["label"],
    "additionalProperties": False,
}

AXES_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {**AXIS_SCHEMA, "description": "X-axis definition."},
        "y": {**AXIS_SCHEMA, "description": "Y-axis definition."},
    },
    "required": ["x", "y"],
    "additionalProperties": False,
}

MEASUREMENT_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "description": "Server-issued measurement session identity."},
        "attempt_id": {"type": "string", "description": "Server-issued measurement attempt identity."},
        "attachment_id": {"type": "string", "description": "Exact source attachment identity from the measurement observation."},
        "panel_id": {"type": ["string", "null"], "description": "Exact source panel identity from the measurement observation."},
    },
    "required": ["session_id", "attempt_id", "attachment_id"],
    "additionalProperties": False,
}

MEASUREMENT_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "description": "当前 measurement.reference 的 session_id；可省略并从 measurement_ref 继承。"},
        "attempt_id": {"type": "string", "description": "当前 measurement.reference 的 attempt_id；可省略并从 measurement_ref 继承。"},
        "status": {"type": "string", "enum": ["selected", "discarded", "abandoned"], "description": "兼容旧调用的显式证据决策；新调用优先直接使用 evidence_refs。"},
        "selected_refs": {"type": "array", "items": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9]{0,15}$"}, "maxItems": 64, "description": "兼容旧调用的证据引用；新调用使用同级 evidence_refs。"},
        "discarded_refs": {"type": "array", "items": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9]{0,15}$"}, "maxItems": 64, "description": "兼容旧调用的舍弃引用，不是新流程的必填生命周期。"},
        "series_map": {"type": "object", "additionalProperties": {"type": "string"}, "maxProperties": 32, "description": "可选的稳定系列身份映射，例如 series_1 到图例名称。"},
        "evidence_basis": {"type": ["string", "null"], "maxLength": 80, "description": "简短说明本次选择依据。"},
    },
    "required": [],
    "additionalProperties": False,
}

MEASUREMENT_PROVENANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["accepted", "inferred", "selected", "discarded", "abandoned", "provisional", "partial"], "description": "代码拥有的测量来源事实；inferred 表示本次只校验了实际传入的 evidence_refs。"},
        "session_id": {"type": "string", "description": "Measurement session identity."},
        "attempt_id": {"type": "string", "description": "Accepted measurement attempt identity."},
        "attachment_id": {"type": "string", "description": "Source attachment identity."},
        "panel_id": {"type": ["string", "null"], "description": "Source panel identity."},
        "tool": {"type": "string", "description": "Measurement tool that produced the accepted evidence."},
        "quality": {"type": "object", "additionalProperties": True, "description": "Bounded quality summary retained for downstream audit."},
        "evidence_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 64, "description": "Evidence refs actually used by the assembled ChartSpec."},
        "selected_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 64, "description": "旧 provenance 的兼容字段。"},
        "discarded_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 64, "description": "旧 provenance 的兼容字段。"},
        "decision_status": {"type": "string", "maxLength": 32, "description": "旧 provenance 的兼容字段，不是新的组装门禁。"},
        "series_map": {"type": "object", "additionalProperties": {"type": "string"}, "maxProperties": 32},
        "evidence_basis": {"type": ["string", "null"], "maxLength": 80},
        "observation_scope": {"type": "object", "additionalProperties": True, "description": "首次观察实际应用的 panel 范围；由服务端保留。"},
    },
    "required": ["status", "session_id", "attempt_id", "attachment_id"],
    "additionalProperties": False,
}

CHART_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "metadata": {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string", "enum": [chart_type.value for chart_type in ChartType], "description": "Chart kind: bar, line, pie, or scatter."},
                "title": {"type": "string", "maxLength": 160, "description": "Optional bounded chart title."},
                "source": {"type": ["string", "null"], "description": "Optional source or provenance label; it is metadata, not a local path authorization."},
                "note": {"type": "string", "maxLength": 160, "description": "Optional bounded note about the chart."},
            },
            "required": ["chart_type"],
            "additionalProperties": False,
        },
        "axes": {"oneOf": [AXES_SCHEMA, {"type": "null"}], "description": "Cartesian x/y axes; omit or use null only for pie charts."},
        "dataset": {"type": "array", "items": POINT_SCHEMA, "minItems": 1, "maxItems": MAX_GENERATION_POINTS, "description": "Ordered typed data points; point shape must match the selected chart type."},
        "provenance": {**MEASUREMENT_PROVENANCE_SCHEMA, "description": "Optional code-owned measurement provenance; evidence_refs only records refs actually used by this ChartSpec."},
        "generation_context": generation_context_schema(),
    },
    "required": ["metadata", "dataset"],
    "additionalProperties": False,
}

FIGURE_SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "attachment_id": {"type": "string", "description": "Exact source attachment identity."},
        "panel_id": {"type": "string", "description": "Exact source panel identity."},
    },
    "required": ["attachment_id", "panel_id"],
    "additionalProperties": False,
}

FIGURE_COVERAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "source_series": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_FIGURE_CHARTS, "description": "Series known to exist in the source panel."},
        "represented_series": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_FIGURE_CHARTS, "description": "Series represented by child charts."},
        "omitted_series": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_FIGURE_CHARTS, "description": "Series not represented; cannot be empty when coverage is incomplete."},
        "basis": {"type": "string", "enum": ["full_source", "requested_subset", "not_applicable"], "description": "Coverage basis; requested_subset permits an explicit intentional omission for the current task."},
        "status": {"type": "string", "enum": ["complete", "incomplete", "unknown"], "description": "Source coverage status."},
    },
    "required": ["source_series", "represented_series", "omitted_series", "status"],
    "additionalProperties": False,
}

FIGURE_CHILD_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "chart_id": {"type": "string", "description": "Stable child chart identity within the figure."},
        "chart_type": {"type": "string", "enum": [chart_type.value for chart_type in ChartType], "description": "Child chart kind."},
        "title": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional child chart title."},
        "display_title": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional title shown by the composite layout."},
        "x_label": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Cartesian child x-axis label."},
        "y_label": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Cartesian child y-axis label."},
        "x_categories": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_GENERATION_POINTS, "description": "Optional ordered x-axis category labels; preserve labels from the source panel for line/scatter charts."},
        "points": {"type": "array", "items": POINT_SCHEMA, "minItems": 1, "maxItems": MAX_GENERATION_POINTS, "description": "Child chart data points."},
        "source": {"type": ["string", "null"], "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional child provenance label."},
        "measurement_ref": {**MEASUREMENT_REF_SCHEMA, "description": "Optional server-issued measurement reference for this child chart."},
        "evidence_refs": {"type": "array", "items": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9]{0,15}$"}, "maxItems": 64, "description": "模型实际用于当前 child 的测量证据引用；必须来自 measurement_ref 对应 attempt。"},
        "measurement_decision": {**MEASUREMENT_DECISION_SCHEMA, "description": "兼容旧 child 输入；新 child 直接传实际采用的 evidence_refs。"},
        "generation_context": generation_context_schema(),
    },
    "required": ["chart_id", "chart_type", "points"],
    "additionalProperties": False,
}

FIGURE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "figure_id": {"type": "string", "description": "Stable identity for the final composite figure."},
        "source": FIGURE_SOURCE_SCHEMA,
        "layout": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["grid"], "description": "Bounded composite layout type."},
                "columns": {"type": "integer", "minimum": 1, "maximum": MAX_FIGURE_COLUMNS, "description": "Number of grid columns."},
            },
            "required": ["type", "columns"],
            "additionalProperties": False,
        },
        "coverage": FIGURE_COVERAGE_SCHEMA,
        "generation_context": generation_context_schema(),
        "charts": {"type": "array", "items": FIGURE_CHILD_INPUT_SCHEMA, "minItems": 1, "maxItems": MAX_FIGURE_CHARTS, "description": "Independent child chart descriptions."},
    },
    "required": ["figure_id", "source", "coverage", "charts"],
    "additionalProperties": False,
}

ASSEMBLE_SPEC = Tool(
    name="assemble_spec",
    description=(
        "根据已收集的证据原子地组装并校验 ChartSpec、同源 ChartFigure 或多来源 ChartSpecCollection。"
        "单图使用 chart_type 和 points；同源多子图使用 figure，必须提供 attachment_id、panel_id、coverage 和独立 charts；不同来源使用 figures。"
        "source-linked 任务应传入 generation_context，明确 mode、coverage basis、represented/omitted series 和 selection_basis；优先提供 source_scope，若当前 attachment/panel 唯一且已授权，服务端只会在该范围内安全绑定，否则拒绝歧义或跨 panel 请求。"
        "若使用测量结果，必须原样传入当前观察返回的 measurement_ref，并可用同级 evidence_refs 提供实际使用的候选引用；服务端会校验来源、attempt 和引用。旧 measurement_decision 仅为兼容字段。不要把 S1、series_1 等证据引用当成最终系列名称。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": [chart_type.value for chart_type in ChartType],
                "description": "单图或 figure 子图的图表类型：bar、line、pie 或 scatter。集合模式不填写。",
            },
            "title": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Optional bounded chart title."},
            "x_label": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Required non-empty x-axis label for bar, line, and scatter charts."},
            "y_label": {"type": "string", "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "Required non-empty y-axis label for bar, line, and scatter charts."},
            "points": {"type": "array", "items": POINT_SCHEMA, "minItems": 1, "maxItems": MAX_GENERATION_POINTS, "description": "单图数据点；bar/pie 使用 category/value，line/scatter 使用 x/y。figure 模式填写到 charts 子项。"},
            "source": {"type": ["string", "null"], "maxLength": MAX_GENERATION_LABEL_LENGTH, "description": "单图可选来源标签；不授权访问本地路径。"},
            "x_categories": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_GENERATION_POINTS, "description": "可选的有序横轴类别标签；line/scatter 必须保留源 panel 中已确认的类别文本，例如 Jan、Feb、Mar。"},
        "measurement_ref": {**MEASUREMENT_REF_SCHEMA, "description": "可选的服务端测量引用；服务端校验其来源、attempt 和当前 run 的证据状态。"},
        "evidence_refs": {"type": "array", "items": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9]{0,15}$"}, "maxItems": 64, "description": "模型实际用于当前 ChartSpec 的测量证据引用；必须来自 measurement_ref 对应 attempt。"},
        "measurement_decision": {**MEASUREMENT_DECISION_SCHEMA, "description": "兼容旧输入；新输入直接传 measurement_ref + evidence_refs，未采用候选无需单独记录。"},
        "generation_context": {**generation_context_schema(), "description": "source-linked 单图的任务合同；必须与 measurement_ref 的 attachment/panel 和 coverage 语义一致。"},
        "figure": {**FIGURE_INPUT_SCHEMA, "description": "同一 attachment_id + panel_id 下的多个独立子图及其 coverage。"},
            "figures": {"type": "array", "items": FIGURE_INPUT_SCHEMA, "minItems": 1, "maxItems": MAX_COLLECTION_FIGURES, "description": "来自多个 panel 的有序 figure 列表；不同来源不会自动合并。"},
            "collection_id": {"type": "string", "maxLength": 128, "description": "可选的稳定集合 ID。"},
        },
        "required": [],
        "additionalProperties": False,
    },
    fn=assemble_spec,
    group="chart-spec",
)

__all__ = [
    "ASSEMBLE_SPEC",
    "CHART_SPEC_SCHEMA",
    "FIGURE_INPUT_SCHEMA",
    "FIGURE_COVERAGE_SCHEMA",
    "FIGURE_CHILD_INPUT_SCHEMA",
    "FIGURE_SOURCE_SCHEMA",
    "MEASUREMENT_REF_SCHEMA",
    "MEASUREMENT_DECISION_SCHEMA",
    "MEASUREMENT_PROVENANCE_SCHEMA",
    "POINT_SCHEMA",
    "assemble_spec",
    "validate_spec",
]
