"""Bounded attachment metadata helpers."""

from __future__ import annotations

from typing import Any

from ..memory.models import Attachment


def attachment_metadata(item: Attachment) -> dict[str, Any]:
    """Return the persisted, path-free metadata representation."""
    return item.metadata()


__all__ = ["attachment_metadata"]
