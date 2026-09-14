"""Declarative tool metadata and the canonical export contract."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping


MAX_TOOL_DESCRIPTION_LENGTH = 2048
MAX_TOOL_DISPLAY_NAME_LENGTH = 80
MAX_TOOL_GROUP_LENGTH = 48
MAX_PARAMETER_DESCRIPTION_LENGTH = 512
_GROUP_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


def _bounded_text(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Tool {field} must be a string.")
    text = " ".join(value.split())
    if not text:
        raise ValueError(f"Tool {field} must be non-empty.")
    if len(text) > maximum:
        raise ValueError(f"Tool {field} exceeds {maximum} characters.")
    return text


def _schema_description(name: str) -> str:
    return f"Input field '{name}'."


def _normalise_schema_node(schema: Mapping[str, Any], *, path: str) -> Dict[str, Any]:
    if not isinstance(schema, Mapping):
        raise TypeError(f"Tool schema at {path} must be an object.")
    result: Dict[str, Any] = copy.deepcopy(dict(schema))

    schema_type = result.get("type")
    if schema_type is None and path == "parameters":
        result["type"] = "object"
        schema_type = "object"
    if schema_type is None and not any(
        key in result
        for key in ("anyOf", "oneOf", "allOf", "$ref", "required", "const", "enum")
    ):
        raise ValueError(f"Tool schema at {path} must declare a type.")

    if schema_type == "object" or "properties" in result:
        properties = result.get("properties", {})
        if not isinstance(properties, Mapping):
            raise TypeError(f"Tool schema properties at {path} must be an object.")
        normalised_properties: Dict[str, Any] = {}
        for name, child in properties.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Tool schema at {path} has an invalid property name.")
            child_schema = _normalise_schema_node(child, path=f"{path}.{name}")
            description = child_schema.get("description", _schema_description(name))
            child_schema["description"] = _bounded_text(
                description,
                field=f"parameter {path}.{name} description",
                maximum=MAX_PARAMETER_DESCRIPTION_LENGTH,
            )
            normalised_properties[name] = child_schema
        result["properties"] = normalised_properties

        required = result.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise TypeError(f"Tool schema required at {path} must be a list of strings.")
        if len(set(required)) != len(required) or any(item not in normalised_properties for item in required):
            raise ValueError(f"Tool schema required at {path} must reference unique properties.")
        result["required"] = list(required)

        additional = result.get("additionalProperties", False)
        if isinstance(additional, Mapping):
            additional = _normalise_schema_node(additional, path=f"{path}.additionalProperties")
        elif not isinstance(additional, bool):
            raise TypeError(f"Tool schema additionalProperties at {path} must be boolean or schema.")
        result["additionalProperties"] = additional

    if isinstance(result.get("items"), Mapping):
        result["items"] = _normalise_schema_node(result["items"], path=f"{path}.items")
    for keyword in ("anyOf", "oneOf", "allOf"):
        variants = result.get(keyword)
        if variants is not None:
            if not isinstance(variants, list):
                raise TypeError(f"Tool schema {keyword} at {path} must be a list.")
            result[keyword] = [
                _normalise_schema_node(item, path=f"{path}.{keyword}[{index}]")
                for index, item in enumerate(variants)
            ]
    return result


def normalise_parameters(parameters: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a bounded object schema with explicit input-policy fields."""
    return _normalise_schema_node(parameters, path="parameters")


def canonical_tool_definition(tool: "Tool") -> dict[str, Any]:
    """Return the one metadata shape shared by Agent and MCP exporters."""
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": copy.deepcopy(tool.parameters),
    }


@dataclass
class Tool:
    """A declarative tool: metadata + a Python callable.

    Attributes:
        name: stable identifier used by the model / external host.
        description: human-readable guidance for choosing this tool.
        parameters: JSON-Schema object describing accepted arguments.
        fn: callable that executes the tool when dispatched.
        display_name: optional local-language name for UI and traces.
        group: bounded stable group identifier for UI and traces.
    """

    name: str
    description: str
    parameters: Mapping[str, Any]
    fn: Callable[..., Any]
    display_name: str | None = None
    group: str = "general"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool name must be a non-empty string.")
        self.name = self.name.strip()
        if not callable(self.fn):
            raise TypeError("Tool.fn must be callable.")
        self.description = _bounded_text(
            self.description,
            field="description",
            maximum=MAX_TOOL_DESCRIPTION_LENGTH,
        )
        if self.display_name is not None:
            self.display_name = _bounded_text(
                self.display_name,
                field="display_name",
                maximum=MAX_TOOL_DISPLAY_NAME_LENGTH,
            )
        if not isinstance(self.group, str) or not _GROUP_PATTERN.fullmatch(self.group):
            raise ValueError(
                "Tool group must match [a-z][a-z0-9_-]{0,47}."
            )
        if len(self.group) > MAX_TOOL_GROUP_LENGTH:
            raise ValueError(f"Tool group exceeds {MAX_TOOL_GROUP_LENGTH} characters.")
        self.parameters = normalise_parameters(self.parameters)

    def definition(self) -> dict[str, Any]:
        """Return the canonical model/external metadata without the callable."""
        return canonical_tool_definition(self)


__all__ = [
    "Tool",
    "canonical_tool_definition",
    "normalise_parameters",
    "MAX_PARAMETER_DESCRIPTION_LENGTH",
    "MAX_TOOL_DESCRIPTION_LENGTH",
    "MAX_TOOL_DISPLAY_NAME_LENGTH",
    "MAX_TOOL_GROUP_LENGTH",
]
