## 1. Shared observation scope

- [x] 1.1 Define the strict `observation_scope` schema shared by `extract_text`, `measure_bars`, `measure_lines`, `measure_scatter`, and `measure_pie`: optional include/exclude arrays, 1–4 polygons per supplied array, 3–32 points per polygon, and integer normalized coordinates in `0..1000`.
- [x] 1.2 Implement scope validation and a source-sized include-union-minus-exclude mask; reject malformed and empty effective scopes without falling back to full-image analysis.
- [x] 1.3 Add focused tests for omitted scope, include union, exclusions taking precedence, irregular polygons, coordinate boundaries, invalid shapes, and empty effective masks.

## 2. Apply scope to Cartesian measurements

- [x] 2.1 Pass the shared mask into bar, line, and scatter geometry detection, OCR, and association while keeping result coordinates in the original Attachment or Panel frame.
- [x] 2.2 Keep the observation scope separate from detected/calibrated plot areas and preserve existing result contracts for bars, lines, and scatter points.
- [x] 2.3 Add tests showing each Cartesian tool excludes out-of-scope evidence, keeps source-pixel coordinates, and returns a bounded failure for invalid scopes.

## 3. Register bounded OCR extraction

- [x] 3.1 Add the authorized `extract_text` tool for Attachment and Panel sources using the shared scope and existing OCR recognizer.
- [x] 3.2 Return the specified source identity, dimensions, coordinate system, availability, truncation, and bounded snippet fields; set truncation for both snippet-count and text-length limits.
- [x] 3.3 Add tests for authorized and rejected sources, available-empty and unavailable OCR, scoped source coordinates, and both truncation limits.

## 4. Add pie measurement

- [x] 4.1 Implement `measure_pie` as a polar sensor that reuses authorized source resolution, scope masking, OCR, and bounded tool results without using Cartesian axes.
- [x] 4.2 Return the specified plot region, ordered sector angles, nullable ratios, color/label associations, confidence, status, and warnings; apply the coverage and boundary-support gates from the spec.
- [x] 4.3 Add tests for supported circular pies, ratio gates, partial evidence, no-evidence images, unsupported donut/exploded/elliptical/perspective/3D geometry, and source authorization.

## 5. Extend the Run measurement projection

- [x] 5.1 Include committed `measure_pie` results in the existing `RunExecutionState.measurements` projection, preserving call/result/source validation and chronological ordering.
- [x] 5.2 Add projection tests for successful and failed pie results, prior-Run ordering, and keeping `extract_text` outside the measurement projection.

## 6. Rebuild visual feedback for the next Provider request

- [x] 6.1 Add transient OCR and pie annotations derived from committed JSON results and authorized source images; keep image bytes out of durable tool results.
- [x] 6.2 Extend request assembly to include OCR and pie feedback only from the immediately preceding fully committed tool batch, preserving tool identity/call association and existing Provider image limits.
- [x] 6.3 Add request tests for successful annotations, old-batch image omission, missing or invalid sources, and image-limit failure before Provider-attempt claim.

## 7. Register the versioned tool contract

- [x] 7.1 Register `extract_text` and `measure_pie`, attach scope schemas to all five observation tools, advance the web registry to `figura-web-v4`, and update the system tool guidance.
- [x] 7.2 Add registry and history tests confirming new calls use v4, completed older tool interactions remain inert history, and unresolved calls fail closed without aliases or old handlers.

## 8. Verify the completed change

- [x] 8.1 Run the focused scope, tool, projection, and request tests in the `agent` Conda environment.
- [x] 8.2 Run the full Python test suite and `git diff --check`; resolve regressions before marking the change complete.
