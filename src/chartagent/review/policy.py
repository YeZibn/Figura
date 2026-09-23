"""Review policy selection and bounded lifecycle limits."""

from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Any

from ..spec import ChartFigure
from .models import (
    MAX_REVIEW_EVIDENCE,
    MAX_REVIEW_ISSUES,
    MAX_REVIEW_TEXT,
    ChartSemantic,
)

DEFAULT_REVIEW_DEADLINE_SECONDS = 300.0
DEFAULT_REVIEW_ATTEMPTS = 3


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

    @classmethod
    def from_dict(cls, value: object) -> "ReviewPolicy | None":
        if not isinstance(value, Mapping):
            return None
        max_attempts_value = value.get("maxAttempts")
        deadline_value = value.get("deadlineSeconds")
        if (
            isinstance(max_attempts_value, bool)
            or not isinstance(max_attempts_value, int)
            or not 1 <= max_attempts_value <= 8
            or isinstance(deadline_value, bool)
            or not isinstance(deadline_value, (int, float))
        ):
            return None
        try:
            deadline = float(deadline_value)
        except OverflowError:
            return None
        if not math.isfinite(deadline) or not 1.0 <= deadline <= 3600.0:
            return None
        if not isinstance(value.get("sourceLinked"), bool) or not isinstance(value.get("semanticRequired"), bool):
            return None
        if not isinstance(value.get("allowWarnings"), bool):
            return None
        checks = value.get("requiredChecks")
        if (
            not isinstance(checks, list)
            or len(checks) > 16
            or any(not isinstance(item, str) or not item or len(item) > 64 for item in checks)
        ):
            return None
        return cls(
            source_linked=value["sourceLinked"],
            semantic_required=value["semanticRequired"],
            allow_warnings=value["allowWarnings"],
            max_attempts=max_attempts_value,
            deadline_seconds=deadline,
            required_checks=tuple(checks),
        )


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


__all__ = [
    "DEFAULT_REVIEW_ATTEMPTS",
    "DEFAULT_REVIEW_DEADLINE_SECONDS",
    "MAX_REVIEW_EVIDENCE",
    "MAX_REVIEW_ISSUES",
    "MAX_REVIEW_TEXT",
    "ReviewPolicy",
    "select_review_policy",
]
