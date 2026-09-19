"""Stable identity helpers for chart specifications."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .chartspec import ChartSpec, ChartSpecCollection, ChartFigure


def _digest(payload: Mapping[str, Any]) -> str:
    """Return a stable digest for the exact ChartSpec snapshot being rendered."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def chart_spec_digest(spec: ChartSpec | Mapping[str, Any]) -> str:
    """Return a stable digest for the exact ChartSpec snapshot being rendered."""
    payload = spec.to_dict() if isinstance(spec, ChartSpec) else dict(spec)
    return _digest(payload)


def chart_figure_digest(figure: ChartFigure | Mapping[str, Any]) -> str:
    """Return a stable digest for one composite figure snapshot."""
    payload = figure.to_dict() if isinstance(figure, ChartFigure) else dict(figure)
    return _digest(payload)


def chart_collection_digest(collection: ChartSpecCollection | Mapping[str, Any]) -> str:
    """Return a stable digest for an ordered collection of figures."""
    payload = collection.to_dict() if isinstance(collection, ChartSpecCollection) else dict(collection)
    return _digest(payload)


__all__ = ["chart_spec_digest", "chart_figure_digest", "chart_collection_digest"]
