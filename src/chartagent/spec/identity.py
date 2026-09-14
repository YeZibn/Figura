"""Stable identity helpers for chart specifications."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .chartspec import ChartSpec


def chart_spec_digest(spec: ChartSpec | Mapping[str, Any]) -> str:
    """Return a stable digest for the exact ChartSpec snapshot being rendered."""
    payload = spec.to_dict() if isinstance(spec, ChartSpec) else dict(spec)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["chart_spec_digest"]
