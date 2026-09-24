## MODIFIED Requirements

### Requirement: U0 end-to-end restoration through the ReAct loop

The system SHALL enable the agent, given a clean annotated bar chart, clean
single/multi-series line chart, clean pie chart, or clean single/multi-series
scatter chart through the normal image-attachment path and the registered
chart tools, to produce a ChartSpec whose semantic dataset matches the chart's
true values when those values are visually recoverable. The attachment path
needed by local-image tools SHALL be available to the model without the user
repeating it. The multimodal model SHALL be allowed to use its visual
understanding as the first-pass semantic evidence, and OCR, chart sensors, and
layout inspection SHALL be auxiliary evidence selected according to observed
uncertainty. The infrastructure MUST NOT force a fixed tool sequence or
require `inspect_chart_layout` or ChartSpec output for every image turn.

#### Scenario: Clear annotated bar-chart restoration

- **WHEN** the user attaches a synthetic single- or multi-series bar chart with
  readable category and value annotations and asks for the underlying data
- **THEN** the agent may directly use visual understanding and `assemble_spec`
  or may call targeted sensors before assembly
- **AND** the dataset values and series identities equal the ground-truth
  values and identities used to draw the chart

#### Scenario: Freely planned annotated bar-chart restoration

- **WHEN** the user attaches a bar chart with partially uncertain annotations,
  layout, or geometry through the standard agent REPL and asks for the
  underlying data
- **THEN** the agent can choose OCR, bar geometry, layout inspection,
  assembly, and validation tools according to the unresolved evidence
- **AND** the resulting values retain warnings or uncertainty when the
  available evidence cannot resolve them

#### Scenario: Freely planned line-chart restoration

- **WHEN** the user attaches a clean line chart with one or more legend-defined
  series and asks for the underlying data
- **THEN** the agent can combine visual understanding, line-series evidence,
  OCR, layout inspection, assembly, or a retry in any order that it chooses
- **AND** the resulting coordinate points preserve the x ordering, y values,
  and semantic series distinction within the supported fixture tolerance

#### Scenario: Freely planned scatter-chart restoration

- **WHEN** the user attaches a clean single- or multi-series scatter chart with
  readable axes and asks for the underlying data
- **THEN** the agent can combine visual understanding, scatter evidence, OCR,
  layout inspection, assembly, and validation tools without a caller-supplied
  workflow prompt
- **AND** the resulting coordinate points preserve the detected x/y values and
  resolved series distinction within the supported fixture tolerance

#### Scenario: Image question does not require restoration

- **WHEN** the user asks a descriptive question that does not require
  structured chart data
- **THEN** the agent can answer without assembling or validating a ChartSpec

#### Scenario: Conflicting evidence is surfaced before assembly

- **WHEN** annotation values, axis calibration, series colors, layout hints, or
  geometric measurements disagree beyond the reported confidence tolerance
- **THEN** the agent receives structured warnings and visual evidence, and can
  re-examine, switch tools, or preserve an unresolved candidate before
  assembling
- **AND** the final answer does not silently claim unresolved values as certain
