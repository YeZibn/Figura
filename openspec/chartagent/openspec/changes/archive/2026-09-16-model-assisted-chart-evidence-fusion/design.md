## Context

See `proposal.md` for the motivation and scope. The current runtime already
has a multimodal Agent loop, authorized image tools, four chart-specific
observation tools, shared source-image evidence envelopes, a model-guided
layout context, and separate `assemble_spec` / `validate_spec` actions.

The current prompt encourages layout inspection before geometry measurement,
and the Agent can silently create a deterministic layout fallback when a
geometry tool is called without a cached context. A supplied layout context can
also influence a sensor's measurement area. The change must preserve the
attachment boundary, native tool protocol, bounded observations, and existing
chart-specific algorithms while preventing a model layout guess from becoming
the only geometric evidence.

## Goals / Non-Goals

**Goals:**

- Make the multimodal model the semantic orchestrator and final evidence
  integrator for chart restoration.
- Let the model call OCR, chart geometry, and layout tools selectively when a
  particular field or relationship is uncertain.
- Keep tool observations attributable, bounded, and useful for another model
  turn, including source-sized overlays where available.
- Treat layout hints as soft priors and preserve independent pixel detection,
  especially for axes, baselines, rotated charts, and horizontal charts.
- Surface field-level conflicts before semantic ChartSpec assembly.
- Preserve a short path for clear charts and a recoverable path for ambiguous
  charts without requiring all four sensors.

**Non-Goals:**

- Replacing rapidocr or rewriting the four chart detectors' core CV algorithms.
- Making `inspect_chart_layout` a new image-understanding model or asking it to
  infer chart values.
- Forcing every chart question to produce a ChartSpec or use a sensor.
- Treating `validate_spec` as proof that source-image values are visually true.
- Changing attachment authorization, generated-chart review/publication rules,
  or the frontend preview protocol.

## Decisions

### 1. Use model-led, uncertainty-driven orchestration

The stable system prompt will describe a model-first evidence loop rather than
a fixed phase sequence. For a restoration request, the model first uses the
multimodal image as a semantic hypothesis, identifies unresolved fields, and
then selects only the relevant observer. If the chart is clear, it may call
`assemble_spec` directly. If text, geometry, orientation, or association is
uncertain, it may call OCR, a chart sensor, or layout inspection before
assembling.

An explicit perception-draft tool is not introduced in the first iteration.
The model's hypothesis remains in its assistant/tool-call context, while the
structured evidence returned by tools provides the durable machine-readable
boundary. This keeps the first change small and avoids creating a second
semantic data model before the evidence contract is proven.

**Alternative considered:** always call every sensor before assembly. Rejected
because it adds latency, produces unrelated evidence, and conflicts with the
existing freely planned chart behavior.

### 2. Keep evidence typed and source-specific

All chart observations will expose a bounded common summary identifying the
evidence kind (text, geometry, layout, or visual artifact), source tool, source
attachment, confidence, warnings, and the relevant pixel or normalized
regions. Chart-specific payloads remain specialized: bar baselines and bar
geometry, line traces and anchors, scatter markers, and pie sectors.

The model will receive both the structured tool message and any valid visual
observation through the existing Agent multimodal path. The summary will be
bounded so a large OCR result or trace does not consume the whole context.

**Alternative considered:** flatten all observations into one canonical data
answer. Rejected because it hides provenance and makes it impossible for the
model to distinguish an OCR candidate from a pixel measurement.

### 3. Make layout context advisory and preserve independent CV

`inspect_chart_layout` remains available, but the Prompt describes it as a
targeted layout-hypothesis validator for rotation, horizontal layout, dense
annotations, or spatial conflicts. It is not a universal precondition.

The Agent will not create a hidden layout preflight solely because a geometry
tool was called. Sensors without a layout context continue their own bounded
frame and axis detection. When a layout context is supplied, explicit valid
fields can narrow or annotate the search, but independent axis, frame, mark,
and baseline evidence remains available and can report disagreement.

Partial or rejected layout hints will not be treated as authoritative
measurement frames. A layout hint can assist a sensor only after the relevant
field passes its validation; a partial frame must not suppress independent
detection.

**Alternative considered:** make the model layout context the canonical frame
for all sensors. Rejected because an inaccurate model frame can create circular
confirmation and is insufficient to diagnose baseline-to-axis residuals.

### 4. Resolve conflicts by field, not by one global authority

The design uses domain-specific evidence roles instead of declaring the model,
OCR, or CV universally correct:

| Field | Primary evidence | Supporting evidence |
| --- | --- | --- |
| Chart type, title, semantic intent | Multimodal model | OCR |
| Printed labels and numeric annotations | OCR | Model visual reading, geometry |
| Plot frame, axes, baseline, mark bounds | CV geometry | Layout hint, model visual reading |
| Legend-to-series association | Model reasoning | OCR, color and spatial evidence |
| Numeric calibration | Axis/tick geometry | OCR and model interpretation |

When candidates disagree, the model receives both candidates and warnings. It
may request a targeted retry, choose a supported candidate with an explicit
confidence, or preserve the value as unresolved. No adapter or sensor silently
rewrites a competing source claim.

### 5. Keep assembly mechanical and validation layered

After evidence fusion, the model calls `assemble_spec` with the semantic
dataset it is prepared to defend. `assemble_spec` remains responsible for
ChartSpec construction and field/type constraints. `validate_spec` remains an
independent structural critic. Neither operation is treated as visual proof.

For generated charts, the existing render and review/publication gate remains
unchanged. For analysis-only turns, the model can return a qualified answer
without assembling a spec when the user did not ask for structured data.

### 6. Verify behavior with a staged matrix

Tests will cover the short path and the evidence-assisted path separately:

1. Clear bar, line, pie, and scatter images can reach assembly without an
   implicit layout call.
2. OCR is selected for unreadable Chinese labels or numeric annotations.
3. Geometry evidence is selected for bar baseline, line trace, scatter marker,
   and pie-sector uncertainty.
4. Horizontal and small-rotation cases preserve independent source coordinates.
5. A deliberately offset layout hint does not suppress the detected baseline
   or axis and produces a conflict warning.
6. Multi-series and conflicting OCR/CV candidates remain attributable and do
   not become silently certain.
7. Descriptive image questions remain free of unnecessary assembly or sensor
   calls.

## Risks / Trade-offs

- **[Risk]** The model may skip an observer that would have improved accuracy.
  **→ Mitigation:** make tool descriptions explicit about uncertainty triggers,
  retain warnings in the next model context, and add real-image chain tests
  that measure both accuracy and unnecessary calls.

- **[Risk]** Direct model assembly can overstate visually guessed values.
  **→ Mitigation:** distinguish assembly validity from visual truth, preserve
  evidence warnings, and require qualified final language for unresolved
  fields.

- **[Risk]** Multiple evidence payloads can exceed the context budget.
  **→ Mitigation:** keep bounded summaries, stable references, compact overlays,
  and only retain the relevant evidence for the current attachment and task.

- **[Risk]** A layout hint can bias a geometry detector into circular agreement.
  **→ Mitigation:** remove hidden fallback injection, preserve independent
  frame/axis/baseline detection, and compare model layout with pixel evidence.

- **[Risk]** Existing callers depend on fallback layout behavior.
  **→ Mitigation:** keep direct Python sensor compatibility, make the change
  additive at the evidence boundary, and cover fallback and no-context calls
  in regression tests before changing Agent behavior.

## Migration Plan

1. Capture current Agent traces and baseline sensor outputs for representative
   chart fixtures and the supplied real chart image.
2. Update the stable Prompt and tool-facing guidance to describe model-led,
   uncertainty-driven evidence planning.
3. Add or normalize bounded evidence summaries and conflict metadata without
   changing attachment authorization or chart-specific measurement semantics.
4. Remove the Agent's hidden layout preflight dependency; preserve sensor-only
   operation when no layout context is explicitly supplied.
5. Adjust layout-context consumption so partial hints remain advisory and
   independent geometric evidence remains visible.
6. Run narrow Python tests, the full `agent`-environment suite, real-image
   integration checks, `git diff --check`, and OpenSpec strict validation.

Rollback can restore the prior Prompt and hidden fallback behavior while
retaining the additive evidence fields. No attachment, persisted ChartSpec, or
frontend protocol migration is required.
