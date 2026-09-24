## Why

`measure_bars` currently derives the baseline from a fixed heuristic plot-area boundary instead of the chart's actual zero axis or shared bar edge. On the existing clean bar fixture, the generated blue baseline is visibly separated from the bars because the heuristic crop ends several pixels before the rendered x-axis; rotated and horizontal bars expose the same assumption more severely. The result schema also contains orientation-specific and duplicated fields that make future bar geometries difficult to represent consistently.

## What Changes

- Detect the actual bar plot boundary and zero baseline from image evidence instead of treating a fixed crop boundary as ground truth.
- Represent the baseline as a fitted pixel line with endpoints, residual, and confidence so horizontal and slightly rotated charts can be described.
- Normalize bar geometry and measurements across vertical, horizontal, positive, negative, grouped, and stacked cases.
- Return polygon geometry and a value-axis measurement for every detected bar while retaining category and series associations.
- Update the bar overlay to draw the measured baseline and bar polygons using one coordinate convention.
- Add explicit uncertainty and unsupported-case warnings for ambiguous, strongly perspective-distorted, or 3D bar images.
- **BREAKING** Remove the legacy bar-result fields `baseline_y`, `h_px`, `stacked`, per-bar `series`, per-bar flat `bbox`, `ratio`, and `stack_total_h_px` in favor of the unified `baseline`, `geometry`, `measure`, `bar_mode`, `series_id`, and `stack` structures.
- Migrate review logic, tests, fixtures, mock trace payloads, and chart-understanding documentation to the unified result contract.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `chart-understanding`: change the bar measurement contract to use orientation-independent geometry, fitted baselines, unified value-axis measurements, explicit uncertainty, and defined behavior for rotated, horizontal, negative, stacked, and unsupported bar charts.

## Impact

- Python sensor and overlay code under `src/chartagent/tools/chart/observation/`.
- Generated-chart review comparisons in `src/chartagent/review/manager.py`.
- Chart observation tests, fixtures, and end-to-end trajectories under `tests/`.
- The bar measurement section of `openspec/specs/chart-understanding/spec.md`.
- Frontend mock trace data may need field updates, but the visual-observation transport and preview protocol remain unchanged.
- No new runtime dependency is planned; implementation should continue using the existing Conda `agent` environment and Pillow/NumPy stack.
