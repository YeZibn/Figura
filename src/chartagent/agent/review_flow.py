"""Generated-chart candidate review lifecycle, backed by ChartReviewManager."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..client.client import LLMClient
from ..measurement import MEASUREMENT_TOOLS
from ..review import (
    CandidateStatus,
    ChartReviewManager,
    PublicationStatus,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
    review_candidate_bytes,
    review_candidate_with_vlm,
)
from ..tools.core import ToolRegistry
from ..tools.core.result import GeneratedImage
from ..trace import TraceEmitter
from .execution import (
    DECOMPOSE_TOOL_NAME as _DECOMPOSE_TOOL_NAME,
    LAYOUT_TOOL_NAME as _LAYOUT_TOOL_NAME,
    RENDER_TOOL_NAMES as _RENDER_TOOL_NAMES,
)


class GeneratedChartReviewFlow:
    """Coordinate candidate review without owning a second review state model."""

    def __init__(
        self,
        review_manager: ChartReviewManager,
        registry: ToolRegistry,
        client: Any,
        chat_kwargs: Mapping[str, Any],
        *,
        memory: Any,
        candidate_input_sink: Any = None,
        checkpoint_sink: Any = None,
        execution_gate_sink: Any = None,
    ) -> None:
        self.manager = review_manager
        self.registry = registry
        self.client = client
        self.chat_kwargs = dict(chat_kwargs)
        self.memory = memory
        self.candidate_input_sink = candidate_input_sink
        self.checkpoint_sink = checkpoint_sink
        self.execution_gate_sink = execution_gate_sink

    def allows_tool_call(self, run_id: str, call_name: str, arguments: Mapping[str, Any]) -> bool:
        """Allow model-selected, source-safe repair work under a review gate.

        The gate owns publication and terminal-state safety.  It deliberately
        does not turn a VLM repair hint into an ordered tool whitelist; each
        selected tool remains responsible for its own authorization, scope,
        lineage and schema checks.
        """
        gate = self.manager.execution_gate(run_id)
        if not gate.blocking:
            return True
        if gate.review_type is None:
            return False
        if gate.state.value in {"failed", "exhausted"}:
            return False
        if gate.review_type.value != "generated_chart":
            return False

        repair_tools = {
            _DECOMPOSE_TOOL_NAME,
            _LAYOUT_TOOL_NAME,
            "extract_text",
            "assemble_spec",
            *_RENDER_TOOL_NAMES,
            *MEASUREMENT_TOOLS,
        }
        if call_name not in repair_tools or self.registry.get(call_name) is None:
            return False

        candidate = self.manager.get(gate.subject_id or "")
        if candidate is None:
            return False
        requested_candidate = arguments.get("candidate_id")
        if requested_candidate is not None and requested_candidate != candidate.candidate_id:
            return False

        # If the model supplies an explicit generation context, it must be the
        # same immutable context as the failed candidate.  Missing context is
        # left to the selected tool's own source-scope validation so a model
        # may first recover a source binding or use a valid visual-only input.
        from ..spec import context_digest, normalize_generation_context

        raw_contexts: list[object] = []
        if arguments.get("generation_context") is not None:
            raw_contexts.append(arguments.get("generation_context"))
        spec = arguments.get("spec")
        if isinstance(spec, Mapping):
            if spec.get("generation_context") is not None:
                raw_contexts.append(spec.get("generation_context"))
            figure = spec.get("figure")
            if isinstance(figure, Mapping) and figure.get("generation_context") is not None:
                raw_contexts.append(figure.get("generation_context"))
        if candidate.context_digest and raw_contexts:
            for raw_context in raw_contexts:
                normalized = normalize_generation_context(raw_context)
                if normalized is None or context_digest(normalized) != candidate.context_digest:
                    return False
        return True

    def advance_repair_phase(self, run_id: str, phase: str) -> None:
        """Move the active generated-chart repair sub-loop to its next phase."""
        gate = self.manager.execution_gate(run_id)
        if (
            gate.blocking
            and gate.review_type is not None
            and gate.review_type.value == "generated_chart"
            and gate.review_id
        ):
            try:
                self.manager.mark_repair_phase(run_id, gate.review_id, phase)
            except (KeyError, ValueError):
                return
            if self.execution_gate_sink is not None:
                try:
                    self.execution_gate_sink(self.manager.execution_gate(run_id).to_dict())
                except Exception:  # noqa: BLE001 - projection cannot stop repair
                    pass

    def record_candidate_review(
        self,
        run: Any,
        candidate: Any,
        *,
        emitter: TraceEmitter | None,
        turn: int,
        tool_name: str,
        call_id: str,
        started: bool,
    ) -> None:
        """Persist and expose one transition derived from the candidate aggregate."""
        gate = self.manager.execution_gate(candidate.run_id)
        review = candidate.review or candidate.safety_result
        if started:
            state = "reviewing"
        elif candidate.publication_status is PublicationStatus.PUBLISHED:
            state = "passed"
        elif candidate.publication_status is PublicationStatus.PUBLISHED_WITH_WARNING:
            state = "passed_with_warning"
        elif candidate.status is CandidateStatus.RETRY_EXHAUSTED or gate.state.value == "exhausted":
            state = "exhausted"
        elif candidate.status is CandidateStatus.REVIEW_FAILED and gate.state.value == "repair_required":
            state = "repair_required"
        else:
            state = "failed"
        generation_context = candidate.generation_context.to_dict() if candidate.generation_context is not None else None
        source_scope = generation_context.get("source_scope") if isinstance(generation_context, Mapping) else None
        coverage = generation_context.get("coverage") if isinstance(generation_context, Mapping) else None
        issues = [issue.to_dict() for issue in (review.issues if review is not None else ())[:32]]
        review_mode = review.review_mode if review is not None else "vlm" if candidate.policy.semantic_required else "safety"
        payload: dict[str, Any] = {
            "unit_id": f"review:{candidate.review_id}",
            "unit_type": "review",
            "phase": "repair" if state == "repair_required" else "review",
            "actor": "system",
            "role": "review",
            "parent_unit_id": f"review:collection:{candidate.collection_id}" if candidate.collection_id else None,
            "transition_id": f"review:{candidate.review_id}:{candidate.lineage_attempt}:{state}",
            "review_id": candidate.review_id,
            "review_type": "generated_chart",
            "subject_id": candidate.candidate_id,
            "candidate_id": candidate.candidate_id,
            "state": state,
            "blocking": started or candidate.publication_status in {PublicationStatus.UNPUBLISHED, PublicationStatus.REJECTED},
            "attempt": candidate.lineage_attempt,
            "issues": issues,
            "decision": review.decision if review is not None else "reviewing",
            "confidence": review.confidence if review is not None else None,
            "review_mode": review_mode,
            "repair_kind": review.repair_kind if review is not None and review.repair_kind else "none",
            "repair_phase": candidate.repair_phase,
            "tool_name": tool_name,
            "call_id": call_id,
            "collection_id": candidate.collection_id,
            "parent_attempt": candidate.parent_attempt,
            "review_status": candidate.review_status.value,
            "candidate_status": candidate.status.value,
            "publication_status": candidate.publication_status.value,
        }
        if isinstance(source_scope, Mapping):
            payload["source_scope"] = dict(source_scope)
        if isinstance(coverage, Mapping):
            payload["coverage"] = dict(coverage)
        self.memory.append(run, "review", {"state": payload})
        if self.execution_gate_sink is not None:
            try:
                self.execution_gate_sink(gate.to_dict())
            except Exception:  # noqa: BLE001 - gate projection cannot stop the Agent
                pass
        if emitter is None:
            return
        if started:
            emitter.emit(
                "review_started",
                turn=turn,
                review_id=candidate.review_id,
                review_type="generated_chart",
                subject_id=candidate.candidate_id,
                unit_id=payload["unit_id"],
                transition_id=f"review:{candidate.review_id}:{candidate.lineage_attempt}:reviewing",
                state="reviewing",
                unit_type="review",
                phase="review",
                actor="system",
                role="review",
                parent_unit_id=(f"review:collection:{candidate.collection_id}" if candidate.collection_id else None),
                attempt=candidate.lineage_attempt,
                blocking=True,
                tool_name=tool_name,
                call_id=call_id,
                candidate_id=candidate.candidate_id,
                collection_id=candidate.collection_id,
            )
            return
        if state in {"passed", "passed_with_warning"}:
            emitter.emit("review_completed", turn=turn, **payload)
        elif state == "repair_required":
            emitter.emit("review_repair_required", turn=turn, **payload)
        else:
            emitter.emit("review_failed", turn=turn, **payload)
        publication_status = candidate.publication_status.value
        publication_kind = "generated_chart_published" if publication_status in {"published", "published_with_warning"} else "generated_chart_rejected"
        emitter.emit(
            publication_kind,
            turn=turn,
            unit_id=f"publication:{candidate.candidate_id}",
            unit_type="publication",
            phase="publish",
            actor="system",
            role="publication",
            parent_unit_id=payload["unit_id"],
            review_id=candidate.review_id,
            candidate_id=candidate.candidate_id,
            subject_id=candidate.candidate_id,
            attempt=candidate.lineage_attempt,
            publication_status=publication_status,
            state=publication_status,
            transition_id=f"publication:{candidate.candidate_id}:{candidate.lineage_attempt}:{publication_status}",
            tool_name=tool_name,
            call_id=call_id,
            reason=("review_failed" if publication_kind == "generated_chart_rejected" else None),
        )

    def apply_generation_review(
        self,
        observation: Any,
        *,
        run: Any | None = None,
        run_id: str,
        call_id: str,
        tool_name: str,
        arguments: str,
        source_attachment_ids: Sequence[str],
        emitter: TraceEmitter | None = None,
        turn: int | None = None,
        checkpoint_review: Callable[[Sequence[str]], None] | None = None,
    ) -> Any:
        """Run the post-generation hook before tool evidence reaches the model."""
        if not observation.images:
            return observation
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except (TypeError, json.JSONDecodeError):
            return observation
        spec_payload = args.get("spec") if isinstance(args, dict) else None
        if not isinstance(spec_payload, dict):
            return observation
        try:
            from ..spec import ChartFigure, ChartSpec, ChartSpecCollection

            collection = None
            if spec_payload.get("kind") == "chart_figure":
                figure_specs = [ChartFigure.from_dict(spec_payload)]
            elif spec_payload.get("kind") == "chart_spec_collection":
                collection = ChartSpecCollection.from_dict(spec_payload)
                figure_specs = list(collection.figures)
            else:
                figure_specs = [ChartSpec.from_dict(spec_payload)]
        except (TypeError, ValueError, KeyError):
            return observation
        generated: list[GeneratedImage] = []
        review_payloads: list[dict[str, Any]] = []
        prepared: list[tuple[GeneratedImage, Any, Any, bool]] = []
        for image in observation.images:
            metadata = image.metadata if hasattr(image.metadata, "get") else {}
            if metadata.get("kind") != "generated_chart":
                generated.append(image)
                continue
            # Legacy custom tools without a ChartSpec digest remain readable;
            # renderer-produced images always carry the digest and enter this
            # mandatory lifecycle.
            if not metadata.get("chart_spec_digest"):
                generated.append(image)
                continue
            review_spec = figure_specs[0]
            if collection is not None and len(figure_specs) > 1:
                figure_id = metadata.get("figure_id") or metadata.get("figureId")
                review_spec = next(
                    (figure for figure in figure_specs if figure.figure_id == figure_id),
                    figure_specs[0],
                )
            candidate = self.manager.create_candidate(
                run_id,
                call_id,
                image,
                review_spec,
                source_attachment_ids=source_attachment_ids,
                tool_name=tool_name,
                turn=turn or 0,
            )
            # The candidate itself opens the derived gate before persistence or review.
            persisted = self.candidate_input_sink is None and self.checkpoint_sink is None
            if self.candidate_input_sink is not None:
                try:
                    staged = self.candidate_input_sink(
                        self.manager.decorate_image(image, candidate),
                        review_spec.to_dict(),
                    )
                    persisted = bool(staged)
                except Exception:  # noqa: BLE001 - candidate storage must fail closed
                    persisted = False
            if run is not None:
                self.record_candidate_review(
                    run,
                    candidate,
                    emitter=emitter,
                    turn=turn or 0,
                    tool_name="generated_chart_review",
                    call_id=call_id,
                    started=True,
                )
            prepared.append((image, candidate, review_spec, persisted))
        if not prepared:
            return observation

        candidate_ids = [candidate.candidate_id for _, candidate, _, _ in prepared]
        for index, (image, candidate, review_spec, persisted) in enumerate(prepared):
            if candidate.safety_result is not None or candidate.status in {
                CandidateStatus.VERIFIED,
                CandidateStatus.WARNING,
                CandidateStatus.REVIEW_FAILED,
                CandidateStatus.TIMED_OUT,
                CandidateStatus.RETRY_EXHAUSTED,
            }:
                continue
            if not persisted:
                deterministic_result = ReviewResult(
                    status=ReviewStatus.FAILED,
                    checks={"candidate_storage": "failed"},
                    issues=(ReviewIssue(
                        "candidate_storage_failure",
                        "candidate.storage",
                        "candidate image and ChartSpec could not be stored for mandatory review",
                    ),),
                    decision="fail",
                    confidence=0.0,
                    review_mode="safety",
                    repair_kind="terminal",
                )
            else:
                deterministic_result = review_candidate_bytes(
                    review_spec,
                    candidate.content,
                    media_type=candidate.media_type,
                    declared_width=candidate.width,
                    declared_height=candidate.height,
                )
            candidate = self.manager.record_safety_result(candidate, deterministic_result)
            review_unit = f"review:{candidate.review_id}"
            if emitter is not None:
                emitter.emit(
                    "review_subcheck",
                    turn=turn,
                    unit_id=review_unit,
                    parent_unit_id=(f"review:collection:{candidate.collection_id}" if candidate.collection_id else None),
                    candidate_id=candidate.candidate_id,
                    review_id=candidate.review_id,
                    unit_type="review",
                    phase="review",
                    actor="system",
                    role="review",
                    transition_id=f"{review_unit}:{candidate.lineage_attempt}:deterministic",
                    attempt=candidate.lineage_attempt,
                    check_type="deterministic_quality_audit",
                    state="failed" if deterministic_result.blocking else "passed",
                    checks=dict(deterministic_result.checks),
                    issues=[issue.to_dict() for issue in deterministic_result.issues[:16]],
                )
            prepared[index] = (image, candidate, review_spec, persisted)

        resumable = all(persisted for _, _, _, persisted in prepared)
        if resumable and checkpoint_review is not None:
            checkpoint_review(candidate_ids)

        for image, candidate, review_spec, persisted in prepared:
            candidate = self.finish_candidate_review(
                candidate,
                review_spec,
                emitter=emitter,
                turn=turn or 0,
                checkpoint_review=checkpoint_review if resumable else None,
                candidate_ids=candidate_ids,
                checkpoint_before_semantic=False,
            )
            if run is not None:
                self.record_candidate_review(
                    run,
                    candidate,
                    emitter=emitter,
                    turn=turn or 0,
                    tool_name="generated_chart_review",
                    call_id=call_id,
                    started=False,
                )
            generated.append(self.manager.decorate_image(image, candidate))
            review_payloads.append(candidate.safe_metadata())
        content = observation.content
        try:
            payload = json.loads(content)
            if isinstance(payload, dict):
                data = payload.get("data")
                if isinstance(data, dict):
                    data = dict(data)
                    data["review"] = review_payloads
                    payload["data"] = data
                payload["review"] = review_payloads
                content = json.dumps(payload, ensure_ascii=False)
        except (TypeError, json.JSONDecodeError):
            pass
        from ..tools.core.result import DispatchedObservation

        return DispatchedObservation(content=content, images=tuple(generated))

    def finish_candidate_review(
        self,
        candidate: Any,
        spec: Any,
        *,
        emitter: TraceEmitter | None,
        turn: int,
        checkpoint_review: Callable[[Sequence[str]], None] | None,
        candidate_ids: Sequence[str],
        checkpoint_before_semantic: bool = True,
    ) -> Any:
        """Apply the stored deterministic result and one semantic decision."""
        if candidate.status in {
            CandidateStatus.VERIFIED,
            CandidateStatus.WARNING,
            CandidateStatus.REVIEW_FAILED,
            CandidateStatus.TIMED_OUT,
            CandidateStatus.RETRY_EXHAUSTED,
        }:
            return candidate
        safety_result = candidate.safety_result
        if safety_result is None:
            safety_result = review_candidate_bytes(
                spec,
                candidate.content,
                media_type=candidate.media_type,
                declared_width=candidate.width,
                declared_height=candidate.height,
            )
            candidate = self.manager.record_safety_result(candidate, safety_result)
            if emitter is not None:
                emitter.emit(
                    "review_subcheck",
                    turn=turn,
                    unit_id=f"review:{candidate.review_id}",
                    candidate_id=candidate.candidate_id,
                    review_id=candidate.review_id,
                    unit_type="review",
                    phase="review",
                    actor="system",
                    role="review",
                    transition_id=f"review:{candidate.review_id}:{candidate.lineage_attempt}:deterministic",
                    attempt=candidate.lineage_attempt,
                    check_type="deterministic_quality_audit",
                    state="failed" if safety_result.blocking else "passed",
                    checks=dict(safety_result.checks),
                    issues=[issue.to_dict() for issue in safety_result.issues[:16]],
                )
        semantic_result = self.manager.semantic_result(candidate)
        if candidate.policy.semantic_required:
            if safety_result.blocking:
                if semantic_result is None and emitter is not None:
                    emitter.emit(
                        "review_subcheck",
                        turn=turn,
                        unit_id=f"review:{candidate.review_id}",
                        candidate_id=candidate.candidate_id,
                        review_id=candidate.review_id,
                        unit_type="review",
                        phase="review",
                        actor="system",
                        role="review",
                        transition_id=f"review:{candidate.review_id}:{candidate.lineage_attempt}:semantic_not_run",
                        attempt=candidate.lineage_attempt,
                        check_type="semantic_vlm",
                        state="not_run",
                        reason="确定性审核未通过",
                    )
            elif semantic_result is None:
                if checkpoint_review is not None and checkpoint_before_semantic:
                    checkpoint_review(candidate_ids)
                if emitter is not None:
                    emitter.emit(
                        "review_subcheck",
                        turn=turn,
                        unit_id=f"review:{candidate.review_id}",
                        parent_unit_id=(f"review:collection:{candidate.collection_id}" if candidate.collection_id else None),
                        candidate_id=candidate.candidate_id,
                        review_id=candidate.review_id,
                        unit_type="review",
                        phase="review",
                        actor="vlm",
                        role="review",
                        transition_id=f"review:{candidate.review_id}:{candidate.lineage_attempt}:semantic_started",
                        attempt=candidate.lineage_attempt,
                        check_type="semantic_vlm",
                        state="running",
                    )
                source_resolution = self.manager.source_resolution(candidate)
                source_payload = (source_resolution.content, source_resolution.media_type) if source_resolution.resolved else None
                if source_payload is None:
                    hint = source_resolution.action_hint or "重新绑定有效的 source_scope"
                    semantic_result = ReviewResult(
                        status=ReviewStatus.FAILED,
                        checks={"source_evidence": source_resolution.status},
                        issues=(ReviewIssue(
                            "source_binding_failure",
                            "generation_context.source_scope",
                            f"source scope is {source_resolution.status}; {hint}",
                        ),),
                        decision="fail",
                        confidence=0.0,
                        review_mode="vlm",
                        candidate_id=candidate.candidate_id,
                        review_id=candidate.review_id,
                        chart_spec_digest=candidate.chart_spec_digest,
                        suggested_action="rebind_source",
                        recovery_classification="source_binding_failure",
                        repair_kind="source_rebind",
                    )
                else:
                    semantic_result = review_candidate_with_vlm(
                        self.client,
                        candidate,
                        spec,
                        source_image=source_payload[0],
                        source_media_type=source_payload[1],
                        chat_kwargs=self.chat_kwargs,
                        trace_kwargs=(
                            {"trace_sink": emitter, "trace_run_id": emitter.run_id, "trace_turn": turn}
                            if emitter is not None and isinstance(self.client, LLMClient) else None
                        ),
                    )
                self.manager.remember_semantic_result(candidate, semantic_result)
                if checkpoint_review is not None:
                    checkpoint_review(candidate_ids)
            if semantic_result is not None and emitter is not None:
                emitter.emit(
                    "review_subcheck",
                    turn=turn,
                    unit_id=f"review:{candidate.review_id}",
                    parent_unit_id=(f"review:collection:{candidate.collection_id}" if candidate.collection_id else None),
                    candidate_id=candidate.candidate_id,
                    review_id=candidate.review_id,
                    unit_type="review",
                    phase="review",
                    actor="vlm",
                    role="review",
                    transition_id=f"review:{candidate.review_id}:{candidate.lineage_attempt}:semantic_completed",
                    attempt=candidate.lineage_attempt,
                    check_type="semantic_vlm",
                    state=semantic_result.status.value,
                    decision=semantic_result.decision,
                    checks=dict(semantic_result.checks),
                    issues=[issue.to_dict() for issue in semantic_result.issues[:16]],
                )
        return self.manager.process(
            candidate,
            safety_result=safety_result,
            semantic_result=semantic_result,
        )
