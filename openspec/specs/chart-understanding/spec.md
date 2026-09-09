# chart-understanding Specification

## Purpose

Give the agent deterministic sensors and a code-side assembler plus an
independent validator, so it can restore a clean annotated bar chart (U0) to a
valid ChartSpec through its own observe-reason-act loop, with the VLM doing
semantic association and tools doing measurement.

## Requirements

### Requirement: Whole-image text extraction tool

The system SHALL provide an `extract_text` tool that runs deterministic OCR on
a whole local image and returns every detected text snippet with its bounding
box and a confidence score. The tool takes no region arguments.
The tool SHALL also produce a generated overlay image that identifies the
detected text regions so the multimodal model can inspect their placement.

#### Scenario: Annotations and labels are returned with visual evidence

- **WHEN** `extract_text` is called with a synthetic bar chart image whose
  value annotations are known
- **THEN** the result contains one entry per printed text with `text`, `bbox`
  (`[x, y, width, height]`), and `confidence` in `[0, 1]`
- **AND** the value annotations appear as their exact printed strings
- **AND** a generated overlay with the source image dimensions visibly marks
  and identifies each returned text region

#### Scenario: Unreadable image reports a structured error

- **WHEN** `extract_text` is called with a path that does not exist
- **THEN** the tool returns `{"error": ...}` naming the path, and never raises
  an uncaught exception into the agent loop
- **AND** the tool produces no visual artifact

#### Scenario: No detected text still produces inspectable evidence

- **WHEN** OCR completes successfully but detects no text
- **THEN** the structured result is empty and the generated overlay preserves
  the source image so the model can inspect the absence of detections

### Requirement: Bar geometry measurement tool

The system SHALL provide a `measure_bars` tool that deterministically detects
bars in a clean bar-chart image and returns, per bar, its bounding box, pixel
height, stable visual identifier, and height ratio normalized to the shortest
bar. It SHALL also produce a generated overlay that marks each returned bar
and the detected baseline using the same identifiers as the structured result.

#### Scenario: Bar ratios and overlay track the detected bars

- **WHEN** `measure_bars` is called with a synthetic bar chart whose values are
  known
- **THEN** the number of detected bars equals the true count
- **AND** each bar's height ratio equals the true value ratio within 10%
  relative tolerance
- **AND** a generated overlay with the source image dimensions visibly marks
  every returned bar, its identifier, and the detected baseline

#### Scenario: Non-chart image remains inspectable

- **WHEN** `measure_bars` is called with an image containing no detectable
  bars
- **THEN** the tool returns an empty bars list (not an error), so the agent can
  observe "no bars found" and re-plan
- **AND** the generated overlay preserves the source image and indicates that
  no baseline or bars were detected

#### Scenario: Missing image reports a structured error

- **WHEN** `measure_bars` is called with a path that does not exist
- **THEN** the tool returns `{"error": ...}` naming the path, produces no
  visual artifact, and never raises an uncaught exception into the agent loop

### Requirement: Code-side ChartSpec assembly tool

The system SHALL provide an `assemble_spec` tool that constructs a ChartSpec
from typed arguments (chart type, title, axis labels, points, source) in code
and returns its dictionary form; the model never hand-writes IR JSON.

#### Scenario: Valid arguments produce a schema-shaped spec

- **WHEN** `assemble_spec` is called with a bar chart type and category/value
  points
- **THEN** the returned dictionary round-trips through `ChartSpec.from_dict`
  and `to_dict` unchanged
- **AND** metadata carries the provided source provenance

#### Scenario: Malformed points are rejected as structured errors

- **WHEN** `assemble_spec` is called with points lacking required fields or a
  chart type outside the enumeration
- **THEN** the tool returns `{"error": ...}` describing the offending input and
  produces no spec

### Requirement: Independent ChartSpec validation tool (Critic)

The system SHALL provide a `validate_spec` tool that checks a given spec
dictionary via `from_dict` plus `validate()` and returns
`{"ok": bool, "issues": [...]}`. Validation is a separate agent action, never
embedded in extraction or assembly.

#### Scenario: Clean spec passes

- **WHEN** `validate_spec` is called with a spec assembled from valid inputs
- **THEN** the result is `{"ok": true, "issues": []}`

#### Scenario: Invalid spec reports located issues without crashing

- **WHEN** `validate_spec` is called with a spec whose dataset is empty or
  whose points mix incompatible shapes
- **THEN** the result is `{"ok": false, "issues": [...]}` with each issue
  carrying a location and message
- **AND** no exception escapes to the agent loop

### Requirement: U0 end-to-end restoration through the ReAct loop

The system SHALL enable the agent, given a clean annotated bar chart through
the normal image-attachment path and the registered chart tools, to produce a
ChartSpec whose dataset matches the chart's true values. The attachment path
needed by local-image tools SHALL be available to the model without the user
repeating it. The infrastructure MUST NOT force a fixed tool sequence or
require ChartSpec output for every image turn.

#### Scenario: Freely planned annotated bar-chart restoration

- **WHEN** the user attaches a synthetic bar chart with printed value
  annotations through the standard agent REPL and asks for the underlying data
- **THEN** the agent can choose and call relevant sensors, assembly, and
  validation tools without a caller-supplied workflow prompt
- **AND** the dataset values equal the ground-truth values used to draw the
  chart

#### Scenario: Image question does not require restoration

- **WHEN** the user asks a descriptive question that does not require
  structured chart data
- **THEN** the agent can answer without assembling or validating a ChartSpec

#### Scenario: OCR misread is caught by geometric cross-check

- **WHEN** the agent uses annotation values and bar-height ratios and those
  evidence channels disagree beyond tolerance
- **THEN** the agent re-examines the evidence before assembling, and the final
  spec uses the values consistent with bar geometry

### Requirement: Chart tools registered for the agent REPL

The system SHALL register the four chart tools alongside the built-in tools
when the agent REPL starts, following the existing tool protocol (JSON
observations, structured errors).

#### Scenario: REPL exposes chart tools

- **WHEN** the `--agent` REPL starts
- **THEN** the tool registry contains `extract_text`, `measure_bars`,
  `assemble_spec`, and `validate_spec` in addition to the built-ins
