# chart-understanding Specification

## Purpose

Give the agent deterministic sensors and a code-side assembler plus an
independent validator, so it can restore clean annotated Cartesian charts to a
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

The system SHALL enable the agent, given a clean annotated bar chart, clean
single/multi-series line chart, clean pie chart, or clean single/multi-series
scatter chart through the normal image-attachment path and the registered
chart tools, to produce a ChartSpec whose semantic dataset matches the chart's
true values. The attachment path needed by local-image tools SHALL be
available to the model without the user repeating it. The infrastructure MUST
NOT force a fixed tool sequence or require ChartSpec output for every image
turn.

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

#### Scenario: Freely planned scatter-chart restoration

- **WHEN** the user attaches a clean single- or multi-series scatter chart with
  readable axes and asks for the underlying data
- **THEN** the agent can choose scatter evidence, OCR, visual inspection,
  assembly, and validation tools without a caller-supplied workflow prompt
- **AND** the resulting coordinate points preserve the detected x/y values and
  resolved series distinction within the supported fixture tolerance

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

The system SHALL register the existing chart tools, the line-series sensor, the
pie-sector sensor, and the scatter-point sensor alongside the built-in tools
when the agent REPL starts, following the existing tool protocol (JSON
observations, structured errors, and optional bounded visual observations).

#### Scenario: REPL exposes Cartesian, pie, and scatter chart tools

- **WHEN** the `--agent` REPL starts
- **THEN** the tool registry contains `extract_text`, `measure_bars`,
  `extract_line_series`, `extract_pie_slices`, `extract_scatter_points`,
  `assemble_spec`, and `validate_spec` in addition to the built-ins

### Requirement: Chart sensors use authorized attachments

In the Agent tool registry, `extract_text`, `measure_bars`,
`extract_line_series`, `extract_pie_slices`, and `extract_scatter_points` SHALL
accept an authorized attachment ID resolved through the active session boundary
and SHALL not expose arbitrary local paths in their model-facing schemas or
results. Direct Python path-based sensor compatibility MAY remain available.
Attachment failures SHALL be bounded structured errors without visual artifacts.

#### Scenario: Authorized sensor call

- **WHEN** a registered chart sensor, including the pie and scatter sensors,
  receives a valid attachment ID
- **THEN** it resolves the internal source image, returns its structured result,
  and preserves any source-sized visual overlay

#### Scenario: Unauthorized sensor call

- **WHEN** a chart sensor, including the pie and scatter sensors, receives an
  unknown, cross-session, missing, or changed ID
- **THEN** it returns a structured error without revealing the source path or
  producing an overlay

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

### Requirement: Independent pie-sector extraction tool

The system SHALL provide an `extract_pie_slices` tool for clean, non-donut pie
charts. The tool SHALL detect a circular plot region and return one structured
entry per reliably detected sector, including a stable sector identifier,
color, center/radius evidence, start and end angles, angular size, and a
normalized ratio. The tool SHALL preserve partial geometry when some labels or
associations cannot be resolved.

#### Scenario: Clean pie sectors are measured

- **WHEN** `extract_pie_slices` is called with a synthetic pie chart whose
  sectors have distinguishable colors
- **THEN** the result contains the true number of sectors within the declared
  fixture tolerance
- **AND** each sector contains a stable ID, color, angle evidence, and a ratio
  whose value matches the ground truth within the declared tolerance
- **AND** the result contains detected center and radius evidence

#### Scenario: Pie geometry is independent of Cartesian axes

- **WHEN** a pie chart has no x-axis, y-axis, or numeric tick labels
- **THEN** the sensor still measures sector angles and ratios
- **AND** it does not report missing Cartesian calibration as a sensor failure

#### Scenario: Non-pie image remains inspectable

- **WHEN** the input contains no reliable circular pie region
- **THEN** the tool returns an empty `slices` list with a bounded warning rather
  than fabricating sectors or raising an exception
- **AND** any generated overlay preserves the source dimensions and explains
  that no reliable pie region was found

#### Scenario: Missing or malformed input is bounded

- **WHEN** `extract_pie_slices` receives a missing, unauthorized, malformed, or
  non-image input
- **THEN** it returns a structured error without exposing a local source path
  or producing a visual artifact

### Requirement: Pie labels and legend associations are explicit

The pie sensor SHALL return detected legend entries, OCR snippets, and
label-to-sector associations as bounded evidence when available. A resolved
association SHALL include its source or confidence; an unresolved or
ambiguous association SHALL remain null or uncertain and SHALL be reported in
warnings instead of being silently guessed. Printed percentages or numeric
values SHALL be retained separately from geometry ratios.

#### Scenario: Legend labels are associated with sectors

- **WHEN** a clean pie chart has a legend whose colors match the sectors
- **THEN** the result associates each reliably matched legend label with the
  corresponding stable sector ID
- **AND** sector color and label evidence remain available for Agent review

#### Scenario: Printed values are distinguished from inferred ratios

- **WHEN** a pie chart contains percentage or numeric labels
- **THEN** the result records the recognized printed value and its association
  confidence separately from the sector's geometry-derived ratio
- **AND** an unrecognized or conflicting printed value does not overwrite the
  geometry evidence

#### Scenario: Ambiguous association is surfaced

- **WHEN** two sectors or labels have insufficiently distinguishable color or
  spatial evidence
- **THEN** the affected association is unresolved or marked uncertain
- **AND** the result contains a warning naming the ambiguity

### Requirement: Pie totals, confidence, and visual evidence are validated

Every successful pie sensor result SHALL include bounded confidence metadata
and warnings. It SHALL report angle and ratio totals, and SHALL identify when
the reliably detected sectors do not account for approximately 360 degrees or
100 percent within the configured tolerance. The sensor SHALL generate a
source-sized overlay marking the circular region, sector boundaries, stable
IDs, colors, and unresolved associations when present.

#### Scenario: Consistent pie totals pass

- **WHEN** detected sectors cover the pie circle and their ratios sum within
  tolerance of 1.0
- **THEN** the result marks the totals as consistent, keeps all confidence
  values within `[0, 1]`, and returns the source-sized overlay

#### Scenario: Incomplete sectors produce a warning

- **WHEN** sector boundaries are occluded, merged, or otherwise leave an angle
  or ratio total outside tolerance
- **THEN** the result preserves the detected sectors and reports a bounded
  total-consistency warning
- **AND** it does not present the incomplete result as a certain complete pie

#### Scenario: Generated evidence is model-visible

- **WHEN** the pie sensor returns structured data and a valid overlay
- **THEN** the existing Agent visual-observation path presents the overlay on
  the next model turn while keeping the structured result available

### Requirement: Pie restoration remains freely planned

The system SHALL enable the Agent, given a clean annotated or legend-defined
pie chart through the normal authorized attachment path, to use pie evidence,
assemble a pie ChartSpec without axes, and independently validate it. The
infrastructure MUST NOT force a fixed pie-tool sequence or require ChartSpec
output for descriptive image questions.

#### Scenario: Agent restores a clean pie chart

- **WHEN** the user attaches a clean pie chart and asks for its underlying data
- **THEN** the Agent can choose `extract_pie_slices`, visual inspection, OCR,
  `assemble_spec`, and `validate_spec` in an order it determines
- **AND** the resulting categorical dataset preserves the resolved labels and
  either the recognized numeric values or the explicitly chosen normalized
  ratios

#### Scenario: Pie ChartSpec does not require axes

- **WHEN** the Agent assembles a valid pie result with categorical points and
  no Cartesian axes
- **THEN** `validate_spec` accepts the result when the dataset and point values
  are valid

#### Scenario: Descriptive pie question does not require restoration

- **WHEN** the user asks a descriptive question about a pie image rather than
  requesting structured data
- **THEN** the Agent can answer without invoking the pie sensor or assembling a
  ChartSpec

### Requirement: Independent scatter-point extraction tool

The system SHALL provide an `extract_scatter_points` tool for clean two-
dimensional Cartesian scatter charts. The tool SHALL detect a plot region and
return structured series with stable identities and points that include pixel
locations, bounded point geometry evidence, and calibrated x/y values when
both axes are readable. The tool SHALL preserve partial pixel evidence when
semantic calibration or series association is unavailable.

#### Scenario: Clean single-series scatter points are measured

- **WHEN** `extract_scatter_points` is called with a synthetic single-series
  scatter chart containing distinguishable point markers and readable axes
- **THEN** the result contains the true number of reliably visible points
  within the declared fixture tolerance
- **AND** each point has a stable ID, pixel location, and calibrated x/y values
  matching the fixture ground truth within the declared tolerance
- **AND** the result contains detected plot-area and axis-calibration evidence

#### Scenario: Multiple scatter series remain distinct

- **WHEN** a clean scatter chart contains multiple color-distinguished series
  with a legend and overlapping x coordinates
- **THEN** the result contains one series entry per reliably detected series
- **AND** points from different series are not merged solely because their
  coordinates overlap
- **AND** each series carries its legend label or a stable color-based fallback
  identity and its resolved color when available

#### Scenario: Partial calibration remains inspectable

- **WHEN** point geometry is detected but one or both axes cannot be calibrated
  reliably
- **THEN** the result preserves pixel points and any partial series evidence
- **AND** it reports a warning identifying the missing calibration
- **AND** it does not fabricate semantic numeric x/y values

#### Scenario: Non-scatter image remains inspectable

- **WHEN** the input contains no reliable scatter point population
- **THEN** the tool returns an empty series or points collection with a bounded
  warning rather than fabricating points or raising an exception
- **AND** any generated overlay preserves the source dimensions and explains
  that no reliable scatter evidence was found

#### Scenario: Missing or malformed input is bounded

- **WHEN** `extract_scatter_points` receives a missing, unauthorized,
  malformed, or non-image input
- **THEN** it returns a structured error without exposing a local source path
  or producing a visual artifact

### Requirement: Scatter overlap, size, and outlier evidence is explicit

The scatter sensor SHALL preserve bounded evidence about point size, opacity,
nearby or overlapping markers, and potential outliers when those properties
can be observed. It SHALL distinguish a reliably counted point from a merged
or occluded point, report unresolved cases in warnings or confidence metadata,
and SHALL not silently discard a potential outlier from the returned evidence.

#### Scenario: Overlapping markers are surfaced

- **WHEN** multiple markers overlap or cannot be separated at the source
  resolution
- **THEN** the result preserves the visible cluster or merged-point evidence
- **AND** it reports the affected count or association as uncertain in warnings
  rather than claiming a precise point count

#### Scenario: Marker appearance does not become fabricated data

- **WHEN** point size or opacity differs between markers but the image does not
  provide a reliable quantitative encoding for that appearance
- **THEN** the result retains the observed size or opacity evidence when
  available
- **AND** it does not convert those appearance differences into unverified
  numeric fields in the semantic dataset

#### Scenario: Potential outliers remain available for review

- **WHEN** one or more points are far from the dominant spatial population
- **THEN** the result retains those points with their normal coordinates and
  marks the potential outlier status as bounded evidence or a warning
- **AND** the agent can choose whether to include them when assembling a
  ChartSpec

### Requirement: Scatter confidence and visual evidence are validated

Every successful scatter sensor result SHALL include bounded confidence
metadata and warnings. The sensor SHALL generate a source-sized overlay that
marks the plot region, detected points, stable IDs, series colors, calibration
status, and unresolved or potential-outlier evidence when present. Confidence
values SHALL remain within `[0, 1]`, and low-confidence evidence SHALL remain
usable for another Agent action.

#### Scenario: Complete scatter evidence reports bounded confidence

- **WHEN** a clean scatter fixture has readable axes, distinguishable series,
  and separable markers
- **THEN** the result contains confidence values in `[0, 1]`, calibrated axis
  evidence, and the source-sized overlay
- **AND** the overlay visibly marks each returned point and its stable identity

#### Scenario: Incomplete scatter evidence produces warnings

- **WHEN** markers are merged, axes are unreadable, or a series association is
  ambiguous
- **THEN** the result preserves reliable point evidence and reports a bounded
  warning naming the affected uncertainty
- **AND** it does not present the incomplete result as a certain complete
  dataset

#### Scenario: Generated scatter evidence is model-visible

- **WHEN** the scatter sensor returns structured data and a valid overlay
- **THEN** the existing Agent visual-observation path presents the overlay on
  the next model turn while keeping the structured result available

### Requirement: Scatter restoration remains freely planned

The system SHALL enable the Agent, given a clean annotated or legend-defined
scatter chart through the normal authorized attachment path, to use scatter
evidence, assemble a coordinate-based scatter ChartSpec with axes, and
independently validate it. The infrastructure MUST NOT force a fixed
scatter-tool sequence or require ChartSpec output for descriptive image
questions.

#### Scenario: Agent restores a clean scatter chart

- **WHEN** the user attaches a clean scatter chart and asks for its underlying
  data
- **THEN** the Agent can choose `extract_scatter_points`, visual inspection,
  OCR, `assemble_spec`, and `validate_spec` in an order it determines
- **AND** the resulting dataset preserves the resolved series identities and
  the calibrated x/y coordinates, with uncertain points explicitly retained
  or flagged

#### Scenario: Scatter ChartSpec requires valid Cartesian axes

- **WHEN** the Agent assembles a scatter result with coordinate points but
  missing or invalid Cartesian axes
- **THEN** `validate_spec` returns located issues without crashing
- **AND** a corrected result with valid x/y axes can pass independently

#### Scenario: Descriptive scatter question does not require restoration

- **WHEN** the user asks a descriptive question about a scatter image rather
  than requesting structured data
- **THEN** the Agent can answer without invoking the scatter sensor or
  assembling a ChartSpec
