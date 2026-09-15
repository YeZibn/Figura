# chartspec Specification

## Purpose

Defines `ChartSpec`, the shared intermediate representation (IR) between the
understanding and generation sides: a serialization-friendly, documented data
model that carries a chart's metadata, axes, and dataset, with a structural
validator so both directions exchange data through one stable contract.

## Requirements

### Requirement: ChartSpec data model

The system SHALL provide a `ChartSpec` data class expressing a chart's
structure for both directions of ChartAgent, composed of chart metadata, chart
type, axes, and a dataset, and SHALL provide serialization to and from plain
dictionaries via `to_dict` and `from_dict`.

#### Scenario: A spec round-trips through dict

- **WHEN** a `ChartSpec` with metadata, axes, and a dataset is converted with
  `to_dict` and rebuilt with `from_dict`
- **THEN** the rebuilt spec equals the original spec

### Requirement: Chart type enumeration

The system SHALL model a chart's type as a closed `ChartType` enumeration
covering common kinds (e.g. bar, line, pie, scatter), so downstream consumers
can switch on a fixed set of values.

#### Scenario: A supported chart type is accepted

- **WHEN** a spec is constructed with a type from the `ChartType` enumeration
- **THEN** the spec holds that type and validation reports no type error

### Requirement: Axes conditional on chart type

The system SHALL require axes for cartesian chart types (bar, line, scatter)
and SHALL allow axes to be absent or empty for pie, so `validate()` judges axes
presence against the declared chart type rather than uniformly.

#### Scenario: Cartesian type without axes reports an issue

- **WHEN** a bar, line, or scatter spec is validated with missing or empty axes
- **THEN** `validate()` returns a problem locating the axes

#### Scenario: Pie without axes validates clean

- **WHEN** a pie spec carries a valid dataset but no axes
- **THEN** `validate()` returns an empty list

### Requirement: Structured validation

The system SHALL provide a `validate()` method that returns a structured list
of validation problems (each with the offending location and a message) rather
than raising a bare exception, so consumers can collect and respond to all
issues at once.

#### Scenario: Invalid data reports an issue list

- **WHEN** a spec carries invalid data (e.g. a dataset point missing a required
  value or an empty axes label)
- **THEN** `validate()` returns a non-empty list of problems describing each
  issue, without raising an uncaught exception

#### Scenario: Valid spec validates clean

- **WHEN** a spec has valid metadata, axes, and a dataset
- **THEN** `validate()` returns an empty list

### Requirement: Dataset as a list of typed points

The system SHALL represent the dataset as a list of typed data points (e.g.
explicit categories/values, or x/y pairs), so both a human and a renderer can
iterate over the restored or to-be-rendered values uniformly.

#### Scenario: Series can be enumerated

- **WHEN** a spec's dataset contains multiple points across series
- **THEN** consumers can iterate the points and read each point's values

### Requirement: Understanding-side provenance fields

The system SHALL allow understanding-side provenance to be carried on the spec
optionally (e.g. per-point measurement confidence and the source chart), without
requiring them for generation, so the understanding pipeline can attach
traceability without burdening the generation side.

#### Scenario: Provenance is optional

- **WHEN** a spec is built with provenance fields present, and another built
  without them
- **THEN** the first carries the provenance values and both validate clean,
  since provenance is optional