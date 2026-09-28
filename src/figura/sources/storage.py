"""Shared filesystem rules for private Figura image sources."""

from __future__ import annotations

from pathlib import Path


def ensure_private_directory(path: Path, name: str) -> None:
    if path.is_symlink():
        raise OSError(f"{name} directory cannot be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise OSError(f"{name} path is not a directory")
    path.chmod(0o700)
