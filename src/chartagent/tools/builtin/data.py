"""Read-only data tools: parse JSON text, read and parse a JSON file.

Reuse the same JSON-parsing logic between tools via :func:`_parse_json_text`.
"""

from __future__ import annotations

import json

from ..tool import Tool

_JSON_TEXT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string", "description": "JSON text to parse."}},
    "required": ["text"],
}

_JSON_FILE_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string", "description": "Path to a JSON file."}},
    "required": ["path"],
}


def _error(message: str) -> str:
    """Structured, JSON-serializable error result matching dispatch protocol."""
    return json.dumps({"error": message}, ensure_ascii=False)


def _parse_json_text(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        return _error(f"parse_json: {exc}")


def _tool_parse_json(text: str):
    return _parse_json_text(text)


def _tool_read_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return _error(f"read_json_file: {exc}")
    return _parse_json_text(content)


PARSE_JSON = Tool(
    name="parse_json",
    description="Parse a JSON string into JSON-serializable data.",
    parameters=_JSON_TEXT_SCHEMA,
    fn=_tool_parse_json,
)

READ_JSON_FILE = Tool(
    name="read_json_file",
    description="Read a JSON file at the given path and return its parsed data.",
    parameters=_JSON_FILE_SCHEMA,
    fn=_tool_read_json_file,
)


BUILTIN_DATA = [PARSE_JSON, READ_JSON_FILE]