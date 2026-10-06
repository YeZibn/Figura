"""Provider-facing JSON Schema fragments shared by image observation tools."""

_SCOPE_POINT = {
    "description": "归一化顶点 [x, y]，不是 {x,y} 对象；左上为原点，x 向右、y 向下。",
    "type": "array",
    "items": {"type": "integer", "minimum": 0, "maximum": 1000},
    "minItems": 2,
    "maxItems": 2,
}

_SCOPE_POLYGON = {
    "type": "array",
    "items": _SCOPE_POINT,
    "minItems": 3,
    "maxItems": 32,
}

OBSERVATION_SCOPE = {
    "description": "可选局部观察范围，相对选定 Attachment 或 Panel 本身归一化至 0–1000；必须提供 include 或 exclude，保留原尺寸和像素坐标。范围与 alpha>0 的可见区域相交；无有效像素时失败。",
    "type": "object",
    "properties": {
        "include": {"description": "多个多边形取并集；省略时包含全图，仍排除透明像素。", "type": "array", "items": _SCOPE_POLYGON, "minItems": 1, "maxItems": 4},
        "exclude": {"description": "多个多边形取并集后从 include 扣除；排除优先，区域外白底中和。OCR 必须整框位于有效范围，几何检测可能得到片段。", "type": "array", "items": _SCOPE_POLYGON, "minItems": 1, "maxItems": 4},
    },
    "additionalProperties": False,
}

SOURCE_PARAMETERS = {
    "type": "object",
    "properties": {
        "source_kind": {"description": "选择已授权原附件或独立 Panel；范围与输出坐标都相对这个来源。", "type": "string", "enum": ["attachment", "panel"]},
        "source_id": {"description": "资源索引中的真实来源 ID，不是工具 call_id 或本地路径。", "type": "string", "minLength": 1, "maxLength": 128},
        "observation_scope": OBSERVATION_SCOPE,
    },
    "required": ["source_kind", "source_id"],
    "additionalProperties": False,
}

PIXEL_POINT = {
    "type": "array",
    "items": {"type": "number", "minimum": 0, "maximum": 100000},
    "minItems": 2,
    "maxItems": 2,
}

_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_NUMBER = {"anyOf": [{"type": "number"}, {"type": "null"}]}

_TICK = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 64},
        "text": {"type": "string", "minLength": 1, "maxLength": 128},
        "value": _NULLABLE_NUMBER,
        "bbox_px": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0, "maximum": 100000},
            "minItems": 4,
            "maxItems": 4,
        },
        "point_px": PIXEL_POINT,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["id", "text", "value", "bbox_px", "point_px", "confidence"],
    "additionalProperties": False,
}

_CALIBRATION = {
    "type": "object",
    "properties": {
        "slope": {"type": "number"},
        "intercept": {"type": "number"},
        "residual_value": {"type": "number", "minimum": 0},
        "support_count": {"type": "integer", "minimum": 2},
        "support_span_px": {"type": "number", "minimum": 0},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "calibrated": {"type": "boolean"},
    },
    "required": [
        "slope", "intercept", "residual_value", "support_count", "support_span_px", "confidence", "calibrated",
    ],
    "additionalProperties": False,
}

_AXIS = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["numeric", "categorical", "unknown"]},
        "label_text": _NULLABLE_STRING,
        "label_confidence": _NULLABLE_NUMBER,
        "points_px": {"anyOf": [{"type": "array", "items": PIXEL_POINT, "minItems": 2, "maxItems": 2}, {"type": "null"}]},
        "ticks": {"type": "array", "items": _TICK},
        "calibration": {"anyOf": [_CALIBRATION, {"type": "null"}]},
    },
    "required": ["kind", "label_text", "label_confidence", "points_px", "ticks", "calibration"],
    "additionalProperties": False,
}

AXES = {
    "type": "object",
    "properties": {"x": _AXIS, "y": _AXIS},
    "required": ["x", "y"],
    "additionalProperties": False,
}

CONFIDENCE = {
    "type": "object",
    "properties": {
        "overall": {"type": "number", "minimum": 0, "maximum": 1},
        "geometry": {"type": "number", "minimum": 0, "maximum": 1},
        "calibration": {"type": "number", "minimum": 0, "maximum": 1},
        "association": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["overall", "geometry", "calibration", "association"],
    "additionalProperties": False,
}

MEASUREMENT_PROPERTIES = {
    "source_kind": {"type": "string", "enum": ["attachment", "panel"]},
    "source_id": {"type": "string", "minLength": 1, "maxLength": 128},
    "image_size": {
        "type": "object",
        "properties": {
            "width": {"type": "integer", "minimum": 1, "maximum": 100000},
            "height": {"type": "integer", "minimum": 1, "maximum": 100000},
        },
        "required": ["width", "height"],
        "additionalProperties": False,
    },
    "coordinate_system": {"type": "string", "enum": ["attachment_px", "panel_px"]},
    "status": {"type": "string", "enum": ["measured", "partial", "no_evidence", "unsupported"]},
    "plot_area_px": {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "minimum": 0},
                    "y": {"type": "integer", "minimum": 0},
                    "width": {"type": "integer", "minimum": 1},
                    "height": {"type": "integer", "minimum": 1},
                },
                "required": ["x", "y", "width", "height"],
                "additionalProperties": False,
            },
            {"type": "null"},
        ]
    },
    "axes": AXES,
    "confidence": CONFIDENCE,
    "warnings": {"type": "array", "items": {"type": "string", "maxLength": 256}},
}

COMMON_REQUIRED = [
    "source_kind", "source_id", "image_size", "coordinate_system", "status", "plot_area_px", "axes", "confidence", "warnings",
]
