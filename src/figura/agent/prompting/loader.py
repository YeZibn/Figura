"""Load the ordered, stable Chinese Agent prompt assets."""

from __future__ import annotations

from importlib import resources
import re

from figura.providers import InstructionBlock, InstructionRole


_STATIC_ASSETS = ("agent.md", "evidence.md", "workflow.md", "response.md")


class PromptAssetError(RuntimeError):
    """A packaged prompt asset is missing, unreadable, or empty."""


def _load_asset(asset: str) -> str:
    try:
        content = (
            resources.files(__package__)
            .joinpath("assets", asset)
            .read_text(encoding="utf-8")
            .strip()
        )
    except (OSError, UnicodeError):
        raise PromptAssetError(f"Figura prompt asset cannot be read: {asset}") from None
    if not content:
        raise PromptAssetError(f"Figura prompt asset is empty: {asset}")
    return content


def build_static_instruction() -> InstructionBlock:
    sections = [_load_asset(asset) for asset in _STATIC_ASSETS]
    feedback, _cues = load_image_feedback()
    sections.append(feedback)
    return InstructionBlock(InstructionRole.SYSTEM, "\n\n".join(sections))


def load_image_feedback() -> tuple[str, dict[str, str]]:
    """Validate the closed Markdown contract and return its per-image cues."""
    content = _load_asset("image_feedback.md")
    parts = re.split(r"^## (.+)$", content, flags=re.MULTILINE)
    expected = ("Common", "Original", "OCR", "Measurement", "Rendered")
    if tuple(parts[1::2]) != expected:
        raise PromptAssetError("image_feedback.md requires ordered, unique feedback sections")
    cues: dict[str, str] = {}
    for heading, body in zip(parts[1::2], parts[2::2]):
        if heading == "Common":
            if not body.strip() or re.search(r"^### ", body, re.MULTILINE):
                raise PromptAssetError("image_feedback.md requires nonempty Common rules")
            continue
        segments = re.split(r"^### (.+)$", body, flags=re.MULTILINE)
        if (
            segments[0].strip()
            or tuple(segments[1::2]) != ("Rules", "Cue")
            or any(not value.strip() for value in segments[2::2])
        ):
            raise PromptAssetError("image_feedback.md requires nonempty Rules and Cue")
        cues[heading.lower()] = segments[4].strip()
    return content, cues


def build_compaction_instruction() -> InstructionBlock:
    """Load the isolated summary task without ordinary Agent workflow rules."""
    return InstructionBlock(InstructionRole.SYSTEM, _load_asset("compaction.md"))
