## 1. Unified pie-result contract

- [x] 1.1 Inventory every `extract_pie_slices` caller, review consumer,
  fixture, mock payload, overlay helper, and documentation reference before
  changing the result shape.
- [x] 1.2 Define the serialized pie evidence model for image size,
  orientation/transform, plot region, circle geometry, sectors, legend/OCR
  evidence, confidence components, warnings, and bounded errors.
- [x] 1.3 Define one source-image coordinate convention and normalized angle
  convention for centers, radii, bboxes, boundary points, sector spans, and
  overlay drawing.
- [x] 1.4 Replace legacy flat sector assumptions with explicit geometry,
  measure, appearance, association, and uncertainty fields while leaving the
  existing categorical pie `ChartSpec` shape unchanged.
- [x] 1.5 Add shared validation and structured error helpers for bounded
  confidence, stable IDs, partial evidence, unsupported geometry, and local
  path redaction.

## 2. Pie-region and transform inference

- [x] 2.1 Implement bounded plot-region candidate collection using color,
  component, edge, circularity, radial-coverage, and area evidence while
  excluding legend-like swatches and annotations.
- [x] 2.2 Fit center, outer radius, source bbox/polygon, residual, and support
  for the selected ordinary pie region instead of using a component envelope
  as ground truth.
- [x] 2.3 Detect translated, resized, and supported rotated layouts while
  preserving all geometry in source-image coordinates.
- [x] 2.4 Classify weak, elliptical, perspective, 3D, donut, exploded,
  nested, and unknown regions as bounded unsupported or low-confidence cases
  without fabricating a flat pie geometry.
- [x] 2.5 Preserve inspectable empty or partial results when no reliable region
  hypothesis passes the evidence threshold.

## 3. Sector extraction and evidence-gated measurement

- [x] 3.1 Replace fixed-radius-only sampling with multi-radius angular evidence
  across the fitted region, retaining color support and separator information.
- [x] 3.2 Detect and cluster sector runs and boundaries while handling
  anti-aliasing, separator gaps, narrow sectors, similar colors, and partial
  occlusion without relying on a single pixel transition.
- [x] 3.3 Generate deterministic clockwise sector IDs and serialize boundary
  geometry, angular spans, color identity, support, residual, and uncertainty
  for every retained candidate.
- [x] 3.4 Gate semantic ratios on coverage, run stability, boundary quality,
  and total-consistency thresholds; retain angular/pixel evidence when a ratio
  is not reliable instead of inventing one.
- [x] 3.5 Compute angle and ratio totals and preserve partial sector evidence
  when merged, missing, or unresolved sectors prevent a complete 360-degree
  result.

## 4. Labels, legends, and semantic associations

- [x] 4.1 Remove the fixed right-side legend assumption and detect bounded
  legend candidates around the fitted region in supported left, right, top,
  bottom, and multi-row layouts.
- [x] 4.2 Associate legend colors and labels with stable sector IDs using
  color, spatial, angular, and layout evidence, retaining association source,
  support, and confidence.
- [x] 4.3 Extend OCR association to internal values, external labels, and
  leader-line or spatial-order evidence without allowing OCR to create sector
  geometry.
- [x] 4.4 Preserve printed numeric values separately from geometry-derived
  ratios and emit explicit warnings for conflicting, ambiguous, or unresolved
  associations.

## 5. Visual evidence and overlay migration

- [x] 5.1 Update `render_pie_overlay` to consume only the unified pie result
  and draw the measured region, center/radius, sector boundaries, IDs, colors,
  ratios, labels, and associations in source-image coordinates.
- [x] 5.2 Render source-sized overlays for clean, partial, unsupported, and
  empty results, making residuals, low-confidence evidence, and warnings
  visible without altering source dimensions.
- [x] 5.3 Add fixture-level assertions that serialized geometry and overlay
  geometry remain aligned after translation, resizing, and supported rotation.

## 6. Repository consumer migration

- [x] 6.1 Migrate generated-chart review comparisons to accepted pie measure
  fields, preserve incomplete/unsupported evidence as bounded review warnings,
  and avoid treating pixel-only or uncertain ratios as complete data.
- [x] 6.2 Update pie fixtures and tool tests for the unified result shape,
  including sector support, residuals, confidence gates, total consistency,
  stable IDs, and source-sized overlays.
- [x] 6.3 Update authorized and unauthorized attachment tests plus the offline
  Agent-loop trajectory so pie restoration remains freely planned and still
  assembles/validates an axis-free `ChartSpec`.
- [x] 6.4 Update frontend mock observations and chart-understanding
  documentation, then search the repository for every removed pie field,
  fixed legend-side assumption, and stale point-count/ratio assertion.

## 7. Regression coverage

- [x] 7.1 Add clean ordinary pie fixtures for centered and translated regions,
  multiple sizes, supported rotations, and legends in each supported layout.
- [x] 7.2 Add fixtures for narrow sectors, similar colors, anti-aliased
  separators, internal percentages, external labels, leader lines, and
  partial occlusion, verifying partial evidence and bounded warnings.
- [x] 7.3 Add fixtures for perspective, ellipse/3D styling, donut, exploded,
  nested, circular non-pie graphics, and blank images, verifying unsupported or
  empty results without complete fabricated ratios.
- [x] 7.4 Add missing, malformed, non-image, and unauthorized-input tests that
  assert structured errors, redacted paths, and no generated artifact on
  failure.
- [x] 7.5 Add regression coverage proving pie ChartSpec assembly and
  validation remain axis-free and that existing bar, line, and scatter
  consumers are unaffected.

## 8. Verification and cleanup

- [x] 8.1 Run focused pie observation, overlay, review, attachment, and
  Agent-loop tests with `conda run -n agent python -m pytest` and resolve
  failures without weakening evidence gates.
- [x] 8.2 Run the full Python suite with `conda run -n agent python -m pytest
  -q`, then run `npm run build` and `npm run smoke` from `frontend`.
- [x] 8.3 Run `git diff --check`, strict OpenSpec validation, and a final search
  confirming that all pie consumers and documentation use the unified result.
