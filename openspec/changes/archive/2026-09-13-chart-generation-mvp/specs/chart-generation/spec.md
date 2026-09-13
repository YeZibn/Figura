## Purpose

Provide a deterministic, validated reverse path that turns Figura's shared ChartSpec data into bounded chart artifacts that an Agent and a user can inspect and reuse.

## ADDED Requirements

### Requirement: Valid ChartSpec produces a bounded chart artifact

The system SHALL accept a structurally valid ChartSpec and produce a chart
artifact for bar, line, pie, and scatter chart types. The artifact SHALL
represent the supplied title, labels, series distinctions, and dataset without
inventing or silently dropping semantic data. The output SHALL use a supported
image media type and SHALL remain within configured size and dimension limits.

#### Scenario: Cartesian ChartSpec is rendered

- **WHEN** a valid bar, line, or scatter ChartSpec is submitted for rendering
- **THEN** the system produces an image artifact with the declared chart type,
  title and available axis labels
- **AND** the plotted values and series distinctions correspond to the
  ChartSpec dataset

#### Scenario: Pie ChartSpec is rendered without axes

- **WHEN** a valid pie ChartSpec contains non-negative categorical values and
  no axes
- **THEN** the system produces an image artifact whose sectors correspond to
  the categories and values
- **AND** the artifact exposes enough legend or label metadata to associate
  each sector with its category

#### Scenario: Multi-series data remains distinct

- **WHEN** a valid ChartSpec contains points assigned to multiple series
- **THEN** the generated chart preserves the series distinction in its visual
  encoding and bounded artifact metadata
- **AND** points are not merged solely because they share a category or axis

#### Scenario: Invalid ChartSpec is rejected before rendering

- **WHEN** a ChartSpec is missing required axes or contains invalid points,
  unsupported values, or an invalid pie dataset
- **THEN** the system returns a bounded structured validation error
- **AND** it produces no chart artifact

### Requirement: Agent can request chart generation through the tool boundary

The Agent SHALL be able to request rendering of a ChartSpec through a
registered tool. The tool SHALL return structured chart metadata together with
an attributed visual payload when rendering succeeds, and SHALL permit the
Agent to decide whether to assemble, validate, render, inspect, retry, or
answer without imposing a fixed tool sequence.

#### Scenario: User asks to redraw understood data

- **WHEN** a user asks the Agent to redraw data recovered from an attached
  chart
- **THEN** the Agent can reuse or assemble a ChartSpec, validate it, request a
  chart artifact, and include the generated result in its answer

#### Scenario: Agent inspects generated visual evidence

- **WHEN** a chart-rendering tool returns a valid visual payload
- **THEN** the Agent can receive the generated chart as attributed visual
  evidence on a later model turn and may accept it, retry it, or ignore it
- **AND** the structured chart metadata remains available independently

#### Scenario: Rendering failure is recoverable

- **WHEN** rendering fails because the input is invalid or a configured output
  limit is exceeded
- **THEN** the tool returns a bounded structured error or warning
- **AND** the Agent run remains able to revise the request or provide a text
  answer without an uncaught renderer exception

### Requirement: Generated chart output is bounded and attributable

Every successful generated chart SHALL expose an opaque artifact reference,
media type, byte count, dimensions, chart type, and bounded caption or title.
Artifact metadata SHALL NOT contain local source paths, credentials, raw
provider payloads, or embedded image bytes. Generated output SHALL be
distinguishable from temporary model-observation images.

#### Scenario: Generated output metadata is safe

- **WHEN** a rendering operation succeeds
- **THEN** its structured result contains bounded metadata and an opaque
  reference suitable for Gateway and desktop-client retrieval
- **AND** the JSON result contains no raw image bytes or local filesystem path

#### Scenario: Output limits are enforced

- **WHEN** the rendered image exceeds the configured byte or dimension limit
- **THEN** the system rejects or bounds the output with an explicit reason
- **AND** it does not publish a partial or unbounded artifact
