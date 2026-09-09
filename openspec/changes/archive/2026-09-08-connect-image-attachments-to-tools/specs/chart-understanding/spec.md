## MODIFIED Requirements

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
- **AND** the resulting dataset values equal the ground-truth values used to
  draw the chart

#### Scenario: Image question does not require restoration

- **WHEN** the user asks a descriptive question that does not require
  structured chart data
- **THEN** the agent can answer without assembling or validating a ChartSpec

#### Scenario: OCR misread is caught by geometric cross-check

- **WHEN** the agent uses annotation values and bar-height ratios and those
  evidence channels disagree beyond tolerance
- **THEN** the agent re-examines the evidence before assembling, and the final
  spec uses the values consistent with bar geometry
