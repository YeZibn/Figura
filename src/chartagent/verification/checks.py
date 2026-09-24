"""Deterministic checks for one rendered chart and its exact specification."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from ..spec import ChartFigure
from .models import MAX_ISSUES, VerificationIssue


@dataclass(frozen=True)
class DeterministicChecks:
    checks: Mapping[str, str]
    issues: tuple[VerificationIssue, ...]

    @property
    def blocking(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


def _issue(code: str, location: str, message: str, severity: str = "error") -> VerificationIssue:
    return VerificationIssue(code[:64], location[:160], message[:240], "warning" if severity == "warning" else "error")


def verify_chart_bytes(
    spec: Any,
    content: bytes,
    *,
    media_type: str,
    declared_width: int,
    declared_height: int,
) -> DeterministicChecks:
    """Check ChartSpec structure and encoded image facts without model state."""
    issues: list[VerificationIssue] = []
    checks: dict[str, str] = {}
    try:
        from ..tools.chart.validation import validate_generation

        if isinstance(spec, ChartFigure):
            structural_issues = [
                _issue("invalid_chart_figure", item.location, item.message)
                for item in spec.validate()
            ]
            if spec.coverage.status != "complete":
                structural_issues.append(_issue("incomplete_coverage", "coverage.status", "figure coverage is incomplete"))
            for index, child in enumerate(spec.charts):
                result = validate_generation(child.spec)
                structural_issues.extend(
                    _issue("invalid_chart_spec", f"charts[{index}].{item.location}", item.message)
                    for item in result.issues
                )
            issues.extend(structural_issues[:MAX_ISSUES])
            structural_blocking = any(item.severity == "error" for item in structural_issues)
        else:
            structural = validate_generation(spec)
            structural_blocking = structural.blocking
            if structural.blocking:
                issues.extend(
                    _issue("invalid_chart_spec", item.location, item.message)
                    for item in structural.issues[:MAX_ISSUES]
                )
        checks["structure"] = "fail" if structural_blocking else "pass"
    except Exception as exc:  # defensive verification boundary
        issues.append(_issue("invalid_chart_spec", "spec", f"ChartSpec validation failed: {type(exc).__name__}"))
        checks["structure"] = "fail"

    if not isinstance(content, bytes) or not content:
        issues.append(_issue("empty_artifact", "artifact", "generated chart image is empty"))
        checks["encoded_artifact"] = "fail"
        checks["render_fidelity"] = "not_run"
        checks["layout_readability"] = "not_run"
        return DeterministicChecks(checks, tuple(issues[:MAX_ISSUES]))

    if not isinstance(media_type, str) or media_type.lower() != "image/png":
        issues.append(_issue("unsupported_artifact", "artifact.mediaType", "generated charts must use PNG"))
    try:
        with Image.open(BytesIO(content)) as image:
            actual_size = image.size
            image_format = image.format
            extrema = image.convert("RGB").getextrema()
            if image_format != "PNG":
                issues.append(_issue("artifact_format", "artifact", "encoded chart does not decode as PNG"))
            if actual_size != (declared_width, declared_height):
                issues.append(_issue("dimension_mismatch", "artifact.dimensions", "encoded dimensions do not match renderer metadata"))
            if all(low == high for low, high in extrema):
                issues.append(_issue("blank_artifact", "artifact", "chart image is a uniform blank canvas"))
        artifact_codes = {"artifact_format", "dimension_mismatch", "blank_artifact", "unsupported_artifact"}
        checks["encoded_artifact"] = "fail" if any(item.code in artifact_codes for item in issues) else "pass"
    except (UnidentifiedImageError, OSError, ValueError):
        issues.append(_issue("artifact_decode", "artifact", "encoded chart image could not be decoded"))
        checks["encoded_artifact"] = "fail"
    checks["render_fidelity"] = "not_run"
    checks["layout_readability"] = "not_run"
    return DeterministicChecks(checks, tuple(issues[:MAX_ISSUES]))


__all__ = ["DeterministicChecks", "verify_chart_bytes"]
