"""Immutable ordered registries for Figura tool definitions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any

from ..json_schema import (
    JsonValueError,
    SchemaDefinitionError,
    canonical_json_dumps,
    validate_schema_definition,
)
from .contracts import ToolDefinition, ToolDefinitionError
from .limits import (
    MAX_REGISTRY_BYTES,
    MAX_REGISTRY_VERSION_BYTES,
    MAX_TOOL_COUNT,
    MAX_TOOL_SCHEMA_BYTES,
)


class ToolRegistry:
    """A fixed definition set whose declaration order is model-facing order."""

    __slots__ = ("_version", "_definitions", "_by_name")

    def __init__(self, registry_version: str, definitions: Iterable[ToolDefinition]) -> None:
        if not isinstance(registry_version, str) or not registry_version:
            raise ToolDefinitionError("registry_version must be a non-empty string")
        try:
            version_size = len(registry_version.encode("utf-8"))
        except UnicodeEncodeError:
            raise ToolDefinitionError("registry_version must be valid UTF-8") from None
        if version_size > MAX_REGISTRY_VERSION_BYTES:
            raise ToolDefinitionError("registry_version exceeds its byte limit")

        ordered = tuple(definitions)
        if len(ordered) > MAX_TOOL_COUNT:
            raise ToolDefinitionError("registry contains too many tools")
        by_name: dict[str, ToolDefinition] = {}
        total_bytes = 0
        for definition in ordered:
            if not isinstance(definition, ToolDefinition):
                raise ToolDefinitionError("registry entries must be ToolDefinition values")
            if definition.name in by_name:
                raise ToolDefinitionError("registry tool names must be unique")
            by_name[definition.name] = definition
            total_bytes += len(definition.description.encode("utf-8"))
            for schema in (definition.parameters_schema, definition.result_schema):
                try:
                    validated = validate_schema_definition(schema, require_object=True)
                    serialized = canonical_json_dumps(validated).encode("utf-8")
                except (SchemaDefinitionError, JsonValueError):
                    raise ToolDefinitionError("registry schemas must be valid bounded object schemas") from None
                if len(serialized) > MAX_TOOL_SCHEMA_BYTES:
                    raise ToolDefinitionError("tool schema exceeds its byte limit")
                total_bytes += len(serialized)
            if total_bytes > MAX_REGISTRY_BYTES:
                raise ToolDefinitionError("registry schemas and descriptions exceed their total byte limit")

        object.__setattr__(self, "_version", registry_version)
        object.__setattr__(self, "_definitions", ordered)
        object.__setattr__(self, "_by_name", MappingProxyType(by_name))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ToolRegistry is immutable")

    @property
    def version(self) -> str:
        return self._version

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._definitions

    @property
    def by_name(self) -> Mapping[str, ToolDefinition]:
        return self._by_name

    def get(self, name: str) -> ToolDefinition | None:
        return self._by_name.get(name)

    def __getitem__(self, name: str) -> ToolDefinition:
        return self._by_name[name]

    def __iter__(self):
        return iter(self._definitions)

    def __len__(self) -> int:
        return len(self._definitions)
