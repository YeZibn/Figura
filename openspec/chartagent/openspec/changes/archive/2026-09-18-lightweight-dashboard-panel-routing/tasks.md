## 1. Lightweight decomposition contract

- [x] 1.1 Change the default dashboard segmentation policy to validated VLM rectangular bounds with bounded padding; ensure `auto` never loads SAM from an environment checkpoint.
- [x] 1.2 Keep the optional SAM adapter behind an explicit mode, preserve bounded fallback behavior, and update segmentation provenance/status fields for deterministic results.
- [x] 1.3 Separate panel scope metadata from optional boundary evidence, including stable `panel_id`, source bbox, local origin, transform, confidence, and warnings.
- [x] 1.4 Update `decompose_chart_image` schemas, descriptions, overlays, and runtime prompt text so SAM is optional and OCR is not used for topology discovery.

## 2. Panel routing and recovery

- [x] 2.1 Add a bounded run-scoped panel index keyed by source attachment and `panel_id`, containing the analysis scope, source transform, chart hint, and uncertainty.
- [x] 2.2 Resolve `panel_id` in Agent geometry-tool dispatch and reject stale, cross-attachment, or unknown panel references without silently scanning the full dashboard.
- [x] 2.3 Persist and restore panel scopes through checkpoint layout context so reconnect and continuation retain the same panel routing.
- [x] 2.4 Preserve the existing authorized attachment boundary and generated-image observation path without exposing local paths or introducing a derived attachment protocol.

## 3. Sensor-local analysis and coordinate mapping

- [x] 3.1 Add a shared panel-scope input/ROI path for bar, line, scatter, and pie sensors while preserving direct whole-image behavior when no panel is supplied.
- [x] 3.2 Make sensors use the panel scope as a search boundary and independently detect their chart-specific measurement frame, axes, baseline, center, marks, and calibration.
- [x] 3.3 Map local sensor geometry, overlays, warnings, and evidence back to the source-image coordinate convention using the declared origin and transform.
- [x] 3.4 Keep title, legend, tick, and data-label regions as annotation evidence so they do not become chart marks solely because they are inside a panel crop.
- [x] 3.5 Return bounded routing errors or explicitly labeled source-ROI fallbacks when a panel scope cannot be resolved.

## 4. Regression and integration coverage

- [x] 4.1 Update dashboard decomposition tests to assert deterministic operation without a SAM checkpoint and explicit opt-in behavior for the optional backend.
- [x] 4.2 Add tests for panel-scope registration, `panel_id` dispatch, cross-attachment rejection, checkpoint restoration, and bounded fallback behavior.
- [x] 4.3 Add sensor tests proving bar, line, pie, and scatter measurements are constrained to the selected panel scope and retain source coordinates.
- [x] 4.4 Add an end-to-end fixture test for `dashboard_text_two_bars_pie.png` that decomposes the image, measures both bar panels and the pie panel, and verifies panel-local evidence.
- [x] 4.5 Add regression coverage showing adjacent dashboard panels, titles, and legends do not become marks or calibrated plot geometry by default.

## 5. Verification and specification alignment

- [x] 5.1 Update the affected tool and architecture documentation to describe PanelRegion, AnalysisScope, MeasurementFrame, and source-coordinate provenance.
- [x] 5.2 Run focused dashboard and chart-understanding tests in `conda run -n agent` and verify the no-SAM path does not import or require `segment_anything`.
- [x] 5.3 Run the full Python suite, `git diff --check`, frontend build, and frontend smoke checks; validate the change with strict OpenSpec validation.
