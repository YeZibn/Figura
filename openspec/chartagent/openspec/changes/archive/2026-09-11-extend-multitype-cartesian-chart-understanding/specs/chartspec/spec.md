## MODIFIED Requirements

### Requirement: ChartSpec data model

The system SHALL provide a `ChartSpec` data class expressing a chart's
structure for both directions of Figura, composed of chart metadata, chart
type, optional axes, and a typed dataset, and SHALL provide serialization to
and from plain dictionaries via `to_dict` and `from_dict`. Dataset points MAY
carry a non-empty semantic series identity and a bounded confidence value so
multi-series understanding results remain distinct without changing the
single-series representation.

#### Scenario: A spec round-trips through dict

- **WHEN** a `ChartSpec` with metadata, axes, and a dataset is converted with
  `to_dict` and rebuilt with `from_dict`
- **THEN** the rebuilt spec equals the original spec

#### Scenario: Multi-series points round-trip without merging

- **WHEN** a `ChartSpec` contains categorical or coordinate points belonging to
  two or more series
- **THEN** each point retains its series identity and optional confidence after
  serialization and reconstruction
- **AND** the original dataset order is preserved

### Requirement: Structured validation

The system SHALL provide a `validate()` method that returns a structured list
of validation problems (each with the offending location and a message) rather
than raising a bare exception, so consumers can collect and respond to all
issues at once. Validation SHALL check that optional series identities are
non-empty strings when present, confidence values are within `[0, 1]`, and
points do not mix incompatible categorical and coordinate shapes for the
declared chart type.

#### Scenario: Invalid data reports an issue list

- **WHEN** a spec carries invalid data (e.g. a dataset point missing a required
  value, an empty series identity, or an out-of-range confidence)
- **THEN** `validate()` returns a non-empty list of problems describing each
  issue, without raising an uncaught exception

#### Scenario: Valid multi-series data validates clean

- **WHEN** a spec has valid metadata, axes, a dataset, and multiple points
  grouped by non-empty series identities
- **THEN** `validate()` returns an empty list

### Requirement: Dataset as a list of typed points

The system SHALL represent the dataset as a list of typed data points (e.g.
explicit categories/values, or x/y pairs), so both a human and a renderer can
iterate over the restored or to-be-rendered values uniformly. For a
multi-series dataset, the optional series field SHALL identify the semantic
series for each point while retaining the point's category or coordinate
values; consumers SHALL be able to group points by that field without relying
on pixel geometry or color.

#### Scenario: Series can be enumerated

- **WHEN** a spec's dataset contains multiple points across series
- **THEN** consumers can iterate the points, read each point's values, and group
  them by their series identity

#### Scenario: Legacy single-series data remains readable

- **WHEN** a valid existing single-series spec omits the optional series field
- **THEN** `from_dict`, `to_dict`, and `validate()` continue to accept it without
  requiring a synthetic series label

### Requirement: Understanding-side provenance fields

The system SHALL allow understanding-side provenance to be carried on the spec
optionally, including an opaque source reference, per-point confidence, and
bounded evidence notes when needed, without requiring those fields for
generation. Provenance SHALL NOT require embedding image bytes or generated
overlay payloads in the ChartSpec.

#### Scenario: Provenance is optional

- **WHEN** a spec is built with provenance fields present, and another built
  without them
- **THEN** the first carries the provenance values and both validate clean,
  since provenance is optional

#### Scenario: Evidence remains separate from semantic data

- **WHEN** an understanding result includes pixel boxes, colors, or overlay
  references used to justify a point or series
- **THEN** the ChartSpec retains only supported semantic values and bounded
  provenance references
- **AND** no image bytes are required for `to_dict`, `from_dict`, or validation

