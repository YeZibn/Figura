## Why

Figura 当前的图表理解能力集中在干净的单系列柱状图，虽然 ChartSpec 已经能够表达折线图和多系列数据，但 Agent 尚无对应的视觉传感器。现在扩展笛卡尔坐标图，可以在保留自由规划和视觉自验证机制的前提下，把系统从 U0 柱状图验证推进到可复用的多类型、多系列图表理解。

## What Changes

- Add an authorized `extract_line_series` chart tool for single-series and multi-series line charts.
- Extend bar measurement to recognize grouped/multi-series bars while preserving the existing single-series output contract.
- Add shared plot-area, axis-calibration, legend, color-series, confidence, and warning metadata for Cartesian chart sensors.
- Return structured points/series together with bounded visual overlays so the Agent can compare geometry, OCR, and model-visible evidence.
- Keep sensor selection optional: the Agent may choose a tool, retry with another tool, or answer directly; no fixed chart-understanding workflow is imposed.
- Extend ChartSpec behavior and validation so extracted series remain semantically distinct and can carry bounded confidence/provenance without storing image bytes.
- Add generated fixtures and evaluation tests for clean line charts, multi-series line charts, grouped bars, stacked bars where supported, axis calibration, overlays, malformed images, and non-chart inputs.
- Preserve authorized attachment IDs, lazy image loading, existing chart tools, Gateway event contracts, and backward compatibility for existing bar-chart consumers.
- Defer pie-chart and scatter-plot extraction, chart rendering/generation, and frontend-specific chart visualizations to later changes.

## Capabilities

### New Capabilities

### Modified Capabilities

- `chart-understanding`: expand visual chart sensors from single-series bars to Cartesian line and multi-series/bar understanding with calibrated structured results and self-validation evidence.
- `chartspec`: formalize multi-series semantic output, bounded confidence/provenance, and validation behavior needed by the expanded chart sensors.

## Impact

- Python chart tools, shared image/layout utilities, ChartSpec validation, Agent tool registration, and visual-observation overlays.
- Offline chart fixtures and tests, including sensor-level accuracy checks and full Agent-loop acceptance scenarios.
- Existing Gateway and desktop clients continue to receive generic tool/result/visual-observation events; no new frontend or Tauri implementation is required for this change.
- The initial implementation should use the existing `agent` Conda environment and avoid requiring a provider call for deterministic sensor tests. Any new image-processing dependency must be evaluated against local installation and runtime compatibility before adoption.
