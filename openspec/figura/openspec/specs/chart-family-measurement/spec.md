# chart-family-measurement Specification

## Purpose

Provides one source-authorized measurement contract for the ten chart families selected for Figura, while keeping type selection with the Agent and preserving uncertainty in pixel-based observations.

## Requirements

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
For every readable source and supported `chart_type`, `measure_chart` SHALL return a bounded version 3 result containing `schema_version`, `chart_type`, `source_kind`, `source_id`, `image_size`, `coordinate_system`, `status`, `plot_area_px`, `observations`, `confidence`, `warnings`, `truncated`, `coverage`, `issues`, `evidence`, `calibrations`, and `value_provenance`. `coordinate_system` SHALL be `attachment_px` or `panel_px`; `image_size` SHALL contain positive `width` and `height`; `status` SHALL be `measured`, `partial`, `no_evidence`, or `unsupported`; and `plot_area_px` SHALL be a source-pixel rectangle or null. `confidence` SHALL contain bounded values from 0 through 1 for `overall`, `geometry`, `calibration`, and `association`. `observations` SHALL have a closed family-specific shape selected by `chart_type`; it SHALL NOT be an untyped arbitrary object. Each observation collection SHALL contain at most 512 items. `warnings` SHALL contain at most 32 strings, each at most 256 characters. Pixel coordinates SHALL be finite, nonnegative, bounded by the source image dimensions, and expressed in the full source-pixel frame.

`measured` SHALL mean the primary visible structure and applicable numeric interpretation and associations have no known critical gap; emitted values SHALL have validated evidence support. It SHALL NOT claim ground truth or complete hidden-object coverage. `partial` SHALL mean some usable family evidence exists but coverage, association, or required calibration is incomplete, or one or more collections were truncated. `no_evidence` SHALL mean no visible candidate for the requested family was found. `unsupported` SHALL mean visible chart geometry is incompatible with the requested family or falls outside its supported two-dimensional scope. `truncated: true` SHALL imply `status: partial`.

The family-specific observation SHALL preserve these minimum evidence:
- `bar`: orientation and grouping/stacking mode, axes and baseline, series, and each bar's pixel rectangle/polygon, category/series association, pixel length, and nullable calibrated value.
- `line`: axes, series, separate pixel polylines, and sampled/marked points with source positions, nullable calibrated coordinates, point source, and nullable category references/labels.
- `scatter`: axes, visible point centers, nullable calibrated x/y coordinates, optional pixel radius/size observations, series association, and merged/occluded/dense/overlap flags.
- `pie`: center and outer radius, ordered sector start/sweep angles, nullable angular ratio, optional label/color, and inner radius when a donut hole is detected.
- `area`: axes, series boundary polylines/polygons, baseline or lower boundaries, nullable calibrated boundary values, and aligned category/x samples with nullable upper, lower, and individual-series values.
- `histogram`: axes and each bin's pixel rectangle, visible interval boundaries, nullable calibrated interval/value, and a visible y-measure classification (`count`, `frequency`, `probability`, `density`, or `unknown`).
- `box_plot`: axes and each category group's box, quartiles, median, lower/upper whisker endpoints, and explicitly visible outlier pixel positions with nullable calibrated values.
- `radar`: center, dimension spokes, radial grid/ticks, and each series' ordered dimension-referenced vertices with nullable pixel positions and calibrated values; a missing vertex SHALL NOT be represented by a spoke endpoint.
- `heatmap`: row and column labels, each cell's pixel rectangle and color, and nullable value supported by associated explicit cell text or a readable calibrated color scale.
- `treemap`: each visible rectangle's pixel bounds, label, hierarchy association, nullable explicit value, observable area ratio, leaf/group/unknown role, and explicit parent/root plot denominator identity.

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

Coverage SHALL record full-source versus scoped observation, supplied scope, structural coverage as established/partial/unknown, and detected counts with family-specific closed keys. It SHALL NOT invent true object counts or coverage percentages. Issues SHALL identify a bounded code, affected JSON Pointer, evidence references and message without prescribing Agent actions. Evidence SHALL have unique local IDs and closed OCR/geometry shapes in source coordinates. Calibrations SHALL have unique IDs, closed axis/radial/color-scale parameters, support evidence references, supported state, residual and support domain. Value provenance SHALL identify the numeric JSON Pointer, method, evidence/calibration references, derived input paths and nullable supported error bound. All collections SHALL be bounded and dependencies of retained values SHALL remain valid. Confidence SHALL remain evidence strength rather than statistical accuracy.

#### Scenario: Geometry without required numeric support is partial
- **WHEN** radar or heatmap geometry exists but required numeric support is missing
- **THEN** geometry remains observable, unsupported values are null, and status is partial with the corresponding issue

#### Scenario: Scoped measurement retains source identity
- **WHEN** a valid local scope is measured
- **THEN** coverage identifies scoped observation, coordinates retain the source frame, and the call creates no Panel

### Requirement: Keep measurement results as fallible candidate evidence
Measurement results SHALL remain observations for the Agent to interpret and SHALL NOT automatically become ChartSpec data. A chart-unit value SHALL be non-null only when directly legible from supported text, supported calibration/geometry for that family, or a validated derivation from supported inputs. Unavailable values SHALL remain null; visible zero, absent data, and unreadable data SHALL remain distinguishable. Pie sector ratio SHALL derive from observed angle coverage; bubble size SHALL be a visual size observation, not a hidden sample count; treemap area SHALL not be reported as an exact source value unless that value is visibly supported. Warnings SHALL identify ambiguity, partial coverage, unsupported geometry, and missing calibration. Measurement SHALL NOT auto-retry, select preferred series, block Figure assembly, include image bytes, or include local paths in durable JSON.

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

### Requirement: Validate numeric provenance and evidence references
Every non-null semantic chart number or ratio SHALL have exactly one provenance entry linking it to supported text, calibration, geometry ratio, or supported derived inputs. Pure pixel geometry, confidence and calibration parameters SHALL NOT require separate chart-value entries. Paths SHALL resolve to emitted values; references SHALL resolve within the same result/source; calibrated values SHALL reference supported calibration; derived input paths SHALL be acyclic. Unresolved text/geometry conflicts SHALL preserve evidence, set the authoritative numeric field to null, and return a value-conflict issue. Results SHALL remain candidate evidence, not automatic ChartSpec data.

#### Scenario: Reject invalid support
- **WHEN** support references are dangling, numeric paths do not exist, or derived inputs are cyclic
- **THEN** result validation rejects the invalid result before successful commit

#### Scenario: Preserve dependency closure during truncation
- **WHEN** an observation or evidence bound is reached
- **THEN** retained observations have complete support, unsupported values are cleared or omitted, and status is partial with truncated true

#### Scenario: Preserve conflicting readings
- **WHEN** associated text and geometry disagree without a supported reconciliation
- **THEN** both evidence sources are retained, the authoritative value is null, and an issue identifies the conflict

### Requirement: Separate data objects from legends and calibration regions
Within the effective authorized scope, measurement SHALL distinguish data objects from titles, legends, axes and color scales using layout and geometric support. Distinct body colors SHALL NOT be suppressed solely by broad RGB similarity, and small legitimate objects SHALL NOT be discarded solely by color-area ranking. OCR roles SHALL use spatial/layout/object relations; ambiguous labels SHALL remain unknown. Excluded pixels SHALL NOT restore calibration.

#### Scenario: Preserve the red bar series
- **WHEN** blue, orange and red series each have four visible grouped bars
- **THEN** all twelve bars and three series remain observable without suppressing red by RGB similarity

#### Scenario: Exclude legend points
- **WHEN** nine scatter data points coexist with two legend markers
- **THEN** nine data points are returned and legend markers only support association

#### Scenario: Do not relabel radar dimensions as series
- **WHEN** a dimension label is close to a colored polygon
- **THEN** proximity alone does not associate it as a series name

#### Scenario: Honor excluded calibration pixels
- **WHEN** scope excludes ticks or legend text
- **THEN** these pixels provide no support and resulting gaps are reported

### Requirement: Calibrate values without unsupported assumptions
Measurement SHALL support readable ordinary linear axis and radial tick mappings and readable color-scale mappings with explicit support, residual and valid domain. It SHALL consistently parse supported signs, decimals, percentages and explicit scale units, handle reversed axes and nonzero origins, and not silently apply linear calibration to detected incompatible nonlinear/broken axes. Failed calibration SHALL preserve geometry. Color-scale matching SHALL use the visible scale rather than assume a named colormap.

#### Scenario: Read a nonzero origin
- **WHEN** supported ticks establish a nonzero axis origin
- **THEN** numeric values follow that origin rather than assuming zero

#### Scenario: Decline ambiguous color inversion
- **WHEN** a cell color matches materially different values on a color scale
- **THEN** color evidence is preserved with null value and an ambiguity issue

### Requirement: Extract native structures across the ten families
Within supported ordinary two-dimensional layouts, measurement SHALL extract structures and supported values for all ten families. Bar SHALL preserve category/series and grouping/stacking; line SHALL distinguish markers from tick sampling, retain categories and disconnected traces; scatter SHALL retain visible centers, independent axis readings and overlap uncertainty; pie SHALL retain angular sectors and ratios without invented totals. Area SHALL retain upper/lower boundaries and aligned samples, using their difference only for established stacked layers. Histogram SHALL retain numeric bin boundaries and measured heights independently of unknown y-measure semantics. Box plots SHALL combine box, median, whisker and outlier evidence in ordinary vertical/horizontal layouts without claiming raw samples. Radar SHALL associate dimension vertices and radial calibration. Heatmaps SHALL retain grid cells independently of shared colors and read supported cell text/color-scale values. Treemaps SHALL retain supported leaves/groups/hierarchy and explicit relative-area denominators without invented parents or absolute values.

#### Scenario: Extract two six-marker lines
- **WHEN** two series contain six visible markers each alongside legend samples
- **THEN** twelve data markers, their categories/series and supported values are returned without extra legend series

#### Scenario: Read stacked area layers
- **WHEN** two layers share five readable sample positions and calibrated upper/lower boundaries
- **THEN** each layer retains five associated samples with individual values rather than cumulative upper values

#### Scenario: Keep calibrated histogram heights with unknown semantics
- **WHEN** six bin intervals and heights are calibrated but the y-axis meaning is unreadable
- **THEN** supported values remain available, y_measure is unknown, and the semantic gap is reported

#### Scenario: Extract colored box groups
- **WHEN** three colored boxes have visible median and whisker evidence
- **THEN** three groups and supported statistics are returned, ordering conflicts are flagged, and sample min/max are not invented

#### Scenario: Extract radar vertices
- **WHEN** five dimensions, two polygons and readable radial ticks exist
- **THEN** vertices reference the correct dimensions and supported radial values, while missing positions remain null

#### Scenario: Retain the heatmap grid
- **WHEN** four rows and five columns coexist with a colorbar and adjacent equal-colored cells
- **THEN** twenty cells have correct associations and the colorbar is not a cell

#### Scenario: Recover tree grouping
- **WHEN** four leaves have readable group headers and boundaries
- **THEN** supported parent relationships and explicit area denominators are returned even without filled group rectangles

#### Scenario: Keep donut angle semantics
- **WHEN** five donut sectors have percentage labels but no total
- **THEN** five sectors and supported angular ratios are returned without absolute values

### Requirement: Publish the measurement contract atomically
Current measurement producers and consumers SHALL activate the updated Registry/contract together without old-contract conversion executors or family aliases. Durable prior facts SHALL remain unchanged and readable as original records without reinterpretation under the new schema. Previous Registry Runs SHALL be terminal before activation. Tool descriptions SHALL include correct normalized-scope examples and distinguish geometry from semantic values.

#### Scenario: Activate after prior Runs terminate
- **WHEN** the updated Registry is deployed
- **THEN** prior Registry Runs are terminal, new results use the updated contract, and old facts are neither rewritten nor converted
