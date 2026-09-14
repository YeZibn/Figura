"""Observation status helpers used by the Agent loop."""

import json


def observation_status(content: str) -> str:
    """Classify a structured observation for tracing."""
    try:
        parsed = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return "success"
    return "error" if isinstance(parsed, dict) and "error" in parsed else "success"


__all__ = ["observation_status"]
