## Purpose

Give the agent deterministic sensors and a code-side assembler plus an
independent validator, so it can restore a clean annotated bar chart (U0) to a
valid ChartSpec through its own observe-reason-act loop, with the VLM doing
semantic association and tools doing measurement.

## ADDED Requirements

### Requirement: Whole-image text extraction tool

The system SHALL provide an `extract_text` tool that runs deterministic OCR on
a whole local image and returns every detected text snippet with its bounding
box and a confidence score. The tool takes no region arguments.

#### Scenario: Annotations and labels are returned

- **WHEN** `extract_text` is called with a synthetic bar chart image whose
  value annotations are known
- **THEN** the result contains one entry per printed text with `text`, `bbox`
  (`[x, y, width, height]`), and `confidence` in `[0, 1]`
- **AND** the value annotations appear as their exact printed strings

#### Scenario: Unreadable image reports a structured error

- **WHEN** `extract_text` is called with a path that does not exist
- **THEN** the tool returns `{"error": ...}` naming the path, and never raises
  an uncaught exception into the agent loop

### Requirement: Bar geometry measurement tool

The system SHALL provide a `measure_bars` tool that deterministically detects
bars in a clean bar-chart image and returns, per bar, its bounding box, pixel
height, and height ratio normalized to the shortest bar.

#### Scenario: Bar ratios track true value ratios

- **WHEN** `measure_bars` is called with a synthetic bar chart whose values are
  known
- **THEN** the number of detected bars equals the true count
- **AND** each bar's height ratio equals the true value ratio within 10%
  relative tolerance

#### Scenario: Non-chart image

- **WHEN** `measure_bars` is called with an image containing no detectable
  bars
- **THEN** the tool returns an empty bars list (not an error), so the agent can
  observe "no bars found" and re-plan

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

The system SHALL enable the agent, given a clean annotated bar chart image and
the four chart tools, to produce a ChartSpec whose dataset matches the chart's
true values, using annotation text as the primary value source and bar height
ratios as the cross-check.

#### Scenario: Annotated bar chart restores to ground-truth values

- **WHEN** the agent is shown a synthetic bar chart with printed value
  annotations and asked for the underlying data
- **THEN** it calls the sensors, cross-checks annotation values against bar
  height ratios, assembles a spec, and returns a `validate_spec`-clean
  ChartSpec
- **AND** the dataset values equal the ground-truth values used to draw the
  chart

#### Scenario: OCR misread is caught by geometric cross-check

- **WHEN** the annotation values disagree with bar height ratios beyond
  tolerance
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
