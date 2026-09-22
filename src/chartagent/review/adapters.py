"""Adapters from domain-specific review results to the shared gate."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..measurement import MeasurementSession
from .gates import ReviewCoordinator, ReviewDecision, ReviewIssue, ReviewRecord, ReviewType
from .models import CandidateStatus, ChartCandidate, PublicationStatus, ReviewStatus


def _bounded_issues(value: object) -> tuple[ReviewIssue, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        issue
        for item in value[:16]
        if (issue := ReviewIssue.from_value(item)) is not None
    )


class MeasurementReviewAdapter:
    """Translate the existing code-owned measurement audit into a gate."""

    def submit(
        self,
        coordinator: ReviewCoordinator,
        *,
        run_id: str,
        tool_name: str,
        payload: Mapping[str, Any],
        session: MeasurementSession | None = None,
    ) -> ReviewRecord | None:
        data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
        measurement = data.get("measurement") if isinstance(data, Mapping) else None
        if not isinstance(measurement, Mapping):
            return None
        reference = measurement.get("reference") if isinstance(measurement.get("reference"), Mapping) else {}
        attempt = measurement.get("attempt") if isinstance(measurement.get("attempt"), Mapping) else {}
        attempt_id = str(reference.get("attempt_id") or attempt.get("attempt_id") or "").strip()
        if not attempt_id:
            return None
        status = str(measurement.get("status") or "provisional")[:32]
        quality = measurement.get("quality") if isinstance(measurement.get("quality"), Mapping) else {}
        issues = _bounded_issues(quality.get("issues"))
        parent_id = str(attempt.get("parent_attempt_id") or "").strip() or None
        evidence = measurement.get("evidence") if isinstance(measurement.get("evidence"), Mapping) else {}
        evidence = dict(evidence)
        focus_suggestion = quality.get("focus_suggestion") or quality.get("repair_action")
        if isinstance(focus_suggestion, Mapping):
            evidence["focus_suggestion"] = dict(focus_suggestion)
        evidence["decision"] = dict(measurement.get("decision") or {}) if isinstance(measurement.get("decision"), Mapping) else {"status": "pending"}
        if issues:
            evidence["issues"] = [issue.to_dict() for issue in issues[:8]]
        max_attempts = (session.max_repair_attempts + 1) if session is not None else 4
        attempt_number = len(session.attempts) if session is not None else 1
        next_action = (
            "根据当前 overlay 和 measurement.evidence.refs，明确选择、舍弃或调用同一测量工具做定向补充"
            if status == "accepted"
            else "根据当前 issues、warnings 和 evidence.refs，由主 Agent 决定舍弃或定向补充；系统不会自动重测"
        )
        record = coordinator.begin(
            run_id,
            ReviewType.MEASUREMENT,
            attempt_id,
            attempt=attempt_number,
            max_attempts=max_attempts,
            parent_id=parent_id,
            subject_ref={
                "session_id": reference.get("session_id"),
                "attempt_id": attempt_id,
                "attachment_id": reference.get("attachment_id"),
                "panel_id": reference.get("panel_id"),
                "tool": tool_name,
            },
            evidence=(evidence,),
            next_action=next_action,
        )
        return record


class GeneratedChartReviewAdapter:
    """Translate ChartReviewManager's candidate lifecycle into the gate."""

    def submit(
        self,
        coordinator: ReviewCoordinator,
        *,
        candidate: ChartCandidate,
    ) -> ReviewRecord:
        review = candidate.review
        issues = tuple(
            ReviewIssue.from_value(item.to_dict())
            for item in (review.issues if review is not None else ())
        )
        issues = tuple(item for item in issues if item is not None)
        if candidate.publication_status is PublicationStatus.PUBLISHED:
            decision = "pass"
        elif candidate.publication_status is PublicationStatus.PUBLISHED_WITH_WARNING:
            decision = "pass_with_warning"
        elif candidate.status is CandidateStatus.RETRY_EXHAUSTED:
            decision = "exhausted"
        elif candidate.status is CandidateStatus.REVIEW_FAILED:
            decision = (
                "exhausted"
                if (review is not None and review.repair_kind == "terminal")
                or candidate.lineage_attempt >= candidate.policy.max_attempts
                else "repair_required"
            )
        elif candidate.review_status in {ReviewStatus.PENDING, ReviewStatus.REQUIRES_MODEL_DECISION}:
            decision = "reviewing"
        else:
            decision = "fail"
        record = coordinator.begin(
            candidate.run_id,
            ReviewType.GENERATED_CHART,
            candidate.candidate_id,
            attempt=candidate.lineage_attempt,
            max_attempts=candidate.policy.max_attempts,
            parent_id=candidate.parent_candidate_id,
            subject_ref={
                "candidate_id": candidate.candidate_id,
                "review_id": candidate.review_id,
                "chart_spec_digest": candidate.chart_spec_digest,
                "source_attachment_ids": list(candidate.source_attachment_ids[:16]),
                "panel_ids": list(candidate.panel_ids[:16]),
                "generation_context": candidate.generation_context.to_dict() if candidate.generation_context is not None else None,
                "context_status": candidate.context_status,
            },
            evidence=(
                {
                    "candidate_id": candidate.candidate_id,
                "review_id": candidate.review_id,
                "chart_spec_digest": candidate.chart_spec_digest,
                "repair_kind": review.repair_kind if review is not None else "none",
                "repair_target": dict(review.repair_target) if review is not None and isinstance(review.repair_target, Mapping) else None,
            },
            ),
            next_action=(review.suggested_action if review is not None else None),
        )
        if decision == "reviewing":
            return record
        return coordinator.apply(
            record.review_id,
            ReviewDecision(
                decision=decision,
                issues=issues,
                confidence=review.confidence if review is not None else None,
                next_action=review.suggested_action if review is not None else None,
                details={
                    "candidate_status": candidate.status.value,
                    "review_status": candidate.review_status.value,
                    "publication_status": candidate.publication_status.value,
                    "review_mode": review.review_mode if review is not None else "unknown",
                },
                repair_kind=review.repair_kind if review is not None else "none",
                repair_target=review.repair_target if review is not None else None,
            ),
        )


__all__ = ["GeneratedChartReviewAdapter", "MeasurementReviewAdapter"]
