"""Load the ordered, stable Chinese Agent prompt assets."""

from __future__ import annotations

from importlib import resources

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
    return InstructionBlock(InstructionRole.SYSTEM, "\n\n".join(sections))


def build_compaction_instruction() -> InstructionBlock:
    """Load the isolated summary task without ordinary Agent workflow rules."""
    return InstructionBlock(InstructionRole.SYSTEM, _load_asset("compaction.md"))
