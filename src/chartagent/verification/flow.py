"""The single generated-chart staging, verification, and promotion path."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..durable_execution import DurableExecutionPort
from .checks import verify_chart_bytes
from ..source_scope import resolve_generation_scope
from ..spec import (
    ChartFigure,
    ChartSpec,
    ChartSpecCollection,
    GenerationContext,
    chart_figure_digest,
    chart_spec_digest,
    context_digest,
)
from ..tools.core.result import GeneratedImage
from .models import (
    ChartManifest,
    PublishedChart,
    VerificationIssue,
    VerificationResult,
    content_digest,
    canonical_json,
)
from .vlm import run_vlm_verification


def _chart_for_image(spec_value: Mapping[str, Any], metadata: Mapping[str, Any]):
    kind = spec_value.get("kind")
    if kind == "chart_spec_collection":
        collection = ChartSpecCollection.from_dict(spec_value)
        figure_id = metadata.get("figure_id") or metadata.get("figureId")
        figure = next((item for item in collection.figures if item.figure_id == figure_id), None)
        if figure is None and len(collection.figures) == 1:
            figure = collection.figures[0]
        return collection, figure
    if kind == "chart_figure":
        return None, ChartFigure.from_dict(spec_value)
    return None, ChartSpec.from_dict(spec_value)


def _source_identity(spec: ChartFigure | ChartSpec) -> tuple[tuple[str, ...], tuple[str, ...], int | None]:
    context = spec.generation_context
    scope = context.source_scope if context is not None else None
    if scope is not None:
        return ((scope.attachment_id,) if scope.attachment_id else ()), scope.panel_ids, scope.revision
    if isinstance(spec, ChartFigure):
        attachment = spec.source.attachment_id.strip()
        panel = spec.source.panel_id.strip()
        return ((attachment,) if attachment else ()), ((panel,) if panel else ()), None
    return (), (), None


def _semantic_required(spec: ChartFigure | ChartSpec, attachment_ids: tuple[str, ...]) -> bool:
    if attachment_ids:
        return True
    if isinstance(spec, ChartFigure):
        return bool(spec.source.attachment_id.strip())
    source = spec.metadata.source
    return isinstance(source, str) and bool(source.strip())


class GeneratedChartVerificationFlow:
    """Verify every renderer image against its exact spec and source scope."""

    def __init__(
        self,
        *,
        client: Any,
        chat_kwargs: Mapping[str, Any],
        attachments: Any,
        session_id: str,
        durable_execution_port: DurableExecutionPort | None = None,
    ) -> None:
        self.client = client
        self.chat_kwargs = dict(chat_kwargs)
        self.attachments = attachments
        self.session_id = session_id
        self.durable_execution_port = durable_execution_port

    def resume_checkpoint(
        self,
        *,
        action: str,
        staged_ref: str,
        run_id: str,
        model_entry_id: str,
        call_id: str,
        turn: int,
        emitter: Any = None,
    ) -> None:
        """Finish a committed verify/promote cursor from its exact staged bytes."""
        if action not in {"verify", "promote"} or self.durable_execution_port is None:
            raise RuntimeError("staged chart continuation is unavailable")
        try:
            stored = self.durable_execution_port.resolve_staged_chart(staged_ref)
        except Exception as exc:  # noqa: BLE001 - missing durable bytes must fail closed.
            raise RuntimeError("staged chart continuation is unavailable") from exc
        if not isinstance(stored, Mapping) or not isinstance(stored.get("manifest"), ChartManifest):
            raise RuntimeError("staged chart continuation is unavailable")
        manifest = stored["manifest"]
        content = stored.get("content")
        media_type = stored.get("mediaType")
        if (
            manifest.staged_ref != staged_ref
            or manifest.session_id != self.session_id
            or manifest.tool_call_id != call_id
            or not isinstance(content, bytes)
            or content_digest(content) != manifest.image_sha256
            or media_type != manifest.media_type
        ):
            raise RuntimeError("staged chart continuation is unavailable")
        image = GeneratedImage(
            content,
            media_type,
            manifest.title,
            {
                "kind": "generated_chart",
                "width": manifest.width,
                "height": manifest.height,
                "chart_spec_digest": manifest.chart_spec_digest,
                "figure_id": manifest.figure_id,
            },
        )
        self.process(
            [image],
            spec_value=manifest.chart_spec,
            run_id=run_id,
            model_entry_id=model_entry_id,
            call_id=call_id,
            turn=turn,
            emitter=emitter,
            manifest_override=manifest,
        )

    def process(
        self,
        images: Sequence[GeneratedImage],
        *,
        spec_value: object,
        run_id: str,
        model_entry_id: str | None,
        call_id: str,
        turn: int,
        emitter: Any = None,
        manifest_override: ChartManifest | None = None,
        tool_name: str = "render_chart",
    ) -> tuple[tuple[GeneratedImage, ...], list[dict[str, Any]]]:
        if not isinstance(spec_value, Mapping):
            return tuple(images), []
        verified_images: list[GeneratedImage] = []
        facts: list[dict[str, Any]] = []
        for ordinal, image in enumerate(images[:16]):
            metadata = image.metadata if isinstance(image.metadata, Mapping) else {}
            if metadata.get("kind") != "generated_chart":
                verified_images.append(image)
                continue
            try:
                collection, chart = _chart_for_image(spec_value, metadata)
            except (TypeError, ValueError, KeyError):
                verified_images.append(image)
                facts.append({"status": "unavailable", "reason": "chart_spec_invalid"})
                continue
            if chart is None:
                verified_images.append(image)
                facts.append({"status": "unavailable", "reason": "chart_spec_image_binding_failed"})
                continue
            exact_spec = chart.to_dict()
            digest = chart_figure_digest(chart) if isinstance(chart, ChartFigure) else chart_spec_digest(chart)
            if metadata.get("chart_spec_digest") not in {None, digest}:
                verified_images.append(image)
                facts.append({"status": "unavailable", "reason": "chart_spec_digest_mismatch"})
                continue
            context = chart.generation_context
            context_value = context.to_dict() if context is not None else None
            context_hash = context_digest(context)
            attachment_ids, panel_ids, source_revision = _source_identity(chart)
            semantic_required = _semantic_required(chart, attachment_ids)
            work_key = f"chart:{model_entry_id or turn}:{call_id}:{ordinal}"
            stable = hashlib.sha256(f"{run_id}:{self.session_id}:{work_key}".encode()).hexdigest()[:32]
            staged_ref = f"stg_{stable}"
            chart_type = "composite" if isinstance(chart, ChartFigure) else chart.metadata.chart_type.value
            title = (
                next((child.title or child.spec.metadata.title for child in chart.charts), "复合图表")
                if isinstance(chart, ChartFigure)
                else chart.metadata.title
            ) or "生成图表"
            manifest = ChartManifest(
                staged_ref=staged_ref,
                run_id=run_id,
                session_id=self.session_id,
                work_key=work_key,
                tool_call_id=call_id,
                output_ordinal=ordinal,
                image_sha256=content_digest(image.content),
                media_type=image.media_type,
                byte_count=len(image.content),
                chart_spec=exact_spec,
                chart_spec_digest=digest,
                chart_type=chart_type,
                title=title[:240],
                width=int(metadata.get("width") or 0),
                height=int(metadata.get("height") or 0),
                source_attachment_ids=attachment_ids,
                panel_ids=panel_ids,
                generation_context=context_value,
                generation_context_digest=context_hash,
                figure_id=chart.figure_id if isinstance(chart, ChartFigure) else None,
                collection_id=collection.collection_id if collection is not None else None,
                child_chart_ids=tuple(child.chart_id for child in chart.charts) if isinstance(chart, ChartFigure) else (),
                source_revision=str(source_revision) if source_revision is not None else None,
                semantic_required=semantic_required,
                allow_warnings=True,
                max_attempts=3,
            )
            replay_manifest = manifest_override if manifest_override is not None and ordinal == 0 else None
            if replay_manifest is None and self.durable_execution_port is not None:
                try:
                    stored_stage = self.durable_execution_port.resolve_staged_work(work_key)
                except Exception:  # noqa: BLE001 - absent staging is handled by the normal stage path.
                    stored_stage = None
                if isinstance(stored_stage, Mapping) and isinstance(stored_stage.get("manifest"), ChartManifest):
                    replay_manifest = stored_stage["manifest"]
            if replay_manifest is not None:
                manifest = replay_manifest
                if (
                    not manifest.run_id
                    or manifest.session_id != self.session_id
                    or manifest.tool_call_id != call_id
                    or manifest.work_key != work_key
                    or manifest.chart_spec_digest != digest
                    or manifest.image_sha256 != content_digest(image.content)
                    or manifest.media_type != image.media_type
                    or manifest.width != int(metadata.get("width") or 0)
                    or manifest.height != int(metadata.get("height") or 0)
                ):
                    verified_images.append(image)
                    facts.append({"status": "unavailable", "reason": "staged_manifest_mismatch"})
                    continue
                exact_spec = dict(manifest.chart_spec)
                digest = manifest.chart_spec_digest
                context_value = dict(manifest.generation_context) if manifest.generation_context is not None else None
                context_hash = manifest.generation_context_digest
                attachment_ids = manifest.source_attachment_ids
                panel_ids = manifest.panel_ids
                source_revision = int(manifest.source_revision) if manifest.source_revision and manifest.source_revision.isdigit() else None
                semantic_required = manifest.semantic_required
                work_key = manifest.work_key
                staged_ref = manifest.staged_ref
                stable = hashlib.sha256(f"{manifest.run_id}:{self.session_id}:{work_key}".encode()).hexdigest()[:32]
            manifest_json = canonical_json(manifest.to_dict(), limit=64 * 1024, name="chart manifest")
            has_model_entry = isinstance(model_entry_id, str) and model_entry_id.startswith("exe_")
            stage_ok = manifest_override is not None
            if self.durable_execution_port is not None:
                try:
                    stage_result = self.durable_execution_port.stage_chart(image, manifest)
                    stage_ok = isinstance(stage_result, Mapping) and stage_result.get("stagedRef") == staged_ref
                except Exception:  # noqa: BLE001 - staging failure closes publication.
                    stage_ok = False
            staged_event = {
                "correlation_version": 2,
                "call_id": call_id,
                "unit_id": f"generation:{staged_ref}",
                "unit_type": "generation",
                "phase": "render",
                "actor": "tool",
                "role": "action",
                "state": "staged" if stage_ok else "unavailable",
                "transition_id": f"generation:{staged_ref}:staged",
                "staged_ref": staged_ref,
                "manifest_digest": content_digest(manifest_json.encode("utf-8")),
                "chart_spec_digest": digest,
                "chart_type": chart_type,
                "title": title[:240],
                "media_type": image.media_type,
                "caption": str(image.caption or title)[:240],
                "byte_count": len(image.content),
                "width": manifest.width,
                "height": manifest.height,
                "figure_id": manifest.figure_id,
                "collection_id": manifest.collection_id,
                "child_chart_ids": list(manifest.child_chart_ids[:16]),
                "parent_unit_id": (
                    f"generation:collection:{manifest.collection_id}"
                    if manifest.collection_id else None
                ),
            }
            if stage_ok and self.durable_execution_port is not None and manifest_override is None:
                self.durable_execution_port.commit_execution_entry(
                    "tool_result",
                    {
                        "stagingCheckpoint": True,
                        "toolName": tool_name[:96],
                        "callId": call_id,
                        "modelEntryId": model_entry_id,
                        "outputOrdinal": ordinal,
                        "stagedRef": staged_ref,
                    },
                    turn=turn,
                    next_action_kind="verify",
                    staged_ref=staged_ref,
                    message_entry_id=model_entry_id,
                    call_id=call_id,
                    work_key=f"stage:{work_key}",
                    event_kind="chart_staged",
                    event_payload=staged_event,
                )
            elif emitter is not None and manifest_override is None:
                emitter.emit("chart_staged", turn=turn, **staged_event)

            stored_payload = None
            if self.durable_execution_port is not None:
                try:
                    stored_payload = self.durable_execution_port.resolve_execution_result(f"verify:{work_key}")
                except Exception:  # noqa: BLE001 - a missing result is recomputed on explicit resume.
                    stored_payload = None
            if isinstance(stored_payload, Mapping) and isinstance(stored_payload.get("verification"), Mapping):
                try:
                    result = VerificationResult.from_dict(stored_payload["verification"])
                    if result.staged_ref != staged_ref or result.manifest_digest != content_digest(manifest_json.encode("utf-8")):
                        result = None
                except (TypeError, ValueError):
                    result = None
            else:
                result = None
            source_diagnostic: str | None = None
            if result is not None:
                result_value = result.to_dict()
                status = result.status
                verification_ref = result.verification_ref
                verification_saved = True
                if self.durable_execution_port is not None:
                    self.durable_execution_port.commit_execution_entry(
                        "verification_result",
                        {
                            "verification": result_value,
                            "modelEntryId": model_entry_id or str(turn),
                            "toolCallId": call_id,
                            "outputOrdinal": ordinal,
                        },
                        turn=turn,
                        next_action_kind=(
                            "promote" if status in {"pass", "pass_with_warning"}
                            else "tool" if has_model_entry else "model"
                        ),
                        message_entry_id=model_entry_id,
                        call_id=call_id,
                        staged_ref=staged_ref if status in {"pass", "pass_with_warning"} else None,
                        verification_ref=verification_ref if status in {"pass", "pass_with_warning"} else None,
                        work_key=f"verify:{work_key}",
                        event_kind="chart_verification_result",
                        event_payload={
                            "correlation_version": 2,
                            "unit_id": f"verification:{verification_ref}",
                            "unit_type": "verification",
                            "parent_unit_id": f"generation:{staged_ref}",
                            "phase": "verify",
                            "actor": "system",
                            "role": "verification",
                            "transition_id": f"verification:{verification_ref}:completed",
                            "state": status,
                            "staged_ref": staged_ref,
                            "verification_ref": verification_ref,
                            "verification": {
                                **result_value,
                                "issues": [issue.to_dict() for issue in result.issues[:8]],
                            },
                            "issue_count": len(result.issues),
                        },
                    )
            else:
                deterministic = verify_chart_bytes(
                    chart,
                    image.content,
                    media_type=image.media_type,
                    declared_width=manifest.width,
                    declared_height=manifest.height,
                )
                issues = list(deterministic.issues[:32])
                checks = dict(deterministic.checks)
                semantic = None
                source_diagnostic: str | None = None
                if not stage_ok:
                    issues.append(VerificationIssue("stage_persistence_failed", "staged_chart", "chart bytes and manifest could not be committed"))
                    checks["staged_chart"] = "fail"
                elif deterministic.blocking:
                    checks["semantic_vlm"] = "not_run"
                elif semantic_required:
                    resolution = resolve_generation_scope(self.attachments, context)
                    if not resolution.resolved:
                        source_diagnostic = resolution.status
                        issues.append(VerificationIssue(
                            "source_binding_failure",
                            "generation_context.source_scope",
                            (resolution.issues[0].get("message") if resolution.issues else "authorized source scope is unavailable")[:240],
                        ))
                        checks["semantic_vlm"] = "fail"
                    else:
                        semantic = run_vlm_verification(
                            self.client,
                            staged_ref=staged_ref,
                            chart_spec_digest=digest,
                            width=manifest.width,
                            height=manifest.height,
                            content=image.content,
                            media_type=image.media_type,
                            spec=chart,
                            source_image=resolution.content,
                            source_media_type=resolution.media_type,
                            chat_kwargs=self.chat_kwargs,
                            trace_kwargs=(
                                {"trace_sink": emitter, "trace_run_id": emitter.run_id, "trace_turn": turn}
                                if emitter is not None and hasattr(emitter, "run_id") else None
                            ),
                        )
                        checks.update(semantic.checks)
                        issues.extend(semantic.issues[:32 - len(issues)])
                else:
                    checks["semantic_vlm"] = "not_run"

                has_errors = any(issue.severity == "error" for issue in issues)
                has_warnings = any(issue.severity == "warning" for issue in issues) or "warning" in checks.values()
                decision = semantic.decision if semantic is not None else ("fail" if has_errors else "pass_with_warning" if has_warnings else "pass")
                status = "fail" if has_errors or decision == "fail" else "pass_with_warning" if decision == "pass_with_warning" or has_warnings else "pass"
                if not stage_ok or any(issue.code == "vlm_unavailable" for issue in issues):
                    status = "unavailable"
                verification_ref = f"ver_{stable}"
                result = VerificationResult(
                    verification_ref=verification_ref,
                    staged_ref=staged_ref,
                    manifest_digest=content_digest(manifest_json.encode("utf-8")),
                    policy_version=manifest.policy_version,
                    status=status,
                    checks=checks,
                    issues=tuple(issues[:32]),
                    decision=decision,
                    confidence=semantic.confidence if semantic is not None else (1.0 if status.startswith("pass") else 0.0),
                    attempt=1,
                )
                result_value = result.to_dict()
                verification_saved = True
                if self.durable_execution_port is not None:
                    try:
                        verification_saved = bool(self.durable_execution_port.record_verification(result))
                    except Exception:  # noqa: BLE001 - immutable result commit fails closed.
                        verification_saved = False
                if self.durable_execution_port is not None:
                    self.durable_execution_port.commit_execution_entry(
                        "verification_result",
                        {
                            "verification": result_value,
                            "modelEntryId": model_entry_id or str(turn),
                            "toolCallId": call_id,
                            "outputOrdinal": ordinal,
                        },
                        turn=turn,
                        next_action_kind=(
                            "promote" if status in {"pass", "pass_with_warning"} and verification_saved
                            else "tool" if has_model_entry else "model"
                        ),
                        message_entry_id=model_entry_id,
                        call_id=call_id,
                        staged_ref=staged_ref if status in {"pass", "pass_with_warning"} and verification_saved else None,
                        verification_ref=verification_ref if status in {"pass", "pass_with_warning"} and verification_saved else None,
                        work_key=f"verify:{work_key}",
                        event_kind="chart_verification_result",
                        event_payload={
                            "correlation_version": 2,
                            "unit_id": f"verification:{verification_ref}",
                            "unit_type": "verification",
                            "parent_unit_id": f"generation:{staged_ref}",
                            "phase": "verify",
                            "actor": "system",
                            "role": "verification",
                            "transition_id": f"verification:{verification_ref}:completed",
                            "state": status,
                            "staged_ref": staged_ref,
                            "verification_ref": verification_ref,
                            "verification": {
                                **result_value,
                                "issues": [issue.to_dict() for issue in result.issues[:8]],
                            },
                            "issue_count": len(issues),
                        },
                    )
            published: Mapping[str, Any] | None = None
            if status in {"pass", "pass_with_warning"} and verification_saved:
                stored_promotion = None
                if self.durable_execution_port is not None:
                    try:
                        stored_promotion = self.durable_execution_port.resolve_execution_result(f"promote:{work_key}")
                    except Exception:  # noqa: BLE001 - a committed result remains reusable on resume.
                        stored_promotion = None
                if (
                    isinstance(stored_promotion, Mapping)
                    and stored_promotion.get("stagedRef") == staged_ref
                    and stored_promotion.get("verificationRef") == verification_ref
                    and isinstance(stored_promotion.get("artifactId"), str)
                ):
                    published = {"artifactId": stored_promotion["artifactId"]}
                    if self.durable_execution_port is not None:
                        promotion_value = dict(stored_promotion)
                        self.durable_execution_port.commit_execution_entry(
                            "promotion_result",
                            promotion_value,
                            turn=turn,
                            next_action_kind="tool" if has_model_entry else "model",
                            message_entry_id=model_entry_id,
                            call_id=call_id,
                            work_key=f"promote:{work_key}",
                            event_kind="chart_promotion_result",
                            event_payload={
                                "correlation_version": 2,
                                "unit_id": f"artifact:{promotion_value['artifactId']}",
                                "unit_type": "artifact",
                                "parent_unit_id": f"generation:{staged_ref}",
                                "phase": "publish",
                                "actor": "system",
                                "role": "artifact",
                                "transition_id": f"artifact:{promotion_value['artifactId']}:published",
                                "state": "published_with_warning" if promotion_value.get("warning") else "published",
                                "artifact_id": promotion_value["artifactId"],
                                "staged_ref": staged_ref,
                                "verification_ref": verification_ref,
                                "warning": bool(promotion_value.get("warning")),
                            },
                        )
                elif self.durable_execution_port is not None:
                    try:
                        published = self.durable_execution_port.promote_chart(manifest, verification_ref)
                    except Exception:  # noqa: BLE001 - publication failure remains previewable.
                        published = None
                if isinstance(published, Mapping) and published.get("artifactId") and stored_promotion is None:
                    promotion_value = PublishedChart(
                        artifact_id=str(published["artifactId"]),
                        staged_ref=staged_ref,
                        verification_ref=verification_ref,
                        warning=status == "pass_with_warning",
                        work_key=work_key,
                    ).to_dict()
                    if self.durable_execution_port is not None:
                        self.durable_execution_port.commit_execution_entry(
                            "promotion_result",
                            promotion_value,
                            turn=turn,
                            next_action_kind="tool" if has_model_entry else "model",
                            message_entry_id=model_entry_id,
                            call_id=call_id,
                            work_key=f"promote:{work_key}",
                            event_kind="chart_promotion_result",
                            event_payload={
                                "correlation_version": 2,
                                "unit_id": f"artifact:{promotion_value['artifactId']}",
                                "unit_type": "artifact",
                                "parent_unit_id": f"generation:{staged_ref}",
                                "phase": "publish",
                                "actor": "system",
                                "role": "artifact",
                                "transition_id": f"artifact:{promotion_value['artifactId']}:published",
                                "state": "published_with_warning" if promotion_value["warning"] else "published",
                                "artifact_id": promotion_value["artifactId"],
                                "staged_ref": staged_ref,
                                "verification_ref": verification_ref,
                                "warning": promotion_value["warning"],
                            },
                        )
            output_metadata = dict(metadata)
            output_metadata["verification"] = result_value
            output_metadata["stagedRef"] = staged_ref if stage_ok else None
            output_metadata["stageCommitted"] = stage_ok
            if isinstance(published, Mapping) and published.get("artifactId"):
                output_metadata["artifactId"] = published["artifactId"]
            verified_image = GeneratedImage(
                content=image.content,
                media_type=image.media_type,
                caption=image.caption,
                metadata=output_metadata,
            )
            verified_images.append(verified_image)
            facts.append({
                "stagedRef": staged_ref,
                "verification": result_value,
                "artifactId": published.get("artifactId") if isinstance(published, Mapping) else None,
                "sourceDiagnostic": source_diagnostic,
            })
        return tuple(verified_images), facts


__all__ = ["GeneratedChartVerificationFlow"]
