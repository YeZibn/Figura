"""Load and assemble Figura's four prompt layers.

Markdown is used for natural-language policy. Machine-facing tool schemas and
runtime state remain structured values and are rendered into bounded, clearly
marked context only at model-call time.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any

PROMPT_BUNDLE_ID = "figura-layered-agent"
PROMPT_BUNDLE_VERSION = "layered-v1"
PROMPT_LAYERS = (
    "static_responsibilities",
    "dynamic_tools",
    "process_artifacts",
    "run_turn_state",
)
_STATIC_ASSETS = (
    "static/agent.md",
    "static/evidence.md",
    "static/workflow.md",
    "static/response.md",
)
_MAX_TOOL_COUNT = 64
_MAX_ARTIFACT_COUNT = 48
_MAX_PANEL_COUNT = 32
_MAX_TEXT = 800
_PATH_PATTERN = re.compile(r"(?:/(?:Users|private|tmp|var|home|opt|etc)/|[A-Za-z]:\\)")


class PromptResourceError(ValueError):
    """Structured error raised when a prompt resource is not usable."""

    def __init__(self, code: str, resource: str, message: str) -> None:
        self.code = code
        self.resource = resource
        self.message = message
        super().__init__(f"{code}: {resource}: {message}")


@dataclass(frozen=True)
class PromptBundleMetadata:
    """Safe identity metadata for a prompt assembly trace."""

    bundle_id: str = PROMPT_BUNDLE_ID
    version: str = PROMPT_BUNDLE_VERSION
    layers: tuple[str, ...] = PROMPT_LAYERS

    def __post_init__(self) -> None:
        if len(set(self.layers)) != len(self.layers):
            raise PromptResourceError("duplicate_layer", "metadata", "layer identifiers must be unique")
        if set(self.layers) != set(PROMPT_LAYERS):
            raise PromptResourceError("invalid_layers", "metadata", "the four required layer identifiers are missing")

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_bundle_id": self.bundle_id,
            "prompt_bundle_version": self.version,
            "layers": list(self.layers),
        }


def _resource(relative_path: str):
    if not isinstance(relative_path, str) or not relative_path or relative_path.startswith("/"):
        raise PromptResourceError("invalid_resource", str(relative_path), "resource must be a relative package path")
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PromptResourceError("invalid_resource", relative_path, "resource path contains an invalid segment")
    return resources.files(__package__).joinpath("assets", *parts)


def load_prompt_asset(relative_path: str) -> str:
    """Read a non-empty UTF-8 Markdown resource from the installed package."""
    try:
        value = _resource(relative_path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PromptResourceError("missing_resource", relative_path, "prompt resource was not packaged") from exc
    except OSError as exc:
        raise PromptResourceError("unreadable_resource", relative_path, "prompt resource could not be read") from exc
    if not value.strip():
        raise PromptResourceError("empty_resource", relative_path, "prompt resource is empty")
    return value.strip()


def load_prompt_template(relative_path: str, **values: object) -> str:
    """Load a Markdown template and render only its declared placeholders."""
    template = load_prompt_asset(relative_path)
    try:
        rendered = template.format(**values)
    except (KeyError, ValueError, IndexError) as exc:
        raise PromptResourceError("template_error", relative_path, str(exc)) from exc
    if not rendered.strip():
        raise PromptResourceError("empty_rendered_resource", relative_path, "rendered prompt is empty")
    return rendered.strip()


def _bounded_text(value: object, limit: int = _MAX_TEXT) -> str:
    text = str(value or "").strip()
    text = _PATH_PATTERN.sub("[已脱敏路径]", text)
    return text[:limit]


def _safe_json(value: object, *, limit: int = 4_000) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return text[:limit]


def _bounded_list(value: object, limit: int = 16) -> list[object]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        return list(value)[:limit]  # type: ignore[arg-type]
    except TypeError:
        return []


def _bounded_ref_list(value: object, limit: int = 64) -> list[object]:
    """Keep compact evidence refs useful without exposing full sensor geometry."""
    result: list[object] = []
    for item in _bounded_list(value, limit):
        if isinstance(item, Mapping):
            safe: dict[str, Any] = {}
            for key in ("ref", "kind", "label", "color", "series_ref", "bbox_px"):
                if item.get(key) is None:
                    continue
                if key == "bbox_px" and isinstance(item.get(key), (list, tuple)):
                    safe[key] = list(item[key])[:4]
                elif key in {"ref", "kind", "label", "color", "series_ref"}:
                    safe[key] = _bounded_text(item.get(key), 120)
            if safe:
                result.append(safe)
        elif isinstance(item, str):
            result.append(_bounded_text(item, 32))
    return result


def _bounded_observation_scope(value: object) -> dict[str, Any] | None:
    """Keep the applied first-observation range visible without raw payloads."""
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for key in ("scope_id", "attachment_id", "panel_id", "coordinate_space", "status", "search_scope", "reason"):
        if value.get(key) is not None:
            result[key] = _bounded_text(value.get(key), 240)
    for key in ("applied", "requested"):
        if value.get(key) is not None:
            result[key] = bool(value.get(key)) if key == "applied" else value.get(key)
    for key in ("objectives",):
        if isinstance(value.get(key), (list, tuple)):
            result[key] = [_bounded_text(item, 96) for item in list(value[key])[:8]]
    for key in ("include", "exclude", "source_regions"):
        regions = value.get(key)
        if not isinstance(regions, (list, tuple)):
            continue
        bounded_regions: list[dict[str, Any]] = []
        for region in list(regions)[:16]:
            if not isinstance(region, Mapping):
                continue
            item = {name: region.get(name) for name in ("role", "label", "bbox_px", "bbox_source_px", "polygon_px", "polygon_source_px") if region.get(name) is not None}
            if item:
                bounded_regions.append(item)
        if bounded_regions:
            result[key] = bounded_regions
    return result or None


def _bounded_measurement_evidence(value: object) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Project the model-facing measurement decision state into bounded JSON."""
    if isinstance(value, (list, tuple)):
        result = []
        for item in list(value)[:16]:
            bounded = _bounded_measurement_evidence(item)
            if isinstance(bounded, Mapping):
                result.append(dict(bounded))
        return result or None
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for key in (
        "action",
        "status",
        "tool",
        "attachment_id",
        "panel_id",
        "session_id",
        "attempt_id",
        "parent_attempt_id",
        "next_action",
        "decision_status",
        "focus_mode",
        "budget_remaining",
        "evidence_basis",
    ):
        if value.get(key) is not None:
            result[key] = _bounded_text(value.get(key), 240)
    for key in ("selected_refs", "discarded_refs", "refs"):
        if value.get(key) is not None:
            result[key] = _bounded_ref_list(value.get(key))
    if isinstance(value.get("series_map"), Mapping):
        result["series_map"] = {
            _bounded_text(name, 80): _bounded_text(item, 120)
            for name, item in list(value["series_map"].items())[:32]
        }
    observation_scope = _bounded_observation_scope(value.get("observation_scope"))
    if observation_scope is not None:
        result["observation_scope"] = observation_scope
    for key in ("warnings", "issues"):
        if isinstance(value.get(key), (list, tuple)):
            result[key] = [
                _bounded_text(item.get("message") if isinstance(item, Mapping) else item, 240)
                for item in list(value[key])[:12]
            ]
    focus = value.get("focus")
    if isinstance(focus, Mapping):
        result["focus"] = {
            key: focus.get(key)
            for key in (
                "requested",
                "applied",
                "status",
                "mode",
                "target_refs",
                "search_scope",
                "region_px",
                "search_area",
            )
            if focus.get(key) is not None
        }
    suggestion = value.get("focus_suggestion")
    if suggestion is None:
        suggestion = value.get("repair_action")
    if isinstance(suggestion, Mapping):
        result["focus_suggestion"] = _bounded_measurement_target(suggestion)
    return result or None


def _bounded_measurement_repair(value: object) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Backward-compatible alias for persisted pre-decision state."""
    return _bounded_measurement_evidence(value)


def _bounded_measurement_target(value: Mapping[str, Any]) -> dict[str, Any]:
    target = value.get("target") if isinstance(value.get("target"), Mapping) else value
    safe_target: dict[str, Any] = {}
    for key in (
        "action",
        "status",
        "tool",
        "target_id",
        "panel_id",
        "parent_attempt_id",
        "region_kind",
        "reason",
        "fields",
        "refs",
        "mode",
        "bbox_source_px",
        "source_image_size",
        "bbox_px",
        "local_image_size",
        "clipped",
        "next_action",
        "budget_remaining",
    ):
        if target.get(key) is not None:
            safe_target[key] = (
                [_bounded_text(item, 96) for item in list(target[key])[:8]]
                if key in {"fields", "refs"} and isinstance(target[key], (list, tuple))
                else target[key]
            )
    if "tool" not in safe_target and value.get("tool") is not None:
        safe_target["tool"] = _bounded_text(value.get("tool"), 80)
    if "next_action" not in safe_target and value.get("next_action") is not None:
        safe_target["next_action"] = _bounded_text(value.get("next_action"), 240)
    return safe_target


def _bounded_generation_context(value: object) -> dict[str, Any] | None:
    """Keep one task contract visible without duplicating raw tool payloads."""
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for key in ("version", "mode", "selection_basis"):
        if value.get(key) is not None:
            result[key] = _bounded_text(value.get(key), 48)
    if value.get("goal_summary") is not None:
        result["goal_summary"] = _bounded_text(value.get("goal_summary"), 240)
    scope = value.get("source_scope")
    if isinstance(scope, Mapping):
        result["source_scope"] = {
            "attachment_id": _bounded_text(scope.get("attachment_id"), 96),
            "panel_ids": [_bounded_text(item, 96) for item in _bounded_list(scope.get("panel_ids"), 16)],
            "revision": scope.get("revision"),
        }
    coverage = value.get("coverage")
    if isinstance(coverage, Mapping):
        omitted = coverage.get("intentionally_omitted_series")
        if omitted is None:
            omitted = coverage.get("omitted_series")
        result["coverage"] = {
            "basis": _bounded_text(coverage.get("basis"), 48),
            "source_series": [_bounded_text(item, 120) for item in _bounded_list(coverage.get("source_series"), 64)],
            "represented_series": [_bounded_text(item, 120) for item in _bounded_list(coverage.get("represented_series"), 64)],
            "intentionally_omitted_series": [_bounded_text(item, 120) for item in _bounded_list(omitted, 64)],
            "status": _bounded_text(coverage.get("status"), 32),
        }
    return result or None


def _tool_record(tool: Any) -> dict[str, Any]:
    if isinstance(tool, Mapping):
        if isinstance(tool.get("function"), Mapping):
            function = tool["function"]
            return {
                "name": function.get("name"),
                "description": function.get("description"),
                "parameters": function.get("parameters"),
            }
        return {
            "name": tool.get("name"),
            "description": tool.get("description"),
            "parameters": tool.get("parameters", tool.get("inputSchema")),
        }
    definition = tool.definition() if callable(getattr(tool, "definition", None)) else {}
    return {
        "name": definition.get("name", getattr(tool, "name", None)),
        "description": definition.get("description", getattr(tool, "description", None)),
        "parameters": definition.get("parameters", getattr(tool, "parameters", None)),
        "group": getattr(tool, "group", "general"),
    }


def validate_tool_surface(tools: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    """Validate the bounded metadata projection used by Agent and MCP views."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in list(tools)[:_MAX_TOOL_COUNT]:
        item = _tool_record(tool)
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PromptResourceError("invalid_tool", "dynamic_tools", "tool name is missing")
        if name in seen:
            raise PromptResourceError("duplicate_tool", name, "tool name is duplicated")
        if not isinstance(item.get("parameters"), Mapping):
            raise PromptResourceError("invalid_tool_schema", name, "tool parameters must be an object schema")
        seen.add(name)
        result.append(item)
    return tuple(result)


def build_tool_surface(tools: Iterable[Any]) -> str:
    """Render the current registered tool surface as bounded Chinese Markdown."""
    records = validate_tool_surface(tools)
    if not records:
        return load_prompt_template("dynamic/tools.md", tool_surface="- 当前没有可调用工具。")
    blocks = [
        "当前工具面只来自本次 runtime 已注册且已授权的工具。工具名、参数名、枚举值和 JSON 字段是稳定协议；下面的中文说明不能扩展 Schema。"
    ]
    for item in records:
        schema = dict(item["parameters"])
        properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        parameter_names = ", ".join(f"`{name}`" for name in list(properties)[:32]) or "无"
        description = _bounded_text(item.get("description"), 1_200) or "未提供用途说明。"
        blocks.append(
            "\n".join(
                (
                    f"### `{item['name']}`",
                    f"- 用途与限制：{description}",
                    f"- 参数：{parameter_names}",
                    f"- 必填参数：{', '.join(f'`{name}`' for name in required[:32]) or '无'}",
                    f"- 原生 Schema：`{_safe_json(schema)}`",
                )
            )
        )
    return load_prompt_template("dynamic/tools.md", tool_surface="\n\n".join(blocks))


def panel_inventory_from_layout_contexts(layout_contexts: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal panel routing contexts into a safe model-visible inventory."""
    inventory: list[dict[str, Any]] = []
    seen: set[str] = set()
    for context in list(layout_contexts.values())[:_MAX_PANEL_COUNT]:
        panel = context.get("panel") if isinstance(context, Mapping) else None
        if not isinstance(panel, Mapping) or not isinstance(panel.get("id"), str):
            continue
        panel_id = str(panel["id"])
        if panel_id in seen:
            continue
        scope = context.get("analysis_scope") if isinstance(context, Mapping) else None
        validation = context.get("validation") if isinstance(context, Mapping) else None
        inventory.append(
            {
                "panel_id": panel_id,
                "name": _bounded_text(panel.get("name"), 160),
                "chart_type": _bounded_text(panel.get("chart_type"), 48),
                "source_attachment_id": _bounded_text(context.get("source_attachment_id"), 96),
                "scope": {
                    "bbox_px": list(scope.get("bbox_px", []))[:4] if isinstance(scope, Mapping) else [],
                    "status": validation.get("status") if isinstance(validation, Mapping) else "unknown",
                },
                "status": validation.get("status") if isinstance(validation, Mapping) else "unknown",
                "resource_ref": _bounded_text((panel.get("crop_ref") or {}).get("resourceKey"), 160)
                if isinstance(panel.get("crop_ref"), Mapping)
                else None,
            }
        )
        seen.add(panel_id)
    return inventory


def build_runtime_context(
    runtime_state: Mapping[str, Any] | None = None,
    *,
    panel_inventory: Iterable[Mapping[str, Any]] = (),
    review_gate: Mapping[str, Any] | None = None,
) -> str:
    """Render code-owned Run/Turn state and panel routing facts."""
    state = dict(runtime_state or {})
    safe_state = {
        "run_id": _bounded_text(state.get("run_id"), 96) or None,
        "phase": _bounded_text(state.get("phase"), 48) or "unknown",
        "active_source": [_bounded_text(item, 96) for item in _bounded_list(state.get("active_source"))],
        "selected_panel": state.get("selected_panel") if isinstance(state.get("selected_panel"), Mapping) else None,
        "current_tool": _bounded_text(state.get("current_tool"), 96) or None,
        "pending_action": _bounded_text(state.get("pending_action"), 160) or "等待模型决定下一步",
        "interrupted": bool(state.get("interrupted", False)),
        "recovery_status": _bounded_text(state.get("recovery_status"), 160) or "none",
        "retry_count": max(0, int(state.get("retry_count", 0) or 0)),
        "retry_budget": max(0, int(state.get("retry_budget", 0) or 0)),
        "publication_status": _bounded_text(state.get("publication_status"), 64) or "not_published",
        "measurement_evidence": _bounded_measurement_evidence(
            state.get("measurement_evidence", state.get("measurement_repair"))
        ),
        "generation_context": _bounded_generation_context(state.get("generation_context")),
    }
    inventory = [dict(item) for item in list(panel_inventory)[:_MAX_PANEL_COUNT] if isinstance(item, Mapping)]
    payload = {
        "state": safe_state,
        "panel_inventory": inventory,
        "review_gate": dict(review_gate) if isinstance(review_gate, Mapping) else {"status": "empty"},
    }
    return load_prompt_template("dynamic/runtime.md", runtime_summary=_safe_json(payload, limit=12_000))


def build_artifact_index(records: Iterable[Mapping[str, Any]] = ()) -> str:
    """Render a bounded attributable index without replacing native messages."""
    safe_records: list[dict[str, Any]] = []
    for record in list(records)[:_MAX_ARTIFACT_COUNT]:
        if not isinstance(record, Mapping):
            continue
        item = {
            "artifact_id": _bounded_text(record.get("artifact_id"), 128),
            "kind": _bounded_text(record.get("kind"), 48) or "unknown",
            "status": _bounded_text(record.get("status"), 64) or "unknown",
            "candidate_id": _bounded_text(record.get("candidate_id"), 160) or None,
            "candidate_attempt": record.get("candidate_attempt"),
            "parent_attempt": record.get("parent_attempt"),
            "generation_context": _bounded_generation_context(record.get("generation_context")),
            "coverage": _bounded_generation_context({"coverage": record.get("coverage")}).get("coverage")
            if isinstance(record.get("coverage"), Mapping)
            else None,
            "repair_kind": _bounded_text(record.get("repair_kind"), 32) or None,
            "repair_phase": _bounded_text(record.get("repair_phase"), 32) or None,
            "source_attachment_ids": [_bounded_text(value, 96) for value in _bounded_list(record.get("source_attachment_ids"))],
            "panel_ids": [_bounded_text(value, 96) for value in _bounded_list(record.get("panel_ids"), 32)],
            "lineage": [_bounded_text(value, 128) for value in _bounded_list(record.get("lineage"))],
            "confidence": record.get("confidence"),
            "warnings": [_bounded_text(value, 240) for value in _bounded_list(record.get("warnings"), 12)],
            "measurement_status": _bounded_text(record.get("measurement_status"), 48) or None,
            "measurement_reference": (
                {
                    key: _bounded_text(value, 160) if isinstance(value, str) else value
                    for key, value in record.get("measurement_reference", {}).items()
                    if key in {"session_id", "attempt_id", "attachment_id", "panel_id"}
                }
                if isinstance(record.get("measurement_reference"), Mapping)
                else None
            ),
            "measurement_issues": [
                {
                    key: _bounded_text(value, 240)
                    for key, value in issue.items()
                    if key in {"code", "location", "severity", "message", "next_action"}
                }
                for issue in _bounded_list(record.get("measurement_issues"), 8)
                if isinstance(issue, Mapping)
            ],
            "measurement_evidence_refs": _bounded_ref_list(record.get("measurement_evidence_refs"), 64),
            "measurement_selected_refs": [
                _bounded_text(value, 32) for value in _bounded_list(record.get("measurement_selected_refs"), 64)
            ],
            "measurement_discarded_refs": [
                _bounded_text(value, 32) for value in _bounded_list(record.get("measurement_discarded_refs"), 64)
            ],
            "measurement_decision_status": _bounded_text(record.get("measurement_decision_status"), 32) or None,
            "measurement_effective_scope": (
                dict(record.get("measurement_effective_scope"))
                if isinstance(record.get("measurement_effective_scope"), Mapping)
                else None
            ),
            "measurement_focus": (
                {
                    key: record.get("measurement_focus").get(key)
                    for key in ("requested", "applied", "status", "mode", "target_refs", "search_scope")
                    if record.get("measurement_focus").get(key) is not None
                }
                if isinstance(record.get("measurement_focus"), Mapping)
                else None
            ),
            "resource_refs": [
                {key: _bounded_text(value, 180) for key, value in ref.items() if key in {"resourceKey", "artifactKind", "mediaType"}}
                for ref in list(record.get("resource_refs") or [])[:8]
                if isinstance(ref, Mapping)
            ],
        }
        if item["artifact_id"]:
            safe_records.append(item)
    summary = _safe_json(safe_records, limit=16_000) if safe_records else "[]"
    return load_prompt_template("dynamic/artifacts.md", artifact_summary=summary)


def build_static_agent_prompt() -> str:
    """Load the stable four-part Chinese responsibility prompt."""
    metadata = PromptBundleMetadata()
    sections = [f"<!-- prompt_bundle={metadata.bundle_id}; version={metadata.version}; layer=static_responsibilities -->"]
    for asset in _STATIC_ASSETS:
        sections.append(load_prompt_asset(asset))
    return "\n\n".join(sections)


def build_reviewer_prompt() -> str:
    """Load the independent tool-free VLM reviewer contract."""
    return load_prompt_asset("reviewer/chart-review.md")


def prompt_trace_metadata(tools: Iterable[Any] = ()) -> dict[str, Any]:
    """Return bounded, redacted trace metadata for one assembled prompt."""
    records = validate_tool_surface(tools)
    metadata = PromptBundleMetadata().to_dict()
    metadata.update(
        {
            "tool_count": len(records),
            "tool_names": [str(item["name"])[:96] for item in records],
            "contains_user_content": False,
            "contains_local_paths": False,
        }
    )
    return metadata


def assemble_prompt_context(
    *,
    tools: Iterable[Any] = (),
    artifacts: Iterable[Mapping[str, Any]] = (),
    runtime_state: Mapping[str, Any] | None = None,
    panel_inventory: Iterable[Mapping[str, Any]] = (),
    review_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build all four logical layers and a transport-ready system string."""
    tool_list = list(tools)
    static = build_static_agent_prompt()
    tool_surface = build_tool_surface(tool_list)
    runtime = build_runtime_context(runtime_state, panel_inventory=panel_inventory, review_gate=review_gate)
    artifact_index = build_artifact_index(artifacts)
    dynamic = "\n\n".join((tool_surface, runtime, artifact_index))
    return {
        "metadata": prompt_trace_metadata(tool_list),
        "static": static,
        "tools": tool_surface,
        "runtime": runtime,
        "artifacts": artifact_index,
        "system": f"{static}\n\n{dynamic}",
    }


__all__ = [
    "PROMPT_BUNDLE_ID",
    "PROMPT_BUNDLE_VERSION",
    "PROMPT_LAYERS",
    "PromptBundleMetadata",
    "PromptResourceError",
    "assemble_prompt_context",
    "build_artifact_index",
    "build_reviewer_prompt",
    "build_runtime_context",
    "build_static_agent_prompt",
    "build_tool_surface",
    "load_prompt_asset",
    "load_prompt_template",
    "panel_inventory_from_layout_contexts",
    "prompt_trace_metadata",
    "validate_tool_surface",
]
