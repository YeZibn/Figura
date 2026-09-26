"""Bounded JSON Schema and JSON value helpers owned by Figura."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


MAX_SCHEMA_DEPTH = 16
MAX_SCHEMA_PROPERTIES = 256
MAX_SCHEMA_BYTES = 128 * 1024
MAX_VALUE_DEPTH = 64
MAX_OBJECT_PROPERTIES = 256

SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "description",
        "title",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "anyOf",
        "const",
    }
)
SCHEMA_TYPES = frozenset({"object", "string", "integer", "number", "boolean", "array", "null"})


@dataclass(frozen=True)
class SchemaIssue:
    """A safe, payload-free schema or instance validation issue."""

    code: str
    pointer: str = ""


class JsonValueError(ValueError):
    """Raised when a Python value cannot be represented as bounded JSON."""


class SchemaDefinitionError(ValueError):
    """Raised for malformed or unsupported schemas without embedding values."""

    def __init__(self, code: str, pointer: str = "") -> None:
        self.code = code
        self.pointer = pointer
        super().__init__(code)


def canonical_json_dumps(value: Any) -> str:
    """Return deterministic compact JSON, rejecting non-JSON Python values."""

    normalized = normalize_json_value(value)
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise JsonValueError("value is not serializable as JSON") from None


def normalize_json_value(value: Any, *, max_depth: int = MAX_VALUE_DEPTH) -> Any:
    """Copy JSON data into plain dict/list values and enforce bounded shape."""

    def visit(item: Any, depth: int) -> Any:
        if depth > max_depth:
            raise JsonValueError("JSON nesting is too deep")
        if item is None or type(item) in (str, bool, int):
            return item
        if type(item) is float:
            if not math.isfinite(item):
                raise JsonValueError("JSON numbers must be finite")
            return item
        if isinstance(item, Mapping):
            if len(item) > MAX_OBJECT_PROPERTIES:
                raise JsonValueError("JSON object has too many properties")
            normalized: dict[str, Any] = {}
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise JsonValueError("JSON object keys must be strings")
                normalized[key] = visit(nested, depth + 1)
            return normalized
        if isinstance(item, (list, tuple)):
            return [visit(nested, depth + 1) for nested in item]
        raise JsonValueError("value is not JSON-compatible")

    return visit(value, 0)


def validate_schema_definition(
    schema: object,
    *,
    require_object: bool = False,
    max_bytes: int = MAX_SCHEMA_BYTES,
) -> dict[str, Any]:
    """Validate a schema in Figura's deliberately small supported dialect."""

    if not isinstance(schema, Mapping):
        raise SchemaDefinitionError("schema_not_object")
    try:
        normalized = normalize_json_value(schema, max_depth=MAX_VALUE_DEPTH)
    except JsonValueError:
        raise SchemaDefinitionError("schema_not_json") from None
    try:
        size = len(canonical_json_dumps(normalized).encode("utf-8"))
    except (JsonValueError, UnicodeEncodeError):
        raise SchemaDefinitionError("schema_not_json") from None
    if size > max_bytes:
        raise SchemaDefinitionError("schema_too_large")
    if require_object and normalized.get("type") != "object":
        raise SchemaDefinitionError("top_level_not_object")
    _validate_schema_node(normalized, depth=0, pointer="")
    return normalized


def _validate_schema_node(schema: Mapping[str, Any], *, depth: int, pointer: str) -> None:
    if depth > MAX_SCHEMA_DEPTH:
        raise SchemaDefinitionError("schema_too_deep", pointer)
    for keyword in schema:
        if keyword not in SUPPORTED_SCHEMA_KEYWORDS:
            raise SchemaDefinitionError("unsupported_keyword", _join(pointer, keyword))

    schema_type = schema.get("type")
    if schema_type is not None and (not isinstance(schema_type, str) or schema_type not in SCHEMA_TYPES):
        raise SchemaDefinitionError("unsupported_type", _join(pointer, "type"))

    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping) or len(properties) > MAX_SCHEMA_PROPERTIES:
        raise SchemaDefinitionError("invalid_properties", _join(pointer, "properties"))
    for name, nested in properties.items():
        if not isinstance(name, str) or not isinstance(nested, Mapping):
            raise SchemaDefinitionError("invalid_properties", _join(pointer, "properties"))
        _validate_schema_node(nested, depth=depth + 1, pointer=_join(_join(pointer, "properties"), name))

    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise SchemaDefinitionError("invalid_required", _join(pointer, "required"))
    if len(required) != len(set(required)) or any(item not in properties for item in required):
        raise SchemaDefinitionError("invalid_required_reference", _join(pointer, "required"))

    if "items" in schema:
        items = schema["items"]
        if not isinstance(items, Mapping):
            raise SchemaDefinitionError("invalid_items", _join(pointer, "items"))
        _validate_schema_node(items, depth=depth + 1, pointer=_join(pointer, "items"))

    additional = schema.get("additionalProperties")
    if isinstance(additional, Mapping):
        _validate_schema_node(
            additional,
            depth=depth + 1,
            pointer=_join(pointer, "additionalProperties"),
        )
    elif additional is not None and type(additional) is not bool:
        raise SchemaDefinitionError("invalid_additional_properties", _join(pointer, "additionalProperties"))

    for key in ("enum", "anyOf"):
        if key in schema and not isinstance(schema[key], list):
            raise SchemaDefinitionError(f"invalid_{key}", _join(pointer, key))
    for key in ("description", "title", "pattern"):
        if key in schema and (not isinstance(schema[key], str) or len(schema[key]) > 8192):
            raise SchemaDefinitionError(f"invalid_{key}", _join(pointer, key))
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except re.error:
            raise SchemaDefinitionError("invalid_pattern", _join(pointer, "pattern")) from None

    for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if key in schema and (type(schema[key]) not in (int, float) or not math.isfinite(schema[key])):
            raise SchemaDefinitionError(f"invalid_{key}", _join(pointer, key))
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            raise SchemaDefinitionError(f"invalid_{key}", _join(pointer, key))
    if "uniqueItems" in schema and type(schema["uniqueItems"]) is not bool:
        raise SchemaDefinitionError("invalid_uniqueItems", _join(pointer, "uniqueItems"))
    if "enum" in schema and (not schema["enum"] or len(schema["enum"]) > 256):
        raise SchemaDefinitionError("invalid_enum", _join(pointer, "enum"))
    if "anyOf" in schema:
        variants = schema["anyOf"]
        if len(variants) < 2 or any(not isinstance(item, Mapping) for item in variants):
            raise SchemaDefinitionError("invalid_anyOf", _join(pointer, "anyOf"))
        for index, nested in enumerate(variants):
            _validate_schema_node(
                nested,
                depth=depth + 1,
                pointer=_join(_join(pointer, "anyOf"), str(index)),
            )


def validate_instance(instance: Any, schema: Mapping[str, Any]) -> SchemaIssue | None:
    """Return the first safe JSON Pointer issue, or ``None`` for a match."""

    try:
        value = normalize_json_value(instance)
        normalized_schema = validate_schema_definition(schema)
    except (JsonValueError, SchemaDefinitionError):
        return SchemaIssue("invalid_json_value")
    return _validate_instance_node(value, normalized_schema, pointer="", depth=0)


def _validate_instance_node(
    value: Any,
    schema: Mapping[str, Any],
    *,
    pointer: str,
    depth: int,
) -> SchemaIssue | None:
    if depth > MAX_VALUE_DEPTH:
        return SchemaIssue("value_too_deep", pointer)
    schema_type = schema.get("type")
    if schema_type is not None and not _matches_type(value, schema_type):
        return SchemaIssue("type", pointer)
    if "const" in schema and not _json_equal(value, schema["const"]):
        return SchemaIssue("const", pointer)
    if "enum" in schema and not any(_json_equal(value, candidate) for candidate in schema["enum"]):
        return SchemaIssue("enum", pointer)

    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                return SchemaIssue("required", _join(pointer, required))
        for key, nested_value in value.items():
            if key in properties:
                issue = _validate_instance_node(
                    nested_value,
                    properties[key],
                    pointer=_join(pointer, key),
                    depth=depth + 1,
                )
                if issue is not None:
                    return issue
                continue
            additional = schema.get("additionalProperties")
            if additional is False:
                return SchemaIssue("additional_property", _join(pointer, key))
            if isinstance(additional, Mapping):
                issue = _validate_instance_node(
                    nested_value,
                    additional,
                    pointer=_join(pointer, key),
                    depth=depth + 1,
                )
                if issue is not None:
                    return issue

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return SchemaIssue("min_items", pointer)
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return SchemaIssue("max_items", pointer)
        if schema.get("uniqueItems") is True:
            seen: set[str] = set()
            for index, item in enumerate(value):
                key = canonical_json_dumps(_normalize_numbers(item))
                if key in seen:
                    return SchemaIssue("unique_items", _join(pointer, str(index)))
                seen.add(key)
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                issue = _validate_instance_node(
                    item,
                    item_schema,
                    pointer=_join(pointer, str(index)),
                    depth=depth + 1,
                )
                if issue is not None:
                    return issue

    if type(value) in (int, float) and type(value) is not bool:
        if "minimum" in schema and value < schema["minimum"]:
            return SchemaIssue("minimum", pointer)
        if "maximum" in schema and value > schema["maximum"]:
            return SchemaIssue("maximum", pointer)
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return SchemaIssue("exclusive_minimum", pointer)
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            return SchemaIssue("exclusive_maximum", pointer)
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return SchemaIssue("min_length", pointer)
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return SchemaIssue("max_length", pointer)
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return SchemaIssue("pattern", pointer)

    if "anyOf" in schema and not any(
        _validate_instance_node(value, nested, pointer=pointer, depth=depth) is None
        for nested in schema["anyOf"]
    ):
        return SchemaIssue("any_of", pointer)
    return None


def _matches_type(value: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(value, Mapping)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return type(value) is int or type(value) is float and value.is_integer()
    if schema_type == "number":
        return type(value) in (int, float) and math.isfinite(value)
    if schema_type == "boolean":
        return type(value) is bool
    if schema_type == "null":
        return value is None
    return False


def _json_equal(left: Any, right: Any) -> bool:
    if type(left) in (int, float) and type(left) is not bool and type(right) in (int, float) and type(right) is not bool:
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        return left.keys() == right.keys() and all(_json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return left == right


def _normalize_numbers(value: Any) -> Any:
    if type(value) is float and value.is_integer():
        return int(value)
    if isinstance(value, Mapping):
        return {key: _normalize_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_numbers(item) for item in value]
    return value


def _join(pointer: str, token: str) -> str:
    escaped = token.replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{escaped}"
