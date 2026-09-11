## 1. Shared Contracts and ChartSpec

- [x] 1.1 Define shared Cartesian evidence helpers for image size, plot area, axis calibration, legend entries, series identities, confidence, and warnings while preserving the current `ToolResult` normalization limits.
- [x] 1.2 Extend `ChartSpec` and `DataPoint` validation/serialization to enforce non-empty optional series identities, bounded confidence, and compatible point shapes without breaking legacy single-series specs.
- [x] 1.3 Extend `assemble_spec` schemas and validation to accept optional `series` and `confidence` fields and preserve them in the existing IR.

## 2. Cartesian Sensors

- [x] 2.1 Refactor bar geometry measurement to retain the current single-series output and add grouped-bar category/series associations, stable IDs, and shared layout evidence.
- [x] 2.2 Add supported stacked-bar segment detection with total-stack preservation, explicit unresolved-association warnings, and source-sized overlays.
- [x] 2.3 Implement `extract_line_series` using the existing Pillow/NumPy/OCR stack, including color grouping, ordered pixel points, optional legend labels, and structured missing-input errors.
- [x] 2.4 Add axis/tick calibration for clean Cartesian fixtures, returning semantic values only when calibration is reliable and retaining pixel evidence with warnings otherwise.
- [x] 2.5 Add line and multi-series overlays that identify plot area, series, point/bar IDs, and unresolved evidence within the existing generated-image limits.

## 3. Agent Integration

- [x] 3.1 Register `extract_line_series` and route it through the authorized attachment wrapper without exposing local paths in model-facing schemas or error results.
- [x] 3.2 Update the Agent's chart-tool description and registration assertions so free tool planning includes line extraction while preserving optional assembly/validation behavior.
- [x] 3.3 Verify Gateway/tool observation serialization carries sensor confidence, warnings, and bounded overlays without changing existing event contracts.

## 4. Fixtures and Tests

- [x] 4.1 Add deterministic fixtures and ground truth for single-series lines, multi-series lines with legends, grouped bars, supported stacked bars, and partial-calibration cases.
- [x] 4.2 Add sensor tests covering calibrated values, series separation, backward-compatible single-series bar fields, warnings, structured errors, overlay dimensions, and non-chart inputs.
- [x] 4.3 Extend ChartSpec and assembly tests for multi-series round trips, optional confidence/provenance, invalid series identities, and legacy specs.
- [x] 4.4 Add attachment-boundary and tool-registry tests for authorized and unauthorized line-sensor calls.
- [x] 4.5 Add an offline scripted Agent-loop acceptance test proving that multi-series evidence survives assembly and independent validation without imposing a fixed tool order.

## 5. Verification and Documentation

- [x] 5.1 Run the focused chart and ChartSpec tests with `conda run -n agent` and fix regressions in existing U0 behavior.
- [x] 5.2 Run the full Python suite, frontend build/smoke checks, and any existing launcher checks using the project’s documented commands.
- [x] 5.3 Run `openspec validate extend-multitype-cartesian-chart-understanding --type change --strict` and reconcile any spec/task inconsistencies.
