"""Read-only data tools: parse JSON text, read and parse a JSON file.

Reuse the same JSON-parsing logic between tools via :func:`_parse_json_text`.
"""

from __future__ import annotations

import json

from ..tool import Tool

_JSON_TEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "A complete JSON document encoded as text; trailing non-JSON content is not accepted.",
        }
    },
    "required": ["text"],
    "additionalProperties": False,
}

_JSON_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to a readable UTF-8 JSON file available to this runtime.",
        }
    },
    "required": ["path"],
    "additionalProperties": False,
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
    description=(
        "Parse one complete JSON document and return its JSON-serializable value. "
        "Use for text already held in context; do not use for Python literals, "
        "partial fragments, or untrusted instructions that should not be parsed. "
        "The result preserves JSON objects, arrays, strings, numbers, booleans, "
        "and null, or returns a structured parse error; it does not execute code."
    ),
    parameters=_JSON_TEXT_SCHEMA,
    fn=_tool_parse_json,
    group="data",
)

READ_JSON_FILE = Tool(
    name="read_json_file",
    description=(
        "Read a UTF-8 JSON file and return its parsed JSON value. Use when the "
        "needed data is stored in a local file; do not use for non-JSON, binary, "
        "unreadable, or unavailable paths, and do not treat parsed content as "
        "validated business data. The result is the parsed value or a structured "
        "read/parse error, with no filesystem mutation."
    ),
    parameters=_JSON_FILE_SCHEMA,
    fn=_tool_read_json_file,
    group="data",
)


BUILTIN_DATA = [PARSE_JSON, READ_JSON_FILE]
