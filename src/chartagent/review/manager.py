"""Single source of truth for generated-candidate review and publication."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from ..attachments import AttachmentRegistry
from ..spec import (
    ChartFigure,
    ChartSpec,
    GenerationContext,
    chart_figure_digest,
    chart_spec_digest,
    context_digest,
    normalize_generation_context,
)
from ..source_scope import SourceScopeResolution, resolve_generation_scope
from ..tools.core.result import GeneratedImage
from .evaluator import merge_review_results
from .gates import ExecutionGate, GateState, ReviewType
from .models import (
    MAX_REVIEW_EVIDENCE,
    CandidateStatus,
    ChartCandidate,
    ChartSemantic,
    PublicationStatus,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
    REPAIR_KINDS,
)
from .policy import ReviewPolicy, select_review_policy

REVIEW_STATE_VERSION = 1
MAX_REVIEW_CANDIDATES = 64
_REPAIR_PHASES = frozenset({"none", "evidence", "assemble", "render", "rebind", "terminal"})


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChartReviewManager:
    """Thread-safe in-process candidate store used by Agent and Gateway hooks."""

    def __init__(
        self,
        *,
        attachments: AttachmentRegistry | None = None,
        candidate_input_resolver: Callable[[str, str, str, str], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self.attachments = attachments
        self.candidate_input_resolver = candidate_input_resolver
        self._items: dict[str, tuple[ChartCandidate, ChartSemantic]] = {}
        self._keys: dict[tuple[str, str, str], str] = {}
        self._lock = RLock()

    def semantic_result(self, candidate: ChartCandidate) -> ReviewResult | None:
        """Return a cached VLM decision for this candidate attempt."""
        with self._lock:
            current = self._items.get(candidate.candidate_id)
            if current is None or current[0].review_id != candidate.review_id:
                return None
            return current[0].semantic_result

    def remember_semantic_result(self, candidate: ChartCandidate, result: ReviewResult) -> ReviewResult:
        """Store and idempotently return the only semantic result for an attempt."""
        with self._lock:
            current_item = self._items.get(candidate.candidate_id)
            if current_item is None or current_item[0].review_id != candidate.review_id:
                raise ValueError("candidate review context does not match")
            current, spec = current_item
            existing = current.semantic_result
            if existing is not None:
                return existing
            if (
                result.candidate_id != current.candidate_id
                or result.review_id != current.review_id
                or result.chart_spec_digest != current.chart_spec_digest
            ):
                raise ValueError("semantic result identity does not match candidate")
            self._items[current.candidate_id] = (
                replace(current, semantic_result=result, updated_at=_timestamp()),
                spec,
            )
            return result

    def create_candidate(
        self,
        run_id: str,
        call_id: str,
        image: GeneratedImage,
        spec: ChartSemantic,
        *,
        source_attachment_ids: Sequence[str] = (),
        explicit_review: bool = False,
        generation_context: GenerationContext | Mapping[str, Any] | None = None,
        tool_name: str = "",
        turn: int = 0,
    ) -> ChartCandidate:
        digest = chart_figure_digest(spec) if isinstance(spec, ChartFigure) else chart_spec_digest(spec)
        key = (run_id, call_id, digest)
        with self._lock:
            existing_id = self._keys.get(key)
            if existing_id is not None:
                return self._items[existing_id][0]
            metadata = image.metadata if isinstance(image.metadata, Mapping) else {}
            context = normalize_generation_context(generation_context)
            if context is None:
                context = getattr(spec, "generation_context", None)
            if context is None:
                raw_context = metadata.get("generation_context") or metadata.get("generationContext")
                context = normalize_generation_context(raw_context)
            policy = select_review_policy(spec, source_attachment_ids=source_attachment_ids, explicit_review=explicit_review)
            parent_candidate_id: str | None = None
            parent_attempt: int | None = None
            lineage_attempt = 1
            semantic_source_ids = (
                (spec.source.attachment_id,)
                if isinstance(spec, ChartFigure) and spec.source.attachment_id.strip()
                else ()
            )
            context_source_ids = (
                (context.source_scope.attachment_id,)
                if context is not None and context.source_scope is not None
                else ()
            )
            effective_source_attachment_ids = tuple(
                dict.fromkeys(tuple(source_attachment_ids) + semantic_source_ids + context_source_ids)
            )[:16]
            panel_values = metadata.get("panelIds", metadata.get("panel_ids", ()))
            if isinstance(spec, ChartFigure) and spec.source.panel_id:
                panel_values = tuple(panel_values) + (spec.source.panel_id,) if isinstance(panel_values, (list, tuple)) else (spec.source.panel_id,)
            if context is not None and context.source_scope is not None:
                context_panel_ids = context.source_scope.panel_ids
                panel_values = tuple(panel_values) + tuple(context_panel_ids) if isinstance(panel_values, (list, tuple)) else tuple(context_panel_ids)
            panel_ids = tuple(
                item[:160]
                for item in panel_values
                if isinstance(item, str) and item.strip()
            )[:16] if isinstance(panel_values, (list, tuple)) else ()
            context_status = "bound" if context is not None else "absent"
            source_linked_without_context = bool(
                source_attachment_ids
                or panel_ids
                or (isinstance(spec, ChartFigure) and spec.source.attachment_id.strip())
                or (
                    isinstance(spec, ChartSpec)
                    and isinstance(spec.metadata.source, str)
                    and spec.metadata.source.strip()
                )
            )
            if context is None and source_linked_without_context:
                context_status = "unbound"
            context_hash = context_digest(context)
            candidate_id = f"cand_{uuid4().hex}"
            review_id = f"review_{uuid4().hex}"
            collection_id = metadata.get("collection_id") if isinstance(metadata.get("collection_id"), str) else None
            figure_id = spec.figure_id if isinstance(spec, ChartFigure) else None
            chart_type = "composite" if isinstance(spec, ChartFigure) else spec.metadata.chart_type.value
            title = str(
                metadata.get("title")
                or (
                    next((item.title or item.spec.metadata.title for item in spec.charts), "复合图表")
                    if isinstance(spec, ChartFigure)
                    else spec.metadata.title
                )
                or "图表"
            )[:240]
            for prior_id, (prior, prior_spec) in tuple(self._items.items()):
                same_candidate_scope = (
                    prior.run_id == run_id
                    and prior.chart_type == chart_type
                    and prior.collection_id == collection_id
                    and prior.figure_id == figure_id
                    and prior.source_attachment_ids == effective_source_attachment_ids
                    and prior.panel_ids == panel_ids
                    and (bool(effective_source_attachment_ids or panel_ids) or prior.title == title)
                )
                if (
                    same_candidate_scope
                    and prior.publication_status is PublicationStatus.REJECTED
                    and prior.status in {CandidateStatus.REVIEW_FAILED, CandidateStatus.RETRY_EXHAUSTED}
                    and not prior.superseded
                ):
                    if parent_candidate_id is None or prior.lineage_attempt > lineage_attempt:
                        parent_candidate_id = prior.candidate_id
                        parent_attempt = prior.lineage_attempt
                        lineage_attempt = prior.lineage_attempt + 1
                    self._items[prior_id] = (replace(prior, superseded=True), prior_spec)
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
                    candidate_id=candidate_id,
                    review_id=review_id,
                    chart_spec_digest=digest,
                    suggested_action="stop_and_keep_unpublished",
                    recovery_classification="retry_exhausted",
                    repair_kind="terminal",
                )
                candidate = ChartCandidate(
                    candidate_id=candidate_id,
                    review_id=review_id,
                    run_id=run_id,
                    chart_spec_digest=digest,
                    chart_type=chart_type,
                    title=title,
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
                    figure_id=figure_id,
                    collection_id=collection_id,
                    child_chart_ids=tuple(item.chart_id for item in spec.charts) if isinstance(spec, ChartFigure) else (),
                    figure_source=spec.source.to_dict() if isinstance(spec, ChartFigure) else None,
                    coverage=spec.coverage.to_dict() if isinstance(spec, ChartFigure) else None,
                    generation_context=context,
                    context_digest=context_hash,
                    context_status=context_status,
                    parent_attempt=parent_attempt,
                    call_id=call_id,
                    tool_name=tool_name,
                    input_run_id=run_id,
                    turn=max(0, int(turn)),
                    repair_phase="terminal",
                    updated_at=_timestamp(),
                )
                self._items[candidate.candidate_id] = (candidate, spec)
                self._keys[key] = candidate.candidate_id
                return candidate
            candidate = ChartCandidate(
                candidate_id=candidate_id,
                review_id=review_id,
                run_id=run_id,
                chart_spec_digest=digest,
                chart_type=chart_type,
                title=title,
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
                figure_id=figure_id,
                collection_id=collection_id,
                child_chart_ids=tuple(item.chart_id for item in spec.charts) if isinstance(spec, ChartFigure) else (),
                figure_source=spec.source.to_dict() if isinstance(spec, ChartFigure) else None,
                coverage=spec.coverage.to_dict() if isinstance(spec, ChartFigure) else None,
                generation_context=context,
                context_digest=context_hash,
                context_status=context_status,
                parent_attempt=parent_attempt,
                call_id=call_id,
                tool_name=tool_name,
                input_run_id=run_id,
                turn=max(0, int(turn)),
                updated_at=_timestamp(),
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
            return self._expire_if_needed(candidate, item[1])

    def _expire_if_needed(self, candidate: ChartCandidate, spec: ChartSemantic) -> ChartCandidate:
        if candidate.status is not CandidateStatus.REVIEW_PENDING or time.monotonic() <= candidate.deadline_at:
            return candidate
        result = ReviewResult(
            status=ReviewStatus.TIMED_OUT,
            checks={"review_deadline": "failed"},
            issues=(ReviewIssue("review_timed_out", "review.deadline", "generated-chart review exceeded its deadline"),),
            decision="fail",
            confidence=0.0,
            review_mode="vlm" if candidate.policy.semantic_required else "safety",
            candidate_id=candidate.candidate_id,
            review_id=candidate.review_id,
            chart_spec_digest=candidate.chart_spec_digest,
            repair_kind="terminal",
        )
        expired = replace(
            candidate,
            status=CandidateStatus.TIMED_OUT,
            review_status=ReviewStatus.TIMED_OUT,
            publication_status=PublicationStatus.REJECTED,
            review=result,
            repair_phase="terminal",
            updated_at=_timestamp(),
        )
        self._items[candidate.candidate_id] = (expired, spec)
        return expired

    def get_spec(self, candidate_id: str, review_id: str | None = None) -> ChartSemantic | None:
        with self._lock:
            item = self._items.get(candidate_id)
            if item is None or (review_id is not None and item[0].review_id != review_id):
                return None
            return item[1]

    def candidates_for_review(
        self,
        run_id: str,
        candidate_ids: Sequence[str] = (),
    ) -> tuple[tuple[ChartCandidate, ChartSemantic], ...]:
        with self._lock:
            if candidate_ids:
                selected = []
                for candidate_id in candidate_ids:
                    item = self._items.get(candidate_id)
                    if item is not None and item[0].run_id == run_id:
                        selected.append(item)
                return tuple(selected)
            return tuple(item for item in self._items.values() if item[0].run_id == run_id)

    def source_resolution(self, candidate: ChartCandidate) -> SourceScopeResolution:
        """Resolve the candidate's exact source scope for internal consumers.

        Source-linked candidates without a bound context are deliberately not
        allowed to fall back to the whole attachment.  They remain
        ``unbound`` until the caller rebinds a panel scope.
        """
        if candidate.generation_context is None:
            if candidate.source_attachment_ids:
                return SourceScopeResolution(
                    status="source_scope_unavailable",
                    attachment_id=candidate.source_attachment_ids[0],
                    issues=(
                        {
                            "location": "generation_context.source_scope",
                            "message": "source-linked candidate has no bound generation context",
                        },
                    ),
                    action_hint="重新绑定当前 attachment 的 active panel handoff",
                )
            return SourceScopeResolution(status="not_applicable")
        return resolve_generation_scope(self.attachments, candidate.generation_context)

    def source_payload(self, candidate: ChartCandidate) -> tuple[bytes, str] | None:
        """Return only the authorized panel crop for an internal reviewer."""
        resolution = self.source_resolution(candidate)
        if not resolution.resolved:
            return None
        return resolution.content, resolution.media_type

    def record_safety_result(
        self,
        candidate: ChartCandidate,
        result: ReviewResult,
    ) -> ChartCandidate:
        """Store the one deterministic result for this immutable candidate."""
        with self._lock:
            item = self._items.get(candidate.candidate_id)
            if item is None or item[0].review_id != candidate.review_id:
                raise ValueError("candidate review context does not match")
            current, spec = item
            if current.safety_result is not None:
                return current
            current = replace(
                current,
                attempts=max(1, current.attempts),
                safety_result=result,
                updated_at=_timestamp(),
            )
            if result.blocking or not current.policy.semantic_required:
                current = self._apply_result(current, result)
            self._items[current.candidate_id] = (current, spec)
            return current

    def process(
        self,
        candidate: ChartCandidate,
        *,
        safety_result: ReviewResult | None = None,
        semantic_result: ReviewResult | None = None,
    ) -> ChartCandidate:
        with self._lock:
            current_item = self._items.get(candidate.candidate_id)
            if current_item is None or current_item[0].review_id != candidate.review_id:
                raise ValueError("candidate review context does not match")
            current, spec = current_item
            if current.status in {CandidateStatus.VERIFIED, CandidateStatus.WARNING, CandidateStatus.REVIEW_FAILED, CandidateStatus.TIMED_OUT, CandidateStatus.RETRY_EXHAUSTED}:
                return current
            if safety_result is not None and current.safety_result is None:
                current = replace(
                    current,
                    attempts=max(1, current.attempts),
                    safety_result=safety_result,
                    updated_at=_timestamp(),
                )
            safety_result = current.safety_result
            if safety_result is None:
                raise ValueError("deterministic result must be recorded before review completion")
            if safety_result.blocking:
                result = safety_result
            elif current.policy.semantic_required:
                semantic_result = current.semantic_result or semantic_result
                if semantic_result is None:
                    self._items[current.candidate_id] = (current, spec)
                    return current
                if (
                    semantic_result.candidate_id != current.candidate_id
                    or semantic_result.review_id != current.review_id
                    or semantic_result.chart_spec_digest != current.chart_spec_digest
                ):
                    semantic_result = ReviewResult(
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
                        candidate_id=current.candidate_id,
                        review_id=current.review_id,
                        chart_spec_digest=current.chart_spec_digest,
                        repair_kind="terminal",
                    )
                    current = replace(
                        current,
                        semantic_result=semantic_result,
                        updated_at=_timestamp(),
                    )
                    result = merge_review_results(safety_result, semantic_result)
                else:
                    if current.semantic_result is None:
                        current = replace(
                            current,
                            semantic_result=semantic_result,
                            updated_at=_timestamp(),
                        )
                    result = merge_review_results(safety_result, semantic_result)
            else:
                result = safety_result
            current = self._apply_result(current, result)
            self._items[current.candidate_id] = (current, spec)
            return current

    def _apply_result(self, candidate: ChartCandidate, result: ReviewResult) -> ChartCandidate:
        if result.blocking:
            source_failure = any(
                issue.code in {"source_binding_failure", "source_scope_unavailable", "stale_source_scope"}
                for issue in result.issues
            )
            repair_kind = result.repair_kind if result.repair_kind in REPAIR_KINDS else None
            if repair_kind in {None, "none"}:
                repair_kind = "source_rebind" if source_failure else "spec_only"
            action = {
                "evidence_needed": "request_same_scope_evidence",
                "source_rebind": "rebind_source",
                "spec_only": "correct_chart_spec",
                "terminal": "stop_and_keep_unpublished",
            }.get(repair_kind, "stop_and_keep_unpublished")
            result = replace(
                result,
                suggested_action=result.suggested_action or action,
                recovery_classification=result.recovery_classification or repair_kind,
                repair_kind=repair_kind,
            )
            phase = {
                "evidence_needed": "evidence",
                "source_rebind": "rebind",
                "spec_only": "assemble",
                "terminal": "terminal",
            }.get(repair_kind, "terminal")
            return replace(candidate, status=CandidateStatus.REVIEW_FAILED, review_status=result.status, publication_status=PublicationStatus.REJECTED, review=result, repair_phase=phase, updated_at=_timestamp())
        if result.warning:
            if candidate.policy.allow_warnings:
                return replace(candidate, status=CandidateStatus.WARNING, review_status=ReviewStatus.COMPLETED, publication_status=PublicationStatus.PUBLISHED_WITH_WARNING, review=result, repair_phase="none", updated_at=_timestamp())
            return replace(candidate, status=CandidateStatus.REVIEW_FAILED, review_status=ReviewStatus.FAILED, publication_status=PublicationStatus.REJECTED, review=result, repair_phase="terminal", updated_at=_timestamp())
        return replace(candidate, status=CandidateStatus.VERIFIED, review_status=ReviewStatus.COMPLETED, publication_status=PublicationStatus.PUBLISHED, review=result, repair_phase="none", updated_at=_timestamp())

    def summary(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            candidates = [
                self._expire_if_needed(candidate, spec)
                for candidate, spec in self._items.values()
                if candidate.run_id == run_id
            ]
        active_candidates = [item for item in candidates if not item.superseded]
        pending = [
            item for item in active_candidates
            if item.policy.semantic_required and item.publication_status is PublicationStatus.UNPUBLISHED
        ]
        failed = [item for item in active_candidates if item.publication_status is PublicationStatus.REJECTED]
        recovery_actions = []
        for item in failed:
            recovery = item.review.recovery_classification if item.review is not None else None
            action = item.review.suggested_action if item.review is not None else None
            if recovery or action:
                recovery_actions.append({
                    "candidateId": item.candidate_id,
                    "classification": recovery or "review_failure",
                    "action": action or "correct_chart_spec",
                    "repairKind": item.review.repair_kind if item.review is not None else "terminal",
                    "target": dict(item.review.repair_target) if item.review is not None and isinstance(item.review.repair_target, Mapping) else None,
                    "parentAttempt": item.parent_attempt,
                })
        retryable = bool(failed) and not any(item.status is CandidateStatus.RETRY_EXHAUSTED for item in failed)
        return {
            "ok": not pending and not failed,
            "pending": [item.safe_metadata() for item in pending[:MAX_REVIEW_EVIDENCE]],
            "failed": [item.safe_metadata() for item in failed[:MAX_REVIEW_EVIDENCE]],
            "published": [
                item.safe_metadata() for item in active_candidates
                if item.publication_status in {PublicationStatus.PUBLISHED, PublicationStatus.PUBLISHED_WITH_WARNING}
            ],
            "retryable": retryable,
            "recoveryActions": recovery_actions[:MAX_REVIEW_EVIDENCE],
        }

    def execution_gate(self, run_id: str) -> ExecutionGate:
        """Derive the current blocking gate from the canonical candidates."""
        with self._lock:
            candidates = [
                self._expire_if_needed(candidate, spec)
                for candidate, spec in self._items.values()
                if candidate.run_id == run_id and not candidate.superseded
            ]
            blocking = [
                candidate for candidate in candidates
                if candidate.publication_status in {PublicationStatus.UNPUBLISHED, PublicationStatus.REJECTED}
            ]
        subject = blocking[0] if blocking else (candidates[-1] if candidates else None)
        if subject is None:
            return ExecutionGate()
        is_blocking = subject.publication_status in {PublicationStatus.UNPUBLISHED, PublicationStatus.REJECTED}
        if not is_blocking:
            state = GateState.OPEN
        elif subject.status is CandidateStatus.TIMED_OUT:
            state = GateState.FAILED
        elif subject.status is CandidateStatus.RETRY_EXHAUSTED or (
            subject.review is not None and subject.review.repair_kind == "terminal"
        ) or subject.lineage_attempt >= subject.policy.max_attempts:
            state = GateState.EXHAUSTED
        elif subject.status is CandidateStatus.REVIEW_FAILED:
            state = GateState.REPAIR_REQUIRED
        else:
            state = GateState.REVIEWING
        review = subject.review or subject.safety_result
        return ExecutionGate(
            state=state,
            blocking=is_blocking,
            review_type=ReviewType.GENERATED_CHART,
            review_id=subject.review_id,
            subject_id=subject.candidate_id,
            attempt=subject.lineage_attempt,
            max_attempts=subject.policy.max_attempts,
            next_action=review.suggested_action if review is not None else None,
            issues=review.issues if review is not None else (),
            repair_kind=(review.repair_kind or "none") if review is not None else "none",
            repair_target=review.repair_target if review is not None else None,
            repair_phase=subject.repair_phase,
            updated_at=subject.updated_at or None,
        )

    def gate(self, run_id: str) -> dict[str, Any]:
        """Return bounded candidate details for prompt context."""
        return self.summary(run_id)

    def mark_repair_phase(self, run_id: str, review_id: str, phase: str) -> ChartCandidate:
        normalized = str(phase or "").strip().lower()
        if normalized not in _REPAIR_PHASES:
            raise ValueError(f"unknown repair phase: {phase}")
        with self._lock:
            for candidate_id, (candidate, spec) in self._items.items():
                if candidate.run_id == run_id and candidate.review_id == review_id:
                    if candidate.status is not CandidateStatus.REVIEW_FAILED:
                        return candidate
                    updated = replace(candidate, repair_phase=normalized, updated_at=_timestamp())
                    self._items[candidate_id] = (updated, spec)
                    return updated
        raise KeyError(f"unknown review_id: {review_id}")

    @staticmethod
    def _snapshot_candidate(candidate: ChartCandidate) -> dict[str, Any]:
        return {
            "candidateId": candidate.candidate_id,
            "reviewId": candidate.review_id,
            "runId": candidate.run_id,
            "inputRunId": candidate.input_run_id,
            "chartSpecDigest": candidate.chart_spec_digest,
            "chartType": candidate.chart_type,
            "title": candidate.title,
            "mediaType": candidate.media_type,
            "byteCount": candidate.byte_count,
            "width": candidate.width,
            "height": candidate.height,
            "policy": candidate.policy.to_dict(),
            "status": candidate.status.value,
            "reviewStatus": candidate.review_status.value,
            "publicationStatus": candidate.publication_status.value,
            "review": candidate.review.to_dict() if candidate.review is not None else None,
            "safetyResult": candidate.safety_result.to_dict() if candidate.safety_result is not None else None,
            "semanticResult": candidate.semantic_result.to_dict() if candidate.semantic_result is not None else None,
            "sourceAttachmentIds": list(candidate.source_attachment_ids[:16]),
            "attempts": candidate.attempts,
            "deadlineRemainingSeconds": max(0.0, candidate.deadline_at - time.monotonic()),
            "superseded": candidate.superseded,
            "parentCandidateId": candidate.parent_candidate_id,
            "lineageAttempt": candidate.lineage_attempt,
            "panelIds": list(candidate.panel_ids[:16]),
            "figureId": candidate.figure_id,
            "collectionId": candidate.collection_id,
            "childChartIds": list(candidate.child_chart_ids[:16]),
            "figureSource": dict(candidate.figure_source) if isinstance(candidate.figure_source, Mapping) else None,
            "coverage": dict(candidate.coverage) if isinstance(candidate.coverage, Mapping) else None,
            "generationContext": candidate.generation_context.to_dict() if candidate.generation_context is not None else None,
            "contextDigest": candidate.context_digest,
            "contextStatus": candidate.context_status,
            "parentAttempt": candidate.parent_attempt,
            "callId": candidate.call_id,
            "toolName": candidate.tool_name,
            "turn": candidate.turn,
            "repairPhase": candidate.repair_phase,
            "updatedAt": candidate.updated_at,
        }

    def to_state(self, run_id: str) -> dict[str, Any]:
        """Serialize one versioned source-of-truth review snapshot."""
        with self._lock:
            candidates = [
                candidate for candidate, _ in self._items.values()
                if candidate.run_id == run_id
            ][-MAX_REVIEW_CANDIDATES:]
            return {
                "version": REVIEW_STATE_VERSION,
                "candidates": [self._snapshot_candidate(item) for item in candidates],
            }

    def restore(self, value: object, *, active_run_id: str | None = None) -> None:
        """Restore canonical aggregates from their private persisted inputs."""
        if (
            not isinstance(value, Mapping)
            or type(value.get("version")) is not int
            or value.get("version") != REVIEW_STATE_VERSION
        ):
            raise ValueError("unsupported_review_state_version")
        raw_candidates = value.get("candidates")
        if not isinstance(raw_candidates, list) or len(raw_candidates) > MAX_REVIEW_CANDIDATES:
            raise ValueError("invalid_review_state")
        if raw_candidates and self.candidate_input_resolver is None:
            raise ValueError("review_candidate_resolver_unavailable")
        restored: dict[str, tuple[ChartCandidate, ChartSemantic]] = {}
        keys: dict[tuple[str, str, str], str] = {}

        def required_int(raw: Mapping[str, Any], key: str, minimum: int, maximum: int) -> int:
            item = raw.get(key)
            if isinstance(item, bool) or not isinstance(item, int) or not minimum <= item <= maximum:
                raise ValueError("invalid_review_candidate")
            return item

        def bounded_strings(raw: Mapping[str, Any], key: str, maximum: int) -> tuple[str, ...]:
            items = raw.get(key)
            if not isinstance(items, list):
                raise ValueError("invalid_review_candidate")
            bounded = items[:maximum]
            if any(not isinstance(item, str) or not item for item in bounded):
                raise ValueError("invalid_review_candidate")
            return tuple(item[:160] for item in bounded)

        for raw in raw_candidates:
            if not isinstance(raw, Mapping):
                raise ValueError("invalid_review_candidate")
            candidate_id = raw.get("candidateId")
            review_id = raw.get("reviewId")
            run_id = raw.get("runId")
            input_run_id = raw.get("inputRunId")
            digest = raw.get("chartSpecDigest")
            if not all(isinstance(item, str) and item for item in (candidate_id, review_id, run_id, input_run_id, digest)):
                raise ValueError("invalid_review_candidate_identity")
            if any(len(item) > 160 for item in (candidate_id, review_id, run_id, input_run_id)) or len(digest) != 64:
                raise ValueError("invalid_review_candidate_identity")
            try:
                stored = self.candidate_input_resolver(input_run_id, candidate_id, review_id, digest)  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001 - storage failures must be a bounded recovery error
                raise ValueError("review_candidate_input_unavailable") from exc
            if not isinstance(stored, Mapping):
                raise ValueError("review_candidate_input_unavailable")
            content = stored.get("content")
            media_type = stored.get("media_type")
            spec_value = stored.get("chart_spec")
            if not isinstance(content, bytes) or not content or not isinstance(media_type, str) or not isinstance(spec_value, Mapping):
                raise ValueError("review_candidate_input_invalid")
            try:
                if spec_value.get("kind") == "chart_figure":
                    spec: ChartSemantic = ChartFigure.from_dict(spec_value)
                else:
                    spec = ChartSpec.from_dict(spec_value)
                actual_digest = chart_figure_digest(spec) if isinstance(spec, ChartFigure) else chart_spec_digest(spec)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("review_candidate_input_invalid") from exc
            media_type_snapshot = raw.get("mediaType")
            if (
                actual_digest != digest
                or len(content) != required_int(raw, "byteCount", 1, 2**31 - 1)
                or not isinstance(media_type_snapshot, str)
                or media_type.lower() != media_type_snapshot.lower()
            ):
                raise ValueError("review_candidate_identity_mismatch")
            policy = ReviewPolicy.from_dict(raw.get("policy"))
            try:
                status = CandidateStatus(str(raw.get("status")))
                review_status = ReviewStatus(str(raw.get("reviewStatus")))
                publication_status = PublicationStatus(str(raw.get("publicationStatus")))
            except ValueError as exc:
                raise ValueError("invalid_review_candidate_state") from exc
            review = ReviewResult.from_dict(raw.get("review"))
            safety_result = ReviewResult.from_dict(raw.get("safetyResult"))
            semantic_result = ReviewResult.from_dict(raw.get("semanticResult"))
            if any(
                raw.get(key) is not None and parsed is None
                for key, parsed in (
                    ("review", review),
                    ("safetyResult", safety_result),
                    ("semanticResult", semantic_result),
                )
            ):
                raise ValueError("invalid_review_candidate_state")
            if policy is None:
                raise ValueError("invalid_review_candidate_policy")
            if review is not None and review.status is not review_status:
                raise ValueError("invalid_review_candidate_state")
            for result in (review, safety_result, semantic_result):
                if result is not None and any(
                    actual is not None and actual != expected
                    for actual, expected in (
                        (result.candidate_id, candidate_id),
                        (result.review_id, review_id),
                        (result.chart_spec_digest, digest),
                    )
                ):
                    raise ValueError("review_candidate_identity_mismatch")
            if semantic_result is not None and (
                semantic_result.candidate_id != candidate_id
                or semantic_result.review_id != review_id
                or semantic_result.chart_spec_digest != digest
            ):
                raise ValueError("review_candidate_identity_mismatch")
            if review is not None and review.review_mode == "vlm" and (
                review.candidate_id != candidate_id
                or review.review_id != review_id
                or review.chart_spec_digest != digest
            ):
                raise ValueError("review_candidate_identity_mismatch")
            if not isinstance(raw.get("superseded"), bool):
                raise ValueError("invalid_review_candidate")
            for key in ("chartType", "title"):
                if not isinstance(raw.get(key), str):
                    raise ValueError("invalid_review_candidate")
            try:
                remaining_value = raw.get("deadlineRemainingSeconds")
                if isinstance(remaining_value, bool) or not isinstance(remaining_value, (int, float)):
                    raise ValueError
                remaining_value = float(remaining_value)
                if not math.isfinite(remaining_value):
                    raise ValueError
                remaining = max(0.0, min(remaining_value, policy.deadline_seconds))
                context = normalize_generation_context(raw.get("generationContext"))
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("invalid_review_candidate") from exc
            context_hash = raw.get("contextDigest")
            if (context is None and context_hash not in (None, "")) or (
                context is not None and context_hash != context_digest(context)
            ):
                raise ValueError("review_candidate_identity_mismatch")
            if context_digest(context) != context_digest(getattr(spec, "generation_context", None)):
                raise ValueError("review_candidate_identity_mismatch")
            parent_attempt_value = raw.get("parentAttempt")
            if parent_attempt_value is not None and (
                isinstance(parent_attempt_value, bool) or not isinstance(parent_attempt_value, int)
            ):
                raise ValueError("invalid_review_candidate")
            optional_strings = ("parentCandidateId", "figureId", "collectionId", "contextStatus", "callId", "toolName", "repairPhase", "updatedAt")
            if any(raw.get(key) is not None and not isinstance(raw.get(key), str) for key in optional_strings):
                raise ValueError("invalid_review_candidate")
            for key in ("figureSource", "coverage"):
                if raw.get(key) is not None and not isinstance(raw.get(key), Mapping):
                    raise ValueError("invalid_review_candidate")
            if raw.get("contextStatus") not in {"bound", "absent", "unbound"}:
                raise ValueError("invalid_review_candidate")
            if (
                publication_status is PublicationStatus.PUBLISHED
                and (status is not CandidateStatus.VERIFIED or review_status is not ReviewStatus.COMPLETED or review is None)
            ) or (
                publication_status is PublicationStatus.PUBLISHED_WITH_WARNING
                and (status is not CandidateStatus.WARNING or review_status is not ReviewStatus.COMPLETED or review is None)
            ) or (
                publication_status is PublicationStatus.REJECTED
                and (status not in {CandidateStatus.REVIEW_FAILED, CandidateStatus.TIMED_OUT, CandidateStatus.RETRY_EXHAUSTED} or review is None)
            ) or (
                publication_status is PublicationStatus.UNPUBLISHED
                and (
                    status is not CandidateStatus.REVIEW_PENDING
                    or review_status is not ReviewStatus.PENDING
                    or review is not None
                    or (safety_result is not None and safety_result.blocking)
                )
            ):
                raise ValueError("invalid_review_candidate_state")
            candidate = ChartCandidate(
                candidate_id=candidate_id,
                review_id=review_id,
                run_id=active_run_id or run_id,
                input_run_id=active_run_id or input_run_id,
                chart_spec_digest=digest,
                chart_type=raw["chartType"][:64],
                title=raw["title"][:240],
                media_type=media_type.lower(),
                byte_count=required_int(raw, "byteCount", 1, 2**31 - 1),
                width=required_int(raw, "width", 0, 2**31 - 1),
                height=required_int(raw, "height", 0, 2**31 - 1),
                policy=policy,
                status=status,
                review_status=review_status,
                publication_status=publication_status,
                review=review,
                source_attachment_ids=bounded_strings(raw, "sourceAttachmentIds", 16),
                attempts=required_int(raw, "attempts", 0, policy.max_attempts),
                deadline_at=time.monotonic() + remaining,
                content=content,
                superseded=raw.get("superseded") if isinstance(raw.get("superseded"), bool) else False,
                parent_candidate_id=raw.get("parentCandidateId") or None,
                lineage_attempt=required_int(raw, "lineageAttempt", 1, 8),
                panel_ids=bounded_strings(raw, "panelIds", 16),
                figure_id=raw.get("figureId") or None,
                collection_id=raw.get("collectionId") or None,
                child_chart_ids=bounded_strings(raw, "childChartIds", 16),
                figure_source=dict(raw["figureSource"]) if isinstance(raw.get("figureSource"), Mapping) else None,
                coverage=dict(raw["coverage"]) if isinstance(raw.get("coverage"), Mapping) else None,
                generation_context=context,
                context_digest=context_hash or None,
                context_status=(raw.get("contextStatus") or "absent")[:32],
                parent_attempt=max(0, min(parent_attempt_value, 8)) if parent_attempt_value is not None else None,
                call_id=(raw.get("callId") or "")[:160],
                tool_name=(raw.get("toolName") or "")[:128],
                turn=required_int(raw, "turn", 0, 2**31 - 1),
                safety_result=safety_result,
                semantic_result=semantic_result,
                repair_phase=(raw.get("repairPhase") or "none") if (raw.get("repairPhase") or "none") in _REPAIR_PHASES else "none",
                updated_at=(raw.get("updatedAt") or "")[:64],
            )
            if candidate_id in restored or any(item[0].review_id == review_id for item in restored.values()):
                raise ValueError("duplicate_review_candidate_identity")
            restored[candidate_id] = (candidate, spec)
            if candidate.call_id:
                key = (candidate.run_id, candidate.call_id, digest)
                if key in keys:
                    raise ValueError("duplicate_review_candidate_identity")
                keys[key] = candidate_id
        with self._lock:
            self._items = restored
            self._keys = keys

    def decorate_image(self, image: GeneratedImage, candidate: ChartCandidate) -> GeneratedImage:
        metadata = dict(image.metadata) if isinstance(image.metadata, Mapping) else {}
        metadata.update(candidate.safe_metadata())
        metadata["kind"] = "generated_chart"
        return replace(image, metadata=metadata)


__all__ = [
    "ChartReviewManager",
]
