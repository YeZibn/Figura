# bar-chart-measurement Specification

## Purpose

Provides structured, source-bound pixel measurements for two-dimensional bar charts so the Agent can use geometric evidence without treating uncertain image analysis as exact chart data.

## Requirements

### Requirement: Measure bars from an authorized Attachment or Panel
Figura SHALL register a `measure_bars` tool accepting exactly `source_kind` (`attachment` or `panel`), an opaque `source_id`, and optional `observation_scope`; it SHALL reject additional arguments. For `attachment`, Figura SHALL resolve only an attachment resource in the target Run's read-only `RunExecutionState.resources` catalog whose typed reference has kind `attachment` and the requested opaque ID; for `panel`, it SHALL resolve only a Panel resource whose typed reference has kind `panel` and the requested opaque ID. Figura SHALL verify ownership through the corresponding source service before reading image bytes. The tool SHALL analyze the complete selected source when scope is omitted, SHALL NOT require a preceding `load_image` call, and SHALL NOT accept a filesystem path, URL, or image bytes from the model.

`observation_scope` SHALL be an object with no fields other than optional `include` and `exclude` arrays of polygons. Each supplied array SHALL contain 1 through 4 polygons; each polygon SHALL contain 3 through 32 points; each point SHALL be an integer `[x, y]` pair with both coordinates in the inclusive range `0..1000`, normalized to the selected source's width and height. When `include` is absent, the full source is included; when present, the included area is the union of its polygons. The union of `exclude` polygons SHALL be removed from the included area, and exclusions SHALL take precedence where polygons overlap. A supplied scope SHALL contain at least one `include` or `exclude` array. Figura SHALL apply the resulting effective area to bar geometry detection, OCR, and label association. All returned geometry SHALL remain in the selected source's pixel coordinate system; the observation scope SHALL NOT itself be treated as a calibrated plot area. A scope that produces no observable source pixels SHALL return a bounded structured tool failure. An invalid scope SHALL return a bounded structured tool failure and SHALL NOT fall back to unscoped measurement.

#### Scenario: Measure an authorized Attachment
- **WHEN** the model calls `measure_bars` with `source_kind: attachment` and an attachment ID matching an attachment resource reference in the target Run's resource catalog
- **THEN** Figura resolves that Attachment within the same Session and measures its image without exposing its local path or bytes in the tool result

#### Scenario: Measure an authorized Panel
- **WHEN** the model calls `measure_bars` with `source_kind: panel` and a Panel resource reference with the matching opaque ID in the target Run's resource catalog
- **THEN** Figura resolves that Panel within the same Session and measures the independent Panel image

#### Scenario: Reject a source outside the Run inventory
- **WHEN** the model supplies an unknown, unreferenced, or cross-Session Attachment or Panel ID
- **THEN** Figura returns a bounded structured tool failure and reads no image bytes

#### Scenario: Measure an Attachment containing multiple charts
- **WHEN** the model selects an authorized Attachment that contains multiple chart regions and omits `observation_scope`
- **THEN** Figura analyzes the entire Attachment and returns source-coordinate candidates and any sensor warnings without silently substituting or cropping to a Panel

#### Scenario: Restrict bar observation to included polygons
- **WHEN** the model supplies one or more valid `include` polygons
- **THEN** Figura uses only source pixels inside their union for bar geometry detection, OCR, and label association, and returns geometry in source-pixel coordinates

#### Scenario: Exclude irrelevant regions from bar observation
- **WHEN** a valid scope contains both included and excluded polygons
- **THEN** the excluded union is removed from the included area before measurement and takes precedence where polygons overlap

#### Scenario: Treat scope as an observation region, not a plot calibration
- **WHEN** the model supplies a valid observation scope around a chart region
- **THEN** Figura uses that region to limit evidence and does not substitute it for a detected or calibrated plot area

#### Scenario: Use the complete source when scope is omitted
- **WHEN** the model omits `observation_scope`
- **THEN** Figura analyzes the complete selected source

#### Scenario: Reject invalid scope without widening observation
- **WHEN** a scope has too many polygons, an invalid point count, out-of-range coordinates, non-integer coordinates, or no polygon
- **THEN** Figura returns a bounded structured tool failure and does not measure the full source as a fallback

#### Scenario: Reject an empty effective scope
- **WHEN** valid include and exclude polygons leave no observable source pixels
- **THEN** Figura returns a bounded structured tool failure without measuring the source

### Requirement: Return pixel-based bar geometry and measurements
For a readable selected source, `measure_bars` SHALL return a bounded JSON object with `source_kind`, `source_id`, `image_size` (`width`, `height`), `coordinate_system` (`attachment_px` or `panel_px`), `status` (`measured`, `partial`, `no_evidence`, or `unsupported`), `orientation` (`vertical`, `horizontal`, `oblique`, or `unknown`), `bar_mode` (`single`, `grouped`, `stacked`, or `unknown`), `plot_area_px`, `baseline`, `axes`, `series`, `bars`, `confidence`, and `warnings`. Pixel geometry SHALL use the selected source's coordinate system. `axes` SHALL contain `x` and `y` observations. Each axis SHALL contain `kind` (`numeric`, `categorical`, or `unknown`), nullable `label_text`, nullable `label_confidence`, nullable two-point `points_px`, `ticks`, and nullable `calibration`. Each tick SHALL contain a stable result-local `id`, OCR `text`, nullable numeric `value`, `bbox_px`, `point_px`, and bounded `confidence`. A non-null calibration SHALL contain `slope`, `intercept`, `residual_value`, `support_count`, `support_span_px`, bounded `confidence`, and `calibrated`. Each detected bar SHALL include an integer `id`, one-based `category_index`, nullable `category_label` and `category_tick_id`, `series_id`, rectangular `geometry` (`bbox_px` as `[x, y, width, height]` and its four-corner `polygon_px`), and `measure` containing signed `value_length_px`, `ratio_to_shortest`, and nullable calibrated `value`. Stacked bars MAY additionally include `stack` with `segment_index`, `total_length_px`, `total_geometry`, and nullable calibrated `total_value`. Each series SHALL include a stable `id`, detected `color`, and nullable OCR-associated `label` and `label_confidence`. `baseline` SHALL be null or include `points_px`, `axis`, `slope`, `intercept`, `residual_px`, and bounded `confidence`. `confidence` SHALL contain bounded numeric `overall`, `geometry`, `calibration`, and `association` values. `warnings` SHALL describe ambiguity, incomplete evidence, or unsupported geometry.

#### Scenario: Return geometry and calibrated values for a measurable bar chart
- **WHEN** the selected image contains supported two-dimensional bars and the value axis passes linear calibration
- **THEN** the result identifies each bar's source-pixel geometry, category and series identity, signed pixel length, relative ratio, and calibrated value

#### Scenario: Preserve geometry when a baseline or axis calibration is uncertain
- **WHEN** bars are detected but the baseline or numeric value-axis calibration cannot be established reliably
- **THEN** Figura returns the detected geometry and warning, sets the status to `partial`, and uses null for every unavailable pixel-derived or calibrated measurement rather than inventing a value

#### Scenario: Return an empty observation when no bars are detected
- **WHEN** the selected image is readable but contains no detectable bar geometry
- **THEN** the tool succeeds with status `no_evidence`, empty `series` and `bars`, null `plot_area_px` and `baseline`, uncalibrated x/y axis observations, and an explanatory warning

#### Scenario: Report unsupported chart geometry
- **WHEN** the sensor identifies perspective, three-dimensional, nonlinear, broken-axis, or otherwise unsupported geometry
- **THEN** Figura returns status `unsupported` with an explanatory warning and does not claim calibrated values

### Requirement: Keep bar measurements as candidate evidence
Bar measurements SHALL remain observations for the Agent to interpret. Figura SHALL return chart-unit values only when OCR-derived numeric ticks and pixel-axis geometry pass the declared calibration gate; it SHALL retain pixel geometry and uncertainty when calibration fails. Figura SHALL NOT automatically repeat measurement or block later Agent actions because of a warning, and SHALL NOT expose image overlays, local paths, or raw image bytes in the measurement result. A readable image with uncertain or unsupported geometry SHALL remain a successful observation; source authorization or image-read failures SHALL use the bounded tool error contract.

#### Scenario: Do not infer chart-unit values without calibration
- **WHEN** a bar baseline and geometry are detected but the numeric value axis has no accepted calibration
- **THEN** the result contains pixel lengths and relative ratios only, with null calibrated values

#### Scenario: Leave evidence selection to the Agent
- **WHEN** a measurement result contains warnings or partial evidence
- **THEN** Figura returns the observation without scheduling a repeat measurement or imposing an assembly gate

#### Scenario: Keep image payloads outside measurement results
- **WHEN** the measurement tool returns a result
- **THEN** the durable JSON result contains measurement data only and no image bytes, overlay, or local filesystem path
