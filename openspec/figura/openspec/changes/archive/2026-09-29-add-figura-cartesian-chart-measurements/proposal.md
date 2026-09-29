## Why

Figura can currently return pixel geometry for bar charts, but it cannot measure line or scatter charts and cannot use recognized axis ticks to convert pixel positions into chart values. The Agent also receives no visual feedback after a measurement, so it cannot inspect whether detected geometry aligns with the selected image.

## What Changes

- Extend `measure_bars` with OCR-backed Cartesian axis observations and calibrated values while preserving pixel geometry and uncertainty.
- Add `measure_lines` and `measure_scatter` for multi-series two-dimensional Cartesian charts.
- Share scoped OCR, axis detection, tick association, and linear calibration across the three measurement tools.
- Project committed outcomes from all three tools into the existing `RunExecutionState.measurements` view without adding another store.
- After a completed measurement batch, include deterministic annotated images with the matching JSON observations in the next model request. Keep overlays out of durable tool results and leave follow-up decisions to the Agent.
- Bump the tool registry contract for the expanded measurement results. Preserve completed calls from earlier registry versions as inert history; keep unresolved older calls fail-closed.

## Capabilities

### New Capabilities

- `line-chart-measurement`: Return source-bound pixel traces and supported, axis-calibrated point observations for two-dimensional line charts.
- `scatter-chart-measurement`: Return source-bound scatter point geometry, series associations, and supported, axis-calibrated coordinates.

### Modified Capabilities

- `bar-chart-measurement`: Add OCR-backed axis and category observations and optional calibrated bar values while retaining uncertain pixel evidence.
- `panel-image-observation`: Project committed bar, line, and scatter outcomes through the existing Session-scoped `RunExecutionState`.
- `agent-react-execution`: Attach annotated measurement images to the next request for the just-committed measurement batch and allow completed prior-version tool interactions as inert history.

## Impact

- Affected code: `src/figura/tools/measurements/`, `src/figura/tools/implementations/`, `src/figura/agent/execution_state.py`, `src/figura/agent/request.py`, and `src/figura/bootstrap.py`.
- Affected contracts: the three measurement capabilities, `panel-image-observation`, and `agent-react-execution`.
- No new measurement table, frontend endpoint, image persistence format, or OCR model-facing tool is introduced. Existing attachment and Panel authorization, durable tool facts, and result-size limits remain in force.
- Scope is ordinary two-dimensional Cartesian charts with linear axes. Pie/polar charts, logarithmic or broken axes, dual-axis charts, and strong perspective or 3D geometry remain unsupported or partial evidence.
