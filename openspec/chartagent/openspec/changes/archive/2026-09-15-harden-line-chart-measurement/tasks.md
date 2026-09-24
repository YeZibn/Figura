## 1. Unified line-result contract

- [x] 1.1 Define the internal and serialized line observation models for
  `image_size`, `orientation`, `plot_frame`, axis evidence, `series`, traces,
  points, confidence, and warnings.
- [x] 1.2 Define one source-image coordinate convention for axis endpoints,
  frame polygons, trace vertices, point positions, and overlay conversion.
- [x] 1.3 Replace the point-only line result assumptions with explicit trace
  geometry, point source metadata, and optional calibrated x/y values without
  emitting fabricated semantic coordinates.

## 2. Line frame and axis inference

- [x] 2.1 Implement line-specific plot-frame evidence from visible axes, ticks,
  gridlines, trace extents, and image boundaries instead of using the fixed
  proportional plot rectangle as ground truth.
- [x] 2.2 Classify upright, small-affine-rotated, and unknown line layouts from
  axis directions and frame consistency while preserving source coordinates.
- [x] 2.3 Fit source-image x/y axis endpoints and numeric pixel-to-value
  transforms with support counts, residuals, and bounded confidence.
- [x] 2.4 Add conservative handling for missing axes, incomplete OCR,
  categorical x labels without numeric mapping, strong perspective, and 3D
  styling.

## 3. Trace and marker evidence

- [x] 3.1 Restrict series-color evidence to the inferred frame and keep legend
  swatches or annotations from becoming trace candidates.
- [x] 3.2 Extract ordered source-image trace polylines or fragments for each
  color-distinguished series while preserving bounded anti-aliased gaps.
- [x] 3.3 Detect marker candidates independently from continuous trace pixels
  and retain their geometry and confidence as point evidence.
- [x] 3.4 Remove arbitrary per-column peak selection as the source of confirmed
  points, retaining density or local-extrema evidence only as trace support.

## 4. Point sampling and series semantics

- [x] 4.1 Emit marker-derived points with stable per-series IDs and source
  metadata when marker centers are reliably supported.
- [x] 4.2 Add markerless point sampling only at reliable ordered x-axis ticks or
  equivalent anchors, with explicit sampling warnings when anchors are absent.
- [x] 4.3 Emit calibrated numeric x/y values only after both axis transforms
  meet residual and confidence thresholds, preserving signed values across
  zero-crossing lines.
- [x] 4.4 Preserve series identity through crossings and shared x positions;
  surface merged, overlapped, occluded, dense, dashed, or fragmented regions
  as bounded uncertainty.

## 5. Visual evidence and overlay migration

- [x] 5.1 Update the line overlay to draw measured trace geometry rather than
  reconstructing lines only from returned points.
- [x] 5.2 Draw the inferred frame, axis evidence, point IDs, series identities,
  calibration status, and material uncertainty in source-image coordinates.
- [x] 5.3 Preserve source dimensions and provide an inspectable empty or
  partial overlay for non-line, unsupported, and incomplete inputs.

## 6. Repository consumer migration

- [x] 6.1 Update line observation tests, fixtures, and end-to-end trajectories
  to the trace-and-point result contract.
- [x] 6.2 Update frontend mock trace payloads and any documentation that still
  assumes point-only line observations; keep preview and observation transport
  behavior unchanged. The frontend mock contains no line point-only payload;
  its generic preview and observation transport remains unchanged.
- [x] 6.3 Search the repository for stale line fields, point-count assumptions,
  fixed-plot-area dependencies, and compatibility assertions, then migrate or
  remove them.

## 7. Regression coverage

- [x] 7.1 Add upright single-series and multi-series marker fixtures verifying
  point identity, calibrated coordinates, legend association, and overlay size.
- [x] 7.2 Add a markerless fixture verifying continuous trace preservation,
  tick-anchored sampling, and no unanchored fabricated points.
- [x] 7.3 Add rotated fixtures in both directions verifying source geometry,
  frame orientation, axis residuals, and bounded calibration confidence.
- [x] 7.4 Add crossing, overlapping, positive/negative, zero-crossing, dense,
  and partially occluded fixtures verifying identity and warning behavior.
- [x] 7.5 Add incomplete-axis, categorical-x, perspective/3D, non-line, and
  missing-image cases verifying partial evidence, structured errors, and no
  fabricated semantic values.

## 8. Verification and cleanup

- [x] 8.1 Run focused line-observation and overlay tests with
  `conda run -n agent python -m pytest` and resolve failures without weakening
  the evidence contract.
- [x] 8.2 Run the full Python suite with `conda run -n agent python -m pytest
  -q`, then run `npm run build` and `npm run smoke` from `frontend`.
- [x] 8.3 Run `git diff --check`, strict OpenSpec validation, and a final search
  confirming that line consumers and documentation use the unified result.
