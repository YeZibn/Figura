"""Multimodal user content: local image files -> OpenAI content parts.

The configured endpoint is multimodal, but the agent pipeline is string-only.
This module closes that gap with stdlib-only builders that produce the OpenAI
content list from a text prompt and local image paths

    [{"type": "text", ...},
     {"type": "image_url", "image_url": {"url": "data:<mime>;base64,<payload>"}}]

that ``Agent.run`` and the CLI can hand straight to the client. The client
forwards message content verbatim, so nothing else changes.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .tools.core.result import GeneratedImage

# Explicit extension -> MIME map: mimetypes can be wrong or absent on some
# systems, and U0 only needs these formats anyway.
_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_TOOL_EVIDENCE_PREAMBLE = (
    "Tool-generated visual evidence follows. This is not a new user request. "
    "Inspect each image together with its structured tool result and decide "
    "freely whether to accept it, retry, use another tool, or answer."
)


@dataclass(frozen=True)
class ToolVisualEvidence:
    """A validated generated image attributed to one native tool call."""

    tool_name: str
    tool_call_id: str
    image: GeneratedImage


def _mime_for(path: Path) -> str | None:
    return _IMAGE_MIME_BY_SUFFIX.get(path.suffix.lower())


def build_user_content(text: str, image_paths: Sequence[str]) -> list[dict]:
    """Build an OpenAI multimodal content list: text part, then image parts.

    Images are attached in the order given. Each becomes a base64 data URL
    with a MIME type resolved from the file extension.

    Raises:
        FileNotFoundError: a path does not exist (or is not a file).
        ValueError: a path has no recognized image extension.
    """
    content: list[dict] = [{"type": "text", "text": text}]
    for raw in image_paths:
        path = Path(raw)
        if not path.is_file():
            raise FileNotFoundError(f"image not found: {raw}")
        mime = _mime_for(path)
        if mime is None:
            raise ValueError(f"not a recognized image type: {raw}")
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{payload}"},
            }
        )
    return content


def build_attachment_turn(text: str, image_paths: Sequence[str]) -> list[dict]:
    """Build a multimodal turn with model-visible local attachment paths.

    The numbered paths correspond to the image content parts in the same order,
    allowing path-based tools to address an attachment when the model chooses.
    """
    paths = list(image_paths)
    path_lines = [
        "Attached local image paths (matching image order):",
        *(f"{index}. {path}" for index, path in enumerate(paths, start=1)),
    ]
    path_block = "\n".join(path_lines)
    turn_text = f"{text}\n\n{path_block}" if text else path_block
    return build_user_content(turn_text, paths)


def build_registered_attachment_turn(text: str, attachments: Sequence[dict]) -> str:
    """Describe registered attachments without uploading bytes or local paths."""
    lines = ["Registered image attachments (load with load_image when useful):"]
    for index, item in enumerate(attachments, start=1):
        lines.append(
            f"{index}. attachment_id={item['attachment_id']}, filename={item['filename']}, "
            f"media_type={item['media_type']}, byte_count={item['byte_count']}"
        )
    metadata = "\n".join(lines)
    return f"{text}\n\n{metadata}" if text else metadata


def build_tool_observation_content(
    evidence: Sequence[ToolVisualEvidence],
) -> list[dict]:
    """Build a model-visible turn from validated in-memory tool images."""
    if not evidence:
        raise ValueError("at least one tool visual evidence item is required")

    content: list[dict] = [{"type": "text", "text": _TOOL_EVIDENCE_PREAMBLE}]
    for item in evidence:
        content.append(
            {
                "type": "text",
                "text": (
                    f"Tool: {item.tool_name}\n"
                    f"Tool call ID: {item.tool_call_id}\n"
                    f"Caption: {item.image.caption}"
                ),
            }
        )
        payload = base64.b64encode(item.image.content).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{item.image.media_type.lower()};base64,{payload}"
                },
            }
        )
    return content
