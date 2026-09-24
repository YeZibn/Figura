## MODIFIED Requirements

### Requirement: Code-side ChartSpec assembly tool

The system SHALL provide an `assemble_spec` tool that constructs a ChartSpec
from typed arguments (chart type, title, axis labels, points, source) in code
and atomically applies the chart-type, axis, point, range, and generation
constraints before returning its dictionary form; the model never hand-writes
IR JSON and does not need a separate validation tool call for the assembled
result. A failed assembly SHALL return bounded, located issues and SHALL NOT
return a ChartSpec that downstream generation can treat as valid.

#### Scenario: Valid arguments produce an already validated schema-shaped spec

- **WHEN** `assemble_spec` is called with a bar chart type and category/value
  points
- **THEN** the returned dictionary round-trips through `ChartSpec.from_dict`
  and `to_dict` unchanged
- **AND** metadata carries the provided source provenance
- **AND** the returned ChartSpec has passed the same semantic constraints used
  by downstream chart generation

#### Scenario: Malformed points are rejected as structured errors

- **WHEN** `assemble_spec` is called with points lacking required fields or a
  chart type outside the enumeration
- **THEN** the tool returns `{"error": ...}` describing the offending input
  and produces no spec

#### Scenario: Semantic validation failure prevents downstream use

- **WHEN** typed inputs produce an empty dataset, incompatible point shape,
  invalid axis contract, invalid range, or another generation-blocking issue
- **THEN** `assemble_spec` returns bounded located issues through its error
  result
- **AND** it does not return a partially accepted ChartSpec for rendering or
  final structured output

### Requirement: Chart tools registered for the agent REPL

The system SHALL register the existing chart tools, the line-series sensor, the
pie-sector sensor, and the scatter-point sensor alongside the built-in tools
when the agent REPL starts, following the existing tool protocol (JSON
observations, structured errors, and optional bounded visual observations).
The model-facing chart tool surface SHALL expose `assemble_spec` as the sole
ChartSpec construction-and-validation gate; internal validation used by
generation or review SHALL NOT be registered as a separate model tool.

#### Scenario: REPL exposes Cartesian, pie, and scatter chart tools

- **WHEN** the `--agent` REPL starts
- **THEN** the tool registry contains `extract_text`, `measure_bars`,
  `extract_line_series`, `extract_pie_slices`, `extract_scatter_points`,
  `assemble_spec`, and `render_chart` in addition to the built-ins
- **AND** the registry does not contain `validate_spec`

### Requirement: Pie restoration remains freely planned

The system SHALL enable the Agent, given a clean annotated or legend-defined
pie chart through the normal authorized attachment path, to use pie evidence
and assemble a pie ChartSpec without axes through the atomic construction and
validation gate. The infrastructure MUST NOT force a fixed pie-tool sequence
or require ChartSpec output for descriptive image questions.

#### Scenario: Agent restores a clean pie chart

- **WHEN** the user attaches a clean pie chart and asks for its underlying data
- **THEN** the Agent can choose `extract_pie_slices`, visual inspection, OCR,
  and `assemble_spec` in an order it determines
- **AND** the resulting categorical dataset preserves the resolved labels and
  either the recognized numeric values or the explicitly chosen normalized
  ratios

#### Scenario: Pie ChartSpec does not require axes

- **WHEN** the Agent assembles a valid pie result with categorical points and
  no Cartesian axes
- **THEN** `assemble_spec` accepts the result when the dataset and point values
  are valid

#### Scenario: Descriptive pie question does not require restoration

- **WHEN** the user asks a descriptive question about a pie image rather than
  requesting structured data
- **THEN** the Agent can answer without invoking the pie sensor or assembling a
  ChartSpec

### Requirement: Scatter restoration remains freely planned

The system SHALL enable the Agent, given a clean annotated or legend-defined
scatter chart through the normal authorized attachment path, to use scatter
evidence, OCR, visual inspection, and assemble a coordinate-based scatter
ChartSpec with axes through the atomic construction and validation gate. The
infrastructure MUST NOT force a fixed scatter-tool sequence or require
ChartSpec output for descriptive image questions.

#### Scenario: Agent restores a clean scatter chart

- **WHEN** the user attaches a clean scatter chart and asks for its underlying
  data
- **THEN** the Agent can choose `extract_scatter_points`, visual inspection,
  OCR, and `assemble_spec` in an order it determines
- **AND** the resulting dataset preserves resolved series identities and
  calibrated x/y coordinates when reliable
- **AND** uncertain or pixel-only points remain explicitly retained or flagged
  before semantic assembly

#### Scenario: Scatter ChartSpec requires valid Cartesian axes

- **WHEN** the Agent assembles a scatter result with coordinate points but
  missing or invalid Cartesian axes
- **THEN** `assemble_spec` returns located issues without crashing
- **AND** a corrected result with valid x/y axes can pass through the same
  atomic assembly gate

#### Scenario: Descriptive scatter question does not require restoration

- **WHEN** the user asks a descriptive question about a scatter image rather
  than requesting structured data
- **THEN** the Agent can answer without invoking the scatter sensor or
  assembling a ChartSpec

## REMOVED Requirements

### Requirement: Independent ChartSpec validation tool (Critic)

**Reason**: A separately registered validation tool is optional from the model's perspective, so the model can skip it after assembly. The desired contract is that construction and semantic validation are one atomic model-facing operation.

**Migration**: Use `assemble_spec` for all model-created ChartSpecs. Keep the shared validation behavior available to render, review, tests, and non-model callers, but remove `validate_spec` from the Agent-facing chart tool registry and update callers that expected a separate model turn.
