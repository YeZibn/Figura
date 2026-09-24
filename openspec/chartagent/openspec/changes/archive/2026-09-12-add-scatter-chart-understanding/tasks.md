## 1. Scatter Evidence Contract

- [x] 1.1 Define the scatter sensor result shape for plot-area evidence,
  series identities, point geometry, pixel/semantic coordinates, marker
  appearance, overlap evidence, outlier candidates, confidence, and warnings
  without changing the existing ChartSpec serialization contract.
- [x] 1.2 Confirm bounded scatter results and structured failures follow
  `ToolResult`, authorized attachment wrappers, and generated visual
  observation limits.

## 2. Independent Scatter Sensor

- [x] 2.1 Add a path-compatible `extract_scatter_points` sensor that validates
  local image input and reuses the shared Cartesian layout and OCR calibration
  evidence.
- [x] 2.2 Implement deterministic color-mask component detection for clean
  scatter markers, including stable series IDs, point IDs, centroids, bounding
  boxes, areas, and pixel coordinates.
- [x] 2.3 Attach calibrated x/y values when both axes are readable and preserve
  pixel-only or partially calibrated evidence with bounded warnings otherwise.
- [x] 2.4 Add conservative handling for merged/overlapping markers, marker
  size or opacity observations, and potential outlier candidates without
  fabricating semantic values.
- [x] 2.5 Add confidence calculation, warning generation, and no-scatter or
  malformed-input behavior that remains inspectable and bounded.

## 3. Visual Evidence and Agent Integration

- [x] 3.1 Add a source-sized scatter overlay that marks the plot region,
  points, IDs, series colors, calibration status, and uncertain/outlier
  evidence.
- [x] 3.2 Register `extract_scatter_points` with the chart tool registry and
  expose only the authorized `attachment_id` schema in Agent mode.
- [x] 3.3 Verify authorized, unauthorized, cross-session, unreadable, and
  changed attachment calls return the expected structured results without
  leaking canonical paths or generating forbidden artifacts.
- [x] 3.4 Verify the existing Agent visual-observation path delivers scatter
  overlays on the next model turn without adding a Gateway route or forcing a
  fixed tool sequence.
- [x] 3.5 Verify `assemble_spec` and `validate_spec` accept valid coordinate
  scatter data with axes and independently reject missing/invalid axes.

## 4. Fixtures and Tests

- [x] 4.1 Add deterministic scatter fixtures and ground truth for clean
  single-series, multi-series, readable-axis, partially calibrated, overlapping
  marker, and potential-outlier cases.
- [x] 4.2 Add sensor tests for point count, stable IDs, centroids, calibrated
  x/y values, series separation, source-sized overlays, and structured missing
  or non-image errors.
- [x] 4.3 Add tests for marker appearance evidence, merged/overlapping points,
  outlier retention, confidence bounds, and uncertainty warnings.
- [x] 4.4 Add attachment-boundary and registry tests for authorized and
  unauthorized scatter-sensor calls.
- [x] 4.5 Add an offline scripted Agent-loop acceptance test proving scatter
  evidence can be assembled into an axis-valid ChartSpec and independently
  validated without a prescribed tool order.

## 5. Verification

- [x] 5.1 Run focused scatter, ChartSpec, attachment, overlay, and Agent-loop
  tests with `conda run -n agent` and fix regressions.
- [x] 5.2 Run the full Python suite, frontend build, and existing Gateway/UI
  smoke checks using the documented project commands.
- [x] 5.3 Run `openspec validate add-scatter-chart-understanding --type change
  --strict` and reconcile any proposal, spec, design, or task inconsistencies.
