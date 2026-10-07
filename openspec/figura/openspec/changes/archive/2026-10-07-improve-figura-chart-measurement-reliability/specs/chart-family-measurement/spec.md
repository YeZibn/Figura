## MODIFIED Requirements

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
- **WHEN** cell regions and colors are visible but neither associated cell text nor a calibrated color scale supports numeric values
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

## ADDED Requirements

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
