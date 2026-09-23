"""Bounded operation, checkpoint, interruption, and resume helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable, Optional

from ..client.models import NormalizedResult, ToolCall
from ..measurement import (
    MeasurementSession,
    sessions_to_state,
)
from ..memory import RunStatus
from .measurement_flow import (
    measurement_repair_contexts_from_sessions,
    merge_measurement_repair_contexts,
)


class AgentInterrupted(RuntimeError):
    """Raised when a cooperative run interruption is observed."""


class AgentRecoveryBlocked(RuntimeError):
    """Raised when a continuation reaches an operation with an unknown outcome."""


def begin_work_unit(
    callback: Callable[..., dict[str, Any]] | None,
    operation_id: str,
    operation_kind: str,
) -> dict[str, Any]:
    """Start one idempotent operation journal entry."""
    if callback is None:
        return {"operationId": operation_id, "state": "in_flight"}
    try:
        result = callback(operation_id, operation_kind)
        return result if isinstance(result, dict) else {"operationId": operation_id, "state": "in_flight"}
    except Exception:  # noqa: BLE001 - journaling remains a bounded diagnostic
        return {"operationId": operation_id, "state": "in_flight"}


def complete_work_unit(
    callback: Callable[..., dict[str, Any] | None] | None,
    uncertain_callback: Callable[..., dict[str, Any] | None] | None,
    operation_id: str,
    operation_kind: str,
    result: dict[str, Any] | None = None,
    references: dict[str, Any] | None = None,
) -> None:
    """Complete one operation, preserving the old persistence-failure fallback."""
    if callback is None:
        return
    try:
        callback(operation_id, result=result, references=references)
    except Exception:  # noqa: BLE001 - trace persistence cannot stop the Agent
        uncertain_work_unit(
            uncertain_callback,
            operation_id,
            f"{operation_kind}_persistence_failed",
        )


def uncertain_work_unit(
    callback: Callable[..., dict[str, Any] | None] | None,
    operation_id: str,
    reason: str,
) -> None:
    """Mark an operation uncertain without allowing recovery bookkeeping to abort the run."""
    if callback is None:
        return
    try:
        callback(operation_id, reason=reason)
    except Exception:  # noqa: BLE001 - bounded recovery fallback
        pass


def checkpoint(
    checkpoint_sink: Callable[..., bool] | None,
    review_manager: Any,
    run: Any,
    *,
    state: dict[str, Any],
    phase: str,
    next_action: str,
) -> bool | None:
    """Persist a bounded checkpoint with the sole canonical review snapshot."""
    if checkpoint_sink is None:
        return None
    try:
        checkpoint_state = dict(state)
        checkpoint_state.setdefault("phase", phase)
        checkpoint_state["nextAction"] = next_action
        if hasattr(run, "id"):
            checkpoint_state["reviewState"] = review_manager.to_state(run.id)
        return bool(checkpoint_sink(checkpoint_state, phase=phase, next_action=next_action))
    except Exception:  # noqa: BLE001 - checkpoint failure is surfaced as unavailable metadata
        return False


def checkpoint_state(
    user_input: str | list[dict],
    messages: Sequence[dict[str, Any]],
    layout_contexts: dict[str, dict[str, Any]],
    attachment_ids: Sequence[str],
    turn: int,
    *,
    pending_tool_calls: Sequence[ToolCall],
    pending_answer: str | None = None,
    visual_references: Sequence[dict[str, Any]] = (),
    artifact_records: Sequence[dict[str, Any]] = (),
    measurement_sessions: Mapping[str, MeasurementSession] | None = None,
    pending_measurement_repairs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the stable JSON-compatible checkpoint projection."""
    repairs = (
        merge_measurement_repair_contexts(pending_measurement_repairs)
        if pending_measurement_repairs is not None
        else measurement_repair_contexts_from_sessions(measurement_sessions or {})
    )
    result: dict[str, Any] = {
        "prompt": user_input if isinstance(user_input, str) else "[image attachment turn]",
        "messages": list(messages),
        "layoutContexts": layout_contexts,
        "attachmentIds": list(attachment_ids),
        "currentTurn": turn,
        "pendingToolCalls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in pending_tool_calls
        ],
        "visualReferences": list(visual_references)[:32],
        "artifactIndex": list(artifact_records)[:48],
        "measurementSessions": sessions_to_state(measurement_sessions or {}),
        "pendingMeasurementRepairs": repairs,
        # Keep the old field as a compatibility projection for older
        # reconnect consumers. Never choose one action when there are
        # multiple pending panels.
        "pendingMeasurementRepair": repairs[0] if len(repairs) == 1 else None,
    }
    if pending_answer is not None:
        result["pendingAnswer"] = pending_answer
    return result


def model_result_payload(result: NormalizedResult) -> dict[str, Any]:
    """Project a model result into the bounded operation journal shape."""
    return {
        "content": result.content,
        "finishReason": result.finish_reason,
        "toolCalls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in result.tool_calls
        ],
    }


def recovery_tool_calls(recovery: Optional[dict[str, Any]]) -> list[ToolCall]:
    """Recover only valid, bounded pending tool calls from a checkpoint."""
    if not isinstance(recovery, dict) or recovery.get("nextAction") not in {"tool", "dispatch_tool", "review"}:
        return []
    raw = recovery.get("pendingToolCalls")
    if not isinstance(raw, list):
        return []
    calls: list[ToolCall] = []
    for item in raw[:16]:
        if not isinstance(item, dict):
            continue
        if not all(isinstance(item.get(key), str) and item.get(key) for key in ("id", "name", "arguments")):
            continue
        calls.append(ToolCall(item["id"], item["name"], item["arguments"]))
    return calls


def interruption_requested(event: Any) -> bool:
    """Read a cooperative interruption source without propagating its errors."""
    if event is None:
        return False
    if callable(event):
        try:
            return bool(event())
        except Exception:  # noqa: BLE001 - cancellation must remain best effort
            return False
    is_set = getattr(event, "is_set", None)
    return bool(is_set()) if callable(is_set) else bool(event)


def raise_if_interrupted(event: Any, memory: Any, run: Any) -> None:
    """Finish the run as interrupted and raise the public interruption error."""
    if not interruption_requested(event):
        return
    try:
        memory.finish(run, RunStatus.INTERRUPTED, "interrupted")
    finally:
        raise AgentInterrupted("Agent run was interrupted")
