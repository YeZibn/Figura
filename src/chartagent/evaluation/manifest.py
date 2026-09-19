"""Versioned manifest and safety checks for real-chart diagnostic samples."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


MANIFEST_SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|access[_-]?token|auth(?:orization)?|password|secret|private[_-]?key)",
    re.IGNORECASE,
)
_DATA_URL_PATTERN = re.compile(r"^data:[^,]+,", re.IGNORECASE)


class DiagnosticManifestError(ValueError):
    """Raised when a diagnostic manifest is unsafe or internally inconsistent."""


@dataclass(frozen=True)
class DiagnosticPanelHint:
    """Bounded expected information used to interpret a real sample."""

    name: str
    chart_type: str | None = None
    role: str | None = None
    bbox_norm: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name}
        if self.chart_type:
            result["chart_type"] = self.chart_type
        if self.role:
            result["role"] = self.role
        if self.bbox_norm is not None:
            result["bbox_norm"] = list(self.bbox_norm)
        return result


@dataclass(frozen=True)
class DiagnosticSample:
    """One image that may be submitted through the normal Gateway path."""

    case_id: str
    asset: str
    sha256: str
    expected_panel_count: int
    expected_panels: tuple[DiagnosticPanelHint, ...]
    asset_path: Path

    def to_dict(self, *, include_resolved_path: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "case_id": self.case_id,
            "asset": self.asset,
            "sha256": self.sha256,
            "expected_panels": {
                "count": self.expected_panel_count,
                "items": [panel.to_dict() for panel in self.expected_panels],
            },
        }
        if include_resolved_path:
            # This is intended for local debugging only. Reports never include
            # this field, so absolute workstation paths cannot leak to them.
            result["asset_path"] = str(self.asset_path)
        return result


@dataclass(frozen=True)
class DiagnosticManifest:
    """Validated manifest plus its local asset root."""

    schema_version: int
    samples: tuple[DiagnosticSample, ...]
    manifest_path: Path
    asset_root: Path

    def sample(self, case_id: str) -> DiagnosticSample:
        for sample in self.samples:
            if sample.case_id == case_id:
                return sample
        raise DiagnosticManifestError(f"未知的 case_id: {case_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "samples": [sample.to_dict() for sample in self.samples],
        }


def load_manifest(path: str | Path, *, asset_root: str | Path | None = None) -> DiagnosticManifest:
    """Load and validate a manifest without exposing absolute paths in data.

    Asset paths are deliberately relative to ``asset_root``. The file's
    SHA-256 is checked before a caller can submit it to the Gateway, which
    makes accidental use of a different local image visible and repeatable.
    """

    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.is_file():
        raise DiagnosticManifestError(f"manifest 不存在: {path}")

    root = _resolve_asset_root(manifest_path, asset_root)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DiagnosticManifestError(f"manifest 不是有效 JSON: {exc}") from exc
    except OSError as exc:
        raise DiagnosticManifestError(f"无法读取 manifest: {exc}") from exc

    _reject_sensitive_values(raw)
    if not isinstance(raw, Mapping):
        raise DiagnosticManifestError("manifest 顶层必须是对象")
    schema_version = raw.get("schema_version")
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise DiagnosticManifestError(
            f"不支持的 manifest schema_version: {schema_version!r}"
        )
    raw_samples = raw.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise DiagnosticManifestError("manifest.samples 必须是非空数组")
    if len(raw_samples) > 32:
        raise DiagnosticManifestError("manifest.samples 最多支持 32 个样本")

    samples: list[DiagnosticSample] = []
    seen_case_ids: set[str] = set()
    for index, raw_sample in enumerate(raw_samples):
        samples.append(
            _parse_sample(
                raw_sample,
                index=index,
                asset_root=root,
                seen_case_ids=seen_case_ids,
            )
        )

    return DiagnosticManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        samples=tuple(samples),
        manifest_path=manifest_path,
        asset_root=root,
    )


def _resolve_asset_root(manifest_path: Path, asset_root: str | Path | None) -> Path:
    if asset_root is not None:
        return Path(asset_root).expanduser().resolve()
    for candidate in (manifest_path.parent, *manifest_path.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd().resolve()


def _parse_sample(
    raw_sample: Any,
    *,
    index: int,
    asset_root: Path,
    seen_case_ids: set[str],
) -> DiagnosticSample:
    if not isinstance(raw_sample, Mapping):
        raise DiagnosticManifestError(f"samples[{index}] 必须是对象")

    case_id = _bounded_string(raw_sample.get("case_id"), f"samples[{index}].case_id", 128)
    if case_id in seen_case_ids:
        raise DiagnosticManifestError(f"重复的 case_id: {case_id}")
    seen_case_ids.add(case_id)

    asset = _bounded_string(raw_sample.get("asset"), f"samples[{index}].asset", 512)
    asset_path = _safe_asset_path(asset, asset_root, field=f"samples[{index}].asset")
    if not asset_path.is_file():
        raise DiagnosticManifestError(f"样本图片不存在: {asset}")

    sha256 = _bounded_string(raw_sample.get("sha256"), f"samples[{index}].sha256", 64).lower()
    if not SHA256_PATTERN.fullmatch(sha256):
        raise DiagnosticManifestError(f"samples[{index}].sha256 必须是 64 位十六进制")
    actual_sha256 = _sha256(asset_path)
    if actual_sha256 != sha256:
        raise DiagnosticManifestError(
            f"样本指纹不匹配: {case_id} (manifest={sha256}, actual={actual_sha256})"
        )

    expected = raw_sample.get("expected_panels")
    if not isinstance(expected, Mapping):
        raise DiagnosticManifestError(f"samples[{index}].expected_panels 必须是对象")
    expected_count = expected.get("count")
    if isinstance(expected_count, bool) or not isinstance(expected_count, int):
        raise DiagnosticManifestError(f"samples[{index}].expected_panels.count 必须是整数")
    if expected_count < 1 or expected_count > 64:
        raise DiagnosticManifestError(f"samples[{index}].expected_panels.count 超出范围")
    raw_panels = expected.get("items", [])
    if not isinstance(raw_panels, list) or len(raw_panels) > 64:
        raise DiagnosticManifestError(
            f"samples[{index}].expected_panels.items 必须是最多 64 项的数组"
        )
    if raw_panels and len(raw_panels) != expected_count:
        raise DiagnosticManifestError(
            f"samples[{index}] 的 panel count 与 items 数量不一致"
        )

    panels = tuple(
        _parse_panel_hint(item, sample_index=index, panel_index=panel_index)
        for panel_index, item in enumerate(raw_panels)
    )
    return DiagnosticSample(
        case_id=case_id,
        asset=asset,
        sha256=sha256,
        expected_panel_count=expected_count,
        expected_panels=panels,
        asset_path=asset_path,
    )


def _parse_panel_hint(item: Any, *, sample_index: int, panel_index: int) -> DiagnosticPanelHint:
    if not isinstance(item, Mapping):
        raise DiagnosticManifestError(
            f"samples[{sample_index}].expected_panels.items[{panel_index}] 必须是对象"
        )
    name = _bounded_string(
        item.get("name"),
        f"samples[{sample_index}].expected_panels.items[{panel_index}].name",
        240,
    )
    chart_type = _optional_string(item.get("chart_type"), 64)
    role = _optional_string(item.get("role"), 64)
    bbox_raw = item.get("bbox_norm")
    bbox: tuple[float, float, float, float] | None = None
    if bbox_raw is not None:
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            raise DiagnosticManifestError(
                f"samples[{sample_index}].expected_panels.items[{panel_index}].bbox_norm 必须是 4 项数组"
            )
        try:
            values = tuple(float(value) for value in bbox_raw)
        except (TypeError, ValueError) as exc:
            raise DiagnosticManifestError("bbox_norm 必须是数字") from exc
        if any(value < 0 or value > 1 for value in values) or values[2] <= values[0] or values[3] <= values[1]:
            raise DiagnosticManifestError("bbox_norm 必须位于 [0, 1] 且右下角大于左上角")
        bbox = values  # type: ignore[assignment]
    return DiagnosticPanelHint(name=name, chart_type=chart_type, role=role, bbox_norm=bbox)


def _safe_asset_path(asset: str, asset_root: Path, *, field: str) -> Path:
    candidate_text = asset.replace("\\", "/")
    candidate = Path(candidate_text)
    if candidate.is_absolute() or candidate_text.startswith("/"):
        raise DiagnosticManifestError(f"{field} 不允许绝对路径")
    if ".." in candidate.parts:
        raise DiagnosticManifestError(f"{field} 不允许跳出 asset_root")
    resolved = (asset_root / candidate).resolve()
    try:
        resolved.relative_to(asset_root)
    except ValueError as exc:
        raise DiagnosticManifestError(f"{field} 不允许跳出 asset_root") from exc
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise DiagnosticManifestError(f"无法读取样本图片: {path.name}") from exc
    return digest.hexdigest()


def _bounded_string(value: Any, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiagnosticManifestError(f"{field} 必须是非空字符串")
    value = value.strip()
    if len(value) > max_length:
        raise DiagnosticManifestError(f"{field} 过长")
    if _DATA_URL_PATTERN.match(value):
        raise DiagnosticManifestError(f"{field} 不允许 data URL")
    return value


def _optional_string(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise DiagnosticManifestError("可选字段必须是有限长度的字符串")
    return value.strip()


def _reject_sensitive_values(value: Any, *, key_path: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_PATTERN.search(key_text):
                raise DiagnosticManifestError(f"manifest 不允许敏感字段: {key_path}.{key_text}")
            _reject_sensitive_values(child, key_path=f"{key_path}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_values(child, key_path=f"{key_path}[{index}]")
    elif isinstance(value, str) and _DATA_URL_PATTERN.match(value):
        raise DiagnosticManifestError(f"manifest 不允许内嵌图片数据: {key_path}")
