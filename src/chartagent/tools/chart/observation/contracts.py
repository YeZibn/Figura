"""Shared model-facing contracts for chart observation tools."""

from __future__ import annotations

from typing import Any

from ....spec import generation_context_schema


_REF_SCHEMA = {
    "type": "string",
    "pattern": "^[A-Za-z][A-Za-z0-9]{0,15}$",
    "description": "当前 attempt 中稳定的 evidence ref，例如 B1、L1、P1 或 S1。",
}

_REGION_SCHEMA = {
    "type": "object",
    "properties": {
        "role": {"type": "string", "maxLength": 48, "description": "区域的几何线索角色，不是最终业务语义。"},
        "label": {"type": "string", "maxLength": 96, "description": "可选的视觉标签，仅作为证据。"},
        "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4, "description": "当前坐标系中的 [left, top, width, height]。"},
        "bbox_norm": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 4, "maxItems": 4, "description": "panel_norm 坐标中的有界框。"},
        "bbox_px": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4, "description": "panel 局部像素坐标中的有界框。"},
        "bbox_source_px": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4, "description": "源图像素坐标中的有界框。"},
        "polygon": {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}, "minItems": 3, "maxItems": 32, "description": "有界多边形；必须落在当前 panel 内。"},
        "polygon_norm": {"type": "array", "items": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 2, "maxItems": 2}, "minItems": 3, "maxItems": 32, "description": "panel_norm 坐标中的有界多边形。"},
        "polygon_source_px": {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}, "minItems": 3, "maxItems": 32, "description": "源图像素坐标中的有界多边形。"},
    },
    "additionalProperties": False,
}


MEASUREMENT_TARGET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "可选的同 panel 定向补充目标；只有主 Agent主动传入时才会创建新 attempt，不会自动触发重测，也不会因为 warning 自动重测。补充结果必须重新阅读。",
    "properties": {
        "target_id": {"type": "string", "maxLength": 128, "description": "有界目标身份。"},
        "attachment_id": {"type": "string", "maxLength": 160, "description": "必须等于当前授权附件。"},
        "panel_id": {"type": "string", "maxLength": 160, "description": "必须等于当前 candidate 的 panel。"},
        "parent_attempt_id": {"type": "string", "maxLength": 160, "description": "当前 measurement attempt 的父 attempt。"},
        "refs": {"type": "array", "items": _REF_SCHEMA, "minItems": 1, "maxItems": 16, "description": "优先使用当前 evidence.refs 定位目标。"},
        "mode": {"type": "string", "enum": ["include", "exclude"], "description": "只包含或排除 refs/区域。"},
        "fields": {"type": "array", "items": {"type": "string", "maxLength": 80}, "maxItems": 16, "description": "本次补充需要确认的字段。"},
        "region_kind": {"type": "string", "enum": ["panel", "geometry", "label", "baseline", "axis", "series", "category", "value", "legend"], "description": "区域线索类型，不是业务角色。"},
        "bbox_source_px": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4, "description": "没有可用 ref 时使用的源图像素框。"},
        "polygon_source_px": {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}, "minItems": 3, "maxItems": 32, "description": "没有可用 ref 时使用的源图像素多边形。"},
        "reason": {"type": "string", "maxLength": 240, "description": "为什么需要补充该区域证据。"},
    },
    "additionalProperties": False,
}


OBSERVATION_SCOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "首次 observation 的当前 panel 有界范围；不是自动重测指令。",
    "properties": {
        "scope_id": {"type": "string", "maxLength": 128, "description": "可选稳定范围身份。"},
        "attachment_id": {"type": "string", "maxLength": 160, "description": "可选；必须等于当前授权附件。"},
        "panel_id": {"type": "string", "maxLength": 160, "description": "可选；通常等于外层 panel_id。"},
        "coordinate_space": {"type": "string", "enum": ["panel_norm", "panel_px", "source_px"], "description": "范围坐标系，默认 panel_norm。"},
        "include": {"type": "array", "items": _REGION_SCHEMA, "maxItems": 16, "description": "需要观察的一个或多个区域。"},
        "exclude": {"type": "array", "items": _REGION_SCHEMA, "maxItems": 16, "description": "当前观察中明确排除的区域。"},
        "objectives": {"type": "array", "items": {"type": "string", "maxLength": 96}, "maxItems": 8, "description": "本次 observation 要确认的少量目标。"},
        "reason": {"type": "string", "maxLength": 240, "description": "选择该观察范围的简短理由。"},
    },
    "additionalProperties": False,
}


def measurement_contract_properties() -> dict[str, Any]:
    """Return fresh common properties for each measurement tool schema."""
    return {
        "measurement_target": dict(MEASUREMENT_TARGET_SCHEMA),
        "observation_scope": dict(OBSERVATION_SCOPE_SCHEMA),
        "generation_context": generation_context_schema(),
    }


__all__ = [
    "MEASUREMENT_TARGET_SCHEMA",
    "OBSERVATION_SCOPE_SCHEMA",
    "measurement_contract_properties",
]
