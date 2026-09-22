"""Deterministic safety evaluation for generated chart artifacts."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from ..spec import ChartFigure
from .models import (
    MAX_REVIEW_EVIDENCE,
    MAX_REVIEW_ISSUES,
    ChartSemantic,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
)


def _issue(code: str, location: str, message: str, severity: str = "error") -> ReviewIssue:
    return ReviewIssue(code, location, message, severity)


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
    is performed by the internal VLM reviewer; this function remains a
    deterministic artifact boundary.
    """
    del source_image
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
                structural_issues.append(
                    _issue("incomplete_coverage", "coverage.status", "figure coverage is incomplete")
                )
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
                issues.extend(
                    _issue("invalid_chart_spec", item.location, item.message)
                    for item in structural.issues[:MAX_REVIEW_ISSUES]
                )
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
        checks["encoded_artifact"] = "failed" if any(
            item.location.startswith("artifact")
            or item.code in {"dimension_mismatch", "blank_artifact", "unsupported_artifact"}
            for item in issues
        ) else "passed"
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


def merge_review_results(safety: ReviewResult, semantic: ReviewResult) -> ReviewResult:
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


__all__ = ["merge_review_results", "review_candidate_bytes"]
