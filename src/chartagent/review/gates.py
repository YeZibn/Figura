"""Immutable execution-gate projection derived from chart review aggregates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .models import ReviewIssue


class ReviewType(str, Enum):
    GENERATED_CHART = "generated_chart"


class GateState(str, Enum):
    OPEN = "open"
    REVIEWING = "reviewing"
    REPAIR_REQUIRED = "repair_required"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class ExecutionGate:
    """Read-only decision projection; it is never restored as authority."""

    state: GateState = GateState.OPEN
    blocking: bool = False
    review_type: ReviewType | None = None
    review_id: str | None = None
    subject_id: str | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    next_action: str | None = None
    issues: tuple[ReviewIssue, ...] = ()
    repair_kind: str = "none"
    repair_target: Mapping[str, Any] | None = None
    repair_phase: str = "none"
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": self.state.value,
            "blocking": self.blocking,
            "issues": [issue.to_dict() for issue in self.issues[:32]],
            "repairKind": self.repair_kind,
            "repairPhase": self.repair_phase,
        }
        if self.updated_at:
            result["updatedAt"] = self.updated_at
        if self.review_type:
            result["reviewType"] = self.review_type.value
        if self.review_id:
            result["reviewId"] = self.review_id[:128]
        if self.subject_id:
            result["subjectId"] = self.subject_id[:160]
        if self.attempt is not None:
            result["attempt"] = self.attempt
        if self.max_attempts is not None:
            result["maxAttempts"] = self.max_attempts
        if self.next_action:
            result["nextAction"] = self.next_action[:240]
        if self.repair_target:
            result["repairTarget"] = dict(self.repair_target)
        return result
