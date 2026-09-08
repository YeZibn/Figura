"""Multimodal user content: local image files -> OpenAI content parts.

The configured endpoint is multimodal, but the agent pipeline is string-only.
This module closes that gap with one pure, stdlib-only builder: given a text
prompt and local image paths, produce the OpenAI content list

    [{"type": "text", ...},
     {"type": "image_url", "image_url": {"url": "data:<mime>;base64,<payload>"}}]

that ``Agent.run`` and the CLI can hand straight to the client. The client
forwards message content verbatim, so nothing else changes.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Sequence

# Explicit extension -> MIME map: mimetypes can be wrong or absent on some
# systems, and U0 only needs these formats anyway.
_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


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
