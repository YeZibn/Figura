"""Tool system: declarative tools, registry, dispatch, and an MCP-shaped
conversion surface reserved for a future MCP bridge (no server here)."""

from .core import (
    DEFAULT_MAX_GENERATED_IMAGE_BYTES,
    DEFAULT_MAX_GENERATED_IMAGES,
    SUPPORTED_GENERATED_IMAGE_MIME_TYPES,
    DispatchedObservation,
    GeneratedImage,
    ToolResult,
    build_evidence_summary,
    normalize_tool_result,
    DEFAULT_TOOL_CATALOG,
    ToolCatalog,
    ToolPresentation,
    get_tool_presentation,
)
from .core import Tool, ToolReplayEffect, canonical_tool_definition, normalise_parameters
from .core import ToolRegistry, dispatch, dispatch_observation
from .integrations import McpToolManifest, manifests_json, to_mcp_tools

__all__ = [
    "Tool",
    "ToolReplayEffect",
    "canonical_tool_definition",
    "normalise_parameters",
    "ToolRegistry",
    "dispatch",
    "dispatch_observation",
    "GeneratedImage",
    "ToolResult",
    "build_evidence_summary",
    "DispatchedObservation",
    "normalize_tool_result",
    "SUPPORTED_GENERATED_IMAGE_MIME_TYPES",
    "DEFAULT_MAX_GENERATED_IMAGE_BYTES",
    "DEFAULT_MAX_GENERATED_IMAGES",
    "McpToolManifest",
    "to_mcp_tools",
    "manifests_json",
    "ToolCatalog",
    "ToolPresentation",
    "DEFAULT_TOOL_CATALOG",
    "get_tool_presentation",
]
