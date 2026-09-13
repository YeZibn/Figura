## 1. Shared Generation Validation

- [x] 1.1 Define a pure, dependency-light generation validation result and
  issue representation with bounded code, severity, location, and message
  fields while preserving the existing `ok` and `issues` compatibility shape.
- [x] 1.2 Move chart-type generation rules into the shared validation layer and
  route `assemble_spec`, `validate_spec`, and `render_chart` through the same
  eligibility checks.
- [x] 1.3 Validate canonical category and series identity, duplicate
  category-series pairs, complete grouped-bar category coverage, finite
  values, pie totals, and supported axis-range declarations.

## 2. Renderer Semantics and Figure Audit

- [x] 2.1 Remove implicit zero filling for missing grouped-bar cells and return
  a located blocking issue unless the caller supplies an explicit zero.
- [x] 2.2 Apply accepted numeric axis bounds to the rendered axes and reject
  values outside declared bounds or unsupported ranges before publication.
- [x] 2.3 Add an in-memory post-layout audit that draws the canvas, verifies
  chart-type-specific artists against the ChartSpec, and checks category,
  series, point, bar, and pie-sector coverage.
- [x] 2.4 Add display-coordinate bounds checks for visible titles, axis labels,
  tick labels, annotations, and legends, classifying minor crowding as a
  warning and critical clipping or fidelity mismatch as a failure.
- [x] 2.5 Ensure every blocking audit issue closes the figure without creating
  or returning a generated image payload.

## 3. Encoded Artifact and Result Contract

- [x] 3.1 Verify the saved PNG with Pillow, fully load it after verification,
  enforce exact format and dimensions, enforce the existing byte limit, and
  reject empty or effectively blank output.
- [x] 3.2 Build the bounded validation summary with semantic, fidelity, layout,
  readability, and artifact check statuses for successful renders, preserving
  existing font fallback warnings.
- [x] 3.3 Preserve existing generated-chart metadata, image transport limits,
  Gateway artifact kind, and opaque-reference behavior while ensuring the new
  validation data contains no image bytes, local paths, or provider payloads.

## 4. Regression and Quality Tests

- [x] 4.1 Add validator-parity tests proving that standalone validation and
  rendering agree on negative or zero-total pies, duplicate points, missing
  grouped-bar data, invalid ranges, and finite-value constraints.
- [x] 4.2 Add renderer tests for explicit zero values, category and series
  fidelity, applied axis bounds, and chart-type-specific artist coverage.
- [x] 4.3 Add layout tests covering long Chinese titles and labels, dense
  legends, annotations near canvas edges, clipping, and warning versus failure
  classification without relying on exact PNG snapshots.
- [x] 4.4 Add artifact tests for PNG verification, full loading, exact
  dimensions, byte limits, blank output, bounded diagnostics, and the absence
  of raw bytes or local paths in serialized results.
- [x] 4.5 Update existing chart-generation expectations for the additive
  validation metadata and the intentional missing-data behavior change.

## 5. Verification

- [x] 5.1 Run the focused chart-generation test modules in the `agent` Conda
  environment and resolve renderer or validator regressions.
- [x] 5.2 Run the complete Python test suite with `conda run -n agent python
  -m pytest -q`.
- [x] 5.3 Run strict OpenSpec validation for the change and main specs, then
  run `git diff --check`.
