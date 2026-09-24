## 1. Baseline and public contract

- [x] 1.1 Inventory all chart observation producers, consumers, tests, fixtures, overlays, Review checks, and mock payloads that read layout or geometry fields.
- [x] 1.2 Capture representative upright, rotated, partial-calibration, unsupported, and malformed results for bar, line, scatter, and pie fixtures.
- [x] 1.3 Define the common evidence envelope for source image, coordinate frame, legend, series, confidence, warnings, and chart-specific mark references.
- [x] 1.4 Add contract tests asserting stable IDs, bounded confidence, source-image coordinate bounds, and valid partial results for all four sensor families.

## 2. Neutral evidence foundation

- [x] 2.1 Create the neutral foundation boundary for image size, bounded geometry, color normalization, stable evidence IDs, and structured quality metadata.
- [x] 2.2 Move generic helpers out of the Cartesian-named module and update pie, bar, line, and scatter imports to use the neutral public boundary.
- [x] 2.3 Add common evidence composition and serialization without importing a chart detector, OCR implementation, ToolResult transport, Review, or frontend module.
- [x] 2.4 Add generic legend and series association evidence that accepts OCR/text evidence as input data rather than invoking OCR internally.

## 3. Coordinate model adapters

- [x] 3.1 Define the coordinate-context contract for source frame, transform evidence, calibration status, residuals, confidence, and unsupported geometry.
- [x] 3.2 Implement the Cartesian2D context for x/y axes, origin or affine basis, tick calibration, rotation, and zero-level evidence.
- [x] 3.3 Implement the Polar2D context for circular region, center, radius, angular orientation, sector support, and rotation evidence.
- [x] 3.4 Add tests proving Cartesian charts do not require polar fields and pie charts do not require Cartesian axes or numeric ticks.
- [x] 3.5 Add calibration-gate tests proving failed transforms preserve pixel geometry while omitting unsupported semantic values.

## 4. Pie migration

- [x] 4.1 Migrate pie color, geometry, quality, association, and result assembly to the neutral foundation and Polar2D context.
- [x] 4.2 Preserve pie-specific sector, printed-value, leader-line, total-consistency, and external-label evidence.
- [x] 4.3 Migrate the pie overlay to the common source-image and warning conventions without changing its sector measurement semantics.
- [x] 4.4 Update pie tests and end-to-end assertions for the common envelope, partial evidence, path-redacted errors, and unchanged preview transport.

## 5. Line and scatter migration

- [x] 5.1 Migrate line frame, axis, tick, transform, legend, and quality assembly to the shared foundation and Cartesian2D context.
- [x] 5.2 Remove line-local duplicate axis, tick, projection, and serialization helpers after all call sites use the public foundation boundary.
- [x] 5.3 Migrate scatter frame, axis, tick, transform, legend, and quality assembly to the shared foundation and Cartesian2D context.
- [x] 5.4 Preserve line trace/marker/anchored-sample semantics and scatter marker/overlap/density/outlier semantics as independent mark evidence.
- [x] 5.5 Update line and scatter overlays to render the shared frame and axes first, then their specialized geometry from serialized source coordinates.
- [x] 5.6 Update line and scatter tests, fixtures, end-to-end flows, and mocks for the common envelope and independent detector boundaries.

## 6. Bar migration and baseline consistency

- [x] 6.1 Migrate bar frame, orientation, color, series, quality, and result assembly to the shared foundation and Cartesian2D context.
- [x] 6.2 Make visible axis and zero-level evidence the preferred baseline reference, with bar-edge fitting retained as fallback or cross-check evidence.
- [x] 6.3 Preserve vertical, horizontal, grouped, stacked, mixed-sign, and supported rotated bar geometry with stable category and series IDs.
- [x] 6.4 Emit explicit baseline disagreement, ambiguous zero-level, and unsupported-geometry warnings without fabricating signed measurements.
- [x] 6.5 Update the bar overlay and tests to assert baseline, bar polygons, frame, and source dimensions use the same coordinates.

## 7. Consumers and transport boundary

- [x] 7.1 Migrate chart Review checks to consume the public common envelope and chart-specific mark payloads rather than private sensor helpers.
- [x] 7.2 Update tool-result fixtures, end-to-end observations, session expectations, and frontend mock payloads that describe chart evidence.
- [x] 7.3 Verify the existing ToolResult, generated-image normalization, Gateway visual observation, and interactive preview contracts remain unchanged.
- [x] 7.4 Remove duplicate or unused layout fields only after repository-wide call-site checks confirm no consumer depends on them; retain documented top-level compatibility aliases still consumed by existing callers.

## 8. Validation and cleanup

- [x] 8.1 Run focused foundation, coordinate-model, and four-sensor regression tests in the `agent` Conda environment.
- [x] 8.2 Run the full Python suite, frontend build, frontend smoke checks, and any Gateway lifecycle checks required by changed consumers.
- [x] 8.3 Run strict OpenSpec validation and verify every scenario in the delta spec has corresponding automated or fixture-backed coverage.
- [x] 8.4 Run `git diff --check`, inspect the final dependency graph for forbidden detector-to-detector imports, and document the migrated public result contract.
