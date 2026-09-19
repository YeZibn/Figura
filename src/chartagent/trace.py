"""Bounded, provider-neutral execution traces for ChartAgent.

Trace events are deliberately separate from model messages. The event boundary
is also the sanitization boundary, so every renderer receives JSON-safe data
without credentials, raw binary payloads, or unbounded text.
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, IO, Mapping, Optional


@dataclass(frozen=True)
class TraceLimits:
    """Central limits applied to diagnostic content."""

    max_text: int = 2000
    max_reasoning: int = 4000
    max_arguments: int = 2000
    max_result: int = 4000
    max_caption: int = 500
    max_items: int = 32
    max_depth: int = 8


DEFAULT_TRACE_LIMITS = TraceLimits()
TRUNCATION_MARKER = "... [truncated]"
REDACTED_MARKER = "[REDACTED]"

# Key names are normalized before matching, so api_key, api-key, and apiKey
# all receive the same treatment.
_SENSITIVE_KEY = re.compile(
    r"(?:api|access|refresh)?(?:key|token|secret|password|credential)"
    r"|authorization|auth|cookie|privatekey|clientsecret"
)
_IMAGE_DATA_URL = re.compile(r"data:image/[^;\s]+;base64,[^\s]+", re.IGNORECASE)
_LOCAL_PATH = re.compile(r"(?:/(?:Users|private|tmp|var|home|opt|etc)/|[A-Za-z]:\\)")

TraceSink = Callable[["TraceEvent"], None]


def new_run_id() -> str:
    """Return a short opaque identifier suitable for terminal traces."""
    return uuid.uuid4().hex[:12]


def truncate_text(value: object, limit: int) -> str:
    """Return text bounded by ``limit`` with an explicit marker if needed."""
    text = value if isinstance(value, str) else str(value)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(TRUNCATION_MARKER):
        return TRUNCATION_MARKER[:limit]
    return text[: limit - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


def _normalized_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _is_sensitive_key(key: object) -> bool:
    normalized = _normalized_key(key)
    return normalized == "reasoningcontent" or bool(_SENSITIVE_KEY.search(normalized))


def _safe_string(value: str, limit: int) -> str:
    # A tool argument or provider field may contain a data URL even when it is
    # not nested under a clearly named image key.
    value = _IMAGE_DATA_URL.sub("[IMAGE_DATA_OMITTED]", value)
    value = _LOCAL_PATH.sub("[PATH_OMITTED]", value)
    return truncate_text(value, limit)


def _sanitize(value: object, limits: TraceLimits, *, depth: int = 0, key: object = None,
              text_limit: Optional[int] = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return REDACTED_MARKER
    if depth > limits.max_depth:
        return "[nested value omitted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _safe_string(value, text_limit or limits.max_text)
    if isinstance(value, bytes):
        return {"binary_omitted": True, "byte_count": len(value)}
    if isinstance(value, bytearray):
        return {"binary_omitted": True, "byte_count": len(value)}
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        items = list(value.items())
        for item_key, item_value in items[: limits.max_items]:
            output[str(item_key)] = _sanitize(
                item_value,
                limits,
                depth=depth + 1,
                key=item_key,
                text_limit=text_limit,
            )
        if len(items) > limits.max_items:
            output["_trace_items_truncated"] = True
        return output
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        output = [
            _sanitize(item, limits, depth=depth + 1, text_limit=text_limit)
            for item in items[: limits.max_items]
        ]
        if len(items) > limits.max_items:
            output.append("[items truncated]")
        return output
    return _safe_string(repr(value), text_limit or limits.max_text)


def sanitize_payload(payload: Mapping[str, Any], *, limits: TraceLimits = DEFAULT_TRACE_LIMITS) -> dict[str, Any]:
    """Recursively sanitize a payload before it reaches any trace sink."""
    value = _sanitize(payload, limits)
    return value if isinstance(value, dict) else {"value": value}


def bounded_reasoning(value: str, *, limits: TraceLimits = DEFAULT_TRACE_LIMITS) -> str:
    return _safe_string(value, limits.max_reasoning)


def summarize_arguments(arguments: str, *, limits: TraceLimits = DEFAULT_TRACE_LIMITS) -> Any:
    """Decode tool arguments when possible, while keeping malformed JSON visible."""
    try:
        parsed = json.loads(arguments) if arguments.strip() else {}
    except (TypeError, json.JSONDecodeError):
        return _safe_string(arguments, limits.max_arguments)
    return _sanitize(parsed, limits, text_limit=limits.max_arguments)


def summarize_result(content: str, *, limits: TraceLimits = DEFAULT_TRACE_LIMITS) -> Any:
    """Decode structured tool output and bound the resulting diagnostic data."""
    try:
        parsed = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return _safe_string(content, limits.max_result)
    return _sanitize(parsed, limits, text_limit=limits.max_result)


def summarize_images(images: object, *, limits: TraceLimits = DEFAULT_TRACE_LIMITS) -> list[dict[str, Any]]:
    """Summarize generated images without ever copying their bytes."""
    output: list[dict[str, Any]] = []
    for image in list(images or ())[: limits.max_items]:
        content = getattr(image, "content", None)
        media_type = getattr(image, "media_type", "")
        caption = getattr(image, "caption", "")
        output.append(
            {
                "media_type": _safe_string(str(media_type).lower(), limits.max_text),
                "caption": _safe_string(str(caption), limits.max_caption),
                "byte_count": len(content) if isinstance(content, (bytes, bytearray)) else None,
            }
        )
    if images is not None and len(list(images or ())) > limits.max_items:
        output.append({"_trace_items_truncated": True})
    return output


@dataclass(frozen=True)
class TraceEvent:
    """One ordered, JSON-serializable execution event."""

    kind: str
    run_id: str = ""
    turn: Optional[int] = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", sanitize_payload(self.payload))

    @property
    def event_type(self) -> str:
        """Compatibility alias for consumers that call the kind an event type."""
        return self.kind

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "run_id": self.run_id,
            "turn": self.turn,
            "sequence": self.sequence,
            "payload": dict(self.payload),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class TraceEmitter:
    """Create ordered events and forward them to an optional sink.

    Sink failures are intentionally isolated from the Agent path: diagnostics
    must not change model/tool behavior or turn termination.
    """

    def __init__(
        self,
        sink: Optional[TraceSink] = None,
        *,
        run_id: Optional[str] = None,
        limits: TraceLimits = DEFAULT_TRACE_LIMITS,
    ) -> None:
        self.sink = sink
        self.run_id = run_id or new_run_id()
        self.limits = limits
        self.sequence = 0

    def emit(
        self,
        kind: str,
        *,
        turn: Optional[int] = None,
        payload: Optional[Mapping[str, Any]] = None,
        **fields: Any,
    ) -> TraceEvent:
        event_payload = dict(payload or {})
        event_payload.update(fields)
        self.sequence += 1
        event = TraceEvent(
            kind=kind,
            run_id=self.run_id,
            turn=turn,
            sequence=self.sequence,
            payload=sanitize_payload(event_payload, limits=self.limits),
        )
        if self.sink is not None:
            try:
                if isinstance(self.sink, TraceEmitter):
                    self.sink.emit_event(event)
                else:
                    self.sink(event)
            except Exception:  # noqa: BLE001 - diagnostics cannot alter execution
                pass
        return event

    def emit_event(self, event: TraceEvent) -> None:
        if self.sink is None:
            return
        try:
            self.sink(event)
        except Exception:  # noqa: BLE001 - diagnostics cannot alter execution
            pass

    def __call__(self, event: TraceEvent) -> None:
        self.emit_event(event)


def _event_prefix(event: TraceEvent) -> str:
    turn = "-" if event.turn is None else str(event.turn)
    return f"[trace run={event.run_id} turn={turn} seq={event.sequence}]"


def _human_message(event: TraceEvent) -> str:
    payload = event.payload
    if event.kind == "model_started":
        return "model started " + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if event.kind == "model_completed":
        return "model completed " + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if event.kind == "reasoning":
        status = payload.get("status", "unavailable")
        return f"provider-returned reasoning ({status}): {payload.get('reasoning', '')}"
    if event.kind == "tool_call":
        return (
            f"tool call {payload.get('tool_name', '')} "
            f"id={payload.get('call_id', '')} args="
            f"{json.dumps(payload.get('arguments'), ensure_ascii=False, sort_keys=True)}"
        )
    if event.kind == "tool_result":
        return (
            f"tool result {payload.get('tool_name', '')} "
            f"id={payload.get('call_id', '')} status={payload.get('status', '')} "
            f"data={json.dumps(payload.get('result'), ensure_ascii=False, sort_keys=True)}"
        )
    if event.kind == "visual_observation":
        return "visual observation " + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if event.kind == "final_answer":
        return f"final answer: {payload.get('answer', '')}"
    if event.kind == "budget_exhausted":
        return "budget exhausted " + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return event.kind + " " + json.dumps(payload, ensure_ascii=False, sort_keys=True)


class TextTraceRenderer:
    """Render one human-readable event per line, normally to stderr."""

    def __init__(self, stream: Optional[IO[str]] = None) -> None:
        self.stream = stream or sys.stderr

    def __call__(self, event: TraceEvent) -> None:
        print(f"{_event_prefix(event)} {_human_message(event)}", file=self.stream, flush=True)


class JsonlTraceRenderer:
    """Render one sanitized JSON event per line."""

    def __init__(self, stream: Optional[IO[str]] = None) -> None:
        self.stream = stream or sys.stderr

    def __call__(self, event: TraceEvent) -> None:
        print(event.to_json(), file=self.stream, flush=True)


# Short aliases make the sink role clear to callers without breaking the
# renderer names used in documentation and tests.
TextTraceSink = TextTraceRenderer
JsonlTraceSink = JsonlTraceRenderer


__all__ = [
    "DEFAULT_TRACE_LIMITS",
    "JsonlTraceRenderer",
    "JsonlTraceSink",
    "REDACTED_MARKER",
    "TRUNCATION_MARKER",
    "TextTraceRenderer",
    "TextTraceSink",
    "TraceEmitter",
    "TraceEvent",
    "TraceLimits",
    "TraceSink",
    "bounded_reasoning",
    "new_run_id",
    "sanitize_payload",
    "summarize_arguments",
    "summarize_images",
    "summarize_result",
    "truncate_text",
]
