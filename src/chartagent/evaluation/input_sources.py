"""One-way filesystem input helpers for persisted Evaluation bundles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class EvaluationBundleSource:
    """Discover bundle roots and enforce bundle-relative file boundaries."""

    def __init__(self, data_root: str | Path) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.evaluations_root = self.data_root / "evaluations"

    def list_roots(self, *, limit: int) -> list[Path]:
        if not self.evaluations_root.is_dir():
            return []
        try:
            children = sorted(
                (path for path in self.evaluations_root.iterdir() if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )
        except OSError:
            return []
        return children[: max(0, int(limit))]

    def resolve_root(self, evaluation_id: str) -> Path | None:
        root = (self.evaluations_root / evaluation_id).resolve()
        try:
            root.relative_to(self.evaluations_root.resolve())
        except ValueError:
            return None
        return root if root.is_dir() else None

    @staticmethod
    def safe_file(root: Path, path: Path) -> Path | None:
        try:
            root_resolved = root.resolve()
            candidate = path if path.is_absolute() else root / path
            resolved = candidate.resolve()
            resolved.relative_to(root_resolved)
            return resolved
        except (OSError, ValueError):
            return None

    @staticmethod
    def read_json(path: Path, *, max_bytes: int) -> Any:
        if not path.is_file() or path.stat().st_size > max_bytes:
            raise OSError("evaluation file is unavailable")
        return json.loads(path.read_text(encoding="utf-8"))


__all__ = ["EvaluationBundleSource"]
