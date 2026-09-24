## MODIFIED Requirements

### Requirement: Bar geometry measurement tool

The system SHALL provide a `measure_bars` tool that deterministically detects
bars in clean Cartesian bar-chart images and returns, per bar, its bounding box,
pixel height, stable visual identifier, and height ratio normalized to the
shortest detected bar. The tool SHALL support a single series, grouped bars,
and supported stacked bars while preserving the existing single-series fields.
It SHALL also produce a generated overlay that marks each returned bar, its
series identity when known, and the detected baseline or stack boundaries.

#### Scenario: Single-series ratios remain backward compatible

- **WHEN** `measure_bars` is called with a synthetic single-series bar chart
  whose values are known
- **THEN** the result contains the existing `bars`, `baseline_y`, `id`, `bbox`,
  `h_px`, and `ratio` fields
- **AND** the number of detected bars equals the true count
- **AND** each bar's height ratio equals the true value ratio within 10%
  relative tolerance
- **AND** a generated overlay with the source image dimensions visibly marks
  every returned bar, its identifier, and the detected baseline

#### Scenario: Grouped bars retain category and series distinctions

- **WHEN** `measure_bars` is called with a clean grouped bar chart containing
  multiple legend-defined series for each category
- **THEN** every returned bar has a stable bar identifier and enough geometry
  to associate it with one category and one series
- **AND** the result does not merge adjacent bars solely because they share a
  category or baseline
- **AND** the overlay marks the individual bars and their resolved series
  identities when those identities are available

#### Scenario: Supported stacked bars expose stack evidence

- **WHEN** `measure_bars` is called with a clean stacked bar chart whose stack
  segments have distinguishable colors
- **THEN** the result exposes the individual segments and their parent category
  when the segments can be separated reliably
- **AND** the result preserves the total stack geometry even when a segment
  label or legend association is unresolved
- **AND** unresolved associations are reported as warnings rather than being
  silently presented as certain data

#### Scenario: Non-chart image remains inspectable

- **WHEN** `measure_bars` is called with an image containing no detectable bars
- **THEN** the tool returns an empty bars list (not an error), so the agent can
  observe "no bars found" and re-plan
- **AND** the generated overlay preserves the source image and indicates that
  no baseline or bars were detected

#### Scenario: Missing image reports a structured error

- **WHEN** `measure_bars` is called with a path or attachment that cannot be
  resolved to an image
- **THEN** the tool returns `{"error": ...}` naming only the bounded failure,
  produces no visual artifact, and never raises an uncaught exception into the
  agent loop

### Requirement: U0 end-to-end restoration through the ReAct loop

The system SHALL enable the agent, given a clean annotated bar chart or clean
single/multi-series line chart through the normal image-attachment path and the
registered chart tools, to produce a ChartSpec whose semantic dataset matches
the chart's true values. The attachment path needed by local-image tools SHALL
be available to the model without the user repeating it. The infrastructure
MUST NOT force a fixed tool sequence or require ChartSpec output for every
image turn.

#### Scenario: Freely planned annotated bar-chart restoration

- **WHEN** the user attaches a synthetic single- or multi-series bar chart with
  printed value annotations through the standard agent REPL and asks for the
  underlying data
- **THEN** the agent can choose and call relevant sensors, assembly, and
  validation tools without a caller-supplied workflow prompt
- **AND** the dataset values and series identities equal the ground-truth
  values and identities used to draw the chart

#### Scenario: Freely planned line-chart restoration

- **WHEN** the user attaches a clean line chart with one or more legend-defined
  series and asks for the underlying data
- **THEN** the agent can use line-series evidence, OCR, visual inspection, or a
  retry in any order that it chooses
- **AND** the resulting coordinate points preserve the x ordering, y values,
  and semantic series distinction within the supported fixture tolerance

#### Scenario: Image question does not require restoration

- **WHEN** the user asks a descriptive question that does not require
  structured chart data
- **THEN** the agent can answer without assembling or validating a ChartSpec

#### Scenario: Conflicting evidence is surfaced before assembly

- **WHEN** annotation values, axis calibration, series colors, or geometric
  measurements disagree beyond the reported confidence tolerance
- **THEN** the agent receives structured warnings and visual evidence, and can
  re-examine or switch tools before assembling
- **AND** the final answer does not silently claim unresolved values as certain

### Requirement: Chart tools registered for the agent REPL

The system SHALL register the existing chart tools and the line-series sensor
alongside the built-in tools when the agent REPL starts, following the existing
tool protocol (JSON observations, structured errors, and optional bounded
visual observations).

#### Scenario: REPL exposes Cartesian chart tools

- **WHEN** the `--agent` REPL starts
- **THEN** the tool registry contains `extract_text`, `measure_bars`,
  `extract_line_series`, `assemble_spec`, and `validate_spec` in addition to
  the built-ins

## ADDED Requirements

### Requirement: Line-series extraction tool

The system SHALL provide an `extract_line_series` tool for clean single-series
and multi-series line charts. The tool SHALL return structured series with
stable series identifiers, ordered points, pixel locations, calibrated values
when the axes are readable, and optional legend labels and colors. It SHALL
return bounded visual evidence that marks the detected plot area, series, and
points so the multimodal model can inspect the associations.

#### Scenario: Single-series line points are returned

- **WHEN** `extract_line_series` is called with a synthetic line chart with
  readable axes and known points
- **THEN** the result contains one series with ordered points whose calibrated
  x and y values match the fixture ground truth within the declared tolerance
- **AND** each point contains a stable identifier or index and its pixel
  location
- **AND** the generated overlay preserves the source dimensions and marks the
  detected line and points

#### Scenario: Multiple line series remain distinct

- **WHEN** `extract_line_series` is called with a chart containing multiple
  colored lines and a legend
- **THEN** the result contains one series entry per resolved line
- **AND** points from different lines are not merged even when their x values
  overlap
- **AND** each series carries its legend label or a stable fallback identity,
  plus its resolved color when available

#### Scenario: Uncalibrated line evidence is bounded and inspectable

- **WHEN** line geometry is detected but one or both axes cannot be calibrated
  reliably
- **THEN** the result preserves pixel points and any partial series evidence
- **AND** it reports a warning identifying the missing calibration
- **AND** it does not fabricate semantic numeric values

#### Scenario: Invalid line input reports a structured error

- **WHEN** `extract_line_series` receives a missing, unauthorized, malformed,
  or non-image input
- **THEN** it returns a bounded structured error without exposing a local source
  path or producing a visual artifact

### Requirement: Shared Cartesian layout and series evidence

Cartesian chart sensors SHALL expose a common evidence envelope containing the
source image dimensions, a plot-area bounding box when detected, axis labels or
tick calibration evidence when available, resolved legend entries, and series
identities. Missing or ambiguous fields SHALL be represented as absent or
uncertain values rather than invented values. The envelope SHALL be sufficient
for the agent to associate geometry, OCR, axes, and legend evidence without a
mandatory sensor order.

#### Scenario: Clean axes and legend are correlated

- **WHEN** a sensor processes a clean Cartesian fixture with visible axes and a
  legend
- **THEN** the structured result identifies the common plot area and includes
  the available axis and legend evidence
- **AND** the series identifiers used in geometry and overlays are consistent
  across the returned evidence

#### Scenario: Partial layout evidence is retained

- **WHEN** a chart has detectable geometry but an axis, legend, or plot boundary
  is partially occluded or unreadable
- **THEN** the sensor returns the reliable geometry it can measure
- **AND** marks the missing association in warnings or confidence metadata
- **AND** the result remains valid JSON suitable for another agent action

### Requirement: Cartesian sensor confidence and warnings

Every successful Cartesian sensor result SHALL include bounded confidence
metadata and a warnings collection. Confidence values SHALL be within `[0, 1]`
and warnings SHALL identify material uncertainty such as merged geometry,
unreadable ticks, unresolved legend mappings, or incomplete calibration. A low
confidence result SHALL remain usable evidence and SHALL not be converted into
an unstructured exception solely because it is uncertain.

#### Scenario: High-confidence fixture reports bounded confidence

- **WHEN** a clean fixture is processed with complete geometry, axes, and legend
  evidence
- **THEN** the result includes confidence values in `[0, 1]`
- **AND** the warnings collection is empty or contains only non-material notes

#### Scenario: Ambiguity becomes an explicit warning

- **WHEN** a sensor cannot reliably resolve a series label or numeric axis
- **THEN** the result includes a material warning naming the unresolved evidence
- **AND** every emitted confidence value remains within `[0, 1]`

