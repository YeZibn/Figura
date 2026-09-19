"""Mandatory review lifecycle for generated chart candidates.

The renderer produces bytes, while this module owns the publication decision.
It deliberately contains no model client: deterministic evidence is collected
here and an Agent may submit a bounded structured decision when evidence is
ambiguous.
"""

from __future__ import annotations

import json
import math
import tempfile
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from ..attachments import AttachmentRegistry
from ..spec import ChartFigure, ChartSpec, ChartType, chart_figure_digest, chart_spec_digest
from ..tools.core.result import DispatchedObservation, GeneratedImage

MAX_REVIEW_ISSUES = 32
MAX_REVIEW_EVIDENCE = 16
MAX_REVIEW_TEXT = 240
DEFAULT_REVIEW_DEADLINE_SECONDS = 300.0
DEFAULT_REVIEW_ATTEMPTS = 3
ChartSemantic = ChartSpec | ChartFigure


class CandidateStatus(str, Enum):
    CANDIDATE = "candidate"
    REVIEW_PENDING = "review_pending"
    VERIFIED = "verified"
    WARNING = "warning"
    REVIEW_FAILED = "review_failed"
    EXPIRED = "expired"
    TIMED_OUT = "timed_out"
    RETRY_EXHAUSTED = "retry_exhausted"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REQUIRES_MODEL_DECISION = "requires_model_decision"
    TIMED_OUT = "timed_out"


class PublicationStatus(str, Enum):
    UNPUBLISHED = "unpublished"
    PUBLISHED = "published"
    PUBLISHED_WITH_WARNING = "published_with_warning"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ReviewPolicy:
    """Bounded policy selected from source provenance and caller context."""

    source_linked: bool
    semantic_required: bool
    allow_warnings: bool = True
    max_attempts: int = DEFAULT_REVIEW_ATTEMPTS
    deadline_seconds: float = DEFAULT_REVIEW_DEADLINE_SECONDS
    required_checks: tuple[str, ...] = (
        "structure",
        "render_fidelity",
        "layout_readability",
        "encoded_artifact",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceLinked": self.source_linked,
            "semanticRequired": self.semantic_required,
            "allowWarnings": self.allow_warnings,
            "maxAttempts": self.max_attempts,
            "deadlineSeconds": self.deadline_seconds,
            "requiredChecks": list(self.required_checks),
        }


def select_review_policy(
    spec: ChartSemantic,
    *,
    source_attachment_ids: Sequence[str] = (),
    explicit_review: bool = False,
    allow_warnings: bool = True,
    max_attempts: int = DEFAULT_REVIEW_ATTEMPTS,
    deadline_seconds: float = DEFAULT_REVIEW_DEADLINE_SECONDS,
) -> ReviewPolicy:
    """Choose review scope without trusting an unbounded model assertion."""
    if isinstance(spec, ChartFigure):
        source_linked = bool(source_attachment_ids) or bool(spec.source.attachment_id.strip())
    else:
        source_linked = bool(source_attachment_ids) or bool(
            isinstance(spec.metadata.source, str) and spec.metadata.source.strip()
        )
    return ReviewPolicy(
        source_linked=source_linked,
        semantic_required=source_linked or explicit_review,
        allow_warnings=bool(allow_warnings),
        max_attempts=max(1, min(int(max_attempts), 8)),
        deadline_seconds=max(1.0, min(float(deadline_seconds), 3600.0)),
    )


@dataclass(frozen=True)
class ReviewIssue:
    code: str
    location: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code[:64],
            "location": self.location[:160],
            "message": self.message[:MAX_REVIEW_TEXT],
            "severity": self.severity if self.severity in {"error", "warning"} else "error",
        }


@dataclass(frozen=True)
class ReviewResult:
    status: ReviewStatus
    checks: Mapping[str, str] = field(default_factory=dict)
    issues: tuple[ReviewIssue, ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()
    model_decision_required: bool = False
    decision: str | None = None
    confidence: float | None = None
    review_mode: str = "safety"
    candidate_id: str | None = None
    review_id: str | None = None
    chart_spec_digest: str | None = None
    suggested_action: str | None = None
    recovery_classification: str | None = None

    @property
    def blocking(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues) or self.status in {
            ReviewStatus.FAILED,
            ReviewStatus.TIMED_OUT,
        }

    @property
    def warning(self) -> bool:
        return bool(self.issues) and not self.blocking

    def to_dict(self) -> dict[str, Any]:
        result = {
            "status": self.status.value,
            "checks": dict(self.checks),
            "issues": [item.to_dict() for item in self.issues[:MAX_REVIEW_ISSUES]],
            "evidence": [dict(item) for item in self.evidence[:MAX_REVIEW_EVIDENCE]],
            "modelDecisionRequired": self.model_decision_required,
            "reviewMode": self.review_mode,
        }
        if self.decision is not None:
            result["decision"] = self.decision
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.candidate_id is not None:
            result["candidateId"] = self.candidate_id
        if self.review_id is not None:
            result["reviewId"] = self.review_id
        if self.chart_spec_digest is not None:
            result["chartSpecDigest"] = self.chart_spec_digest
        if self.suggested_action is not None:
            result["suggestedAction"] = self.suggested_action
        if self.recovery_classification is not None:
            result["recoveryClassification"] = self.recovery_classification
        return result


@dataclass(frozen=True)
class ChartCandidate:
    candidate_id: str
    review_id: str
    run_id: str
    chart_spec_digest: str
    chart_type: str
    title: str
    media_type: str
    byte_count: int
    width: int
    height: int
    policy: ReviewPolicy
    status: CandidateStatus = CandidateStatus.REVIEW_PENDING
    review_status: ReviewStatus = ReviewStatus.PENDING
    publication_status: PublicationStatus = PublicationStatus.UNPUBLISHED
    review: ReviewResult | None = None
    source_attachment_ids: tuple[str, ...] = ()
    attempts: int = 0
    created_at: float = field(default_factory=time.monotonic)
    deadline_at: float = 0.0
    content: bytes = field(default=b"", repr=False, compare=False)
    superseded: bool = False
    parent_candidate_id: str | None = None
    lineage_attempt: int = 1
    panel_ids: tuple[str, ...] = ()
    figure_id: str | None = None
    collection_id: str | None = None
    child_chart_ids: tuple[str, ...] = ()
    figure_source: Mapping[str, str] | None = None
    coverage: Mapping[str, Any] | None = None

    def safe_metadata(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "candidateId": self.candidate_id,
            "reviewId": self.review_id,
            "runId": self.run_id,
            "chartSpecDigest": self.chart_spec_digest,
            "chartType": self.chart_type[:64],
            "title": self.title[:240],
            "mediaType": self.media_type,
            "byteCount": max(0, self.byte_count),
            "width": max(0, self.width),
            "height": max(0, self.height),
            "candidateStatus": self.status.value,
            "reviewStatus": self.review_status.value,
            "publicationStatus": self.publication_status.value,
            "reviewRequired": self.policy.semantic_required,
            "reviewMode": "vlm" if self.policy.semantic_required else "safety",
            "policy": self.policy.to_dict(),
            "attempts": self.attempts,
            "lineageAttempt": self.lineage_attempt,
        }
        if self.parent_candidate_id:
            result["parentCandidateId"] = self.parent_candidate_id
        if self.panel_ids:
            result["panelIds"] = list(self.panel_ids[:16])
        if self.source_attachment_ids:
            result["sourceAttachmentIds"] = list(self.source_attachment_ids[:16])
        if self.figure_id:
            result["figureId"] = self.figure_id[:128]
        if self.collection_id:
            result["collectionId"] = self.collection_id[:128]
        if self.child_chart_ids:
            result["childChartIds"] = list(self.child_chart_ids[:16])
        if isinstance(self.figure_source, Mapping):
            result["source"] = {
                str(key)[:32]: str(value)[:160]
                for key, value in self.figure_source.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        if isinstance(self.coverage, Mapping):
            result["coverage"] = {
                "sourceSeries": [str(item)[:160] for item in self.coverage.get("source_series", [])[:16]],
                "representedSeries": [str(item)[:160] for item in self.coverage.get("represented_series", [])[:16]],
                "omittedSeries": [str(item)[:160] for item in self.coverage.get("omitted_series", [])[:16]],
                "status": str(self.coverage.get("status", "unknown"))[:32],
            }
        if self.superseded:
            result["superseded"] = True
        if self.review is not None:
            result["review"] = self.review.to_dict()
        return result


def _issue(code: str, location: str, message: str, severity: str = "error") -> ReviewIssue:
    return ReviewIssue(code, location, message, severity)


def _expected_points(spec: ChartSpec) -> int:
    return len(spec.dataset)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ratios(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    scale = max(abs(value) for value in values)
    return [value / scale for value in values] if scale > 0 else [0.0 for _ in values]


def _close_enough(actual: float, expected: float, tolerance: float = 0.18) -> bool:
    scale = max(1.0, abs(expected))
    return abs(actual - expected) <= tolerance * scale


def _common_sensor_evidence(data: Mapping[str, Any]) -> Mapping[str, Any]:
    evidence = data.get("evidence")
    return evidence if isinstance(evidence, Mapping) else {}


def _sensor_warnings(data: Mapping[str, Any]) -> list[str]:
    common = _common_sensor_evidence(data).get("warnings")
    if isinstance(common, list):
        return [item for item in common if isinstance(item, str)]
    warnings = data.get("warnings")
    return [item for item in warnings if isinstance(item, str)] if isinstance(warnings, list) else []


def _sensor_result(path: Path, chart_type: ChartType) -> tuple[Mapping[str, Any] | None, str | None]:
    """Run the existing deterministic sensor against an ephemeral candidate."""
    try:
        if chart_type is ChartType.BAR:
            from ..tools.chart.observation.bars import measure_bars
            sensor = measure_bars
        elif chart_type is ChartType.LINE:
            from ..tools.chart.observation.line import extract_line_series
            sensor = extract_line_series
        elif chart_type is ChartType.PIE:
            from ..tools.chart.observation.pie import extract_pie_slices
            sensor = extract_pie_slices
        else:
            from ..tools.chart.observation.scatter import extract_scatter_points
            sensor = extract_scatter_points
        result = sensor(str(path))
        if isinstance(result, dict):
            return None, str(result.get("error", "sensor failed"))
        data = result.data
        return data if isinstance(data, Mapping) else None, None
    except Exception as exc:  # noqa: BLE001 - evidence failures are review data.
        return None, str(exc)[:MAX_REVIEW_TEXT]


def _compare_sensor(spec: ChartSpec, data: Mapping[str, Any] | None, sensor_error: str | None) -> tuple[list[ReviewIssue], list[dict[str, Any]]]:
    issues: list[ReviewIssue] = []
    evidence: list[dict[str, Any]] = []
    if data is None:
        return [_issue("sensor_unavailable", "candidate", sensor_error or "chart sensor produced no evidence")], evidence
    chart_type = spec.metadata.chart_type
    common = _common_sensor_evidence(data)
    if common:
        evidence.append(
            {
                "kind": "common_chart_evidence",
                "coordinateSystem": common.get("coordinate_system"),
                "frame": common.get("frame"),
                "confidence": common.get("confidence"),
            }
        )
    if chart_type is ChartType.BAR:
        items = data.get("bars")
        actual_count = len(items) if isinstance(items, list) else 0
        expected_count = _expected_points(spec)
        evidence.append({"kind": "bar_geometry", "count": actual_count})
        if actual_count != expected_count:
            issues.append(_issue("bar_count_mismatch", "bars", f"expected {expected_count} bars, detected {actual_count}"))
        actual = [
            _finite((item.get("measure") or {}).get("value_length_px"))
            for item in items or ()
            if isinstance(item, Mapping) and isinstance(item.get("measure"), Mapping)
        ]
        actual_values = [value for value in actual if value is not None]
        expected_values = [_finite(point.value) for point in spec.dataset]
        expected_values = [value for value in expected_values if value is not None]
        if len(actual_values) == len(expected_values) and len(actual_values) > 1:
            if any(not _close_enough(a, e, 0.24) for a, e in zip(_ratios(actual_values), _ratios(expected_values))):
                issues.append(_issue("bar_value_mismatch", "dataset", "detected bar proportions do not match the ChartSpec"))
    elif chart_type is ChartType.PIE:
        items = data.get("sectors")
        actual_count = len(items) if isinstance(items, list) else 0
        expected_count = _expected_points(spec)
        totals = data.get("totals") if isinstance(data.get("totals"), Mapping) else {}
        evidence.append({
            "kind": "pie_geometry",
            "count": actual_count,
            "totals": dict(totals),
            "confidence": data.get("confidence"),
        })
        sensor_warnings = _sensor_warnings(data)
        unreliable = (
            bool(sensor_warnings)
        ) or totals.get("consistent") is not True
        if actual_count != expected_count:
            issues.append(_issue(
                "pie_evidence_unresolved" if unreliable else "pie_count_mismatch",
                "sectors",
                f"expected {expected_count} sectors, detected {actual_count}",
                "warning" if unreliable else "error",
            ))
        actual = [
            _finite((item.get("measure") or {}).get("ratio"))
            for item in items or ()
            if isinstance(item, Mapping) and isinstance(item.get("measure"), Mapping)
        ]
        actual_values = [value for value in actual if value is not None]
        expected_total = sum((_finite(point.value) or 0.0) for point in spec.dataset)
        expected_values = [((_finite(point.value) or 0.0) / expected_total) for point in spec.dataset] if expected_total else []
        if len(actual_values) == len(expected_values) and totals.get("consistent") is True:
            if any(not _close_enough(a, e, 0.12) for a, e in zip(sorted(actual_values), sorted(expected_values))):
                issues.append(_issue("pie_value_mismatch", "dataset", "detected sector proportions do not match the ChartSpec"))
        elif actual_count or not expected_values:
            issues.append(_issue(
                "pie_ratio_unresolved",
                "sectors",
                "one or more pie sector ratios are unavailable or incomplete",
                "warning",
            ))
    else:
        series = data.get("series")
        series = series if isinstance(series, list) else []
        is_line = chart_type is ChartType.LINE
        is_scatter = chart_type is ChartType.SCATTER
        actual_points = sum(
            len(item.get("points", []))
            for item in series
            if isinstance(item, Mapping) and isinstance(item.get("points"), list)
        )
        trace_count = sum(
            1
            for item in series
            if isinstance(item, Mapping)
            and isinstance(item.get("trace"), Mapping)
            and isinstance(item.get("trace", {}).get("polyline_px"), list)
            and item.get("trace", {}).get("polyline_px")
        )
        trace_vertex_count = sum(
            len(item.get("trace", {}).get("polyline_px", []))
            for item in series
            if isinstance(item, Mapping)
            and isinstance(item.get("trace"), Mapping)
            and isinstance(item.get("trace", {}).get("polyline_px"), list)
        )
        expected_points = _expected_points(spec)
        evidence.append(
            {
                "kind": f"{chart_type.value}_geometry",
                "seriesCount": len(series),
                "pointCount": actual_points,
                **(
                    {
                        "traceCount": trace_count,
                        "traceVertexCount": trace_vertex_count,
                    }
                    if is_line
                    else {}
                ),
            }
        )
        if is_scatter:
            scatter_points = [
                point
                for item in series
                if isinstance(item, Mapping) and isinstance(item.get("points"), list)
                for point in item["points"]
                if isinstance(point, Mapping)
            ]
            calibrated_points = sum(
                1
                for point in scatter_points
                if _finite(point.get("x")) is not None and _finite(point.get("y")) is not None
            )
            pixel_only_points = len(scatter_points) - calibrated_points
            uncertain_points = sum(
                1
                for point in scatter_points
                if any(point.get(field) for field in ("merged_candidate", "overlap_candidate", "dense_candidate", "occluded_candidate", "outlier_candidate"))
            )
            evidence[-1].update(
                {
                    "calibratedPointCount": calibrated_points,
                    "pixelOnlyPointCount": pixel_only_points,
                    "uncertainPointCount": uncertain_points,
                }
            )
            if pixel_only_points:
                issues.append(
                    _issue(
                        "scatter_calibration_unresolved",
                        "dataset.coordinates",
                        f"{pixel_only_points} scatter points retain pixel-only evidence",
                        "warning",
                    )
                )
            if uncertain_points:
                issues.append(
                    _issue(
                        "scatter_point_uncertainty",
                        "dataset.points",
                        f"{uncertain_points} scatter points carry overlap, density, occlusion, or outlier evidence",
                        "warning",
                    )
                )
        if is_line and series and trace_count != len(series):
            issues.append(
                _issue(
                    "trace_evidence_unresolved",
                    "series.trace",
                    f"expected trace evidence for {len(series)} series, detected {trace_count}",
                    "warning",
                )
            )
        if actual_points != expected_points:
            unreliable = (
                bool(_sensor_warnings(data))
                and (
                    actual_points == 0
                    or is_line
                    and any(
                        isinstance(warning, str)
                        and any(
                            marker in warning
                            for marker in ("sampling", "calibration", "fragmented", "overlap", "unresolved")
                        )
                        for warning in _sensor_warnings(data)
                    )
                )
            )
            issues.append(_issue("point_evidence_unresolved" if unreliable else "point_count_mismatch", "dataset", f"expected {expected_points} points, detected {actual_points}", "warning" if unreliable else "error"))
        expected_series = {point.series or "default" for point in spec.dataset}
        if len(series) != len(expected_series):
            unreliable = not series and bool(_sensor_warnings(data))
            issues.append(_issue("series_evidence_unresolved" if unreliable else "series_count_mismatch", "dataset.series", f"expected {len(expected_series)} series, detected {len(series)}", "warning" if unreliable else "error"))
        actual_labels = {
            str(item.get("label")).strip()
            for item in series
            if isinstance(item, Mapping) and isinstance(item.get("label"), str) and item.get("label", "").strip()
        }
        if actual_labels and actual_labels != expected_series:
            issues.append(_issue("series_identity_mismatch", "dataset.series", "detected series labels do not match the ChartSpec"))
        if series and actual_points == expected_points:
            expected_by_series: dict[str, list[tuple[float, float]]] = {}
            for point in spec.dataset:
                x_value, y_value = _finite(point.x), _finite(point.y)
                if x_value is not None and y_value is not None:
                    expected_by_series.setdefault(point.series or "default", []).append((x_value, y_value))
            for index, entry in enumerate(series):
                if not isinstance(entry, Mapping) or not isinstance(entry.get("points"), list):
                    continue
                label = str(entry.get("label") or entry.get("series_id") or f"series_{index + 1}")
                expected_values = expected_by_series.get(label)
                actual_values = [
                    (_finite(item.get("x")), _finite(item.get("y")))
                    for item in entry["points"]
                    if isinstance(item, Mapping)
                ]
                actual_values = [(x, y) for x, y in actual_values if x is not None and y is not None]
                if expected_values and len(actual_values) == len(expected_values):
                    if any(not (_close_enough(actual[0], expected[0], 0.12) and _close_enough(actual[1], expected[1], 0.12)) for actual, expected in zip(actual_values, expected_values)):
                        issues.append(_issue("point_value_mismatch", f"dataset.series[{index}]", "detected point coordinates do not match the ChartSpec"))
    warnings = _sensor_warnings(data)
    for warning in warnings[:MAX_REVIEW_ISSUES]:
        if isinstance(warning, str) and warning.strip():
            issues.append(_issue("sensor_warning", "evidence", warning, "warning"))
    return issues, evidence


def review_candidate_bytes(
    spec: ChartSemantic,
    content: bytes,
    *,
    media_type: str,
    declared_width: int,
    declared_height: int,
    source_image: bytes | None = None,
) -> ReviewResult:
    """Check encoded candidate safety against one immutable ChartSpec.

    Semantic fidelity is intentionally not evaluated here. Source comparison
    is performed by the internal VLM reviewer; this function remains as a
    compatibility-named, deterministic artifact boundary.
    """
    issues: list[ReviewIssue] = []
    evidence: list[dict[str, Any]] = []
    checks: dict[str, str] = {}
    try:
        from ..tools.chart.validation import validate_generation

        if isinstance(spec, ChartFigure):
            structural_issues: list[ReviewIssue] = [
                _issue("invalid_chart_figure", issue.location, issue.message)
                for issue in spec.validate()
            ]
            if spec.coverage.status != "complete":
                structural_issues.append(_issue("incomplete_coverage", "coverage.status", "figure coverage is incomplete"))
            for index, child in enumerate(spec.charts):
                child_validation = validate_generation(child.spec)
                structural_issues.extend(
                    _issue("invalid_chart_spec", f"charts[{index}].{issue.location}", issue.message)
                    for issue in child_validation.issues
                )
            issues.extend(structural_issues[:MAX_REVIEW_ISSUES])
            structural_blocking = any(item.severity == "error" for item in structural_issues)
        else:
            structural = validate_generation(spec)
            structural_blocking = structural.blocking
            if structural.blocking:
                issues.extend(_issue("invalid_chart_spec", item.location, item.message) for item in structural.issues[:MAX_REVIEW_ISSUES])
        checks["structure"] = "failed" if structural_blocking else "passed"
    except Exception as exc:  # pragma: no cover - defensive boundary
        issues.append(_issue("invalid_chart_spec", "spec", str(exc)))
        checks["structure"] = "failed"

    if not isinstance(content, bytes) or not content:
        issues.append(_issue("empty_artifact", "artifact", "candidate image is empty"))
        checks["encoded_artifact"] = "failed"
        checks["render_fidelity"] = "not_run"
        checks["layout_readability"] = "not_run"
        return ReviewResult(ReviewStatus.FAILED, checks, tuple(issues), tuple(evidence), review_mode="safety")
    if not isinstance(media_type, str) or media_type.lower() != "image/png":
        issues.append(_issue("unsupported_artifact", "artifact.mediaType", "generated chart candidates must be PNG"))
    try:
        from io import BytesIO
        with Image.open(BytesIO(content)) as image:
            actual_size = image.size
            image_format = image.format
            extrema = image.convert("RGB").getextrema()
            if image_format != "PNG":
                issues.append(_issue("artifact_format", "artifact", "candidate does not decode as PNG"))
            if actual_size != (declared_width, declared_height):
                issues.append(_issue("dimension_mismatch", "artifact.dimensions", "encoded dimensions do not match candidate metadata"))
            if all(low == high for low, high in extrema):
                issues.append(_issue("blank_artifact", "artifact", "candidate image is a uniform blank canvas"))
            evidence.append({"kind": "encoded_artifact", "format": image_format, "width": actual_size[0], "height": actual_size[1]})
        checks["encoded_artifact"] = "failed" if any(item.location.startswith("artifact") or item.code in {"dimension_mismatch", "blank_artifact", "unsupported_artifact"} for item in issues) else "passed"
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        issues.append(_issue("artifact_decode", "artifact", f"candidate could not be decoded: {exc}"))
        checks["encoded_artifact"] = "failed"
    checks["render_fidelity"] = "not_run"
    checks["layout_readability"] = "not_run"
    blocking = any(item.severity == "error" for item in issues)
    status = ReviewStatus.FAILED if blocking else ReviewStatus.COMPLETED
    return ReviewResult(
        status,
        checks,
        tuple(issues[:MAX_REVIEW_ISSUES]),
        tuple(evidence[:MAX_REVIEW_EVIDENCE]),
        decision="pass" if not blocking else "fail",
        confidence=1.0 if not blocking else 0.0,
        review_mode="safety",
    )


def _merge_review_results(safety: ReviewResult, semantic: ReviewResult) -> ReviewResult:
    """Combine code-owned safety checks with the VLM semantic decision."""
    status = (
        ReviewStatus.TIMED_OUT
        if safety.status is ReviewStatus.TIMED_OUT or semantic.status is ReviewStatus.TIMED_OUT
        else ReviewStatus.FAILED
        if safety.status is ReviewStatus.FAILED or semantic.status is ReviewStatus.FAILED
        else ReviewStatus.COMPLETED
    )
    return ReviewResult(
        status=status,
        checks={**dict(safety.checks), **dict(semantic.checks)},
        issues=(safety.issues + semantic.issues)[:MAX_REVIEW_ISSUES],
        evidence=(safety.evidence + semantic.evidence)[:MAX_REVIEW_EVIDENCE],
        model_decision_required=False,
        decision=semantic.decision,
        confidence=semantic.confidence,
        review_mode="vlm",
        candidate_id=semantic.candidate_id,
        review_id=semantic.review_id,
        chart_spec_digest=semantic.chart_spec_digest,
        suggested_action=semantic.suggested_action,
        recovery_classification=semantic.recovery_classification,
    )


class ChartReviewManager:
    """Thread-safe in-process candidate store used by Agent and Gateway hooks."""

    def __init__(self, *, attachments: AttachmentRegistry | None = None) -> None:
        self.attachments = attachments
        self._items: dict[str, tuple[ChartCandidate, ChartSemantic]] = {}
        self._keys: dict[tuple[str, str, str], str] = {}
        self._lock = RLock()

    def create_candidate(
        self,
        run_id: str,
        call_id: str,
        image: GeneratedImage,
        spec: ChartSemantic,
        *,
        source_attachment_ids: Sequence[str] = (),
        explicit_review: bool = False,
    ) -> ChartCandidate:
        digest = chart_figure_digest(spec) if isinstance(spec, ChartFigure) else chart_spec_digest(spec)
        key = (run_id, call_id, digest)
        with self._lock:
            existing_id = self._keys.get(key)
            if existing_id is not None:
                return self._items[existing_id][0]
            metadata = image.metadata if isinstance(image.metadata, Mapping) else {}
            policy = select_review_policy(spec, source_attachment_ids=source_attachment_ids, explicit_review=explicit_review)
            parent_candidate_id: str | None = None
            lineage_attempt = 1
            for prior_id, (prior, prior_spec) in tuple(self._items.items()):
                if (
                    prior.run_id == run_id
                    and prior.chart_type == ("composite" if isinstance(spec, ChartFigure) else spec.metadata.chart_type.value)
                    and prior.publication_status is PublicationStatus.REJECTED
                    and prior.status in {CandidateStatus.REVIEW_FAILED, CandidateStatus.RETRY_EXHAUSTED}
                    and not prior.superseded
                ):
                    if parent_candidate_id is None or prior.lineage_attempt > lineage_attempt:
                        parent_candidate_id = prior.candidate_id
                        lineage_attempt = prior.lineage_attempt + 1
                    self._items[prior_id] = (replace(prior, superseded=True), prior_spec)
            semantic_source_ids = (
                (spec.source.attachment_id,)
                if isinstance(spec, ChartFigure) and spec.source.attachment_id.strip()
                else ()
            )
            effective_source_attachment_ids = tuple(dict.fromkeys(tuple(source_attachment_ids) + semantic_source_ids))[:16]
            panel_values = metadata.get("panelIds", metadata.get("panel_ids", ()))
            if isinstance(spec, ChartFigure) and spec.source.panel_id:
                panel_values = tuple(panel_values) + (spec.source.panel_id,) if isinstance(panel_values, (list, tuple)) else (spec.source.panel_id,)
            panel_ids = tuple(
                item[:160]
                for item in panel_values
                if isinstance(item, str) and item.strip()
            )[:16] if isinstance(panel_values, (list, tuple)) else ()
            if lineage_attempt > policy.max_attempts:
                exhausted = ReviewResult(
                    status=ReviewStatus.FAILED,
                    checks={"review_lifecycle": "failed"},
                    issues=(ReviewIssue(
                        "retry_exhausted",
                        "review.attempts",
                        "candidate correction retry budget has been exhausted",
                    ),),
                    decision="fail",
                    confidence=0.0,
                    review_mode="vlm" if policy.semantic_required else "safety",
                    suggested_action="stop_and_keep_unpublished",
                    recovery_classification="retry_exhausted",
                )
                candidate = ChartCandidate(
                    candidate_id=f"cand_{uuid4().hex}",
                    review_id=f"review_{uuid4().hex}",
                    run_id=run_id,
                    chart_spec_digest=digest,
                    chart_type="composite" if isinstance(spec, ChartFigure) else spec.metadata.chart_type.value,
                    title=str(metadata.get("title") or (next((item.title or item.spec.metadata.title for item in spec.charts), "复合图表") if isinstance(spec, ChartFigure) else spec.metadata.title) or "图表")[:240],
                    media_type=str(image.media_type).lower(),
                    byte_count=len(image.content),
                    width=int(metadata.get("width", 0) or 0),
                    height=int(metadata.get("height", 0) or 0),
                    policy=policy,
                    status=CandidateStatus.RETRY_EXHAUSTED,
                    review_status=ReviewStatus.FAILED,
                    publication_status=PublicationStatus.REJECTED,
                    review=exhausted,
                    source_attachment_ids=effective_source_attachment_ids,
                    created_at=time.monotonic(),
                    deadline_at=time.monotonic() + policy.deadline_seconds,
                    content=image.content,
                    parent_candidate_id=parent_candidate_id,
                    lineage_attempt=lineage_attempt,
                    panel_ids=panel_ids,
                    figure_id=spec.figure_id if isinstance(spec, ChartFigure) else None,
                    collection_id=metadata.get("collection_id") if isinstance(metadata.get("collection_id"), str) else None,
                    child_chart_ids=tuple(item.chart_id for item in spec.charts) if isinstance(spec, ChartFigure) else (),
                    figure_source=spec.source.to_dict() if isinstance(spec, ChartFigure) else None,
                    coverage=spec.coverage.to_dict() if isinstance(spec, ChartFigure) else None,
                )
                self._items[candidate.candidate_id] = (candidate, spec)
                self._keys[key] = candidate.candidate_id
                return candidate
            candidate = ChartCandidate(
                candidate_id=f"cand_{uuid4().hex}",
                review_id=f"review_{uuid4().hex}",
                run_id=run_id,
                chart_spec_digest=digest,
                chart_type="composite" if isinstance(spec, ChartFigure) else spec.metadata.chart_type.value,
                title=str(metadata.get("title") or (next((item.title or item.spec.metadata.title for item in spec.charts), "复合图表") if isinstance(spec, ChartFigure) else spec.metadata.title) or "图表")[:240],
                media_type=str(image.media_type).lower(),
                byte_count=len(image.content),
                width=int(metadata.get("width", 0) or 0),
                height=int(metadata.get("height", 0) or 0),
                policy=policy,
                source_attachment_ids=effective_source_attachment_ids,
                created_at=time.monotonic(),
                deadline_at=time.monotonic() + policy.deadline_seconds,
                content=image.content,
                parent_candidate_id=parent_candidate_id,
                lineage_attempt=lineage_attempt,
                panel_ids=panel_ids,
                figure_id=spec.figure_id if isinstance(spec, ChartFigure) else None,
                collection_id=metadata.get("collection_id") if isinstance(metadata.get("collection_id"), str) else None,
                child_chart_ids=tuple(item.chart_id for item in spec.charts) if isinstance(spec, ChartFigure) else (),
                figure_source=spec.source.to_dict() if isinstance(spec, ChartFigure) else None,
                coverage=spec.coverage.to_dict() if isinstance(spec, ChartFigure) else None,
            )
            self._items[candidate.candidate_id] = (candidate, spec)
            self._keys[key] = candidate.candidate_id
            return candidate

    def supersede_failed_for_retry(self, run_id: str, chart_type: str) -> None:
        """Keep a prior rejected attempt attributable without blocking its retry."""
        with self._lock:
            for candidate_id, (candidate, spec) in tuple(self._items.items()):
                if (
                    candidate.run_id == run_id
                    and candidate.chart_type == chart_type
                    and candidate.publication_status is PublicationStatus.REJECTED
                    and candidate.status is CandidateStatus.REVIEW_FAILED
                ):
                    self._items[candidate_id] = (replace(candidate, superseded=True), spec)

    def get(self, candidate_id: str, review_id: str | None = None) -> ChartCandidate | None:
        with self._lock:
            item = self._items.get(candidate_id)
            if item is None or (review_id is not None and item[0].review_id != review_id):
                return None
            candidate = item[0]
            if candidate.status is CandidateStatus.REVIEW_PENDING and time.monotonic() > candidate.deadline_at:
                candidate = replace(candidate, status=CandidateStatus.TIMED_OUT, review_status=ReviewStatus.TIMED_OUT, publication_status=PublicationStatus.REJECTED)
                self._items[candidate_id] = (candidate, item[1])
            return candidate

    def get_spec(self, candidate_id: str, review_id: str | None = None) -> ChartSemantic | None:
        with self._lock:
            item = self._items.get(candidate_id)
            if item is None or (review_id is not None and item[0].review_id != review_id):
                return None
            return item[1]

    def source_payload(self, candidate: ChartCandidate) -> tuple[bytes, str] | None:
        """Load one authorized source image for an internal reviewer."""
        if self.attachments is None or not candidate.source_attachment_ids:
            return None
        item, error = self.attachments.validate(candidate.source_attachment_ids[0])
        if error or item is None:
            return None
        try:
            return Path(item.canonical_path).read_bytes(), item.media_type
        except OSError:
            return None

    def process(
        self,
        candidate: ChartCandidate,
        *,
        semantic_result: ReviewResult | None = None,
    ) -> ChartCandidate:
        with self._lock:
            current_item = self._items.get(candidate.candidate_id)
            if current_item is None or current_item[0].review_id != candidate.review_id:
                raise ValueError("candidate review context does not match")
            current, spec = current_item
            if current.status in {CandidateStatus.VERIFIED, CandidateStatus.WARNING, CandidateStatus.REVIEW_FAILED, CandidateStatus.TIMED_OUT, CandidateStatus.RETRY_EXHAUSTED}:
                return current
            if current.review_status is ReviewStatus.REQUIRES_MODEL_DECISION and semantic_result is None:
                return current
            if current.attempts >= current.policy.max_attempts:
                current = replace(current, status=CandidateStatus.RETRY_EXHAUSTED, review_status=ReviewStatus.FAILED, publication_status=PublicationStatus.REJECTED)
                self._items[current.candidate_id] = (current, spec)
                return current
            current = replace(current, attempts=current.attempts + 1)
            safety_result = review_candidate_bytes(
                spec,
                current.content,
                media_type=current.media_type,
                declared_width=current.width,
                declared_height=current.height,
            )
            if safety_result.blocking:
                result = safety_result
            elif current.policy.semantic_required and semantic_result is None:
                current = replace(current, attempts=current.attempts, review_status=ReviewStatus.PENDING)
                self._items[current.candidate_id] = (current, spec)
                return current
            elif current.policy.semantic_required:
                if any(
                    value is not None and value != expected
                    for value, expected in (
                        (semantic_result.candidate_id, current.candidate_id),
                        (semantic_result.review_id, current.review_id),
                        (semantic_result.chart_spec_digest, current.chart_spec_digest),
                    )
                ):
                    result = ReviewResult(
                        status=ReviewStatus.FAILED,
                        checks={"vlm_review": "failed"},
                        issues=(ReviewIssue(
                            "review_identity_mismatch",
                            "review",
                            "VLM review result does not match the candidate context",
                        ),),
                        decision="fail",
                        confidence=0.0,
                        review_mode="vlm",
                    )
                else:
                    result = _merge_review_results(safety_result, semantic_result)
            else:
                result = safety_result
            current = self._apply_result(current, result)
            self._items[current.candidate_id] = (current, spec)
            return current

    def _apply_result(self, candidate: ChartCandidate, result: ReviewResult) -> ChartCandidate:
        if result.blocking:
            if result.recovery_classification is None:
                source_failure = any(issue.code == "source_binding_failure" for issue in result.issues)
                result = replace(
                    result,
                    suggested_action="rebind_source" if source_failure else "correct_chart_spec",
                    recovery_classification="source_binding_failure" if source_failure else "semantic_rejection",
                )
            return replace(candidate, status=CandidateStatus.REVIEW_FAILED, review_status=result.status, publication_status=PublicationStatus.REJECTED, review=result)
        if result.warning:
            if candidate.policy.allow_warnings:
                return replace(candidate, status=CandidateStatus.WARNING, review_status=ReviewStatus.COMPLETED, publication_status=PublicationStatus.PUBLISHED_WITH_WARNING, review=result)
            return replace(candidate, status=CandidateStatus.REVIEW_FAILED, review_status=ReviewStatus.FAILED, publication_status=PublicationStatus.REJECTED, review=result)
        return replace(candidate, status=CandidateStatus.VERIFIED, review_status=ReviewStatus.COMPLETED, publication_status=PublicationStatus.PUBLISHED, review=result)

    def gate(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            candidates = [item[0] for item in self._items.values() if item[0].run_id == run_id]
        pending = [item for item in candidates if item.policy.semantic_required and item.publication_status is PublicationStatus.UNPUBLISHED]
        failed = [item for item in candidates if item.publication_status is PublicationStatus.REJECTED and not item.superseded]
        recovery_actions = []
        for item in failed:
            recovery = item.review.recovery_classification if item.review is not None else None
            action = item.review.suggested_action if item.review is not None else None
            if recovery or action:
                recovery_actions.append({
                    "candidateId": item.candidate_id,
                    "classification": recovery or "review_failure",
                    "action": action or "correct_chart_spec",
                })
        retryable = bool(failed) and not any(item.status is CandidateStatus.RETRY_EXHAUSTED for item in failed)
        return {
            "ok": not pending and not failed,
            "pending": [item.safe_metadata() for item in pending[:MAX_REVIEW_EVIDENCE]],
            "failed": [item.safe_metadata() for item in failed[:MAX_REVIEW_EVIDENCE]],
            "published": [item.safe_metadata() for item in candidates if item.publication_status in {PublicationStatus.PUBLISHED, PublicationStatus.PUBLISHED_WITH_WARNING}],
            "retryable": retryable,
            "recoveryActions": recovery_actions[:MAX_REVIEW_EVIDENCE],
        }

    def decorate_image(self, image: GeneratedImage, candidate: ChartCandidate) -> GeneratedImage:
        metadata = dict(image.metadata) if isinstance(image.metadata, Mapping) else {}
        metadata.update(candidate.safe_metadata())
        metadata["kind"] = "generated_chart"
        return replace(image, metadata=metadata)


__all__ = [
    "CandidateStatus",
    "ChartCandidate",
    "ChartReviewManager",
    "PublicationStatus",
    "ReviewIssue",
    "ReviewPolicy",
    "ReviewResult",
    "ReviewStatus",
    "ChartSemantic",
    "chart_spec_digest",
    "review_candidate_bytes",
    "select_review_policy",
]
