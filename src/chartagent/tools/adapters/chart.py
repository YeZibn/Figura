"""Attachment-authorized wrappers for chart observation tools."""

from __future__ import annotations

from collections.abc import Mapping

from ...attachments import AttachmentRegistry
from ...spec import normalize_generation_context
from ..core.definition import Tool
from ..core.result import GeneratedImage, ToolResult


def authorized_chart_tool(tool: Tool, attachments: AttachmentRegistry) -> Tool:
    """Replace an internal image path with an authorized attachment ID."""
    original = tool.fn

    def call(attachment_id: str, **kwargs):
        # Import chart observation modules lazily.  The chart catalog imports
        # this adapter, so eager imports here would create a package cycle.
        from ..chart.observation.dashboard import reuse_decomposition, stabilize_decomposition_result
        from ..chart.observation.scope import (
            add_scope_metadata,
            localize_layout_context,
            resolve_observation_scope,
            resolve_measurement_target,
            resolve_panel_scope,
            scoped_image_path,
        )

        panel_id = kwargs.pop("panel_id", None)
        raw_generation_context = kwargs.pop("generation_context", None)
        measurement_target = kwargs.get("measurement_target")
        observation_scope = kwargs.get("observation_scope")
        if not isinstance(panel_id, str) and isinstance(measurement_target, Mapping):
            candidate_panel_id = measurement_target.get("panel_id")
            if isinstance(candidate_panel_id, str) and candidate_panel_id.strip():
                panel_id = candidate_panel_id
        if not isinstance(panel_id, str) and isinstance(observation_scope, Mapping):
            candidate_panel_id = observation_scope.get("panel_id")
            if isinstance(candidate_panel_id, str) and candidate_panel_id.strip():
                panel_id = candidate_panel_id
        if not isinstance(panel_id, str):
            layout_context = kwargs.get("layout_context")
            panel_summary = layout_context.get("panel") if isinstance(layout_context, Mapping) else None
            panel_id = panel_summary.get("id") if isinstance(panel_summary, Mapping) else None
        panel_store = getattr(attachments, "panel_store", None)
        if not isinstance(panel_id, str) and callable(getattr(panel_store, "list_panel_handoffs", None)):
            handoffs = panel_store.list_panel_handoffs(attachment_id)
            if len(handoffs) == 1:
                panel_id = getattr(handoffs[0], "panel_id", None)
        source_scope_hint = (
            {"attachment_id": attachment_id, "panel_ids": [panel_id]}
            if isinstance(panel_id, str) and panel_id.strip()
            else None
        )
        generation_context = normalize_generation_context(
            raw_generation_context,
            source_scope_hint=source_scope_hint,
        )
        if raw_generation_context is not None and generation_context is None:
            return {
                "error": "generation_context must contain a valid mode, coverage, selection_basis and goal_summary",
                "issues": [{"location": "generation_context", "message": "generation_context is malformed"}],
            }
        if generation_context is not None:
            context_issues = generation_context.validate()
            if context_issues:
                return {
                    "error": "generation_context failed validation",
                    "issues": context_issues[:8],
                    "action_hint": "修正 mode、source_scope、coverage 和 goal_summary 后重试",
                }
        if generation_context is not None and generation_context.source_scope is not None:
            scoped_attachment = generation_context.source_scope.attachment_id
            if scoped_attachment and scoped_attachment != attachment_id:
                return {
                    "error": "generation_context source scope does not match attachment_id",
                    "issues": [{"location": "generation_context.source_scope.attachment_id", "message": "source scope attachment differs from the authorized attachment"}],
                    "action_hint": "使用当前工具调用的 attachment_id 重新提交 context",
                }
        source_scope_resolution = None
        if generation_context is not None and generation_context.source_scope is not None:
            from ...source_scope import resolve_generation_scope

            source_scope_resolution = resolve_generation_scope(attachments, generation_context)
            if not source_scope_resolution.resolved:
                return {
                    "error": "generation_context source scope could not be resolved",
                    "source_scope": source_scope_resolution.to_dict(),
                    "action_hint": source_scope_resolution.action_hint or "重新绑定 active panel handoff",
                }
        if not isinstance(panel_id, str) and generation_context is not None and generation_context.source_scope is not None:
            context_panels = generation_context.source_scope.panel_ids
            if len(context_panels) == 1:
                panel_id = context_panels[0]
        if not isinstance(panel_id, str):
            layout_context = kwargs.get("layout_context")
            panel_summary = layout_context.get("panel") if isinstance(layout_context, Mapping) else None
            panel_id = panel_summary.get("id") if isinstance(panel_summary, Mapping) else None
        scoped_tool_names = {
            "extract_text",
            "measure_bars",
            "extract_line_series",
            "extract_pie_slices",
            "extract_scatter_points",
        }
        if source_scope_resolution is not None and tool.name in scoped_tool_names:
            context_panels = set(generation_context.source_scope.panel_ids) if generation_context and generation_context.source_scope else set()
            if isinstance(panel_id, str) and panel_id not in context_panels:
                return {
                    "error": "panel_id is outside generation_context source scope",
                    "source_scope": source_scope_resolution.to_dict(),
                    "action_hint": "只使用 generation_context.source_scope.panel_ids 中的 panel_id",
                }
            if len(context_panels) > 1 and not isinstance(panel_id, str):
                return {
                    "error": "measurement scope is ambiguous across multiple panels",
                    "source_scope": source_scope_resolution.to_dict(),
                    "action_hint": "为本次观察明确指定一个 panel_id",
                }
        item, error = attachments.validate(attachment_id)
        if error or item is None:
            return {"error": error or "attachment is not authorized"}
        if tool.name in {"inspect_chart_layout", "decompose_chart_image"}:
            kwargs.setdefault("attachment_id", attachment_id)

        panel_store = getattr(attachments, "panel_store", None)
        if tool.name == "decompose_chart_image" and panel_store is not None and kwargs.get("segmentation_mode") != "sam":
            existing = panel_store.list_panel_handoffs(attachment_id)
            if existing and _regions_match_existing(kwargs.get("regions"), existing):
                return reuse_decomposition(item.canonical_path, existing, attachment_id=attachment_id)

        if isinstance(panel_id, str) and panel_id.strip():
            scope, scope_error = resolve_panel_scope(
                item.canonical_path,
                attachment_id=attachment_id,
                panel_id=panel_id,
                panel_store=panel_store,
            )
            if scope is None:
                return {"error": f"panel routing failed: {scope_error or 'panel scope is unavailable'}"}
            localized = localize_layout_context(kwargs.get("layout_context"), scope)
            if tool.name in {"measure_bars", "extract_line_series", "extract_pie_slices", "extract_scatter_points"}:
                kwargs["layout_context"] = localized
                if observation_scope is not None:
                    resolved_scope, scope_error = resolve_observation_scope(observation_scope, scope)
                    if resolved_scope is None:
                        return {
                            "error": f"observation scope routing failed: {scope_error or 'scope is unavailable'}",
                            "observation_scope": {
                                "status": "rejected",
                                "code": "observation_scope_invalid",
                                "panel_id": scope.panel.panel_id,
                                "next_action": "重新提交当前 panel 内的 bounded include/exclude 范围，或直接观察整个 panel",
                            },
                        }
                    kwargs["observation_scope"] = resolved_scope
                if measurement_target is not None:
                    resolved_target, target_error = resolve_measurement_target(measurement_target, scope)
                    if resolved_target is None:
                        return {
                            "error": f"measurement target routing failed: {target_error or 'target is unavailable'}",
                            "measurement_target_error": {
                                "status": "rejected",
                                "code": "measurement_target_invalid",
                                "panel_id": scope.panel.panel_id,
                                "next_action": "重新读取当前 panel 的 evidence.refs 后再发起定向补充",
                            },
                        }
                    kwargs["measurement_target"] = resolved_target
            else:
                kwargs.pop("layout_context", None)
            with scoped_image_path(item.canonical_path, scope) as local_path:
                result = original(image_path=local_path, **kwargs)
            return _decorate_scoped_result(
                result,
                scope,
                measurement_target=kwargs.get("measurement_target"),
                observation_scope=kwargs.get("observation_scope"),
                generation_context=generation_context,
            )

        if tool.name in scoped_tool_names and panel_store is not None and hasattr(panel_store, "list_panel_handoffs"):
            existing = panel_store.list_panel_handoffs(attachment_id)
            if len(existing) > 1:
                return _reject_unscoped(
                    [item.panel_id for item in existing if getattr(item, "panel_id", None)],
                )
        result = original(image_path=item.canonical_path, **kwargs)
        if tool.name == "decompose_chart_image" and panel_store is not None:
            return stabilize_decomposition_result(
                result,
                session_id=str(item.session_id or ""),
                attachment_id=item.id,
                attachment_sha256=item.sha256,
                origin_run_id=item.run_id,
                panel_store=panel_store,
            )
        return _decorate_context_result(
            result,
            generation_context=generation_context,
        )

    schema = dict(tool.parameters)
    schema["properties"] = dict(schema.get("properties", {}))
    schema["properties"].pop("image_path", None)
    # Layout context is an internal, run-scoped evidence injection. It is not
    # exposed as a model argument on the attachment-authorized wrapper.
    schema["properties"].pop("layout_context", None)
    if tool.name in {
        "extract_text",
        "measure_bars",
        "extract_line_series",
        "extract_pie_slices",
        "extract_scatter_points",
    }:
        schema["properties"]["panel_id"] = {
            "type": "string",
            "description": "Optional stable panel ID returned by decompose_chart_image; selects the scoped panel measurement context.",
        }
        if tool.name in {"measure_bars", "extract_line_series", "extract_pie_slices", "extract_scatter_points"}:
            from ..chart.observation.contracts import measurement_contract_properties

            schema["properties"].update(measurement_contract_properties())
    schema["properties"]["attachment_id"] = {
        "type": "string",
        "description": "Opaque authorized attachment ID from the user turn; never a local filesystem path or URL.",
    }
    schema["required"] = [
        field for field in schema.get("required", []) if field != "image_path"
    ]
    if "attachment_id" not in schema["required"]:
        schema["required"].append("attachment_id")
    return Tool(
        tool.name,
        tool.description,
        schema,
        call,
        display_name=tool.display_name,
        group=tool.group,
        replay_effect=tool.replay_effect,
    )


def _regions_match_existing(regions: object, handoffs: list) -> bool:
    if regions is None:
        return True
    if not isinstance(regions, list) or not regions:
        return True
    names = {
        str(item.get("name", "")).strip().casefold()
        for item in regions
        if isinstance(item, Mapping) and str(item.get("name", "")).strip()
    }
    if not names:
        return True
    existing_names = {str(item.name).strip().casefold() for item in handoffs}
    return names.issubset(existing_names) or len(handoffs) >= len(regions)


def _decorate_scoped_result(
    result: object,
    scope,
    *,
    measurement_target: Mapping | None = None,
    observation_scope: Mapping | None = None,
    generation_context: object = None,
) -> object:
    from ..chart.observation.scope import add_scope_metadata

    if not isinstance(result, ToolResult):
        if isinstance(result, dict):
            payload = dict(result)
            payload["scope"] = scope.envelope()
            if isinstance(observation_scope, Mapping):
                payload["observation_scope"] = dict(observation_scope)
            return _decorate_context_result(
                payload,
                generation_context=generation_context,
            )
        return result
    data = add_scope_metadata(result.data, scope)
    if isinstance(data, dict) and isinstance(measurement_target, Mapping):
        data["measurement_target"] = dict(measurement_target)
    if isinstance(data, dict) and isinstance(observation_scope, Mapping):
        data["observation_scope"] = dict(observation_scope)
    data = _context_data(data, generation_context)
    images = []
    for image in result.images:
        metadata = dict(image.metadata) if isinstance(image.metadata, Mapping) else {}
        metadata.update({"panel_id": scope.panel.panel_id, "scope_mode": "panel", "source_origin_x": scope.origin[0], "source_origin_y": scope.origin[1], "source_width": scope.source_size[0], "source_height": scope.source_size[1]})
        if generation_context is not None:
            metadata["generation_context"] = generation_context.to_dict() if hasattr(generation_context, "to_dict") else generation_context
        images.append(GeneratedImage(image.content, image.media_type, f"{image.caption}（局部面板）", metadata))
    evidence = dict(result.evidence or {})
    evidence["scope"] = scope.envelope()
    return ToolResult(data, images=tuple(images), warnings=result.warnings, evidence=evidence)


def _context_data(
    data: object,
    context: object,
) -> object:
    if not isinstance(data, Mapping):
        return data
    result = dict(data)
    if context is not None:
        result["generation_context"] = context.to_dict() if hasattr(context, "to_dict") else context
    return result


def _decorate_context_result(
    result: object,
    *,
    generation_context: object,
) -> object:
    if isinstance(result, ToolResult):
        data = _context_data(result.data, generation_context)
        images = []
        for image in result.images:
            metadata = dict(image.metadata) if isinstance(image.metadata, Mapping) else {}
            if generation_context is not None:
                metadata["generation_context"] = generation_context.to_dict() if hasattr(generation_context, "to_dict") else generation_context
            images.append(GeneratedImage(image.content, image.media_type, image.caption, metadata))
        return ToolResult(data, images=tuple(images), warnings=result.warnings, evidence=result.evidence)
    if isinstance(result, Mapping):
        return _context_data(result, generation_context)
    return result


def _reject_unscoped(panel_ids: list[str]) -> dict[str, object]:
    """Reject a multi-panel full-image scan before invoking the sensor."""
    return {
        "error": "panel_id is required when an attachment has multiple active panels",
        "scope": {
            "mode": "unscoped",
            "status": "rejected",
            "available_panel_ids": list(dict.fromkeys(panel_ids))[:16],
        },
        "action_hint": "复用拆解结果中的 panel_id，并在同一 panel 范围内观察或测量",
    }


__all__ = ["authorized_chart_tool"]
