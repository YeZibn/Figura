"""Provider-facing JSON Schema fragments shared by image observation tools."""

_SCOPE_POINT = {
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
    "type": "object",
    "properties": {
        "include": {"type": "array", "items": _SCOPE_POLYGON, "minItems": 1, "maxItems": 4},
        "exclude": {"type": "array", "items": _SCOPE_POLYGON, "minItems": 1, "maxItems": 4},
    },
    "additionalProperties": False,
}

SOURCE_PARAMETERS = {
    "type": "object",
    "properties": {
        "source_kind": {"type": "string", "enum": ["attachment", "panel"]},
        "source_id": {"type": "string", "minLength": 1, "maxLength": 128},
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
