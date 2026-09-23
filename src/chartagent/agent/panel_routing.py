"""Panel layout context recovery and scoped tool routing."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

MAX_LAYOUT_CONTEXTS = 32
GEOMETRY_TOOL_NAMES = frozenset(
    {"measure_bars", "extract_line_series", "extract_scatter_points", "extract_pie_slices"}
)
SCOPED_TOOL_NAMES = GEOMETRY_TOOL_NAMES | {"extract_text"}


def layout_arguments(
    tool_name: str,
    arguments: str,
    layout_contexts: dict[str, dict[str, Any]],
) -> str:
    """Inject one cached validated layout into a geometry call."""
    if tool_name not in GEOMETRY_TOOL_NAMES or not layout_contexts:
        return arguments
    try:
        parsed = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError:
        return arguments
    if not isinstance(parsed, dict) or parsed.get("layout_context") is not None:
        return arguments
    attachment_id = parsed.get("attachment_id")
    panel_id = parsed.get("panel_id")
    context = None
    if isinstance(attachment_id, str) and isinstance(panel_id, str) and panel_id:
        context = layout_contexts.get(f"{attachment_id}::{panel_id}")
    if context is None and isinstance(attachment_id, str):
        context = layout_contexts.get(attachment_id)
    if context is None and len(layout_contexts) == 1:
        context = next(iter(layout_contexts.values()))
    if context is None:
        return arguments
    parsed["layout_context"] = context
    # Keep the public call compatible with direct test/custom sensors; the
    # authorized adapter recovers the panel ID from the injected context.
    parsed.pop("panel_id", None)
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def panel_routing_error(
    tool_name: str,
    arguments: str,
    layout_contexts: dict[str, dict[str, Any]],
) -> str | None:
    """Reject an unresolved explicit panel route before sensor dispatch."""
    if tool_name not in SCOPED_TOOL_NAMES:
        return None
    try:
        parsed = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or "panel_id" not in parsed:
        return None
    panel_id = parsed.get("panel_id")
    attachment_id = parsed.get("attachment_id")
    if not isinstance(panel_id, str) or not panel_id.strip():
        return "panel routing failed: panel_id must be a non-empty stable identifier"
    if not isinstance(attachment_id, str) or not attachment_id.strip():
        return "panel routing failed: attachment_id is required with panel_id"
    key = f"{attachment_id}::{panel_id}"
    context = layout_contexts.get(key)
    if not isinstance(context, dict):
        return f"panel routing failed: {panel_id!r} is not registered for this attachment"
    scope = context.get("analysis_scope", context.get("panel_scope"))
    if not isinstance(scope, dict) or not isinstance(scope.get("bbox_px"), (list, tuple)):
        return f"panel routing failed: {panel_id!r} has no usable analysis scope"
    return None


def hydrate_persisted_panel_contexts(
    attachments: Any,
    layout_contexts: dict[str, dict[str, Any]],
    attachment_ids: Sequence[str],
) -> None:
    """Load durable panel scopes into this run's routing cache."""
    store = getattr(attachments, "panel_store", None)
    if store is None or not hasattr(store, "list_panel_handoffs"):
        return
    ids = tuple(attachment_ids)
    if not ids and hasattr(store, "get_active_source"):
        ids = tuple(getattr(store.get_active_source(), "attachment_ids", ()) or ())
    for attachment_id in ids[:16]:
        try:
            handoffs = store.list_panel_handoffs(attachment_id)
        except Exception:  # noqa: BLE001 - persisted routing is advisory
            continue
        for handoff in handoffs[:MAX_LAYOUT_CONTEXTS]:
            context = {
                "version": 1,
                "context_id": f"{handoff.panel_id}_layout",
                "source_attachment_id": handoff.attachment_id,
                "coordinate_system": "polar_2d" if handoff.chart_type == "pie" else "cartesian_2d" if handoff.role == "chart" or handoff.chart_type in {"bar", "line", "scatter"} else "unknown",
                "analysis_scope": {
                    "role": "panel_scope",
                    "bbox_px": list(handoff.analysis_scope),
                    "source_origin_px": list(handoff.source_origin),
                    "confidence": handoff.confidence,
                    "evidence": ["persisted_panel_handoff"],
                },
                "measurement_frame": None,
                "panel": {
                    "id": handoff.panel_id,
                    "name": handoff.name,
                    "source_bbox_px": list(handoff.source_bbox),
                    "scope_bbox_px": list(handoff.analysis_scope),
                },
                "validation": {
                    "status": "accepted" if handoff.status == "active" else "partial",
                    "accepted_for_analysis": handoff.status == "active",
                    "accepted_for_measurement": False,
                    "confidence": handoff.confidence,
                    "warnings": list(handoff.warnings),
                },
                "evidence": ["persisted_panel_handoff", "source_coordinates"],
            }
            layout_contexts[f"{attachment_id}::{handoff.panel_id}"] = context
            if len(layout_contexts) >= MAX_LAYOUT_CONTEXTS:
                return


def remember_layout_context(
    content: str,
    arguments: str,
    layout_contexts: dict[str, dict[str, Any]],
) -> None:
    """Cache validated layout contexts returned by decomposition tools."""
    try:
        payload = json.loads(content)
        parsed_arguments = json.loads(arguments) if arguments.strip() else {}
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(payload, dict) or not isinstance(parsed_arguments, dict):
        return
    attachment_id = parsed_arguments.get("attachment_id")
    if not isinstance(attachment_id, str) or not attachment_id:
        return
    data = payload.get("data")
    if not isinstance(data, dict):
        return
    if isinstance(data.get("panels"), list):
        for panel in data["panels"]:
            if not isinstance(panel, dict) or not isinstance(panel.get("id"), str):
                continue
            context = panel.get("layout_context")
            if not isinstance(context, dict):
                continue
            cached = dict(context)
            cached["source_attachment_id"] = attachment_id
            panel_summary = dict(cached.get("panel") or {})
            panel_summary.update(
                {
                    "id": panel["id"],
                    "name": panel.get("name"),
                    "chart_type": panel.get("chart_type"),
                }
            )
            cached["panel"] = panel_summary
            layout_contexts[f"{attachment_id}::{panel['id']}"] = cached
            while len(layout_contexts) > MAX_LAYOUT_CONTEXTS:
                layout_contexts.pop(next(iter(layout_contexts)))
        return
    context = data.get("layout_context")
    if not isinstance(context, dict):
        return
    cached = dict(context)
    cached["source_attachment_id"] = attachment_id
    layout_contexts[attachment_id] = cached
    while len(layout_contexts) > MAX_LAYOUT_CONTEXTS:
        layout_contexts.pop(next(iter(layout_contexts)))
