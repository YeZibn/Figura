"""Read-only filesystem tools: read a file, list a directory.

All tools are pure side-effect-free primitives. Failures are returned as
structured errors so they flow through dispatch's JSON result protocol.
"""

from __future__ import annotations

import json
import os

from ..tool import Tool

_PATH_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string", "description": "Filesystem path."}},
    "required": ["path"],
}


def _tool_read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return _error(f"read_file: {exc}")


def _tool_list_dir(path: str) -> list:
    try:
        return sorted(os.listdir(path))
    except OSError as exc:
        return _error(f"list_dir: {exc}")


def _error(message: str) -> str:
    """Structured, JSON-serializable error result matching dispatch protocol."""
    return json.dumps({"error": message}, ensure_ascii=False)


READ_FILE = Tool(
    name="read_file",
    description="Read a file at the given path and return its text content.",
    parameters=_PATH_SCHEMA,
    fn=_tool_read_file,
)

LIST_DIR = Tool(
    name="list_dir",
    description="List the entry names in the directory at the given path.",
    parameters=_PATH_SCHEMA,
    fn=_tool_list_dir,
)


BUILTIN_FILES = [READ_FILE, LIST_DIR]