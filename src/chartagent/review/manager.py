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
from ..spec import ChartSpec, ChartType, chart_spec_digest
from ..tools.core.result import DispatchedObservation, GeneratedImage

MAX_REVIEW_ISSUES = 32
MAX_REVIEW_EVIDENCE = 16
MAX_REVIEW_TEXT = 240
DEFAULT_REVIEW_DEADLINE_SECONDS = 300.0
DEFAULT_REVIEW_ATTEMPTS = 3


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
    spec: ChartSpec,
    *,
    source_attachment_ids: Sequence[str] = (),
    explicit_review: bool = False,
    allow_warnings: bool = True,
    max_attempts: int = DEFAULT_REVIEW_ATTEMPTS,
    deadline_seconds: float = DEFAULT_REVIEW_DEADLINE_SECONDS,
) -> ReviewPolicy:
    """Choose review scope without trusting an unbounded model assertion."""
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
        return {
            "status": self.status.value,
            "checks": dict(self.checks),
            "issues": [item.to_dict() for item in self.issues[:MAX_REVIEW_ISSUES]],
            "evidence": [dict(item) for item in self.evidence[:MAX_REVIEW_EVIDENCE]],
            "modelDecisionRequired": self.model_decision_required,
        }


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
            "policy": self.policy.to_dict(),
            "attempts": self.attempts,
        }
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
        sensor_warnings = data.get("warnings")
        unreliable = (
            isinstance(sensor_warnings, list)
            and any(isinstance(item, str) for item in sensor_warnings)
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
                isinstance(data.get("warnings"), list)
                and bool(data.get("warnings"))
                and (
                    actual_points == 0
                    or is_line
                    and any(
                        isinstance(warning, str)
                        and any(
                            marker in warning
                            for marker in ("sampling", "calibration", "fragmented", "overlap", "unresolved")
                        )
                        for warning in data["warnings"]
                    )
                )
            )
            issues.append(_issue("point_evidence_unresolved" if unreliable else "point_count_mismatch", "dataset", f"expected {expected_points} points, detected {actual_points}", "warning" if unreliable else "error"))
        expected_series = {point.series or "default" for point in spec.dataset}
        if len(series) != len(expected_series):
            unreliable = not series and isinstance(data.get("warnings"), list) and bool(data.get("warnings"))
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
    warnings = data.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings[:MAX_REVIEW_ISSUES]:
            if isinstance(warning, str) and warning.strip():
                issues.append(_issue("sensor_warning", "evidence", warning, "warning"))
    return issues, evidence


def review_candidate_bytes(
    spec: ChartSpec,
    content: bytes,
    *,
    media_type: str,
    declared_width: int,
    declared_height: int,
    source_image: bytes | None = None,
) -> ReviewResult:
    """Independently review encoded bytes against one immutable ChartSpec."""
    issues: list[ReviewIssue] = []
    evidence: list[dict[str, Any]] = []
    checks: dict[str, str] = {}
    try:
        from ..tools.chart.validation import validate_generation

        structural = validate_generation(spec)
        if structural.blocking:
            issues.extend(_issue("invalid_chart_spec", item.location, item.message) for item in structural.issues[:MAX_REVIEW_ISSUES])
        checks["structure"] = "failed" if structural.blocking else "passed"
    except Exception as exc:  # pragma: no cover - defensive boundary
        issues.append(_issue("invalid_chart_spec", "spec", str(exc)))
        checks["structure"] = "failed"

    if not isinstance(content, bytes) or not content:
        issues.append(_issue("empty_artifact", "artifact", "candidate image is empty"))
        checks["encoded_artifact"] = "failed"
        return ReviewResult(ReviewStatus.FAILED, checks, tuple(issues), tuple(evidence))
    if media_type.lower() != "image/png":
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
        checks["encoded_artifact"] = "failed" if any(item.location.startswith("artifact") or item.code in {"dimension_mismatch", "blank_artifact"} for item in issues) else "passed"
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        issues.append(_issue("artifact_decode", "artifact", f"candidate could not be decoded: {exc}"))
        checks["encoded_artifact"] = "failed"

    with tempfile.NamedTemporaryFile(suffix=".png") as stream:
        stream.write(content)
        stream.flush()
        data, sensor_error = _sensor_result(Path(stream.name), spec.metadata.chart_type)
    sensor_issues, sensor_evidence = _compare_sensor(spec, data, sensor_error)
    issues.extend(sensor_issues)
    evidence.extend(sensor_evidence)
    checks["render_fidelity"] = "failed" if any(item.severity == "error" and item.code not in {"sensor_warning"} for item in sensor_issues) else "passed"
    checks["layout_readability"] = "warning" if any(item.severity == "warning" for item in issues) else "passed"

    if source_image is not None:
        # Source comparison is intentionally structural, never pixel equality.
        with tempfile.NamedTemporaryFile(suffix=".png") as stream:
            stream.write(source_image)
            stream.flush()
            source_data, source_error = _sensor_result(Path(stream.name), spec.metadata.chart_type)
        if source_data is None:
            issues.append(_issue("source_evidence_unavailable", "source", source_error or "source evidence unavailable"))
        else:
            source_issues, _ = _compare_sensor(spec, source_data, source_error)
            for item in source_issues:
                if item.severity == "error":
                    issues.append(replace(item, code=f"source_{item.code}"))
            evidence.append({"kind": "source_structural_comparison", "available": True, "issueCount": len(source_issues)})

    blocking = any(item.severity == "error" for item in issues)
    status = ReviewStatus.FAILED if blocking else ReviewStatus.COMPLETED
    return ReviewResult(status, checks, tuple(issues[:MAX_REVIEW_ISSUES]), tuple(evidence[:MAX_REVIEW_EVIDENCE]))


class ChartReviewManager:
    """Thread-safe in-process candidate store used by Agent and Gateway hooks."""

    def __init__(self, *, attachments: AttachmentRegistry | None = None) -> None:
        self.attachments = attachments
        self._items: dict[str, tuple[ChartCandidate, ChartSpec]] = {}
        self._keys: dict[tuple[str, str, str], str] = {}
        self._lock = RLock()

    def create_candidate(
        self,
        run_id: str,
        call_id: str,
        image: GeneratedImage,
        spec: ChartSpec,
        *,
        source_attachment_ids: Sequence[str] = (),
        explicit_review: bool = False,
    ) -> ChartCandidate:
        digest = chart_spec_digest(spec)
        key = (run_id, call_id, digest)
        with self._lock:
            existing_id = self._keys.get(key)
            if existing_id is not None:
                return self._items[existing_id][0]
            metadata = image.metadata if isinstance(image.metadata, Mapping) else {}
            policy = select_review_policy(spec, source_attachment_ids=source_attachment_ids, explicit_review=explicit_review)
            candidate = ChartCandidate(
                candidate_id=f"cand_{uuid4().hex}",
                review_id=f"review_{uuid4().hex}",
                run_id=run_id,
                chart_spec_digest=digest,
                chart_type=spec.metadata.chart_type.value,
                title=str(metadata.get("title") or spec.metadata.title or "图表")[:240],
                media_type=str(image.media_type).lower(),
                byte_count=len(image.content),
                width=int(metadata.get("width", 0) or 0),
                height=int(metadata.get("height", 0) or 0),
                policy=policy,
                source_attachment_ids=tuple(source_attachment_ids)[:16],
                created_at=time.monotonic(),
                deadline_at=time.monotonic() + policy.deadline_seconds,
                content=image.content,
            )
            self._items[candidate.candidate_id] = (candidate, spec)
            self._keys[key] = candidate.candidate_id
            return candidate

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

    def process(self, candidate: ChartCandidate, *, decision: Mapping[str, Any] | None = None) -> ChartCandidate:
        with self._lock:
            current_item = self._items.get(candidate.candidate_id)
            if current_item is None or current_item[0].review_id != candidate.review_id:
                raise ValueError("candidate review context does not match")
            current, spec = current_item
            if current.status in {CandidateStatus.VERIFIED, CandidateStatus.WARNING, CandidateStatus.REVIEW_FAILED, CandidateStatus.TIMED_OUT, CandidateStatus.RETRY_EXHAUSTED}:
                return current
            if current.review_status is ReviewStatus.REQUIRES_MODEL_DECISION and decision is None:
                return current
            if current.attempts >= current.policy.max_attempts:
                current = replace(current, status=CandidateStatus.RETRY_EXHAUSTED, review_status=ReviewStatus.FAILED, publication_status=PublicationStatus.REJECTED)
                self._items[current.candidate_id] = (current, spec)
                return current
            current = replace(current, attempts=current.attempts + 1)
            source_image = self._load_source(current.source_attachment_ids)
            if current.policy.source_linked and source_image is None:
                result = ReviewResult(
                    ReviewStatus.FAILED,
                    {"source_evidence": "failed"},
                    (_issue("source_evidence_unavailable", "source", "authorized source attachment is unavailable"),),
                )
            else:
                result = review_candidate_bytes(
                    spec,
                    current.content,
                    media_type=current.media_type,
                    declared_width=current.width,
                    declared_height=current.height,
                    source_image=source_image,
                )
            if result.status is ReviewStatus.COMPLETED and current.policy.semantic_required and decision is None:
                # A deterministic pass is enough only when source evidence did
                # not leave an association unresolved. Explicit decisions are
                # accepted as a second, structured evidence binding.
                unresolved = any(issue.code.startswith("source_") or issue.code in {"sensor_warning", "sensor_unavailable"} for issue in result.issues)
                if unresolved:
                    result = replace(result, status=ReviewStatus.REQUIRES_MODEL_DECISION, model_decision_required=True)
            if result.status is ReviewStatus.REQUIRES_MODEL_DECISION:
                if decision is None:
                    current = replace(current, attempts=current.attempts, review_status=result.status, review=result)
                else:
                    accepted = bool(decision.get("accepted"))
                    decision_text = str(decision.get("reason", ""))[:MAX_REVIEW_TEXT]
                    evidence_refs = decision.get("evidence_refs")
                    valid_refs = tuple(
                        str(item)[:120]
                        for item in evidence_refs[:MAX_REVIEW_EVIDENCE]
                        if isinstance(item, str) and item.strip()
                    ) if isinstance(evidence_refs, list) else ()
                    decision_issue = ()
                    if not accepted:
                        decision_issue = (_issue("model_decision_rejected", "decision", decision_text or "model rejected the candidate"),)
                    elif current.policy.semantic_required and not valid_refs:
                        accepted = False
                        decision_issue = (_issue("model_decision_missing_evidence", "decision.evidence_refs", "accepted model decisions must cite bounded evidence references"),)
                    decision_evidence = tuple(result.evidence) + (({"kind": "model_decision", "evidenceRefs": list(valid_refs)},) if valid_refs else ())
                    result = ReviewResult(ReviewStatus.COMPLETED if accepted else ReviewStatus.FAILED, result.checks, decision_issue, decision_evidence, False)
                    current = self._apply_result(current, result)
            else:
                current = self._apply_result(current, result)
            self._items[current.candidate_id] = (current, spec)
            return current

    def _apply_result(self, candidate: ChartCandidate, result: ReviewResult) -> ChartCandidate:
        if result.blocking:
            return replace(candidate, status=CandidateStatus.REVIEW_FAILED, review_status=result.status, publication_status=PublicationStatus.REJECTED, review=result)
        if result.warning:
            if candidate.policy.allow_warnings:
                return replace(candidate, status=CandidateStatus.WARNING, review_status=ReviewStatus.COMPLETED, publication_status=PublicationStatus.PUBLISHED_WITH_WARNING, review=result)
            return replace(candidate, status=CandidateStatus.REVIEW_FAILED, review_status=ReviewStatus.FAILED, publication_status=PublicationStatus.REJECTED, review=result)
        return replace(candidate, status=CandidateStatus.VERIFIED, review_status=ReviewStatus.COMPLETED, publication_status=PublicationStatus.PUBLISHED, review=result)

    def _load_source(self, attachment_ids: Sequence[str]) -> bytes | None:
        if self.attachments is None or not attachment_ids:
            return None
        for attachment_id in attachment_ids[:1]:
            item, error = self.attachments.validate(attachment_id)
            if error or item is None:
                return None
            try:
                return Path(item.canonical_path).read_bytes()
            except OSError:
                return None
        return None

    def review_tool(self):
        """Compatibility facade; the canonical factory lives in tools.adapters."""
        from ..tools.adapters.review import review_generated_chart_tool

        return review_generated_chart_tool(self)

    def gate(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            candidates = [item[0] for item in self._items.values() if item[0].run_id == run_id]
        pending = [item for item in candidates if item.policy.semantic_required and item.publication_status is PublicationStatus.UNPUBLISHED]
        failed = [item for item in candidates if item.publication_status is PublicationStatus.REJECTED]
        return {
            "ok": not pending and not failed,
            "pending": [item.safe_metadata() for item in pending[:MAX_REVIEW_EVIDENCE]],
            "failed": [item.safe_metadata() for item in failed[:MAX_REVIEW_EVIDENCE]],
            "published": [item.safe_metadata() for item in candidates if item.publication_status in {PublicationStatus.PUBLISHED, PublicationStatus.PUBLISHED_WITH_WARNING}],
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
    "chart_spec_digest",
    "review_candidate_bytes",
    "select_review_policy",
]
