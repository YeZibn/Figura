"""Load the ordered, stable Chinese Agent prompt assets."""

from __future__ import annotations

from importlib import resources

from figura.providers import InstructionBlock, InstructionRole


_STATIC_ASSETS = ("agent.md", "evidence.md", "workflow.md", "response.md")


def build_static_instruction() -> InstructionBlock:
    sections = []
    for asset in _STATIC_ASSETS:
        content = (
            resources.files(__package__)
            .joinpath("assets", asset)
            .read_text(encoding="utf-8")
            .strip()
        )
        if not content:
            raise RuntimeError(f"Figura prompt asset is empty: {asset}")
        sections.append(content)
    return InstructionBlock(InstructionRole.SYSTEM, "\n\n".join(sections))
