## MODIFIED Requirements

### Requirement: U0 end-to-end restoration through the ReAct loop

The system SHALL enable the agent, given a clean annotated bar chart, clean
single/multi-series line chart, clean pie chart, or clean single/multi-series
scatter chart through the normal image-attachment path and the registered
chart tools, to produce a ChartSpec whose semantic dataset matches the
chart's true values. The attachment path needed by local-image tools SHALL be
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

- **WHEN** annotation values, axis calibration, series colors, point geometry,
  or geometric measurements disagree beyond the reported confidence tolerance
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

## ADDED Requirements

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

- **WHEN** `extract_scatter_points` receives a missing, unauthorized, malformed,
  or non-image input
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
