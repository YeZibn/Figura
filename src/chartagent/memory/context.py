"""Deterministic, protocol-safe context reconstruction."""

from __future__ import annotations

import json
from typing import Any, Iterable

from .models import Record, Run, RunStatus

SENSITIVE_KEYS = frozenset({"reasoning", "raw", "raw_response", "credentials", "api_key", "authorization", "image_bytes", "data_url"})


def sanitize_payload(payload: Any, *, limit: int = 12000) -> Any:
    if isinstance(payload, dict):
        clean = {}
        for key, value in payload.items():
            lower = str(key).lower()
            if lower in SENSITIVE_KEYS:
                continue
            if lower in {"url", "uri"} and isinstance(value, str) and value.startswith("data:"):
                clean[str(key)] = "[image content omitted from memory]"
                continue
            # Tool messages carry JSON text. Truncating that text as a plain
            # string can create unmatched braces and invalid provider input.
            if str(key) == "message" and isinstance(value, dict) and value.get("role") == "tool":
                message = sanitize_payload(value, limit=limit)
                content = value.get("content")
                if isinstance(content, str) and len(content) > limit:
                    try:
                        parsed = json.loads(content)
                    except json.JSONDecodeError:
                        parsed = {"truncated": True, "preview": content[: max(0, limit // 2)]}
                    message["content"] = _bounded_json(parsed, limit)
                clean[str(key)] = message
            else:
                clean[str(key)] = sanitize_payload(value, limit=limit)
        return clean
    if isinstance(payload, (list, tuple)):
        return [sanitize_payload(v, limit=limit) for v in payload[:100]]
    if isinstance(payload, str):
        if payload.startswith("data:"):
            return "[binary content omitted from memory]"
        return payload if len(payload) <= limit else payload[:max(0, limit - 17)] + "... [truncated]"
    if isinstance(payload, (int, float, bool)) or payload is None:
        return payload
    return str(payload)[:limit]


def _bounded_json(value: Any, limit: int) -> str:
    """Return valid JSON with an explicit marker under the requested bound."""
    candidate = sanitize_payload(value, limit=limit)
    encoded = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) <= limit:
        return encoded
    return json.dumps({"truncated": True, "original_type": type(value).__name__}, ensure_ascii=False, separators=(",", ":"))


def json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def records_to_messages(records: Iterable[Record]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for record in records:
        message = record.payload.get("message")
        if isinstance(message, dict) and message.get("role") in {"user", "assistant", "tool", "system"}:
            messages.append(sanitize_payload(message))
    return messages


def recovery_messages(state: dict[str, Any] | None, *, budget: int = 24000) -> list[dict[str, Any]]:
    """Read only an explicitly supplied checkpoint context.

    Interrupted runs are intentionally absent from ``build_context``.  This
    separate API makes the authorization boundary visible to callers and
    keeps recovery from accidentally becoming ordinary conversation history.
    """
    if not isinstance(state, dict):
        return []
    raw = state.get("messages")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    used = 0
    for item in raw[:48]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant", "tool", "system"}:
            continue
        clean = sanitize_payload(item)
        size = json_size(clean)
        if used + size > max(1024, budget):
            break
        result.append(clean)
        used += size
    return result


def summarize_run(run: Run, *, limit: int = 1200) -> dict[str, Any]:
    user = ""
    terminal = ""
    tools: list[str] = []
    statuses: list[str] = []
    attachments: list[str] = []
    for record in run.records:
        payload = record.payload
        if record.kind == "user": user = str(payload.get("text", payload.get("message", "")))
        if record.kind in {"tool_call", "tool_result"}:
            if payload.get("tool_name"): tools.append(str(payload["tool_name"]))
            if payload.get("status"): statuses.append(str(payload["status"]))
        if record.kind == "attachment" and payload.get("attachment_id"): attachments.append(str(payload["attachment_id"]))
        if record.kind in {"final", "terminal"}: terminal = str(payload.get("answer", payload.get("text", "")))
    summary = {"run_id": run.id, "user": user, "tools": tools, "statuses": statuses, "attachments": attachments, "terminal": terminal}
    if len(json.dumps(summary, ensure_ascii=False, sort_keys=True)) > limit:
        summary["user"] = user[:200]
        summary["terminal"] = terminal[:200]
        summary["truncated"] = True
    return summary


def build_context(system: dict[str, Any] | None, completed_runs: list[Run], current_records: list[Record], *, current_messages: list[dict[str, Any]] | None = None, budget: int = 24000) -> list[dict[str, Any]]:
    # The active turn is recovery-critical. Reserve it before selecting older
    # runs so history can never crowd out the request currently being answered.
    result: list[dict[str, Any]] = [system] if system else []
    active = current_messages if current_messages is not None else records_to_messages(current_records)
    active_size = json_size(active)
    used = json_size(result) + active_size
    selected: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for run in reversed([r for r in completed_runs if r.status == RunStatus.COMPLETED]):
        messages = records_to_messages(run.records)
        if used + json_size(messages) <= budget:
            selected = messages + selected
            used += json_size(messages)
        else:
            summaries.insert(0, summarize_run(run))
    if summaries:
        result.append({"role": "system", "content": "Prior completed runs (deterministic summary): " + json.dumps(summaries, ensure_ascii=False, sort_keys=True)})
    result.extend(selected)
    result.extend(active)
    return result
