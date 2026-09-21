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
            resolve_observation_scope,
            resolve_measurement_target,
            resolve_panel_scope,
            scoped_image_path,
        )

        panel_id = kwargs.pop("panel_id", None)
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
                            "measurement_repair": {
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
                "description": "可选的当前 panel 内定向补充测量目标。优先使用当前 measurement.evidence.refs 中的 B1、S1、P1、C1、L1 等引用；运行时负责补全来源和父 attempt。",
                "properties": {
                    "refs": {"type": "array", "items": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9]{0,15}$"}, "minItems": 1, "maxItems": 16, "description": "当前 attempt 中需要包含或排除的证据引用。"},
                    "mode": {"type": "string", "enum": ["include", "exclude"], "description": "include 只在引用区域内测量；exclude 排除引用区域后测量。"},
                    "fields": {"type": "array", "items": {"type": "string"}, "description": "本次重测需要解决的字段路径。"},
                    "bbox_source_px": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4, "description": "没有可用 ref 时才使用的有界源图像像素区域 [left, top, width, height]。"},
                    "polygon_source_px": {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}, "minItems": 3, "maxItems": 32, "description": "没有可用 ref 时才使用的有界源图像多边形。"},
                    "reason": {"type": "string", "description": "为什么要复查该区域。"},
                },
                "additionalProperties": False,
            }
            schema["properties"]["observation_scope"] = {
                "type": "object",
                "description": "首次观察的当前 panel 有界范围。主模型先给出粗略 include/exclude 区域；运行时会校验其属于 panel，再交给传感器执行。它不同于 measurement_target，后者仅用于已有 attempt 的定向补充测量。",
                "properties": {
                    "panel_id": {"type": "string", "description": "可选；通常与外层 panel_id 一致。"},
                    "attachment_id": {"type": "string", "description": "可选；必须与当前 attachment_id 一致。"},
                    "coordinate_space": {"type": "string", "enum": ["panel_norm", "panel_px", "source_px"], "description": "范围坐标系；默认 panel_norm。"},
                    "include": {"type": "array", "maxItems": 16, "items": {"type": "object", "additionalProperties": True}, "description": "要搜索的一个或多个区域，至少提供 bbox；也可提供 polygon。"},
                    "exclude": {"type": "array", "maxItems": 16, "items": {"type": "object", "additionalProperties": True}, "description": "在搜索范围内明确排除的区域。"},
                    "objectives": {"type": "array", "maxItems": 8, "items": {"type": "string"}, "description": "本次观察要确认的少量目标。"},
                    "reason": {"type": "string", "description": "选择该范围的简短理由。"},
                    "scope_id": {"type": "string", "description": "可选稳定范围 ID。"},
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


def _decorate_scoped_result(
    result: object,
    scope,
    *,
    measurement_target: Mapping | None = None,
    observation_scope: Mapping | None = None,
) -> object:
    from ..chart.observation.scope import add_scope_metadata

    if not isinstance(result, ToolResult):
        if isinstance(result, dict):
            payload = dict(result)
            payload["scope"] = scope.envelope()
            if isinstance(observation_scope, Mapping):
                payload["observation_scope"] = dict(observation_scope)
            return payload
        return result
    data = add_scope_metadata(result.data, scope)
    if isinstance(data, dict) and isinstance(measurement_target, Mapping):
        data["measurement_target"] = dict(measurement_target)
    if isinstance(data, dict) and isinstance(observation_scope, Mapping):
        data["observation_scope"] = dict(observation_scope)
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
