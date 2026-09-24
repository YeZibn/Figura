## 1. Evidence contract and baseline

- [x] 1.1 Record current Agent traces and sensor outputs for clean bar, line, pie, and scatter fixtures plus the representative real chart image, including tool-call count, warnings, confidence, and overlays.
- [x] 1.2 Define the bounded common evidence summary used by OCR, geometry sensors, and layout inspection, including evidence type, source tool, attachment identity, confidence, warnings, and source-image references.
- [x] 1.3 Add focused unit coverage proving evidence summaries remain JSON-safe, bounded, attributable, and distinguish text, geometry, layout, and visual artifact evidence.

## 2. Model-led adaptive orchestration

- [x] 2.1 Update the stable Agent Prompt to describe model-first visual hypothesis, uncertainty-driven OCR/CV selection, direct `assemble_spec` for clear charts, and qualified handling of unresolved values.
- [x] 2.2 Update chart tool descriptions and model-visible guidance so `inspect_chart_layout` is a targeted layout-hypothesis validator rather than a universal precondition.
- [x] 2.3 Remove the Agent's hidden automatic layout preflight dependency for geometry calls; preserve independent sensor operation when no explicit layout context is supplied.
- [x] 2.4 Preserve run-scoped tool observations and bounded visual observations so the model can fuse multiple evidence sources on a later turn without exposing local paths or image bytes.

## 3. Soft layout and conflict handling

- [x] 3.1 Change layout-context consumption so accepted fields can assist measurement while partial or rejected hints cannot become an authoritative frame or suppress independent axis, mark, or baseline detection.
- [x] 3.2 Add bounded conflict diagnostics for model layout versus independent geometry and for OCR values versus geometry/calibration evidence, preserving candidates, sources, and warnings without silent overwrite.
- [x] 3.3 Ensure bar baseline, line frame, scatter frame, and pie center/radius results retain independent pixel evidence when a layout hint disagrees or is absent.
- [x] 3.4 Verify `assemble_spec` and `validate_spec` remain mechanical structural operations and that successful assembly is not reported as visual verification.

## 4. Regression and real-chain acceptance

- [x] 4.1 Add Agent-loop tests showing a clear chart can call `assemble_spec` without `inspect_chart_layout` and a descriptive image question does not require restoration tools.
- [x] 4.2 Add targeted orchestration tests showing OCR is selected for text uncertainty, chart sensors for geometry uncertainty, and layout inspection only for relevant spatial uncertainty.
- [x] 4.3 Add rotated, horizontal, and deliberately offset-layout cases proving independent geometry remains source-aligned and baseline/axis conflicts are surfaced.
- [x] 4.4 Add multi-series and conflicting-evidence cases proving semantic associations, candidate values, confidence, and warnings remain attributable through final assembly.
- [x] 4.5 Run the supplied real chart through the frontend/Gateway Agent path, compare the evidence trace with the recorded baseline, and document remaining limitations.
- [x] 4.6 Run focused tests, `conda run -n agent python -m pytest -q`, frontend build and smoke checks when affected, `git diff --check`, and `conda run -n agent openspec validate --all --strict`.
