"""Generated-chart review gate constants and model context."""

from __future__ import annotations

import json
from typing import Any, Mapping

_BUDGET_MSG = "*stopped: max_steps reached*"
_REVIEW_REQUIRED_MSG = "*stopped: generated chart review incomplete*"
_REVIEW_FAILED_MSG = "*stopped: generated chart review failed; no artifact published*"
REVIEW_INCOMPLETE_MESSAGE = _REVIEW_REQUIRED_MSG


def review_gate_context(gate: Mapping[str, Any]) -> str:
    """Serialize bounded review obligations as model-visible JSON context."""
    pending = gate.get("pending")
    failed = gate.get("failed")
    published = gate.get("published")
    required_action = "review_pending_candidates" if pending else "correct_failed_candidates" if failed else "resolve_review_outcome"
    payload = {
        "type": "chart_review_gate",
        "required_action": required_action,
        "pending": list(pending) if isinstance(pending, list) else [],
        "failed": list(failed) if isinstance(failed, list) else [],
        "published": list(published) if isinstance(published, list) else [],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

__all__ = [
    "_BUDGET_MSG",
    "_REVIEW_REQUIRED_MSG",
    "_REVIEW_FAILED_MSG",
    "REVIEW_INCOMPLETE_MESSAGE",
    "review_gate_context",
]
