from __future__ import annotations

import math

import pytest

from figura.json_schema import (
    JsonValueError,
    SchemaDefinitionError,
    canonical_json_dumps,
    validate_instance,
    validate_schema_definition,
)


def test_supported_schema_subset_validates_nested_objects_arrays_and_scalars() -> None:
    schema = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": "Choose a response mode.",
                "title": "Mode",
                "enum": ["summary", "detail"],
            },
            "query": {
                "anyOf": [
                    {"type": "string", "minLength": 3, "maxLength": 32, "pattern": "^[a-z]+$"},
                    {"type": "null", "const": None},
                ]
            },
            "scores": {
                "type": "array",
                "items": {"type": "number", "minimum": 0, "exclusiveMaximum": 1},
                "minItems": 1,
                "maxItems": 4,
                "uniqueItems": True,
            },
            "revision": {"type": "integer", "const": 2},
        },
        "required": ["mode", "query", "scores", "revision"],
        "additionalProperties": {"type": "boolean"},
    }

    validate_schema_definition(schema, require_object=True)
    assert validate_instance(
        {"mode": "detail", "query": "chart", "scores": [0.2, 0.8], "revision": 2, "cached": True},
        schema,
    ) is None
    assert validate_instance(
        {"mode": "detail", "query": None, "scores": [0.2, 0.8], "revision": 2},
        schema,
    ) is None


@pytest.mark.parametrize(
    ("value", "expected_code", "expected_pointer"),
    [
        ({"mode": "other", "query": "chart", "scores": [0.2], "revision": 2}, "enum", "/mode"),
        ({"mode": "detail", "query": "a", "scores": [0.2], "revision": 2}, "any_of", "/query"),
        ({"mode": "detail", "query": None, "scores": [0.2, 0.2], "revision": 2}, "unique_items", "/scores/1"),
        ({"mode": "detail", "query": None, "scores": [1], "revision": 2}, "exclusive_maximum", "/scores/0"),
        ({"mode": "detail", "query": None, "scores": [0.2], "revision": True}, "type", "/revision"),
        ({"mode": "detail", "query": None, "scores": [0.2], "revision": 2, "bad": "text"}, "type", "/bad"),
    ],
)
def test_instance_validation_returns_safe_json_pointer_issue(
    value: object, expected_code: str, expected_pointer: str
) -> None:
    schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["summary", "detail"]},
            "query": {"anyOf": [{"type": "string", "minLength": 3}, {"type": "null"}]},
            "scores": {
                "type": "array",
                "items": {"type": "number", "minimum": 0, "exclusiveMaximum": 1},
                "uniqueItems": True,
            },
            "revision": {"type": "integer", "const": 2},
        },
        "required": ["mode", "query", "scores", "revision"],
        "additionalProperties": {"type": "boolean"},
    }

    issue = validate_instance(value, schema)

    assert issue is not None
    assert issue.code == expected_code
    assert issue.pointer == expected_pointer


def test_schema_rejects_unsupported_keywords_and_malformed_anyof() -> None:
    with pytest.raises(SchemaDefinitionError) as unsupported:
        validate_schema_definition({"type": "object", "properties": {}, "$ref": "#/$defs/x"})
    with pytest.raises(SchemaDefinitionError) as malformed:
        validate_schema_definition({"type": "object", "anyOf": [{"type": "string"}]})

    assert unsupported.value.code == "unsupported_keyword"
    assert malformed.value.code == "invalid_anyOf"


def test_schema_and_instance_depth_and_property_bounds_are_enforced() -> None:
    deeply_nested: dict[str, object] = {"type": "string"}
    for _ in range(17):
        deeply_nested = {"type": "object", "properties": {"nested": deeply_nested}}
    with pytest.raises(SchemaDefinitionError) as depth_error:
        validate_schema_definition(deeply_nested)

    too_many_schema_properties = {
        "type": "object",
        "properties": {f"field_{index}": {"type": "string"} for index in range(257)},
    }
    with pytest.raises(SchemaDefinitionError):
        validate_schema_definition(too_many_schema_properties)

    instance = {f"field_{index}": index for index in range(257)}
    issue = validate_instance(instance, {"type": "object"})

    assert depth_error.value.code == "schema_too_deep"
    assert issue is not None
    assert issue.code == "invalid_json_value"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_deterministic_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(JsonValueError):
        canonical_json_dumps({"value": value})


def test_deterministic_json_sorts_keys_and_uses_compact_utf8_output() -> None:
    assert canonical_json_dumps({"中": [1, True], "a": None}) == '{"a":null,"中":[1,true]}'
