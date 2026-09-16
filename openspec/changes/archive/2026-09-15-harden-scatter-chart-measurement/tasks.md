## 1. Establish the scatter result contract

- [x] 1.1 Inventory all `extract_scatter_points` callers, review consumers, fixtures, mocks, and overlay/observation payload assumptions so the point-only contract has an explicit migration list.
- [x] 1.2 Define the unified scatter result types and serialization fields for image size, orientation, plot frame, axis/tick evidence, series identity, marker geometry, confidence, warnings, and bounded errors.
- [x] 1.3 Add shared validation helpers for confidence ranges, stable IDs, source-image coordinates, optional calibrated values, and incomplete evidence without fabricating defaults.
- [x] 1.4 Add structured error construction that redacts local source paths for missing, unauthorized, malformed, unsupported, and non-image inputs.

## 2. Extract neutral Cartesian fitting helpers

- [x] 2.1 Move numeric tick parsing, legend/color normalization, and line/tick fitting primitives out of private line-only coupling into a neutral Cartesian helper boundary.
- [x] 2.2 Extend fit results with usable support, residual, axis direction, and confidence metadata while preserving the line sensor's current behavior and compatible fields.
- [x] 2.3 Update line and scatter imports to use the neutral helpers and add regression coverage proving bar and line measurements are unchanged.

## 3. Infer scatter frame and orientation

- [x] 3.1 Implement scatter-specific frame candidate detection from visible axes, ticks, gridlines, marker extents, and image boundaries, retaining candidate evidence and confidence.
- [x] 3.2 Implement upright versus small-oblique orientation detection and source-image axis directions, including a bounded unknown/unsupported result for excessive skew or perspective.
- [x] 3.3 Replace fixed proportional crop assumptions in scatter extraction with the inferred frame while retaining a proportional region only as a low-priority search hint.
- [x] 3.4 Add frame and axis geometry serialization in source-image pixels and ensure fallback results never claim fabricated frame or axis evidence.

## 4. Detect markers and preserve series identity

- [x] 4.1 Restrict marker component detection to the inferred frame and retain component bounds, center, size, color, opacity/appearance evidence, and source-image coordinates.
- [x] 4.2 Associate legend entries outside the frame using normalized color and spatial evidence, with deterministic color-based identities and explicit warnings when labels are unresolved.
- [x] 4.3 Generate stable series and point IDs that remain deterministic across repeated extraction of the same image and do not merge color-distinguished series solely on coordinate overlap.
- [x] 4.4 Record merged, oversized, dense, locally occluded, and potential-outlier evidence without inferring hidden marker counts or semantic appearance values.

## 5. Calibrate axes with evidence gates

- [x] 5.1 Implement x/y tick collection and numeric transforms using source-axis projections so upright and supported oblique charts share one calibration path.
- [x] 5.2 Compute per-axis support, residual, span, and confidence and define the thresholds that qualify a transform for semantic values.
- [x] 5.3 Emit numeric x/y only when both axis transforms qualify; otherwise preserve pixel-only point evidence and identify the insufficient axis in warnings.
- [x] 5.4 Preserve partial calibration and bounded confidence for unreadable ticks, missing axes, ambiguous legends, and unsupported geometry without raising uncaught exceptions.

## 6. Render and expose visual evidence

- [x] 6.1 Update the scatter overlay to use source-image dimensions and mark the inferred frame, axis directions, ticks/calibration status, point IDs, series colors, and uncertainty evidence.
- [x] 6.2 Keep preview and Agent observation transport behavior unchanged while attaching the richer scatter payload and source-sized overlay.
- [x] 6.3 Add visual assertions or fixture checks for overlay dimensions, frame alignment, point markers, and visible uncertainty labels on clean and partial cases.

## 7. Migrate in-repository consumers

- [x] 7.1 Update review logic to consume calibrated or pixel-only scatter points explicitly, preserve warnings, and avoid treating incomplete point collections as complete datasets.
- [x] 7.2 Update chart fixtures and tool-level expectations for the unified scatter fields, including multi-series, rotated, partial-calibration, overlap, dense, and outlier cases.
- [x] 7.3 Update chart-understanding end-to-end trajectories so the Agent can combine scatter extraction, OCR, visual inspection, spec assembly, and independent validation.
- [x] 7.4 Audit frontend mock observations and TypeScript types for scatter payload assumptions, updating only stale scatter fields while preserving preview behavior.
- [x] 7.5 Update relevant OpenSpec/main documentation and repository guidance to record the scatter evidence contract and the Conda `agent`/RapidOCR execution requirement.

## 8. Verify regressions and operational boundaries

- [x] 8.1 Add focused unit tests for frame/orientation inference, axis fit quality, semantic-value gating, stable IDs, legend fallback, overlap evidence, and bounded error redaction.
- [x] 8.2 Run actual RapidOCR-backed scatter fixture tests in `conda run -n agent` and assert that clean charts retain calibrated values while partial charts retain inspectable pixel evidence.
- [x] 8.3 Run the existing bar and line focused suites plus the full Python suite in `conda run -n agent python -m pytest` to detect shared-helper regressions.
- [x] 8.4 Run frontend `npm run build` and `npm run smoke` after mock/consumer migration, then run `git diff --check` and review the final change for unintended file or payload changes.
