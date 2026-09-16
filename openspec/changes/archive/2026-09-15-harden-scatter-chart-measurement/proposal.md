## Why

`extract_scatter_points` can identify clean marker components, but its current
fixed plot rectangle and low-evidence tick fit make semantic coordinates
fragile: real fixture runs may return correct pixel points while losing y-axis
calibration and legend labels. The sensor also reuses private line helpers and
does not preserve source-frame or fit-quality evidence, so rotation, partial
OCR, overlaps, and dense markers are harder to inspect safely.

## What Changes

- Infer a scatter-specific source-image plot frame and axis directions from
  visible axes, ticks, gridlines, marker extents, and image boundaries instead
  of treating the proportional crop as ground truth.
- Return a unified scatter evidence contract with image dimensions,
  orientation, frame geometry, axis/tick transforms, support, residuals,
  confidence, warnings, stable series identities, and source-image point
  geometry.
- Keep marker/component evidence separate from calibrated semantic values;
  emit numeric `x`/`y` only when both axis fits satisfy residual and support
  thresholds, otherwise preserve `x_px`/`y_px` without fabrication.
- Preserve merged, overlapping, oversized, occluded, dense, and outlier
  evidence explicitly, including bounded uncertainty and incomplete point
  counts.
- Scope color and legend association to the inferred frame, retain stable
  color identities when labels are unavailable, and remove the scatter sensor's
  dependency on private line-only behavior.
- Support clean upright charts and small affine rotations while keeping all
  frame, axis, point, and overlay coordinates in source-image pixels.
- Update the scatter overlay, review consumers, fixtures, end-to-end flows,
  frontend mock observations, and documentation to the unified contract.
- **BREAKING** Replace point-only assumptions with explicit geometry,
  calibration evidence, point appearance, and uncertainty fields; preserve
  preview and observation transport behavior.
- Return bounded structured errors without exposing internal local image paths
  for missing, malformed, unauthorized, unsupported, or non-scatter inputs.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `chart-understanding`: strengthen scatter-point extraction with an inferred
  frame, source-image axis geometry, evidence-backed calibration, stable series
  association, overlap/outlier uncertainty, and source-sized overlays.

## Impact

- Scatter sensor and overlay code under
  `src/chartagent/tools/chart/observation/`.
- Shared Cartesian evidence helpers may need neutral extraction from the line
  sensor without changing bar or line behavior unexpectedly.
- Review logic, chart fixtures, chart-understanding end-to-end trajectories,
  tool payload tests, and frontend mock observation data.
- The scatter section of `openspec/specs/chart-understanding/spec.md`.
- No new runtime dependency, database migration, or persisted-data migration;
  Python commands and OCR tests continue to use the Conda `agent` environment.
