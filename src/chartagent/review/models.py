"""Canonical value objects for generated-chart review."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping

from ..spec import ChartFigure, ChartSpec, GenerationContext, context_digest

if TYPE_CHECKING:
    from .policy import ReviewPolicy

MAX_REVIEW_ISSUES = 32
MAX_REVIEW_EVIDENCE = 16
MAX_REVIEW_TEXT = 240
ChartSemantic = ChartSpec | ChartFigure
REPAIR_KINDS = frozenset({"none", "spec_only", "evidence_needed", "source_rebind", "terminal"})


class CandidateStatus(str, Enum):
    REVIEW_PENDING = "review_pending"
    VERIFIED = "verified"
    WARNING = "warning"
    REVIEW_FAILED = "review_failed"
    TIMED_OUT = "timed_out"
    RETRY_EXHAUSTED = "retry_exhausted"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class PublicationStatus(str, Enum):
    UNPUBLISHED = "unpublished"
    PUBLISHED = "published"
    PUBLISHED_WITH_WARNING = "published_with_warning"
    REJECTED = "rejected"


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

    @classmethod
    def from_dict(cls, value: object) -> "ReviewIssue | None":
        if not isinstance(value, Mapping):
            return None
        code = value.get("code")
        location = value.get("location")
        message = value.get("message")
        severity = value.get("severity")
        if (
            not isinstance(code, str)
            or not code.strip()
            or len(code) > 64
            or not isinstance(location, str)
            or not location.strip()
            or len(location) > 160
            or not isinstance(message, str)
            or not message.strip()
            or len(message) > MAX_REVIEW_TEXT
            or not isinstance(severity, str)
            or severity not in {"error", "warning"}
        ):
            return None
        return cls(code, location, message, severity)


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
    repair_kind: str | None = None
    repair_target: Mapping[str, Any] | None = None
    candidate_attempt: int | None = None

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
        if self.repair_kind is not None:
            result["repairKind"] = self.repair_kind if self.repair_kind in REPAIR_KINDS else "terminal"
        if isinstance(self.repair_target, Mapping):
            result["repairTarget"] = dict(self.repair_target)
        if self.candidate_attempt is not None:
            result["candidateAttempt"] = max(1, min(int(self.candidate_attempt), 8))
        return result

    @classmethod
    def from_dict(cls, value: object) -> "ReviewResult | None":
        if not isinstance(value, Mapping):
            return None
        try:
            status = ReviewStatus(str(value.get("status") or ""))
        except ValueError:
            return None
        checks = value.get("checks")
        issues = value.get("issues")
        evidence = value.get("evidence")
        confidence = value.get("confidence")
        model_decision_required = value.get("modelDecisionRequired")
        review_mode = value.get("reviewMode")
        if (
            not isinstance(checks, Mapping)
            or len(checks) > 64
            or any(
                not isinstance(key, str)
                or not key
                or len(key) > 96
                or not isinstance(item, str)
                or len(item) > 32
                for key, item in checks.items()
            )
            or not isinstance(issues, list)
            or len(issues) > MAX_REVIEW_ISSUES
            or not isinstance(evidence, list)
            or len(evidence) > MAX_REVIEW_EVIDENCE
            or any(not isinstance(item, Mapping) for item in evidence)
            or not isinstance(model_decision_required, bool)
            or not isinstance(review_mode, str)
            or not review_mode
            or len(review_mode) > 32
        ):
            return None
        parsed_issues = tuple(ReviewIssue.from_dict(item) for item in issues)
        if any(issue is None for issue in parsed_issues):
            return None
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                return None
            try:
                confidence = float(confidence)
            except OverflowError:
                return None
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                return None
        repair_target = value.get("repairTarget")
        if repair_target is not None and not isinstance(repair_target, Mapping):
            return None
        string_fields = (
            ("decision", 32),
            ("candidateId", 160),
            ("reviewId", 160),
            ("chartSpecDigest", 64),
            ("suggestedAction", MAX_REVIEW_TEXT),
            ("recoveryClassification", 64),
            ("repairKind", 32),
        )
        if any(
            raw is not None and (not isinstance(raw, str) or not raw or len(raw) > limit)
            for key, limit in string_fields
            if (raw := value.get(key)) is not None
        ):
            return None
        candidate_attempt = value.get("candidateAttempt")
        if candidate_attempt is not None and (
            isinstance(candidate_attempt, bool)
            or not isinstance(candidate_attempt, int)
            or not 1 <= candidate_attempt <= 8
        ):
            return None
        repair_kind = value.get("repairKind")
        if repair_kind is not None and repair_kind not in REPAIR_KINDS:
            return None
        return cls(
            status=status,
            checks=dict(checks),
            issues=tuple(issue for issue in parsed_issues if issue is not None),
            evidence=tuple(dict(item) for item in evidence),
            model_decision_required=model_decision_required,
            decision=value.get("decision"),
            confidence=confidence,
            review_mode=review_mode,
            candidate_id=value.get("candidateId"),
            review_id=value.get("reviewId"),
            chart_spec_digest=value.get("chartSpecDigest"),
            suggested_action=value.get("suggestedAction"),
            recovery_classification=value.get("recoveryClassification"),
            repair_kind=repair_kind,
            repair_target=dict(repair_target) if isinstance(repair_target, Mapping) else None,
            candidate_attempt=candidate_attempt,
        )


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
    generation_context: GenerationContext | None = None
    context_digest: str | None = None
    context_status: str = "absent"
    parent_attempt: int | None = None
    input_run_id: str = ""
    call_id: str = ""
    tool_name: str = ""
    turn: int = 0
    safety_result: ReviewResult | None = None
    semantic_result: ReviewResult | None = None
    repair_phase: str = "none"
    updated_at: str = ""

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
            # Candidate lineage is distinct from the number of deterministic /
            # VLM checks made against this candidate.  Keep an explicit alias
            # so durable projections do not have to infer it from attempts.
            "candidateAttempt": self.lineage_attempt,
            "lineageAttempt": self.lineage_attempt,
            "contextStatus": self.context_status[:32],
        }
        if self.parent_candidate_id:
            result["parentCandidateId"] = self.parent_candidate_id
        if self.parent_attempt is not None:
            result["parentAttempt"] = max(0, int(self.parent_attempt))
        if self.context_digest:
            result["generationContextDigest"] = self.context_digest
        if self.generation_context is not None:
            result["generationContext"] = self.generation_context.to_dict()
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
                "basis": str(self.coverage.get("basis", "full_source"))[:32],
            }
        if self.superseded:
            result["superseded"] = True
        if self.review is not None:
            result["review"] = self.review.to_dict()
        return result


__all__ = [
    "CandidateStatus",
    "ChartCandidate",
    "ChartSemantic",
    "MAX_REVIEW_EVIDENCE",
    "MAX_REVIEW_ISSUES",
    "MAX_REVIEW_TEXT",
    "PublicationStatus",
    "REPAIR_KINDS",
    "ReviewIssue",
    "ReviewResult",
    "ReviewStatus",
]
