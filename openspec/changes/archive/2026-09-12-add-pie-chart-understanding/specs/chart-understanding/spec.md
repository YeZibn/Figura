## MODIFIED Requirements

### Requirement: Chart tools registered for the agent REPL

The system SHALL register the existing chart tools, the line-series sensor, and
the pie-sector sensor alongside the built-in tools when the agent REPL starts,
following the existing tool protocol (JSON observations, structured errors, and
optional bounded visual observations).

#### Scenario: REPL exposes Cartesian and pie chart tools

- **WHEN** the `--agent` REPL starts
- **THEN** the tool registry contains `extract_text`, `measure_bars`,
  `extract_line_series`, `extract_pie_slices`, `assemble_spec`, and
  `validate_spec` in addition to the built-ins

### Requirement: Chart sensors use authorized attachments

In the Agent tool registry, `extract_text`, `measure_bars`,
`extract_line_series`, and `extract_pie_slices` SHALL accept an authorized
attachment ID resolved through the active session boundary and SHALL not expose
arbitrary local paths in their model-facing schemas or results. Direct Python
path-based sensor compatibility MAY remain available. Attachment failures SHALL
be bounded structured errors without visual artifacts.

#### Scenario: Authorized sensor call

- **WHEN** a registered chart sensor, including the pie sensor, receives a
  valid attachment ID
- **THEN** it resolves the internal source image, returns its structured
  result, and preserves any source-sized visual overlay

#### Scenario: Unauthorized sensor call

- **WHEN** a chart sensor, including the pie sensor, receives an unknown,
  cross-session, missing, or changed ID
- **THEN** it returns a structured error without revealing the source path or
  producing an overlay

## ADDED Requirements

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
