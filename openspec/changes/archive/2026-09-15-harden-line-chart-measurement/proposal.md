## Why

`extract_line_series` currently estimates data points from per-column color
peaks inside a fixed heuristic plot rectangle, so it can confuse line shape,
markers, legends, and sampling density. The bar-measurement change established
an evidence-driven geometry contract; line charts now need the same separation
between source-image geometry, calibrated values, associations, and bounded
uncertainty.

## What Changes

- Infer a line-chart frame from visible axes, ticks, grid or trace evidence
  instead of treating `default_plot_area` as ground truth.
- Represent source-image axis/frame geometry and small affine rotation evidence
  so point and trace coordinates remain inspectable in the original image.
- Detect colored series traces and marker candidates without treating arbitrary
  pixel-density peaks as confirmed data points.
- Support marker-derived points and, when reliable x-axis anchors exist,
  tick-sampled points for line charts without markers.
- Preserve continuous trace geometry when sampling positions or numeric
  calibration cannot be established; do not fabricate semantic x/y values.
- Fit numeric axis calibration with residual and confidence evidence, including
  positive, negative, and zero-crossing series.
- Preserve stable series identities across crossings and overlaps, with
  explicit warnings for unresolved legend mappings, merged traces, occlusion,
  dense sampling, and unsupported geometry.
- Update the line overlay to show the measured trace, frame, points, identities,
  calibration evidence, and material uncertainty at source-image dimensions.
- **BREAKING** Replace the current point-only assumptions with a unified trace
  and point evidence contract while migrating review, tests, fixtures, and
  mock observations to the new result shape.
- Keep numeric x/y coordinates as the supported ChartSpec restoration target;
  categorical x labels without a representable numeric mapping remain bounded
  evidence rather than silently becoming fabricated coordinates.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `chart-understanding`: strengthen line-series extraction with an inferred
  chart frame, trace geometry, evidence-backed point sampling, calibrated
  coordinates, rotation handling, and explicit uncertainty behavior.

## Impact

- Line sensor and overlay code under `src/chartagent/tools/chart/observation/`.
- Shared Cartesian evidence helpers may need line-specific extensions, while
  the existing scatter sensor should remain behaviorally stable unless a
  helper migration is explicitly covered by the design.
- Chart observation tests, synthetic fixtures, end-to-end trajectories, and
  frontend mock trace payloads under `tests/` and `frontend/`.
- The line-series sections of `openspec/specs/chart-understanding/spec.md`.
- No new runtime dependency is planned; implementation continues to use the
  Conda `agent` environment and the existing Pillow/NumPy/OCR stack.
- No database, attachment, or persisted-data migration is required because
  line observations are per-run tool evidence.
