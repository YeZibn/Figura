"""Tool system: declarative tools, registry, dispatch, and an MCP-shaped
conversion surface reserved for a future MCP bridge (no server here)."""

from .mcp_converter import McpToolManifest, manifests_json, to_mcp_tools
from .presentation import DEFAULT_TOOL_CATALOG, ToolCatalog, ToolPresentation, get_tool_presentation
from .registry import ToolRegistry, dispatch, dispatch_observation
from .result import (
    DEFAULT_MAX_GENERATED_IMAGE_BYTES,
    DEFAULT_MAX_GENERATED_IMAGES,
    SUPPORTED_GENERATED_IMAGE_MIME_TYPES,
    DispatchedObservation,
    GeneratedImage,
    ToolResult,
    normalize_tool_result,
)
from .tool import Tool, canonical_tool_definition, normalise_parameters

__all__ = [
    "Tool",
    "canonical_tool_definition",
    "normalise_parameters",
    "ToolRegistry",
    "dispatch",
    "dispatch_observation",
    "GeneratedImage",
    "ToolResult",
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
