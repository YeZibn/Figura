"""Strict parsing and canonical serialization for ChartSpecData v2."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any

from figura.shared.json_schema import (
    MAX_VALUE_DEPTH,
    JsonValueError,
    SchemaIssue,
    canonical_json_dumps,
    validate_instance,
)

from ..limits import MAX_TEXT_LENGTH
from .errors import ChartSpecIssue, ChartSpecParseError, ChartSpecSerializationError
from .limits import CHART_SPEC_SCHEMA_VERSION, MAX_CHART_SPEC_DATA_BYTES, MAX_FINITE_NUMBER
from .models import (
    AreaDataset,
    AxisKind,
    BarDataset,
    BarMode,
    BarOrientation,
    BoxPlotDataset,
    BoxPlotGroup,
    CartesianAxis,
    CartesianCoordinateSystem,
    ChartCategory,
    ChartDataset,
    ChartMetadata,
    ChartSpecData,
    ChartType,
    CoordinateSystemKind,
    HistogramBin,
    HistogramDataset,
    HistogramMeasure,
    HeatmapDataset,
    LineDataset,
    PieDataset,
    PieSlice,
    PolarCoordinateSystem,
    RadarDataset,
    RadarDimension,
    ScatterDataset,
    ScatterPoint,
    ScatterSeries,
    SimpleCoordinateSystem,
    TreemapDataset,
    TreemapNode,
    ValueSeries,
    XYPoint,
    XYSeries,
)
from .schema import CHART_DATASET_SCHEMAS, CHART_SPEC_DATA_SCHEMA, MAX_ID_LENGTH


class _DuplicateKey(ValueError):
    pass


MAX_OBJECT_PROPERTIES = 256


def _issue(code: str, field_path: str, message: str) -> ChartSpecIssue:
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
        return {
            key: _normalize_input(value[key], f"{path}/{_escape_pointer(key)}", depth + 1)
            for key in keys
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_input(item, f"{path}/{index}", depth + 1) for index, item in enumerate(value)]
    _fail("invalid_json_value", path, "输入包含非 JSON 数据。")


def _check_size(value: object, *, path: str = "") -> Any:
    normalized = _normalize_input(value, path)
    try:
        encoded = canonical_json_dumps(normalized).encode("utf-8")
    except (JsonValueError, UnicodeEncodeError, RecursionError, OverflowError):
        _fail("invalid_json_value", path, "输入不是受支持的 JSON 数据。")
    if len(encoded) > MAX_CHART_SPEC_DATA_BYTES:
        _fail("content_too_large", path, "ChartSpec 内容超过 256 KiB 限制。")
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


def _top_level_schema() -> dict[str, Any]:
    schema = deepcopy(CHART_SPEC_DATA_SCHEMA)
    schema["properties"]["dataset"] = {"type": "object"}
    return schema


def parse_chart_spec_data(value: object) -> ChartSpecData:
    normalized = _check_size(value)
    if not isinstance(normalized, Mapping):
        _fail("invalid_object", "", "ChartSpec 顶层必须是对象。")
    if "schema_version" in normalized and type(normalized["schema_version"]) is not int:
        _fail("invalid_schema_version", "/schema_version", "ChartSpec schema_version 必须是整数。")

    top_issue = validate_instance(normalized, _top_level_schema())
    if top_issue is not None:
        _raise_schema_issue(top_issue)

    metadata_raw = normalized["metadata"]
    chart_type_raw = metadata_raw["chart_type"]
    try:
        chart_type = ChartType(chart_type_raw)
    except (TypeError, ValueError):
        _fail("unsupported_chart_type", "/metadata/chart_type", "ChartSpec chart_type 不受支持。")
    if type(normalized["schema_version"]) is not int or normalized["schema_version"] != CHART_SPEC_SCHEMA_VERSION:
        _fail("unsupported_schema_version", "/schema_version", "ChartSpec schema_version 不受支持。")

    dataset_raw = normalized["dataset"]
    dataset_schema = CHART_DATASET_SCHEMAS[chart_type.value]
    dataset_issue = validate_instance(dataset_raw, dataset_schema)
    if dataset_issue is not None:
        _raise_schema_issue(dataset_issue, prefix="/dataset")

    coordinate_raw = normalized["coordinate_system"]
    coordinate = _parse_coordinate_system(coordinate_raw)
    dataset = _parse_dataset(chart_type, dataset_raw)
    metadata = ChartMetadata(
        chart_type=chart_type,
        title=metadata_raw.get("title", ""),
        source=metadata_raw.get("source"),
        note=metadata_raw.get("note", ""),
    )
    return ChartSpecData(
        metadata=metadata,
        coordinate_system=coordinate,
        dataset=dataset,
        schema_version=normalized["schema_version"],
    )


def _raise_schema_issue(issue: SchemaIssue, *, prefix: str = "") -> None:
    path = f"{prefix}{issue.pointer}"
    code = issue.code
    messages = {
        "required": "缺少必需字段。",
        "additional_property": "包含未声明字段。",
        "type": "字段类型无效。",
        "enum": "字段值不在允许范围内。",
        "const": "字段值不受支持。",
        "min_length": "文本长度小于允许范围。",
        "max_length": "文本长度超过限制。",
        "min_items": "数组项数小于允许范围。",
        "max_items": "数组项数超过限制。",
        "minimum": "数值小于允许范围。",
        "maximum": "数值超过允许范围。",
        "exclusive_minimum": "数值必须大于下界。",
        "exclusive_maximum": "数值必须小于上界。",
        "any_of": "字段结构与所选图表类型不匹配。",
    }
    if code == "const" and path == "/schema_version":
        code = "unsupported_schema_version"
        message = "ChartSpec schema_version 不受支持。"
    elif code == "enum" and path == "/metadata/chart_type":
        code = "unsupported_chart_type"
        message = "ChartSpec chart_type 不受支持。"
    else:
        message = messages.get(code, "ChartSpec 字段结构无效。")
    _fail(code, path, message)


def _parse_coordinate_system(value: Mapping[str, Any]):
    kind = value["kind"]
    if kind == "cartesian":
        return CartesianCoordinateSystem(
            x_axis=_parse_axis(value["x_axis"]),
            y_axis=_parse_axis(value["y_axis"]),
        )
    if kind == "polar":
        bounds = value["value_range"]
        return PolarCoordinateSystem(minimum=bounds["min"], maximum=bounds["max"])
    return SimpleCoordinateSystem(CoordinateSystemKind(kind))


def _parse_axis(value: Mapping[str, Any]) -> CartesianAxis:
    return CartesianAxis(kind=AxisKind(value["kind"]), label=value.get("label"))


def _parse_category(value: Mapping[str, Any]) -> ChartCategory:
    return ChartCategory(id=value["id"], label=value["label"])


def _parse_value_series(value: Mapping[str, Any]) -> ValueSeries:
    return ValueSeries(value["id"], value["label"], tuple(value["values"]))


def _parse_xy_series(value: Mapping[str, Any]) -> XYSeries:
    return XYSeries(
        id=value["id"],
        label=value["label"],
        points=tuple(XYPoint(point["x"], point["y"]) for point in value["points"]),
    )


def _parse_dataset(chart_type: ChartType, value: Mapping[str, Any]) -> ChartDataset:
    if chart_type is ChartType.BAR:
        return BarDataset(
            orientation=BarOrientation(value["orientation"]),
            mode=BarMode(value["mode"]),
            categories=tuple(_parse_category(item) for item in value["categories"]),
            series=tuple(_parse_value_series(item) for item in value["series"]),
        )
    if chart_type is ChartType.LINE:
        return LineDataset(tuple(_parse_xy_series(item) for item in value["series"]))
    if chart_type is ChartType.AREA:
        return AreaDataset(value["stacking"], tuple(_parse_xy_series(item) for item in value["series"]))
    if chart_type is ChartType.SCATTER:
        series = tuple(
            ScatterSeries(
                item["id"],
                item["label"],
                tuple(ScatterPoint(point["x"], point["y"], point.get("size")) for point in item["points"]),
            )
            for item in value["series"]
        )
        return ScatterDataset(series)
    if chart_type is ChartType.PIE:
        slices = tuple(PieSlice(item["id"], item["label"], item["value"]) for item in value["slices"])
        return PieDataset(slices, value.get("inner_radius_ratio"))
    if chart_type is ChartType.HISTOGRAM:
        bins = tuple(HistogramBin(item["start"], item["end"], item["value"]) for item in value["bins"])
        return HistogramDataset(HistogramMeasure(value["measure"]), bins)
    if chart_type is ChartType.BOX_PLOT:
        groups = tuple(
            BoxPlotGroup(
                id=item["id"],
                label=item["label"],
                lower_whisker=item["lower_whisker"],
                q1=item["q1"],
                median=item["median"],
                q3=item["q3"],
                upper_whisker=item["upper_whisker"],
                outliers=tuple(item.get("outliers", ())),
            )
            for item in value["groups"]
        )
        return BoxPlotDataset(BarOrientation(value["orientation"]), groups)
    if chart_type is ChartType.RADAR:
        dimensions = tuple(_parse_category(item) for item in value["dimensions"])
        return RadarDataset(dimensions, tuple(_parse_value_series(item) for item in value["series"]))
    if chart_type is ChartType.HEATMAP:
        return HeatmapDataset(
            x_categories=tuple(_parse_category(item) for item in value["x_categories"]),
            y_categories=tuple(_parse_category(item) for item in value["y_categories"]),
            values=tuple(tuple(row) for row in value["values"]),
        )
    if chart_type is ChartType.TREEMAP:
        nodes = tuple(
            TreemapNode(item["id"], item["parent_id"], item["label"], item.get("value"))
            for item in value["nodes"]
        )
        return TreemapDataset(value["root_id"], nodes)
    raise AssertionError("ChartType exhaustiveness")


def serialize_chart_spec_data(value: ChartSpecData) -> str:
    if not isinstance(value, ChartSpecData):
        raise ChartSpecSerializationError(_issue("invalid_chart_spec", "", "需要 ChartSpecData 值。"))
    try:
        raw = value.to_dict()
        parse_chart_spec_data(raw)
        from .validation import validate_chart_spec_data

        issues = validate_chart_spec_data(value)
        if issues:
            raise ChartSpecParseError(issues[0])
        encoded = canonical_json_dumps(raw)
        size = len(encoded.encode("utf-8"))
    except ChartSpecParseError as error:
        raise ChartSpecSerializationError(error.issue) from None
    except (JsonValueError, UnicodeEncodeError, RecursionError, OverflowError, TypeError, ValueError):
        raise ChartSpecSerializationError(_issue("invalid_chart_spec", "", "ChartSpecData 无法序列化为 JSON。")) from None
    if size > MAX_CHART_SPEC_DATA_BYTES:
        raise ChartSpecSerializationError(_issue("content_too_large", "", "ChartSpec 内容超过 256 KiB 限制。"))
    return encoded


def _rfc3339(value: str) -> bool:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None
