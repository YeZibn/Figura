"""Strict parsing and deterministic serialization for ChartSpecData."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from figura.shared.json_schema import (
    MAX_OBJECT_PROPERTIES,
    MAX_VALUE_DEPTH,
    JsonValueError,
    SchemaIssue,
    canonical_json_dumps,
    validate_instance,
)

from ..limits import MAX_TEXT_LENGTH
from .errors import (
    ChartSpecIssue,
    ChartSpecParseError,
    ChartSpecSerializationError,
)
from .limits import MAX_CHART_SPEC_DATA_BYTES, MAX_FINITE_NUMBER
from .models import (
    Axis,
    Axes,
    CategoryValuePoint,
    ChartMetadata,
    ChartSpecData,
    ChartType,
    CoordinatePoint,
)
from .schema import (
    CHART_SPEC_DATA_SCHEMA,
    _CATEGORY_POINT_SCHEMA,
    _COORDINATE_POINT_SCHEMA,
)


class _DuplicateKey(ValueError):
    pass


def _issue(
    code: str,
    field_path: str,
    message: str,
) -> ChartSpecIssue:
    try:
        path_size = len(field_path.encode("utf-8"))
    except UnicodeEncodeError:
        field_path = ""
        path_size = 0
    if path_size > 256:
        field_path = ""
    return ChartSpecIssue(code, field_path, message[:240])


def _fail(code: str, field_path: str, message: str) -> None:
    raise ChartSpecParseError(_issue(code, field_path, message))


def _escape_pointer(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def _normalize_input(value: object, path: str = "", depth: int = 0) -> Any:
    if depth > MAX_VALUE_DEPTH:
        _fail("value_too_deep", path, "ChartSpec 数据嵌套超过限制。")
    if value is None or type(value) in (bool, str):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                _fail("invalid_text", path, "文本不是有效 UTF-8。")
        return value
    if type(value) in (int, float):
        if type(value) is float and not math.isfinite(value):
            _fail("non_finite_number", path, "数值必须是有限数字。")
        try:
            in_range = abs(value) <= MAX_FINITE_NUMBER
        except OverflowError:
            in_range = False
        if not in_range:
            _fail("number_out_of_range", path, "数值超出有限 binary64 范围。")
        return value
    if isinstance(value, Mapping):
        if len(value) > MAX_OBJECT_PROPERTIES:
            _fail("too_many_properties", path, "对象字段数量超过限制。")
        keys = list(value.keys())
        if any(not isinstance(key, str) for key in keys):
            _fail("invalid_object_key", path, "对象字段名必须是字符串。")
        try:
            for key in keys:
                key.encode("utf-8")
        except UnicodeEncodeError:
            _fail("invalid_object_key", path, "对象字段名不是有效 UTF-8。")
        normalized: dict[str, Any] = {}
        for key in sorted(keys):
            child_path = f"{path}/{_escape_pointer(key)}"
            normalized[key] = _normalize_input(value[key], child_path, depth + 1)
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _normalize_input(item, f"{path}/{index}", depth + 1)
            for index, item in enumerate(value)
        ]
    _fail("invalid_json_value", path, "输入包含非 JSON 数据。")


def _check_payload_size(value: object) -> Any:
    normalized = _normalize_input(value)
    try:
        encoded = canonical_json_dumps(normalized).encode("utf-8")
    except (JsonValueError, UnicodeEncodeError, RecursionError, OverflowError):
        _fail("invalid_json_value", "", "输入不是受支持的 JSON 数据。")
    if len(encoded) > MAX_CHART_SPEC_DATA_BYTES:
        _fail("content_too_large", "", "ChartSpec 内容超过 256 KiB 限制。")
    return normalized


def parse_chart_spec_data_json(value: str) -> ChartSpecData:
    if not isinstance(value, str):
        _fail("invalid_json_text", "", "ChartSpec JSON 必须是字符串。")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        _fail("invalid_json_text", "", "ChartSpec JSON 不是有效 UTF-8。")
    if len(encoded) > MAX_CHART_SPEC_DATA_BYTES:
        _fail("content_too_large", "", "ChartSpec JSON 超过 256 KiB 限制。")

    def object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise _DuplicateKey
            result[key] = item
        return result

    try:
        parsed = json.loads(value, object_pairs_hook=object_from_pairs)
    except _DuplicateKey:
        _fail("duplicate_key", "", "ChartSpec JSON 包含重复字段。")
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError):
        _fail("invalid_json_text", "", "ChartSpec JSON 格式无效。")
    return parse_chart_spec_data(parsed)


def parse_chart_spec_data(value: object) -> ChartSpecData:
    normalized = _check_payload_size(value)
    if not isinstance(normalized, Mapping):
        _fail("invalid_object", "", "ChartSpec 顶层必须是对象。")
    ordered = _order_for_schema(normalized, CHART_SPEC_DATA_SCHEMA)
    if "schema_version" in ordered and type(ordered["schema_version"]) is not int:
        _fail("invalid_schema_version", "/schema_version", "ChartSpec schema_version 必须是整数。")

    issue = validate_instance(ordered, CHART_SPEC_DATA_SCHEMA)
    if issue is not None:
        issue = _refine_point_variant_issue(ordered, issue)
        code = issue.code
        message = _SCHEMA_MESSAGES.get(code, "ChartSpec 字段结构无效。")
        if code == "const":
            code = "unsupported_schema_version"
            message = "ChartSpec schema_version 不受支持。"
        elif code == "enum":
            code = "unsupported_chart_type"
            message = "ChartSpec chart_type 不受支持。"
        _fail(code, issue.pointer, message)

    metadata_raw = ordered["metadata"]
    try:
        chart_type = ChartType(metadata_raw["chart_type"])
    except (TypeError, ValueError):
        _fail("unsupported_chart_type", "/metadata/chart_type", "ChartSpec chart_type 不受支持。")

    metadata = ChartMetadata(
        chart_type=chart_type,
        title=metadata_raw.get("title", ""),
        source=metadata_raw.get("source"),
        note=metadata_raw.get("note", ""),
    )
    axes_raw = ordered["axes"]
    axes = None
    if isinstance(axes_raw, Mapping):
        axes = Axes(
            x=_parse_axis(axes_raw["x"]),
            y=_parse_axis(axes_raw["y"]),
        )
    dataset = tuple(_parse_point(point) for point in ordered["dataset"])
    return ChartSpecData(
        metadata=metadata,
        axes=axes,
        dataset=dataset,
        schema_version=ordered["schema_version"],
    )


def _order_for_schema(value: Any, schema: Mapping[str, Any]) -> Any:
    """Order known properties by their contract, independent of input order."""
    variants = schema.get("anyOf")
    if isinstance(variants, list):
        schema = _select_variant(value, variants)
    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            return dict(value)
        result = {
            key: _order_for_schema(value[key], nested)
            for key, nested in properties.items()
            if key in value and isinstance(nested, Mapping)
        }
        for key in sorted(set(value) - set(result)):
            result[key] = value[key]
        return result
    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, Mapping):
            return [_order_for_schema(item, items) for item in value]
    return value


def _select_variant(value: Any, variants: list[Any]) -> Mapping[str, Any]:
    if value is None:
        for candidate in variants:
            if isinstance(candidate, Mapping) and candidate.get("type") == "null":
                return candidate
    if isinstance(value, Mapping):
        scored: list[tuple[int, int, int, Mapping[str, Any]]] = []
        keys = set(value)
        for index, candidate in enumerate(variants):
            if not isinstance(candidate, Mapping):
                continue
            properties = candidate.get("properties", {})
            required = set(candidate.get("required", ()))
            if not isinstance(properties, Mapping):
                properties = {}
            required_matches = len(required & keys)
            known_matches = len(set(properties) & keys)
            extra_count = len(keys - set(properties))
            scored.append((required_matches, known_matches - extra_count, -index, candidate))
        if scored:
            return max(scored, key=lambda item: item[:3])[3]
    for candidate in variants:
        if isinstance(candidate, Mapping):
            candidate_type = candidate.get("type")
            if candidate_type == "null" and value is None:
                return candidate
            if candidate_type == "object" and isinstance(value, Mapping):
                return candidate
    return next((candidate for candidate in variants if isinstance(candidate, Mapping)), {})


def _parse_axis(value: Mapping[str, Any]) -> Axis:
    return Axis(
        label=value["label"],
        categories=tuple(value["categories"]) if "categories" in value else None,
        min_value=value.get("min_value"),
        max_value=value.get("max_value"),
    )


def _parse_point(value: Mapping[str, Any]) -> CategoryValuePoint | CoordinatePoint:
    series = value.get("series")
    if "category" in value:
        return CategoryValuePoint(
            category=value["category"],
            value=value["value"],
            series=series,
        )
    return CoordinatePoint(x=value["x"], y=value["y"], series=series)


def _refine_point_variant_issue(
    value: Mapping[str, Any],
    issue: SchemaIssue,
) -> SchemaIssue:
    """Expose the failing child field when a point does not match either variant."""
    if issue.code != "any_of":
        return issue
    parts = issue.pointer.split("/")
    if len(parts) != 3 or parts[1] != "dataset" or not parts[2].isdigit():
        return issue
    index = int(parts[2])
    dataset = value.get("dataset")
    if not isinstance(dataset, list) or index >= len(dataset):
        return issue
    point = dataset[index]
    if not isinstance(point, Mapping):
        return issue
    if "category" in point or "value" in point:
        variants = (_CATEGORY_POINT_SCHEMA, _COORDINATE_POINT_SCHEMA)
    elif "x" in point or "y" in point:
        variants = (_COORDINATE_POINT_SCHEMA, _CATEGORY_POINT_SCHEMA)
    else:
        variants = (_CATEGORY_POINT_SCHEMA, _COORDINATE_POINT_SCHEMA)
    for schema in variants:
        candidate = validate_instance(point, schema)
        if candidate is not None and candidate.code != "additional_property":
            return type(issue)(candidate.code, f"{issue.pointer}{candidate.pointer}")
    for schema in variants:
        candidate = validate_instance(point, schema)
        if candidate is not None:
            return type(issue)(candidate.code, f"{issue.pointer}{candidate.pointer}")
    return issue


def serialize_chart_spec_data(value: ChartSpecData) -> str:
    if not isinstance(value, ChartSpecData):
        raise ChartSpecSerializationError(
            _issue("invalid_chart_spec", "", "需要 ChartSpecData 值。")
        )
    try:
        encoded = canonical_json_dumps(value.to_dict())
        size = len(encoded.encode("utf-8"))
    except (JsonValueError, UnicodeEncodeError, AttributeError, RecursionError, OverflowError):
        raise ChartSpecSerializationError(
            _issue("invalid_chart_spec", "", "ChartSpecData 无法序列化为 JSON。")
        ) from None
    if size > MAX_CHART_SPEC_DATA_BYTES:
        raise ChartSpecSerializationError(
            _issue("content_too_large", "", "ChartSpec 内容超过 256 KiB 限制。")
        )
    return encoded


_SCHEMA_MESSAGES = {
    "required": "缺少必需字段。",
    "additional_property": "包含未定义字段。",
    "type": "字段类型无效。",
    "enum": "字段值不在允许范围内。",
    "const": "字段值不受支持。",
    "any_of": "字段结构与允许的形状不匹配。",
    "min_length": "文本不能为空。",
    "max_length": "文本长度超过限制。",
    "min_items": "列表不能为空。",
    "max_items": "列表长度超过限制。",
    "unique_items": "列表包含重复项。",
    "minimum": "数值低于允许范围。",
    "maximum": "数值高于允许范围。",
    "invalid_json_value": "输入包含无效 JSON 数据。",
    "value_too_deep": "ChartSpec 数据嵌套超过限制。",
}
