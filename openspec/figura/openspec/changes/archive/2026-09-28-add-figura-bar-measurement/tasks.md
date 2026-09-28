## 1. Implement the Bar Measurement Sensor

- [x] 1.1 Add a pure bar-measurement sensor that accepts image bytes and returns JSON-compatible geometry without local paths or overlay payloads.
- [x] 1.2 Implement supported single, grouped, and stacked bar detection with vertical, horizontal, and reportable oblique orientation in the selected source's pixel coordinates.
- [x] 1.3 Return baseline, signed pixel lengths, `ratio_to_shortest`, bounded confidence, status, and warnings; preserve geometry and null numeric measurements when calibration is uncertain.

## 2. Add the Model-Facing Tool

- [x] 2.1 Define `measure_bars` input and result schemas using `source_kind` and `source_id`, with no path, URL, or image-byte parameters.
- [x] 2.2 Resolve Attachments and Panels only through the target Run's `RunExecutionState` inventories and their corresponding source services; map source-read failures to bounded tool errors.
- [x] 2.3 Register the additive `replay_safe` tool in `src/figura/bootstrap.py` while retaining the existing registry version and all existing definitions unchanged.

## 3. Project Measurement Outcomes into RunExecutionState

- [x] 3.1 Add an immutable measurement-observation projection and rebuild it from committed `measure_bars` call/result facts across the target Session, ordered by Run ordinal and tool-call order.
- [x] 3.2 Preserve call ID, attempt ID, source identity, outcome, and the complete bounded result or error; exclude unresolved attempts, unauthorized sources, and other Sessions without adding a separate store.
- [x] 3.3 Keep the Provider image-inventory message unchanged so the measurement projection does not duplicate tool-result messages already present in Session history.

## 4. Verify Contracts and Regression Behavior

- [x] 4.1 Add sensor coverage for supported bar layouts, missing or uncertain baselines, no detected bars, unsupported perspective/3D-like geometry, and source-coordinate output.
- [x] 4.2 Add tool tests for authorized Attachment and Panel reads, prior-Run source access, rejected or cross-Session IDs, bounded failures, and absence of paths or image bytes in results.
- [x] 4.3 Add RunExecutionState tests for ordered cross-Run committed outcomes, success and failure projections, and exclusion of unresolved or uncommitted attempts.
- [x] 4.4 Verify historical Session tool messages still assemble with the retained registry version; run focused Figura regressions and the complete Python test suite in the `agent` environment.
- [x] 4.5 Validate the OpenSpec change and its delta specifications.
