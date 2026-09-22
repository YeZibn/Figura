"""Generated-chart review gate constants and model context."""

from __future__ import annotations

import json
from typing import Any, Mapping

_BUDGET_MSG = "*stopped: max_steps reached*"
_REVIEW_REQUIRED_MSG = "*stopped: generated chart review incomplete*"
_REVIEW_FAILED_MSG = "*stopped: generated chart review failed; no artifact published*"
REVIEW_INCOMPLETE_MESSAGE = _REVIEW_REQUIRED_MSG


def review_gate_context(gate: Mapping[str, Any]) -> str:
    """Serialize bounded review facts as model-visible JSON context.

    A failed review blocks publication, but it does not prescribe a single
    repair action.  Keep the candidate identity, scope-bearing metadata and
    diagnostic hints visible while leaving the next authorized tool choice to
    the main Agent.
    """
    pending = gate.get("pending")
    failed = gate.get("failed")
    published = gate.get("published")
    retryable = bool(gate.get("retryable"))
    status = "reviewing" if pending else "repair_available" if failed and retryable else "terminal" if failed else "open"
    payload = {
        "type": "chart_review_gate",
        "status": status,
        "publication_blocked": bool(pending or failed),
        "pending": list(pending)[:8] if isinstance(pending, list) else [],
        "failed": list(failed)[:8] if isinstance(failed, list) else [],
        "published": list(published)[:8] if isinstance(published, list) else [],
        "retryable": retryable,
        "repair_hints": list(gate.get("recoveryActions", ()))[:8] if isinstance(gate.get("recoveryActions"), list) else [],
    }
    if isinstance(gate.get("recoveryActions"), list) and gate.get("recoveryActions"):
        first_action = gate["recoveryActions"][0]
        if isinstance(first_action, Mapping):
            payload["repair_kind"] = str(first_action.get("repairKind") or "terminal")[:32]
            payload["repair_hint"] = str(first_action.get("action") or "")[:160] or None
            payload["repair_target"] = first_action.get("target") if isinstance(first_action.get("target"), Mapping) else None
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

__all__ = [
    "_BUDGET_MSG",
    "_REVIEW_REQUIRED_MSG",
    "_REVIEW_FAILED_MSG",
    "REVIEW_INCOMPLETE_MESSAGE",
    "review_gate_context",
]
