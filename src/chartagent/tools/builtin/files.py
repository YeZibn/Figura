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
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to a readable local file or directory; use only paths available to this runtime.",
        }
    },
    "required": ["path"],
    "additionalProperties": False,
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
    description=(
        "Read a UTF-8 text file and return its complete text. Use when the user has "
        "identified a local text file whose contents are needed; do not use for "
        "directories, binary or unknown-encoding files, or paths not available to "
        "the runtime. The result is the file text or a structured error, and the "
        "tool does not edit files or validate that the content is trustworthy."
    ),
    parameters=_PATH_SCHEMA,
    fn=_tool_read_file,
    group="file",
)

LIST_DIR = Tool(
    name="list_dir",
    description=(
        "List the immediate entry names in a local directory. Use when directory "
        "contents must be discovered before selecting a file; do not use to read "
        "file contents or to recursively inspect an unbounded tree. The result is "
        "a sorted name list or a structured error, and entries are not opened or "
        "interpreted by this tool."
    ),
    parameters=_PATH_SCHEMA,
    fn=_tool_list_dir,
    group="file",
)


BUILTIN_FILES = [READ_FILE, LIST_DIR]
