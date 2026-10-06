## REMOVED Requirements

### Requirement: Versioned single-chart content model
**Reason**: The four-family ChartSpec v1 contract is replaced by the v2 ten-family content model.
**Migration**: New content SHALL use the v2 structure described by the added requirements; the new version does not parse or convert v1.

### Requirement: Strict typed parsing and canonical serialization
**Reason**: The version 1 field layout is replaced by the strict v2 field layout.
**Migration**: Serialize and parse only the v2 metadata, coordinate-system, and typed dataset fields.

### Requirement: Data point shape matches the chart type
**Reason**: Two generic v1 point shapes cannot express the selected chart families safely.
**Migration**: Use the typed v2 dataset branch that corresponds to `metadata.chart_type`.

### Requirement: Chart-specific semantic validation
**Reason**: V2 introduces family-specific data shapes and constraints that replace v1 point validation.
**Migration**: Validate new content against the v2 family rules; no v1 conversion is performed.

### Requirement: Pure and bounded validation result
**Reason**: This requirement is replaced to state the v2 validation boundary and version behavior explicitly.
**Migration**: Consume bounded deterministic v2 parse and validation issues.

## ADDED Requirements

### Requirement: Provide a version 2 single-chart content model
Figura SHALL provide an immutable `ChartSpecData` version 2 with exactly `schema_version`, `metadata`, `coordinate_system`, and `dataset`. `schema_version` SHALL equal 2. `metadata.chart_type` SHALL be exactly one of `bar`, `line`, `scatter`, `pie`, `area`, `histogram`, `box_plot`, `radar`, `heatmap`, or `treemap`. Metadata SHALL contain `chart_type` and MAY contain `title`, display-only `source`, and `note`; omitted text SHALL normalize to the documented empty or null default. Metadata SHALL NOT contain Run identity, source authorization, evidence provenance, generation context, storage location, rendering state, or publication state.

`coordinate_system` SHALL be a typed value with kind `cartesian`, `polar`, `matrix`, `hierarchical`, or `none`. Bar, line, scatter, area, histogram, and box plot SHALL use `cartesian`; radar SHALL use `polar`; heatmap SHALL use `matrix`; treemap SHALL use `hierarchical`; pie SHALL use `none`. Any mismatch between chart type and coordinate-system kind SHALL be rejected. Numeric values SHALL be finite binary64-representable values. Text fields SHALL retain the shared 160-character contract. Ordered collections SHALL retain the current 512-item ChartSpec bound, and the canonical serialized ChartSpec SHALL remain within the existing 256 KiB ChartSpec bound.

The closed coordinate-system shapes SHALL be: `cartesian` with exactly `kind`, `x_axis`, and `y_axis`, where each axis has `kind` (`categorical`, `numeric`, or `time`) and optional `label`; `polar` with exactly `kind` and `value_range` (`min`, `max`, with `min < max`); and `matrix`, `hierarchical`, or `none` with exactly `kind`. Categorical coordinate values SHALL be strings, numeric coordinate values SHALL be finite numbers, and time coordinate values SHALL be RFC 3339 date-time strings. Axis labels SHALL be display text only; renderers SHALL derive ranges from valid dataset values and SHALL NOT infer units from labels.

#### Scenario: Round-trip a v2 chart of every supported family
- **WHEN** valid v2 ChartSpecData is serialized and parsed
- **THEN** the result preserves its family, metadata, coordinate system, typed dataset, and declared order

#### Scenario: Reject a v1 ChartSpec
- **WHEN** the new ChartSpec parser receives `schema_version: 1`
- **THEN** it returns a bounded unsupported-version issue and produces no ChartSpecData value

#### Scenario: Reject a coordinate-system mismatch
- **WHEN** a chart family is paired with a coordinate-system kind not allowed for that family
- **THEN** validation reports the applicable field path and marks the ChartSpec invalid

#### Scenario: Keep runtime identity outside chart content
- **WHEN** input includes Run identity, evidence provenance, storage, or publication fields
- **THEN** strict parsing rejects those undeclared fields

### Requirement: Use a strict typed dataset for each selected family
The v2 `dataset` SHALL have a closed family-specific shape selected by `metadata.chart_type`; it SHALL NOT accept arbitrary row objects or unknown nested fields. IDs SHALL be unique within their collection and be nonempty strings of at most 64 characters. Display labels SHALL use the shared 160-character text bound. Every ordered collection SHALL contain at most 512 items.

- Bar data SHALL contain exactly `orientation`, `mode`, `categories`, and `series`. `orientation` SHALL be `vertical` or `horizontal`; `mode` SHALL be `grouped` or `stacked`. Categories SHALL be ordered `{id, label}` items. Series SHALL be ordered `{id, label, values}` items whose values array has one finite number per category. Vertical bars SHALL use categorical x and numeric y; horizontal bars SHALL use numeric x and categorical y. Negative values SHALL be valid; stacked positive and negative values SHALL accumulate separately around zero.
- Line data SHALL contain exactly `series`; each series SHALL contain `id`, `label`, and ordered `{x, y}` points. Its coordinate system SHALL use a categorical, numeric, or time x-axis and a numeric y-axis. `x` SHALL match the declared x-axis kind; `y` SHALL be finite numeric or null. Null y SHALL represent an explicit line gap.
- Area data SHALL contain exactly `stacking` and `series`, using the Line series/point shape. Its coordinate system SHALL use a categorical, numeric, or time x-axis and a numeric y-axis. `stacking` SHALL be `none` or `stacked`; stacked series SHALL share the same ordered x values and SHALL NOT contain null y values. Positive and negative stacked values SHALL accumulate separately around zero.
- Scatter data SHALL contain exactly `series`; its coordinate system SHALL use numeric x and y axes. Each series SHALL contain `id`, `label`, and points with numeric `x`, numeric `y`, and optional positive `size`. Size SHALL be present on every point or absent from every point in the dataset. Absent size SHALL mean ordinary scatter; present size SHALL encode bubble area.
- Pie data SHALL contain exactly `slices` and optional `inner_radius_ratio`. Each slice SHALL contain a unique `id`, `label`, and nonnegative finite `value`; the total SHALL be positive and finite. `inner_radius_ratio` SHALL be from 0 through 0.75; zero or omission means pie, and a positive ratio means donut.
- Histogram data SHALL contain exactly `measure` and `bins` and SHALL use numeric x and y axes. `measure` SHALL be `count`, `frequency`, `probability`, `density`, or `unknown`. Each bin SHALL contain finite `start`, `end`, and nonnegative `value`, with `start < end`. Bins SHALL be ordered and SHALL NOT overlap; a gap between bins SHALL remain a gap.
- Box-plot data SHALL contain exactly `orientation` and `groups`. `orientation` SHALL be `vertical` or `horizontal`. Each group SHALL contain `id`, `label`, `lower_whisker`, `q1`, `median`, `q3`, `upper_whisker`, and optional finite `outliers[]`, ordered so `lower_whisker <= q1 <= median <= q3 <= upper_whisker`. The coordinate axes SHALL be categorical/numeric according to orientation. Outliers are explicitly plotted observations and SHALL NOT be inferred from a statistical rule by the renderer.
- Radar data SHALL contain exactly ordered `dimensions` and `series`. Dimensions SHALL contain unique `{id, label}` items. Each series SHALL contain `id`, `label`, and exactly one finite value per dimension. The polar `value_range` SHALL be finite and contain all values.
- Heatmap data SHALL contain exactly ordered `x_categories`, ordered `y_categories`, and `values`. Categories SHALL contain unique `{id, label}` items. `values` SHALL be rectangular and row-major, with rows matching y categories and columns matching x categories; cells SHALL be finite numbers or null. Null SHALL mean an explicitly absent cell, not an unreadable value.
- Treemap data SHALL contain exactly `root_id` and `nodes`. Each node SHALL contain `id`, nullable `parent_id`, `label`, and optional finite `value`. There SHALL be one root matching `root_id`, all parent references SHALL resolve, and the hierarchy SHALL be acyclic. Leaves SHALL have positive finite values. An internal node's optional value SHALL agree with the sum of descendant leaf values when `abs(value - descendant_sum) <= 1e-9 * max(1, abs(value), abs(descendant_sum))`. When absent, the renderer SHALL derive the parent's area from descendant leaf weights.

#### Scenario: Reject a dataset shape for another family
- **WHEN** a dataset's fields do not match the selected `metadata.chart_type`
- **THEN** parsing or validation returns a bounded issue and accepts no partial value

#### Scenario: Preserve zero, missing, and gaps distinctly
- **WHEN** a valid dataset contains numeric zero, a permitted null cell, or a null line/area y value
- **THEN** Figura preserves each meaning and does not coerce missing content to zero

#### Scenario: Reject malformed radar, matrix, or hierarchy structure
- **WHEN** radar series lengths differ from dimensions, heatmap rows differ from the declared width, or treemap parents are missing/cyclic
- **THEN** semantic validation identifies the invalid path and the ChartSpec is not generation-ready

#### Scenario: Validate donut and bubble as family variants
- **WHEN** a pie dataset supplies a valid inner radius or a scatter dataset supplies positive point sizes
- **THEN** the content remains a `pie` or `scatter` family with the corresponding donut or bubble behavior

### Requirement: Parse strictly and serialize canonically
The v2 parser SHALL reject duplicate JSON keys, unknown fields at every nesting level, missing required fields, booleans used as numbers, numeric strings, NaN, infinity, and values outside declared text, item, or payload bounds. It SHALL NOT coerce, fill, clamp, reorder, silently discard, or partially accept input. Canonical serialization SHALL emit only the v2 contract fields, preserve meaningful array order, normalize only documented defaults, and be deterministic for the same value. Parse issues SHALL include bounded stable codes and JSON Pointer paths without echoing submitted values. The v2 contract SHALL NOT include a v1 compatibility parser, converter, or serializer.

#### Scenario: Reject unknown fields and duplicate keys
- **WHEN** JSON contains an undeclared field or duplicate object key at any nesting level
- **THEN** parsing reports a bounded issue and returns no ChartSpecData value

#### Scenario: Reject coercion and non-finite values
- **WHEN** numeric fields contain booleans, strings, NaN, or infinity
- **THEN** parsing or semantic validation reports the affected path without converting the value

#### Scenario: Serialize the same content deterministically
- **WHEN** the same valid v2 content is serialized repeatedly
- **THEN** every serialization is byte-identical and within the shared ChartSpec bound

### Requirement: Keep v2 validation pure and bounded
ChartSpec v2 parsing and validation SHALL be deterministic and side-effect free. Validation SHALL distinguish shape/parsing failures from semantic issues, SHALL return issues in stable order within the configured issue bound, and SHALL NOT access Runs, attachments, measurements, files, Providers, storage, or rendering. Validation SHALL report defects without repairing or mutating the supplied content.

#### Scenario: Report multiple independent v2 defects
- **WHEN** a correctly shaped v2 value contains multiple independent semantic errors
- **THEN** validation returns bounded issues in stable order without raising an uncaught exception

#### Scenario: Leave invalid data unchanged
- **WHEN** validation receives unordered, incomplete, or out-of-domain chart data
- **THEN** it reports the applicable issues and preserves the original order and values
