"""Strict parsing and canonical serialization for ChartFigure values."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from figura.shared.json_schema import (
    JsonValueError,
    canonical_json_dumps,
    normalize_json_value,
    validate_instance,
)

from ..chartspec.codec import parse_chart_spec_data
from .errors import (
    ChartFigureIssue,
    ChartFigureParseError,
    ChartFigureSerializationError,
)
from .limits import MAX_CHART_FIGURE_BYTES
from .models import ChartFigure, ChartFigureItem, FigureLayout, MeasurementRef
from .schema import CHART_FIGURE_SCHEMA
from .validation import validate_chart_figure


class _DuplicateKey(ValueError):
    pass


class _InvalidConstant(ValueError):
    pass


def _issue(code: str, field_path: str, message: str) -> ChartFigureIssue:
    try:
        path_size = len(field_path.encode("utf-8"))
    except UnicodeEncodeError:
        field_path = ""
        path_size = 0
    if path_size > 256:
        field_path = ""
    return ChartFigureIssue(code, field_path, message[:240])


def _fail(code: str, field_path: str, message: str) -> None:
    raise ChartFigureParseError(_issue(code, field_path, message))


def _check_payload_size(value: object) -> Any:
    try:
        normalized = normalize_json_value(value)
        encoded = canonical_json_dumps(normalized).encode("utf-8")
    except (JsonValueError, UnicodeEncodeError, RecursionError, OverflowError):
        _fail("invalid_json_value", "", "ChartFigure 包含无效 JSON 数据。")
    if len(encoded) > MAX_CHART_FIGURE_BYTES:
        _fail("content_too_large", "", "ChartFigure 内容超过 64 KiB 限制。")
    return normalized


def parse_chart_figure_json(value: str) -> ChartFigure:
    if not isinstance(value, str):
        _fail("invalid_json_text", "", "ChartFigure JSON 必须是字符串。")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        _fail("invalid_json_text", "", "ChartFigure JSON 不是有效 UTF-8。")
    if len(encoded) > MAX_CHART_FIGURE_BYTES:
        _fail("content_too_large", "", "ChartFigure JSON 超过 64 KiB 限制。")

    def object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise _DuplicateKey
            result[key] = item
        return result

    def reject_constant(_constant: str) -> None:
        raise _InvalidConstant

    try:
        parsed = json.loads(
            value,
            object_pairs_hook=object_from_pairs,
            parse_constant=reject_constant,
        )
    except _DuplicateKey:
        _fail("duplicate_key", "", "ChartFigure JSON 包含重复字段。")
    except _InvalidConstant:
        _fail("non_finite_number", "", "ChartFigure 数值必须是有限数字。")
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError):
        _fail("invalid_json_text", "", "ChartFigure JSON 格式无效。")
    return parse_chart_figure(parsed)


def parse_chart_figure(value: object) -> ChartFigure:
    normalized = _check_payload_size(value)
    if not isinstance(normalized, Mapping):
        _fail("invalid_object", "", "ChartFigure 顶层必须是对象。")
    if "schema_version" in normalized and type(normalized["schema_version"]) is not int:
        _fail("invalid_schema_version", "/schema_version", "ChartFigure schema_version 必须是整数。")

    layout = normalized.get("layout")
    if isinstance(layout, Mapping) and "columns" in layout and type(layout["columns"]) is not int:
        _fail("invalid_columns", "/layout/columns", "layout.columns 必须是整数。")

    issue = validate_instance(normalized, CHART_FIGURE_SCHEMA)
    if issue is not None:
        code = issue.code
        message = _SCHEMA_MESSAGES.get(code, "ChartFigure 字段结构无效。")
        if code == "const":
            code = "unsupported_schema_version"
            message = "ChartFigure schema_version 不受支持。"
        _fail(code, issue.pointer, message)

    parsed_charts: list[ChartFigureItem] = []
    for index, raw_chart in enumerate(normalized["charts"]):
        chart_path = f"/charts/{index}"
        try:
            chart_spec = parse_chart_spec_data(raw_chart["chart_spec"])
        except ValueError as error:
            child_issue = getattr(error, "issue", None)
            child_path = getattr(child_issue, "field_path", "")
            _fail(
                getattr(child_issue, "code", "invalid_chart_spec"),
                f"{chart_path}/chart_spec{child_path}",
                getattr(child_issue, "message", "嵌套 ChartSpecData 无法解析。"),
            )
        references = tuple(
            MeasurementRef(run_id=reference["run_id"], call_id=reference["call_id"])
            for reference in raw_chart.get("measurement_refs", [])
        )
        parsed_charts.append(
            ChartFigureItem(
                chart_id=raw_chart["chart_id"],
                chart_spec=chart_spec,
                measurement_refs=references,
            )
        )

    figure = ChartFigure(
        schema_version=normalized["schema_version"],
        title=normalized.get("title", ""),
        layout=FigureLayout(columns=normalized["layout"]["columns"]),
        charts=tuple(parsed_charts),
    )
    issues = validate_chart_figure(figure)
    if issues:
        issue = issues[0]
        _fail(issue.code, issue.field_path, issue.message)
    return figure


def serialize_chart_figure(value: ChartFigure) -> str:
    if not isinstance(value, ChartFigure):
        raise ChartFigureSerializationError(
            _issue("invalid_chart_figure", "", "需要 ChartFigure 值。")
        )
    try:
        encoded = canonical_json_dumps(value.to_dict())
        size = len(encoded.encode("utf-8"))
        if size > MAX_CHART_FIGURE_BYTES:
            raise ChartFigureSerializationError(
                _issue("content_too_large", "", "ChartFigure 内容超过 64 KiB 限制。")
            )
        parse_chart_figure_json(encoded)
    except ChartFigureSerializationError:
        raise
    except ChartFigureParseError as error:
        raise ChartFigureSerializationError(error.issue) from None
    except (JsonValueError, UnicodeEncodeError, AttributeError, TypeError, RecursionError, OverflowError):
        raise ChartFigureSerializationError(
            _issue("invalid_chart_figure", "", "ChartFigure 无法序列化为 JSON。")
        ) from None
    return encoded


def chart_figure_digest(value: ChartFigure) -> str:
    """Return the lowercase SHA-256 digest of canonical Figure JSON."""
    return hashlib.sha256(serialize_chart_figure(value).encode("utf-8")).hexdigest()


_SCHEMA_MESSAGES = {
    "required": "缺少必需字段。",
    "additional_property": "包含未定义字段。",
    "type": "字段类型无效。",
    "enum": "字段值不在允许范围内。",
    "const": "字段值不受支持。",
    "pattern": "字段格式无效。",
    "any_of": "字段结构与允许的形状不匹配。",
    "min_length": "文本不能为空。",
    "max_length": "文本长度超过限制。",
    "min_items": "列表不能为空。",
    "max_items": "列表长度超过限制。",
    "unique_items": "列表包含重复项。",
    "minimum": "数值低于允许范围。",
    "maximum": "数值高于允许范围。",
}
