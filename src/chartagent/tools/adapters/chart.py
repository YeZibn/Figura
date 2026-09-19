"""Attachment-authorized wrappers for chart observation tools."""

from __future__ import annotations

from collections.abc import Mapping

from ...attachments import AttachmentRegistry
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
            resolve_measurement_target,
            resolve_panel_scope,
            scoped_image_path,
        )

        panel_id = kwargs.pop("panel_id", None)
        measurement_target = kwargs.get("measurement_target")
        if not isinstance(panel_id, str) and isinstance(measurement_target, Mapping):
            candidate_panel_id = measurement_target.get("panel_id")
            if isinstance(candidate_panel_id, str) and candidate_panel_id.strip():
                panel_id = candidate_panel_id
        if not isinstance(panel_id, str):
            layout_context = kwargs.get("layout_context")
            panel_summary = layout_context.get("panel") if isinstance(layout_context, Mapping) else None
            panel_id = panel_summary.get("id") if isinstance(panel_summary, Mapping) else None
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
                if measurement_target is not None:
                    resolved_target, target_error = resolve_measurement_target(measurement_target, scope)
                    if resolved_target is None:
                        return {
                            "error": f"measurement target routing failed: {target_error or 'target is unavailable'}",
                            "measurement_repair": {
                                "status": "rejected",
                                "code": "measurement_target_invalid",
                                "panel_id": scope.panel.panel_id,
                                "next_action": "重新读取当前 panel 的 repair_action 后再发起定向重测",
                            },
                        }
                    kwargs["measurement_target"] = resolved_target
            else:
                kwargs.pop("layout_context", None)
            with scoped_image_path(item.canonical_path, scope) as local_path:
                result = original(image_path=local_path, **kwargs)
            return _decorate_scoped_result(result, scope, measurement_target=kwargs.get("measurement_target"))

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
        if tool.name in {"extract_text", "measure_bars", "extract_line_series", "extract_pie_slices", "extract_scatter_points"} and panel_store is not None:
            existing = panel_store.list_panel_handoffs(attachment_id)
            if len(existing) > 1:
                return _mark_unscoped(result)
        return result

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
            schema["properties"]["measurement_target"] = {
                "type": "object",
                "description": "可选的当前 panel 内定向重测目标；必须使用 source image 坐标、当前 parent attempt 和受影响字段。",
                "properties": {
                    "target_id": {"type": "string", "description": "模型为本次复查提出的稳定目标标识。"},
                    "panel_id": {"type": "string", "description": "目标所属的当前 panel ID。"},
                    "parent_attempt_id": {"type": "string", "description": "measurement.quality.repair_action 指定的父 attempt。"},
                    "region_kind": {"type": "string", "description": "baseline、bars、axes、series、points、sectors、legend 或 panel。"},
                    "fields": {"type": "array", "items": {"type": "string"}, "description": "本次重测需要解决的字段路径。"},
                    "bbox_source_px": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4, "description": "源图像像素坐标 [left, top, width, height]。"},
                    "source_image_size": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2, "description": "提出 bbox 时所依据的源图尺寸。"},
                    "reason": {"type": "string", "description": "为什么要复查该区域。"},
                },
                "additionalProperties": False,
            }
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


def _decorate_scoped_result(result: object, scope, *, measurement_target: Mapping | None = None) -> object:
    from ..chart.observation.scope import add_scope_metadata

    if not isinstance(result, ToolResult):
        if isinstance(result, dict):
            payload = dict(result)
            payload["scope"] = scope.envelope()
            return payload
        return result
    data = add_scope_metadata(result.data, scope)
    if isinstance(data, dict) and isinstance(measurement_target, Mapping):
        data["measurement_target"] = dict(measurement_target)
    images = []
    for image in result.images:
        metadata = dict(image.metadata) if isinstance(image.metadata, Mapping) else {}
        metadata.update({"panel_id": scope.panel.panel_id, "scope_mode": "panel", "source_origin_x": scope.origin[0], "source_origin_y": scope.origin[1], "source_width": scope.source_size[0], "source_height": scope.source_size[1]})
        images.append(GeneratedImage(image.content, image.media_type, f"{image.caption}（局部面板）", metadata))
    evidence = dict(result.evidence or {})
    evidence["scope"] = scope.envelope()
    return ToolResult(data, images=tuple(images), warnings=result.warnings, evidence=evidence)


def _mark_unscoped(result: object) -> object:
    warning = "multi-panel attachment was analyzed without panel_id; evidence is unscoped"
    if not isinstance(result, ToolResult):
        if isinstance(result, dict):
            payload = dict(result)
            payload.setdefault("warnings", []).append(warning)
            payload["scope"] = {"mode": "unscoped"}
            return payload
        return result
    warnings = tuple(result.warnings) + (warning,)
    if isinstance(result.data, dict):
        data = dict(result.data)
        data["scope"] = {"mode": "unscoped"}
        data["unscoped"] = True
    else:
        data = result.data
    return ToolResult(data, images=result.images, warnings=warnings, evidence=result.evidence)


__all__ = ["authorized_chart_tool"]
