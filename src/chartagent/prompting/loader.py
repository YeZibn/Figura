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
_MAX_ARTIFACT_SUMMARY_CHARS = 16_000
_MAX_COMPACT_ARTIFACT_SUMMARY_CHARS = 32_000
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
            for key in ("ref", "kind", "label", "color", "series_ref", "bbox_px", "has_numeric_value"):
                if item.get(key) is None:
                    continue
                if key == "bbox_px" and isinstance(item.get(key), (list, tuple)):
                    safe[key] = list(item[key])[:4]
                elif key == "has_numeric_value":
                    safe[key] = bool(item.get(key))
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
    """Project current candidate results and source facts into bounded JSON."""
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
    for key in ("status", "tool", "attachment_id", "panel_id", "parent_attempt_id"):
        if value.get(key) is not None:
            result[key] = _bounded_text(value.get(key), 240)
    measurement_ref = value.get("measurement_ref")
    if isinstance(measurement_ref, Mapping):
        result["measurement_ref"] = {
            key: _bounded_text(measurement_ref.get(key), 160) if isinstance(measurement_ref.get(key), str) else None
            for key in ("session_id", "attempt_id", "attachment_id", "panel_id")
            if measurement_ref.get(key) is not None
        }
    result["evidence_refs"] = _bounded_ref_list(value.get("evidence_refs"), 64)
    result["series_metadata"] = _bounded_ref_list(value.get("series_metadata"), 64)
    for key in ("scope", "effective_scope"):
        if isinstance(value.get(key), Mapping):
            result[key] = {
                _bounded_text(name, 64): (
                    _bounded_text(item, 160)
                    if isinstance(item, str)
                    else list(item)[:16]
                    if isinstance(item, (list, tuple))
                    else item
                )
                for name, item in list(value[key].items())[:16]
                if isinstance(name, str) and isinstance(item, (str, int, float, bool, list, tuple))
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
    return result or None


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


def _bounded_decision_context(value: object) -> dict[str, Any] | None:
    """Project factual decision context without ordinary action whitelists."""
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for key in ("unit_id", "unit_type", "phase", "status"):
        if value.get(key) is not None:
            result[key] = _bounded_text(value.get(key), 240)
    for key in ("hard_constraints",):
        if isinstance(value.get(key), (list, tuple)):
            result[key] = [_bounded_text(item, 96) for item in list(value[key])[:12]]
    verification = value.get("verification")
    if isinstance(verification, Mapping):
        result["verification"] = _bounded_verification(verification)
    if value.get("budget_remaining") is not None:
        try:
            result["budget_remaining"] = max(0, int(value.get("budget_remaining") or 0))
        except (TypeError, ValueError):
            result["budget_remaining"] = 0
    scope = value.get("scope")
    if isinstance(scope, Mapping):
        result["scope"] = {
            "panel_id": _bounded_text(scope.get("panel_id"), 96) or None,
            "attachment_ids": [
                _bounded_text(item, 96)
                for item in _bounded_list(scope.get("attachment_ids"), 16)
            ],
        }
    evidence = _bounded_measurement_evidence(value.get("evidence"))
    if evidence is not None:
        result["evidence"] = evidence
    generation_context = _bounded_generation_context(value.get("generation_context"))
    if generation_context is not None:
        result["generation_context"] = generation_context
    return result or None


def _bounded_verification(value: Mapping[str, Any]) -> dict[str, Any]:
    issues = value.get("issues") if isinstance(value.get("issues"), list) else []
    checks = value.get("checks") if isinstance(value.get("checks"), Mapping) else {}
    return {
        "verification_ref": _bounded_text(value.get("verificationRef"), 160),
        "staged_ref": _bounded_text(value.get("stagedRef"), 160),
        "status": _bounded_text(value.get("status"), 48),
        "checks": {str(key)[:64]: _bounded_text(item, 32) for key, item in list(checks.items())[:16]},
        "issues": [
            {key: _bounded_text(issue.get(key), 240) for key in ("code", "location", "message", "severity") if issue.get(key) is not None}
            for issue in issues[:8] if isinstance(issue, Mapping)
        ],
    }


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
        "retry_budget": max(0, int(state.get("retry_budget", 0) or 0)),
        "measurement_evidence": _bounded_measurement_evidence(
            state.get("measurement_evidence")
        ),
        "generation_context": _bounded_generation_context(state.get("generation_context")),
        "decision_context": _bounded_decision_context(state.get("decision_context")),
    }
    inventory = [dict(item) for item in list(panel_inventory)[:_MAX_PANEL_COUNT] if isinstance(item, Mapping)]
    payload = {
        "state": safe_state,
        "panel_inventory": inventory,
    }
    return load_prompt_template("dynamic/runtime.md", runtime_summary=_safe_json(payload, limit=12_000))


def build_artifact_index(records: Iterable[Mapping[str, Any]] = ()) -> str:
    """Render bounded staged-chart, verification, and measurement facts."""
    safe_records: list[dict[str, Any]] = []
    for record in list(records)[:_MAX_ARTIFACT_COUNT]:
        if not isinstance(record, Mapping):
            continue
        item = {
            "artifact_id": _bounded_text(record.get("artifact_id"), 160) or None,
            "kind": _bounded_text(record.get("kind"), 48) or "unknown",
            "status": _bounded_text(record.get("status"), 48) or "unknown",
            "staged_ref": _bounded_text(record.get("staged_ref"), 160) or None,
            "published_artifact_id": _bounded_text(record.get("artifact_id_published"), 160) or None,
            "verification": dict(record.get("verification")) if isinstance(record.get("verification"), Mapping) else None,
            "generation_context": _bounded_generation_context(record.get("generation_context")),
            "source_attachment_ids": [_bounded_text(value, 96) for value in _bounded_list(record.get("source_attachment_ids"), 16)],
            "panel_ids": [_bounded_text(value, 96) for value in _bounded_list(record.get("panel_ids"), 16)],
            "collection_id": _bounded_text(record.get("collection_id"), 128) or None,
            "child_chart_ids": [_bounded_text(value, 128) for value in _bounded_list(record.get("child_chart_ids"), 16)],
            "measurement_status": _bounded_text(record.get("measurement_status"), 48) or None,
            "measurement_reference": (
                {key: _bounded_text(value, 160) if isinstance(value, str) else value
                 for key, value in record.get("measurement_reference", {}).items()
                 if key in {"session_id", "attempt_id", "attachment_id", "panel_id"}}
                if isinstance(record.get("measurement_reference"), Mapping) else None
            ),
            "measurement_issues": [
                {key: _bounded_text(value, 240) for key, value in issue.items()
                 if key in {"code", "location", "severity", "message"}}
                for issue in _bounded_list(record.get("measurement_issues"), 8)
                if isinstance(issue, Mapping)
            ],
            "measurement_evidence_refs": _bounded_ref_list(record.get("measurement_evidence_refs"), 64),
            "measurement_series_metadata": _bounded_ref_list(record.get("measurement_series_metadata"), 64),
            "measurement_scope": dict(record.get("measurement_scope")) if isinstance(record.get("measurement_scope"), Mapping) else None,
            "measurement_effective_scope": dict(record.get("measurement_effective_scope")) if isinstance(record.get("measurement_effective_scope"), Mapping) else None,
            "measurement_observation_scope": _bounded_observation_scope(record.get("measurement_observation_scope"))
            if isinstance(record.get("measurement_observation_scope"), Mapping) else None,
        }
        item = {
            key: value
            for key, value in item.items()
            if key in {"artifact_id", "kind", "status"} or value not in (None, [], {})
        }
        if item.get("artifact_id") or item.get("staged_ref"):
            safe_records.append(item)
    summary = _artifact_index_json(safe_records)
    return load_prompt_template("dynamic/artifacts.md", artifact_summary=summary)


def _artifact_index_json(records: list[dict[str, Any]]) -> str:
    """Keep every bounded artifact row while shortening detail before JSON is emitted."""
    summary = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(summary) <= _MAX_ARTIFACT_SUMMARY_CHARS:
        return summary

    compact_records: list[dict[str, Any]] = []
    for record in records:
        compact = {
            key: record[key]
            for key in ("artifact_id", "kind", "status", "staged_ref", "published_artifact_id", "collection_id")
            if key in record
        }
        verification = record.get("verification")
        if isinstance(verification, Mapping):
            compact["verification"] = {
                key: verification[key]
                for key in ("verification_ref", "status")
                if key in verification
            }
            issues = verification.get("issues")
            if isinstance(issues, list) and issues:
                compact["verification"]["issues"] = [
                    {
                        key: _bounded_text(issue.get(key), 120)
                        for key in ("code", "location", "severity", "message")
                        if issue.get(key) is not None
                    }
                    for issue in issues[:2]
                    if isinstance(issue, Mapping)
                ]
        if record.get("child_chart_ids"):
            compact["child_chart_ids"] = [
                _bounded_text(value, 64) for value in record["child_chart_ids"][:8]
            ]
        compact_records.append(compact)

    summary = json.dumps(compact_records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(summary) <= _MAX_COMPACT_ARTIFACT_SUMMARY_CHARS:
        return summary

    minimal_records = []
    for record in compact_records:
        minimal = {
            key: _bounded_text(record[key], 80 if key in {"artifact_id", "staged_ref", "published_artifact_id", "collection_id"} else 32)
            for key in ("artifact_id", "kind", "status", "staged_ref", "published_artifact_id", "collection_id")
            if key in record
        }
        verification = record.get("verification")
        if isinstance(verification, Mapping):
            minimal["verification"] = {
                key: _bounded_text(verification[key], 80 if key == "verification_ref" else 24)
                for key in ("verification_ref", "status")
                if key in verification
            }
        minimal_records.append(minimal)
    return json.dumps(minimal_records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_static_agent_prompt() -> str:
    """Load the stable four-part Chinese responsibility prompt."""
    metadata = PromptBundleMetadata()
    sections = [f"<!-- prompt_bundle={metadata.bundle_id}; version={metadata.version}; layer=static_responsibilities -->"]
    for asset in _STATIC_ASSETS:
        sections.append(load_prompt_asset(asset))
    return "\n\n".join(sections)


def build_chart_verification_prompt() -> str:
    """Load the independent tool-free chart verification contract."""
    return load_prompt_asset("verification/chart-verification.md")


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
) -> dict[str, Any]:
    """Build all four logical layers and a transport-ready system string."""
    tool_list = list(tools)
    static = build_static_agent_prompt()
    tool_surface = build_tool_surface(tool_list)
    runtime = build_runtime_context(runtime_state, panel_inventory=panel_inventory)
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
    "build_chart_verification_prompt",
    "build_runtime_context",
    "build_static_agent_prompt",
    "build_tool_surface",
    "load_prompt_asset",
    "load_prompt_template",
    "panel_inventory_from_layout_contexts",
    "prompt_trace_metadata",
    "validate_tool_surface",
]
