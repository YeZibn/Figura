## MODIFIED Requirements

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
