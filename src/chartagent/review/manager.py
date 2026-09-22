"""Mandatory review lifecycle for generated chart candidates.

The renderer produces bytes, while this module owns the publication decision.
It deliberately contains no model client: deterministic evidence is collected
by the evaluator and an Agent may submit a bounded structured decision when
evidence is ambiguous.
"""

from __future__ import annotations

import time
from dataclasses import replace
from threading import RLock
from typing import Any, Mapping, Sequence
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
from .evaluator import merge_review_results, review_candidate_bytes
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

class ChartReviewManager:
    """Thread-safe in-process candidate store used by Agent and Gateway hooks."""


    def __init__(self, *, attachments: AttachmentRegistry | None = None) -> None:
        self.attachments = attachments
        self._items: dict[str, tuple[ChartCandidate, ChartSemantic]] = {}
        self._keys: dict[tuple[str, str, str], str] = {}
        self._semantic_results: dict[tuple[str, str, str], ReviewResult] = {}
        self._lock = RLock()

    @staticmethod
    def _semantic_key(candidate: ChartCandidate) -> tuple[str, str, str]:
        """Identify one immutable semantic review input."""
        return candidate.candidate_id, candidate.review_id, candidate.chart_spec_digest

    def semantic_result(self, candidate: ChartCandidate) -> ReviewResult | None:
        """Return a cached VLM decision for this candidate attempt."""
        with self._lock:
            return self._semantic_results.get(self._semantic_key(candidate))

    def remember_semantic_result(self, candidate: ChartCandidate, result: ReviewResult) -> ReviewResult:
        """Store and idempotently return the only semantic result for an attempt."""
        with self._lock:
            key = self._semantic_key(candidate)
            existing = self._semantic_results.get(key)
            if existing is not None:
                return existing
            self._semantic_results[key] = result
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
                        parent_attempt = prior.lineage_attempt
                        lineage_attempt = prior.lineage_attempt + 1
                    self._items[prior_id] = (replace(prior, superseded=True), prior_spec)
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
                context_status = "legacy_unknown"
            context_hash = context_digest(context)
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
                    repair_kind="terminal",
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
                    generation_context=context,
                    context_digest=context_hash,
                    context_status=context_status,
                    parent_attempt=parent_attempt,
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
                generation_context=context,
                context_digest=context_hash,
                context_status=context_status,
                parent_attempt=parent_attempt,
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

    def source_resolution(self, candidate: ChartCandidate) -> SourceScopeResolution:
        """Resolve the candidate's exact source scope for internal consumers.

        Source-linked candidates without a bound context are deliberately not
        allowed to fall back to the whole attachment.  They remain
        ``legacy_unknown`` until the caller rebinds a panel scope.
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
                        repair_kind="terminal",
                    )
                else:
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
                    "repairKind": item.review.repair_kind if item.review is not None else "terminal",
                    "target": dict(item.review.repair_target) if item.review is not None and isinstance(item.review.repair_target, Mapping) else None,
                    "parentAttempt": item.parent_attempt,
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
