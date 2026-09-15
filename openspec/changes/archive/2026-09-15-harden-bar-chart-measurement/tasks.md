## 1. Unified bar-result contract

- [x] 1.1 Define the internal and serialized bar observation models for `image_size`, `orientation`, `bar_mode`, `plot_area`, `baseline`, `series`, `bars`, confidence, and warnings.
- [x] 1.2 Define one half-open source-image coordinate convention for bboxes, polygons, baseline endpoints, and overlay conversion, and add focused geometry helpers for converting between detection and drawing coordinates.
- [x] 1.3 Replace legacy bar fields with `geometry`, `measure`, `series_id`, and optional `stack` data, ensuring the new result does not emit `baseline_y`, `h_px`, `stacked`, per-bar `series`, flat `bbox`, flat `ratio`, or `stack_total_h_px`.

## 2. Bar frame and orientation inference

- [x] 2.1 Implement bar-specific plot-frame evidence that uses visible axes, shared bar edges, and candidate regions instead of treating `default_plot_area`'s crop boundary as the baseline.
- [x] 2.2 Classify vertical, horizontal, oblique, and unknown bar layouts from candidate geometry, including a bounded supported range for small affine rotation.
- [x] 2.3 Detect and fit a zero baseline as source-image endpoints with residual and confidence, preserving an oblique line when rotated evidence supports it.
- [x] 2.4 Add conservative ambiguity handling for missing zero-axis evidence, strong perspective, 3D styling, and unknown orientation so the sensor returns warnings instead of fabricated signed measurements.

## 3. Candidate extraction and measurement

- [x] 3.1 Refactor candidate extraction to retain all plausible bars before baseline alignment filtering and to support scans along both the category and value axes.
- [x] 3.2 Generate polygon geometry and source-image bboxes for each candidate while constraining color/connected-region matches to the inferred plot frame and bar-like shapes.
- [x] 3.3 Measure signed `value_length_px` along the inferred value axis and compute `measure.ratio` from absolute reliable lengths without assuming vertical height.
- [x] 3.4 Preserve category and series associations for single and grouped bars, using stable bar identifiers and explicit `category_index`/`series_id` fields.
- [x] 3.5 Represent stacked segments with parent category, optional segment index, segment length, and total stack evidence; report unresolved associations through warnings.

## 4. Overlay and evidence output

- [x] 4.1 Update the bar overlay to consume only the unified geometry result and draw each returned polygon, identity, and stack boundary in source-image coordinates.
- [x] 4.2 Draw the fitted baseline as its measured line segment rather than a full-width horizontal line, and visualize material residual or uncertainty without changing source dimensions.
- [x] 4.3 Ensure detection geometry, serialized geometry, and overlay drawing share the same edge convention, including the actual zero axis and bar bottoms on the clean fixture.

## 5. Repository consumer migration

- [x] 5.1 Migrate generated-chart review comparisons from `h_px` to `measure.value_length_px` while preserving ratio tolerance behavior for vertical and horizontal bars.
- [x] 5.2 Update chart observation unit tests, fixtures, and end-to-end trajectory assertions to the unified result shape and remove assertions for deleted legacy fields.
- [x] 5.3 Update frontend mock trace payloads and chart-understanding documentation/spec references that still describe the legacy bar fields; keep preview and visual-observation transport behavior unchanged.
- [x] 5.4 Search the repository for every removed field and eliminate stale producers, consumers, comments, and test-only compatibility assumptions.

## 6. Regression coverage

- [x] 6.1 Add a pixel-level regression for the clean upright chart showing that the fitted baseline overlaps the real zero axis/bar bottoms and preserves source dimensions in the overlay.
- [x] 6.2 Add rotated vertical-bar cases in both directions, verifying that all candidates remain, the baseline has two oblique endpoints, and residual/confidence warnings are bounded.
- [x] 6.3 Add horizontal, positive/negative/mixed-sign, grouped, and stacked fixtures verifying orientation, signed value-axis lengths, category/series identity, and stack evidence.
- [x] 6.4 Add non-chart, ambiguous, perspective/3D, and missing-image cases verifying empty or partial bounded results, structured warnings/errors, and no fabricated baseline or ratio.

## 7. Verification and cleanup

- [x] 7.1 Run the focused bar-observation and overlay tests with `conda run -n agent python -m pytest` and resolve failures without weakening the new contract.
- [x] 7.2 Run the full Python suite with `conda run -n agent python -m pytest -q`, then run `npm run build` and `npm run smoke` from `frontend`.
- [x] 7.3 Run `git diff --check`, strict OpenSpec validation, and a final repository search confirming that only the unified bar-result fields are documented and consumed.
