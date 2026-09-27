## Purpose

Defines Figura's versioned, single-chart semantic data contract. The contract lets later assembly and rendering capabilities consume the same strictly parsed chart content and consistent generation-readiness validation.

## ADDED Requirements

### Requirement: Versioned single-chart content model

Figura SHALL provide a versioned `ChartSpecData` value that represents one chart using `schema_version`, `metadata`, `axes`, and an ordered `dataset`. Version 1 SHALL support exactly `bar`, `line`, `pie`, and `scatter`. A spec SHALL contain between 1 and 512 data points. The content model SHALL NOT contain runtime identity, Run identity, source authorization, provenance, generation context, storage location, rendering state, or publication state.

`metadata` SHALL contain `chart_type` and MAY contain `title`, `source`, and `note`. Missing optional metadata text SHALL normalize to an empty string; missing `source` SHALL normalize to null. Text values SHALL be strings no longer than 160 Unicode code points. `source` SHALL remain display text and SHALL NOT be treated as evidence or authorization.

`axes` SHALL be an x/y object for `bar`, `line`, and `scatter`, and null for `pie`. Each Cartesian axis SHALL contain a non-empty `label` and MAY contain `categories`, `min_value`, and `max_value`. Axis labels, categories, and series labels SHALL be non-empty strings of at most 160 Unicode code points. A category list SHALL contain between 1 and 512 unique labels. Every data number and numeric axis bound SHALL be representable as a finite IEEE-754 binary64 value (absolute value no greater than `1.7976931348623157e308`); when both axis bounds are present, `min_value` SHALL be less than `max_value`.

#### Scenario: Valid version 1 content round-trips
- **WHEN** valid ChartSpecData content is serialized and parsed again
- **THEN** the parsed content SHALL preserve chart type, metadata, axis declarations, data point values, and list order
- **AND** the canonical serialized form SHALL include `schema_version`, `metadata`, `axes`, and `dataset`

#### Scenario: Unsupported version or chart type is rejected
- **WHEN** input contains an unsupported schema version or a chart type outside the four version 1 values
- **THEN** parsing SHALL return a bounded issue at the corresponding field path
- **AND** no ChartSpecData value SHALL be returned

#### Scenario: Runtime and provenance fields are not part of the core model
- **WHEN** input contains fields such as `chart_spec_id`, `run_id`, `provenance`, or `generation_context`
- **THEN** strict parsing SHALL reject the unknown field
- **AND** it SHALL NOT silently retain or discard it

### Requirement: Strict typed parsing and canonical serialization

The system SHALL parse ChartSpecData from JSON-compatible mappings without coercing values, silently dropping unknown fields, or accepting duplicate object keys in JSON text. The parser SHALL reject missing required fields, unexpected fields at any nesting level, invalid object shapes, out-of-range text or list sizes, booleans used as numbers, and non-finite numbers. Parsing issues SHALL identify a JSON Pointer field path and SHALL NOT echo the submitted value.

Canonical serialization SHALL emit only the fields defined by the version 1 contract, preserve array order, normalize omitted optional metadata to their documented defaults, and produce deterministic JSON for the same value. Parsing and serialization SHALL use bounded input and output sizes; the maximum serialized ChartSpecData size SHALL be 256 KiB.

#### Scenario: Unknown nested field is rejected
- **WHEN** metadata, an axis, or a data point contains an undeclared field
- **THEN** parsing SHALL report that field's path
- **AND** parsing SHALL NOT produce a partially accepted value

#### Scenario: Invalid primitive type is rejected without coercion
- **WHEN** a numeric field contains a boolean, numeric string, NaN, or infinity
- **THEN** parsing or validation SHALL report the numeric field path
- **AND** the value SHALL NOT be converted to a number

#### Scenario: Serialization is deterministic and bounded
- **WHEN** the same valid ChartSpecData value is serialized more than once
- **THEN** both serializations SHALL be byte-identical
- **AND** content exceeding 256 KiB SHALL be rejected with a bounded issue

### Requirement: Data point shape matches the chart type

Each version 1 data point SHALL use exactly one shape: categorical points contain `category` and `value`; coordinate points contain `x` and `y`. Either shape MAY contain a `series` label. Categorical fields SHALL be used only by `bar` and `pie`; coordinate fields SHALL be used only by `line` and `scatter`. Values and coordinates SHALL be finite binary64-representable JSON numbers, and a point SHALL NOT mix the two shapes.

#### Scenario: Categorical chart accepts category and value points
- **WHEN** a bar or pie spec contains non-empty categories and finite values
- **THEN** its points SHALL validate as categorical points
- **AND** coordinate fields SHALL be rejected on those points

#### Scenario: Coordinate chart accepts x and y points
- **WHEN** a line or scatter spec contains finite x and y coordinates
- **THEN** its points SHALL validate as coordinate points
- **AND** category/value fields SHALL be rejected on those points

#### Scenario: Point shape conflicts with chart type
- **WHEN** a bar, line, pie, or scatter spec contains the other point shape
- **THEN** validation SHALL return an issue at that point's field path
- **AND** the spec SHALL be considered not generation-ready

### Requirement: Chart-specific semantic validation

Validation SHALL check chart-specific data meaning in addition to field types. Bar data SHALL have at most one point for each `(category, series)` pair; every series SHALL provide an explicit value for every category in the effective x-axis domain. If `axes.x.categories` is omitted, that domain SHALL be derived in first-seen dataset order. Bar x axes SHALL NOT declare numeric bounds.

Pie data SHALL use unique categories, SHALL NOT declare a series label, SHALL contain no negative values, and SHALL have a finite, strictly positive total. Dataset order SHALL define slice order.

Line data SHALL have unique x coordinates within each series and SHALL be ordered by strictly increasing x within each series. When `axes.x.categories` is present, its labels SHALL map to x positions exactly `0` through `len(categories)-1`; line points SHALL use integer x positions in that range, and all declared positions SHALL be represented in every series. Without categories, line x coordinates SHALL be numeric and SHALL NOT use categorical labels.

Scatter data SHALL use numeric x/y coordinates and SHALL NOT declare x-axis categories. Repeated coordinates SHALL remain valid. Version 1 SHALL reject `axes.y.categories` for all Cartesian chart types. For all Cartesian charts, axis numeric bounds SHALL be applicable only to numeric axes, and every plotted value SHALL fall within any declared bound.

Validation SHALL return issues in stable dataset/field order, with at most 32 issues. Each issue SHALL contain a stable code no longer than 64 ASCII characters, a JSON Pointer path no longer than 256 UTF-8 bytes, and a message no longer than 240 Unicode code points. Validation SHALL NOT sort, fill, clamp, relabel, or otherwise repair chart data.

#### Scenario: Bar series has an omitted category value
- **WHEN** a bar chart contains multiple series and one series lacks a category present in the effective domain
- **THEN** validation SHALL report the missing category for that series
- **AND** it SHALL NOT interpret the missing value as zero

#### Scenario: Pie has invalid values or total
- **WHEN** a pie chart contains a negative value, repeated category, or a total that is not positive
- **THEN** validation SHALL report the applicable issue paths
- **AND** the pie chart SHALL not be generation-ready

#### Scenario: Pie total overflows
- **WHEN** individually finite pie values produce a non-finite total
- **THEN** validation SHALL report the dataset total as invalid
- **AND** the pie chart SHALL not be generation-ready

#### Scenario: Categorical line positions map to ordered labels
- **WHEN** a line chart declares categories `Jan`, `Feb`, and `Mar`
- **THEN** each series SHALL use x positions 0, 1, and 2 in increasing order
- **AND** a missing, fractional, duplicate, or out-of-range position SHALL be reported

#### Scenario: Numeric axis bound excludes a plotted value
- **WHEN** a point falls below the declared minimum or above the declared maximum
- **THEN** validation SHALL report the point field path and the chart SHALL not be generation-ready

### Requirement: Pure and bounded validation result

ChartSpecData parsing and validation SHALL be deterministic and side-effect free. Validation SHALL distinguish parse-shape failures from semantic issues, SHALL not access Run state, attachments, evidence, files, providers, or storage, and SHALL not perform rendering. All returned issue text and paths SHALL remain within the configured bounds.

#### Scenario: Multiple semantic problems are reported together
- **WHEN** a correctly shaped ChartSpecData value contains multiple independent semantic errors
- **THEN** validation SHALL return the errors in stable order up to the configured issue limit
- **AND** it SHALL not raise an uncaught exception

#### Scenario: Validation does not repair content
- **WHEN** validation receives unordered line points or incomplete bar series
- **THEN** it SHALL report the problems
- **AND** the original point order and values SHALL remain unchanged
