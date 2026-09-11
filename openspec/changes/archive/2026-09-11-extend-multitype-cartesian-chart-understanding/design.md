## Context

The current understanding side has deterministic OCR and bar geometry tools,
an attachment-aware registry boundary, bounded in-memory visual observations,
and a `ChartSpec` IR that already represents line points and an optional
`DataPoint.series`. The missing capability is reliable sensor evidence for
Cartesian line charts and multi-series bars, plus a clear contract for keeping
pixel evidence separate from semantic chart data.

The change must continue to run deterministic sensor tests in the `agent`
Conda environment, preserve the existing single-series bar result, keep image
bytes inside the tool-observation boundary, and leave tool selection to the
Agent. See `proposal.md` and the delta specs for the motivation and behavior
contract.

## Goals / Non-Goals

**Goals:**

- Add a line-series sensor and extend bar measurement to grouped and supported
  stacked layouts.
- Give Cartesian sensors a shared, inspectable representation of plot area,
  axis calibration, legend evidence, series identity, confidence, warnings,
  and one or more bounded overlays.
- Preserve semantic distinction between series when converting sensor output to
  `ChartSpec`.
- Keep existing path-based Python sensor calls useful for offline tests while
  using opaque authorized attachment IDs in the Agent-facing registry.
- Make ambiguity visible to the Agent so it can retry, inspect the image again,
  or answer without claiming a complete restoration.

**Non-Goals:**

- A universal chart-understanding pipeline or a mandatory tool order.
- Pie/scatter extraction, chart rendering, frontend changes, or Tauri/Rust
  work.
- Storing source image bytes, pixel crops, or generated overlay bytes in
  `ChartSpec`.

## Decisions

### 1. Keep sensors specialized and planning optional

`extract_text`, `measure_bars`, and the new `extract_line_series` remain
independent tools. Each tool can return useful partial evidence and the Agent
decides whether to combine it with OCR, `load_image`, `assemble_spec`, or
`validate_spec`. No coordinator will force a fixed OCR-then-geometry sequence;
this preserves the existing ReAct behavior and supports non-restoration image
questions.

The registry will expose the new sensor through the same `Tool` protocol and
the same attachment wrapper used by the existing image sensors. Direct Python
functions may continue to accept a validated local path for deterministic
tests, but model-facing schemas will expose only `attachment_id`.

### 2. Use a shared evidence envelope with backward-compatible sensor payloads

Cartesian sensor data will carry common fields conceptually equivalent to:

```text
image_size: [width, height]
plot_area: {bbox: [x, y, width, height], confidence: number} | null
axes: {x: ..., y: ...}
legend: [{id, label?, color?}]
series: [{id, label?, color?, ...geometry...}]
confidence: {overall, geometry?, calibration?, association?}
```

The exact geometry remains sensor-specific. `measure_bars` keeps its current
top-level `bars` and `baseline_y` keys and adds category/series associations
when available. `extract_line_series` returns ordered point geometry grouped by
series. Missing fields are represented by `null`, an empty collection, or a
warning instead of a guessed value. Confidence numbers are normalized to
`[0, 1]`; warnings are carried through the existing `ToolResult.warnings`
channel and remain visible in normalized observations.

This allows future sensors to share enough context for the Agent without
creating a large base class or coupling all detection algorithms to one
pipeline.

### 3. Calibrate pixels only when axis evidence supports it

The sensors will first locate a plot region and axis/tick evidence, then map
pixel coordinates to semantic values using the detected tick positions and
labels. Category bars use ordered x positions and category labels; line points
use calibrated x/y values. When calibration is incomplete, the tool preserves
pixel coordinates and emits a warning rather than fabricating numeric values.

The first implementation will use the existing Pillow/NumPy stack and the
existing OCR boundary. Color masks, quantization, connected components, and
line continuity are sufficient for the clean generated fixtures in this
change. A new image-processing dependency is not part of the design; it would
need a separate compatibility decision if real-chart evaluation shows the
current stack is insufficient.

### 4. Treat legend labels and colors as association evidence, not IR identity

Color and pixel bounding boxes are useful for matching a detected geometry to a
legend entry, so sensors and overlays will return them when available. The
semantic output passed to `assemble_spec` uses the resolved series label in
`DataPoint.series`; color and pixel provenance stay in the tool observation.
This keeps `ChartSpec` portable for generation and avoids making renderers
depend on a particular source image's palette.

### 5. Extend assembly and validation without changing the IR shape for old data

`assemble_spec` will accept an optional `series` field on each point and retain
it in the existing `DataPoint` shape. It will validate series labels and
confidence values before constructing the spec. `ChartSpec.validate()` will
enforce the same bounded confidence and point-shape rules, while still
accepting legacy points that omit `series`.

No image or overlay payload is added to the IR. The existing source metadata
and point confidence fields provide lightweight provenance; any richer visual
evidence remains in the Agent trace and tool observation.

### 6. Reuse the existing visual-observation limits

Sensor overlays will be created as in-memory `GeneratedImage` values and
normalized through the existing image MIME, count, and byte-size limits. A
sensor may omit an overlay only for an invalid or unauthorized input; uncertain
successful detections still produce inspectable source-sized evidence when
possible. This preserves Gateway event contracts and prevents local paths from
leaking through model-facing results.

### 7. Validate through offline fixtures before provider-loop tests

Fixtures will cover clean single-series lines, multi-series lines with legends,
grouped bars, supported stacked bars, missing calibration, blank/non-chart
images, and malformed attachments. Sensor tests will assert structured fields,
ratios/calibrated values, warnings, overlay dimensions, and backward
compatibility. An offline scripted Agent loop will then verify that the new
tool is selectable and that series survive assembly and independent critique;
provider calls are not required for the deterministic test suite.

## Risks / Trade-offs

- [Risk] Similar colors, anti-aliased lines, or overlapping series can merge in
  pixel masks. -> Mitigation: retain stable geometry IDs, emit association and
  confidence warnings, and allow the Agent to use OCR or `load_image` for a
  second observation.
- [Risk] Axis OCR may find labels but not enough tick/value pairs for a valid
  scale. -> Mitigation: return pixel evidence with explicit uncalibrated
  warnings and never invent semantic numbers.
- [Risk] Stacked bars are ambiguous when segment colors are reused. ->
  Mitigation: preserve total stack geometry and mark unresolved segments rather
  than presenting an incorrect series assignment.
- [Risk] Adding fields to sensor results can surprise existing consumers. ->
  Mitigation: retain the current single-series keys and only add fields; add
  regression tests for old fixtures and normalized observations.
- [Risk] A richer tool observation can approach transport limits. -> Mitigation:
  reuse `ToolResult` normalization, emit a bounded number of source-sized
  overlays, and keep large evidence out of `ChartSpec`.
- [Risk] Clean synthetic fixtures may overstate real-world accuracy. ->
  Mitigation: report confidence and warnings as first-class output and defer
  broad chart-style claims until additional fixture families are available.

## Migration Plan

1. Add the shared result helpers and line sensor without changing existing
   single-series callers.
2. Extend bar detection, assembly, validation, registration, and the Agent
   system-tool description behind the existing registry boundary.
3. Add fixtures and run the offline test suite in the `agent` Conda
   environment, then run the existing full test and frontend smoke checks.
4. If a regression is found, disable the new sensor registration and retain the
   existing bar path while correcting the detector; no stored ChartSpec data
   migration is required because the IR remains backward compatible.

