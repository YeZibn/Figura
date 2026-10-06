## Purpose

Provides one source-authorized measurement contract for the ten chart families selected for Figura, while keeping type selection with the Agent and preserving uncertainty in pixel-based observations.

## ADDED Requirements

### Requirement: The Agent selects a supported chart family before measurement
The model-facing tool registry SHALL expose one chart-measurement tool named `measure_chart` and SHALL NOT expose separate `measure_bars`, `measure_lines`, `measure_scatter`, or `measure_pie` tools to new Runs. `measure_chart` SHALL require `chart_type` from exactly `bar`, `line`, `scatter`, `pie`, `area`, `histogram`, `box_plot`, `radar`, `heatmap`, or `treemap`. Bubble charts SHALL use `scatter`; donut charts SHALL use `pie`. The Agent SHALL select the family from the user's description, already available visual context, or an explicitly loaded source image. When the family cannot be judged from available information, the Agent SHALL use `load_image` and make the selection after the image is included in a later Provider request. `measure_chart` SHALL NOT call a Provider, run a hidden classifier, or silently change the requested family. A family mismatch or unsupported geometry SHALL be returned as an observation outcome for the Agent to interpret. Figura SHALL NOT automatically repeat a measurement because its result is partial, unsupported, or uncertain.

#### Scenario: Measure a family named by the user
- **WHEN** the user's request identifies a supported family and the Agent invokes `measure_chart` with that `chart_type`
- **THEN** Figura routes the call to that family's measurement behavior without requiring an image-loading call solely to satisfy the tool

#### Scenario: Observe an image before choosing an unclear family
- **WHEN** the family cannot be determined from the user's request or current visual context
- **THEN** the Agent can call `load_image`, receive the original image in a subsequent Provider request, and then select one supported `chart_type`

#### Scenario: Do not classify through a hidden Provider call
- **WHEN** `measure_chart` executes
- **THEN** it performs no nested or hidden Provider request and the Run records one ordinary tool call with the selected `chart_type`

#### Scenario: Reject a family outside the selected scope
- **WHEN** the image depicts a chart family outside the ten supported values
- **THEN** the Agent does not coerce it into a supported family and explains that the chart is outside the current measurement scope

#### Scenario: Keep the prior Registry out of the new Registry
- **WHEN** the new chart-family Registry is activated
- **THEN** it exposes only `measure_chart` for chart measurement and contains no aliases or compatibility executor for the previous Registry; deployment SHALL occur only after Runs bound to the previous Registry are terminal

### Requirement: Measure only an authorized source with one common input contract
`measure_chart` SHALL accept exactly `source_kind` (`attachment` or `panel`), an opaque `source_id`, required `chart_type`, and optional `observation_scope`; it SHALL reject additional arguments. Figura SHALL resolve only a matching Attachment or Panel in the target Run's authorized resource catalog and verify Session ownership through the corresponding Sources service before reading image bytes. It SHALL NOT accept a filesystem path, URL, or image bytes from the model, and it SHALL NOT require a preceding `load_image` call. When `observation_scope` is omitted, Figura SHALL analyze the complete selected source. Invalid scope or a scope with no observable pixels SHALL return a bounded structured failure and SHALL NOT widen the analysis to the full image.

`observation_scope` SHALL contain only optional `include` and `exclude` arrays. Each supplied array SHALL contain 1 through 4 polygons; each polygon SHALL contain 3 through 32 integer `[x, y]` points in the inclusive range `0..1000`, normalized to the selected source dimensions. The effective area SHALL be the union of included polygons, or the full source when `include` is absent, minus the union of excluded polygons; exclusions SHALL take precedence. Figura SHALL apply the same effective area to the selected family's geometry, OCR, and label association while retaining complete source-pixel coordinates. The scope SHALL NOT be treated as a plot boundary or calibration.

#### Scenario: Measure an authorized Attachment or Panel
- **WHEN** the call names an Attachment or Panel reference in the target Run's same-Session resource catalog
- **THEN** Figura reads only that authorized image and returns coordinates in its full source-pixel frame

#### Scenario: Reject an unavailable or cross-Session source
- **WHEN** the source ID is unknown, unreferenced, or belongs to another Session
- **THEN** Figura returns a bounded failure without reading its image bytes

#### Scenario: Exclude an irrelevant region
- **WHEN** a valid scope contains both included and excluded polygons
- **THEN** geometry, OCR, and label association use the effective included area after exclusions take precedence

#### Scenario: Reject invalid or empty scope
- **WHEN** the scope has invalid polygon counts, invalid points, unknown fields, or no remaining observable pixels
- **THEN** Figura returns a bounded structured failure and does not fall back to unscoped measurement

### Requirement: Return a common envelope with typed family observations
For every readable source and supported `chart_type`, `measure_chart` SHALL return a bounded version 2 result containing `schema_version`, `chart_type`, `source_kind`, `source_id`, `image_size`, `coordinate_system`, `status`, `plot_area_px`, `observations`, `confidence`, `warnings`, and `truncated`. `coordinate_system` SHALL be `attachment_px` or `panel_px`; `image_size` SHALL contain positive `width` and `height`; `status` SHALL be `measured`, `partial`, `no_evidence`, or `unsupported`; and `plot_area_px` SHALL be a source-pixel rectangle or null. `confidence` SHALL contain bounded values from 0 through 1 for `overall`, `geometry`, `calibration`, and `association`. `observations` SHALL have a closed family-specific shape selected by `chart_type`; it SHALL NOT be an untyped arbitrary object. Each observation collection SHALL contain at most 512 items. `warnings` SHALL contain at most 32 strings, each at most 256 characters. Pixel coordinates SHALL be finite, nonnegative, bounded by the source image dimensions, and expressed in the full source-pixel frame.

`measured` SHALL mean the requested family and its primary visible geometry are sufficiently established for the returned observations; any emitted numeric value SHALL have direct text or calibration support. `partial` SHALL mean some usable family evidence exists but coverage, association, or required calibration is incomplete, or one or more collections were truncated. `no_evidence` SHALL mean no visible candidate for the requested family was found. `unsupported` SHALL mean visible chart geometry is incompatible with the requested family or falls outside its supported two-dimensional scope. `truncated: true` SHALL imply `status: partial`.

The family-specific observation SHALL preserve these minimum evidence:
- `bar`: orientation and grouping/stacking mode, axes and baseline, series, and each bar's pixel rectangle/polygon, category/series association, pixel length, and nullable calibrated value.
- `line`: axes, series, separate pixel polylines, and sampled/marked points with source positions, nullable calibrated coordinates, and point source.
- `scatter`: axes, visible point centers, nullable calibrated x/y coordinates, optional pixel radius/size observations, series association, and merged/occluded/dense/overlap flags.
- `pie`: center and outer radius, ordered sector start/sweep angles, nullable angular ratio, optional label/color, and inner radius when a donut hole is detected.
- `area`: axes, series boundary polylines/polygons, baseline or lower boundaries, and nullable calibrated boundary values.
- `histogram`: axes and each bin's pixel rectangle, visible interval boundaries, nullable calibrated interval/value, and a visible y-measure classification (`count`, `frequency`, `probability`, `density`, or `unknown`).
- `box_plot`: axes and each category group's box, quartiles, median, lower/upper whisker endpoints, and explicitly visible outlier pixel positions with nullable calibrated values.
- `radar`: center, dimension spokes, radial grid/ticks, and each series' ordered pixel vertices with nullable calibrated values.
- `heatmap`: row and column labels, each cell's pixel rectangle and color, and nullable calibrated value when a readable color scale supports it.
- `treemap`: each visible rectangle's pixel bounds, label, hierarchy association, nullable explicit value, and observable area ratio.

The result SHALL retain at most the applicable shared observation limits. If the sensor omits candidates because a bound is reached, it SHALL set `truncated` and include a warning. It SHALL NOT silently return a truncated result as complete.

#### Scenario: Return the requested family shape
- **WHEN** an authorized chart of one supported family is measurable
- **THEN** the result contains the common envelope and only that family's typed observation shape

#### Scenario: Preserve separate trace segments
- **WHEN** a line or area trace is visibly fragmented
- **THEN** the result retains separate observed segments and does not bridge an unsupported gap

#### Scenario: Distinguish categorical bars from histogram bins
- **WHEN** the selected chart is a histogram with numeric intervals
- **THEN** the result represents ordered intervals and counts rather than inventing discrete category labels

#### Scenario: Preserve heatmap geometry without a calibrated color scale
- **WHEN** cell regions and colors are visible but the color scale cannot be calibrated
- **THEN** the result retains cell geometry and color observations with null numeric values and a warning

#### Scenario: Mark observations truncated at a shared bound
- **WHEN** the number of detected observations exceeds the applicable result bound
- **THEN** Figura returns a bounded partial result with `truncated: true` and an explanatory warning

### Requirement: Keep measurement results as fallible candidate evidence
Measurement results SHALL remain observations for the Agent to interpret and SHALL NOT automatically become ChartSpec data. A chart-unit value SHALL be non-null only when directly legible from supported text or supported calibration/geometry for that family. Unavailable values SHALL remain null; visible zero, absent data, and unreadable data SHALL remain distinguishable. Pie sector ratio SHALL derive from observed angle coverage; bubble size SHALL be a visual size observation, not a hidden sample count; treemap area SHALL not be reported as an exact source value unless that value is visibly supported. Warnings SHALL identify ambiguity, partial coverage, unsupported geometry, and missing calibration. Measurement SHALL NOT auto-retry, select preferred series, block Figure assembly, include image bytes, or include local paths in durable JSON.

#### Scenario: Preserve geometry when calibration fails
- **WHEN** family geometry is visible but required axes, ticks, or color scale cannot be calibrated
- **THEN** Figura returns the pixel evidence, nulls unavailable numeric values, and reports `partial` with a warning

#### Scenario: Do not infer hidden scatter points
- **WHEN** scatter markers overlap, merge, or form a dense cluster
- **THEN** Figura marks visible uncertainty and does not claim an exact hidden-point count

#### Scenario: Do not convert pie labels into unsupported source values
- **WHEN** a pie label is visible but sector geometry or the label's meaning is uncertain
- **THEN** Figura preserves the visible label as observation and does not claim a source value or ratio unsupported by evidence

#### Scenario: Leave follow-up decisions to the Agent
- **WHEN** a result is partial or contains warnings
- **THEN** Figura commits the observation once and leaves any further observation choice to the Agent

#### Scenario: Keep source bytes out of result facts
- **WHEN** a measurement result commits
- **THEN** its JSON contains no original image bytes, annotation image, filesystem path, or raw implementation exception
