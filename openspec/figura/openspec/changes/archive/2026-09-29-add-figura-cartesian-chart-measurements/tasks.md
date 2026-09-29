## 1. Shared Source and Cartesian Axis Foundation

- [x] 1.1 Add one shared Attachment/Panel source resolver for measurement handlers, validating IDs against the target `RunExecutionState` and resolving bytes through the existing source services.
- [x] 1.2 Implement scoped OCR observations with text, bounding boxes, and confidence for axis ticks, category labels, axis labels, and legends; keep OCR internal to measurement tools.
- [x] 1.3 Implement shared Cartesian axis geometry, tick association, pixel projection, and linear calibration with the declared support-span, residual, and confidence gates.
- [x] 1.4 Add focused tests for numeric and categorical ticks, tilted axes, low-support calibration, conflicting OCR, and unavailable OCR evidence.

## 2. Upgrade Bar Measurement

- [x] 2.1 Extend `measure_bars` result and tool schemas with x/y axis observations, category label/tick associations, calibrated values, and the shared confidence shape while retaining current bar geometry and baseline evidence.
- [x] 2.2 Add sensor and handler coverage for vertical, horizontal, grouped, and stacked bars with successful calibration, failed calibration, no evidence, unsupported geometry, and authorized Attachment/Panel resolution.

## 3. Add Line and Scatter Measurement

- [x] 3.1 Implement `measure_lines` with multi-series pixel traces, preserved fragments, marker observations, and samples only at recognized x-axis ticks when markers are absent.
- [x] 3.2 Add `measure_lines` schema, source authorization, bounded errors, and tests for calibrated coordinates, categorical x labels, missing calibration, fragmented traces, and no evidence.
- [x] 3.3 Implement `measure_scatter` with multi-series point geometry, independently nullable x/y values, and visible merged, occluded, dense, and overlap uncertainty flags.
- [x] 3.4 Add `measure_scatter` schema, source authorization, bounded errors, and tests for calibrated and partially calibrated axes, overlapping points, unsupported geometry, and no evidence.
- [x] 3.5 Verify all measurement results remain within the existing tool-result contract; reject oversized complete results without truncating or silently dropping observations.

## 4. Extend Session Projection and Registry History

- [x] 4.1 Extend `RunExecutionState.measurements` reconstruction to include committed `measure_bars`, `measure_lines`, and `measure_scatter` results in Session Run and tool-call order, preserving the existing observation fields and source checks.
- [x] 4.2 Bump the registry to `figura-web-v3` and allow fully paired version-mismatched tool interactions as inert Provider history while keeping unresolved or incomplete calls fail-closed.
- [x] 4.3 Add projection and request-history regression coverage for current and prior Runs, successful and failed outcomes, missing results, source isolation, and prior registry versions.

## 5. Add Measurement Visual Feedback

- [x] 5.1 Implement deterministic bar, line, and scatter overlays from authorized source images and committed result JSON, including status/warning labels when geometry is unavailable.
- [x] 5.2 Extend request assembly to add one matching annotated image per successful measurement call from the immediately preceding committed batch, in tool-call order, without storing overlay bytes in tool facts or `RunExecutionState`.
- [x] 5.3 Preserve explicit `load_image` behavior, unified tool-call ordering, provider image bounds, and fail-before-provider-claim behavior when a source cannot be resolved or image limits are exceeded.
- [x] 5.4 Add request and visualization tests for mixed `load_image`/measurement batches, multiple sources and tools, no-evidence results, old overlays not repeating, unresolved sources, and provider-limit failures.

## 6. Validate the Change

- [x] 6.1 Run focused Figura measurement, request-assembly, and `RunExecutionState` regressions, then the complete Python test suite in the `agent` environment.
- [x] 6.2 Validate the OpenSpec change and reconcile any schema, delta-spec, or task inconsistencies.

Validation record: the focused Figura regression passed (`120 passed`), and strict OpenSpec validation passed with no issues. The complete Python suite ran (`857 passed, 13 failed`); failures are confined to unchanged legacy storage migration tests that expect schema v5 while the current store initializes v6, and unchanged legacy ChartAgent Gateway tests that receive `503` because provider configuration is unavailable.
