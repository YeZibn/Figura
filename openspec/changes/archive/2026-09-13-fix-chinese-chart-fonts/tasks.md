## 1. Font Resolution

- [x] 1.1 Add a bounded CJK font resolver with `CHARTAGENT_FONT_PATH` override and ordered cross-platform system-family lookup.
- [x] 1.2 Define resolved-font metadata and fallback warnings without exposing local font paths through Gateway payloads.
- [x] 1.3 Keep the resolver per-render and avoid mutating global Matplotlib `rcParams` or font cache state.

## 2. Renderer Integration

- [x] 2.1 Apply the resolved font to titles, axis labels, ticks, legends, and annotations in Cartesian charts.
- [x] 2.2 Apply the resolved font to pie labels and percentage text, preserving current values, dimensions, and chart layout.
- [x] 2.3 Preserve bounded `ToolResult` and generated-artifact behavior when the configured or system font is unavailable.

## 3. Tests and Verification

- [x] 3.1 Add resolver tests for configured, system-discovered, invalid, and unavailable font cases.
- [x] 3.2 Add Chinese rendering coverage for bar, line, pie, and scatter titles, labels, legends, ticks, and annotations where applicable.
- [x] 3.3 Assert font status and warning semantics while retaining existing PNG dimension, metadata, validation, and artifact assertions.
- [x] 3.4 Run `conda run -n agent python -m pytest -q`, `npm --prefix frontend run build`, and `npm --prefix frontend run smoke`.
