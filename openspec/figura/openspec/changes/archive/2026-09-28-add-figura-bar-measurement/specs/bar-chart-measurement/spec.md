## Purpose

Provides structured, source-bound pixel measurements for two-dimensional bar charts so the Agent can use geometric evidence without treating uncertain image analysis as exact chart data.

## ADDED Requirements

### Requirement: Measure bars from an authorized Attachment or Panel
Figura SHALL register a `measure_bars` tool accepting exactly `source_kind` (`attachment` or `panel`) and an opaque `source_id`. For `attachment`, Figura SHALL resolve only an attachment in the target Run's `RunExecutionState.available_attachments`; for `panel`, it SHALL resolve only a Panel in `RunExecutionState.panels`. Figura SHALL verify ownership through the corresponding source service before reading image bytes. The tool SHALL analyze the entire selected source, SHALL NOT require a preceding `load_image` call, and SHALL NOT accept a filesystem path, URL, or image bytes from the model.

#### Scenario: Measure an authorized Attachment
- **WHEN** the model calls `measure_bars` with `source_kind: attachment` and an attachment ID in the target Run's available attachment inventory
- **THEN** Figura resolves that Attachment within the same Session and measures its image without exposing its local path or bytes in the tool result

#### Scenario: Measure an authorized Panel
- **WHEN** the model calls `measure_bars` with `source_kind: panel` and a Panel ID in `RunExecutionState.panels`
- **THEN** Figura resolves that Panel within the same Session and measures the independent Panel image

#### Scenario: Reject a source outside the Run inventory
- **WHEN** the model supplies an unknown, unreferenced, or cross-Session Attachment or Panel ID
- **THEN** Figura returns a bounded structured tool failure and reads no image bytes

#### Scenario: Measure an Attachment containing multiple charts
- **WHEN** the model selects an authorized Attachment that contains multiple chart regions
- **THEN** Figura analyzes the entire Attachment and returns source-coordinate candidates and any sensor warnings without silently substituting or cropping to a Panel

### Requirement: Return pixel-based bar geometry and measurements
For a readable selected source, `measure_bars` SHALL return a bounded JSON object with `source_kind`, `source_id`, `image_size` (`width`, `height`), `coordinate_system` (`attachment_px` or `panel_px`), `status` (`measured`, `partial`, `no_evidence`, or `unsupported`), `orientation` (`vertical`, `horizontal`, `oblique`, or `unknown`), `bar_mode` (`single`, `grouped`, `stacked`, or `unknown`), `plot_area_px`, `baseline`, `series`, `bars`, `confidence`, and `warnings`. Pixel geometry SHALL use the selected source's coordinate system. Each detected bar SHALL include an integer `id`, one-based `category_index`, `series_id`, rectangular `geometry` (`bbox_px` as `[x, y, width, height]` and its four-corner `polygon_px`), and `measure` containing signed `value_length_px` and `ratio_to_shortest`. Stacked bars MAY additionally include `stack` with `segment_index`, `total_length_px`, and `total_geometry`. Each series SHALL include a stable `id` and detected `color`; its semantic label SHALL NOT be inferred when unavailable. `baseline` SHALL be null or include `points_px`, `axis`, `slope`, `intercept`, `residual_px`, and `confidence`. `confidence` SHALL contain bounded numeric `overall`, `geometry`, `baseline`, and `association` values. `warnings` SHALL describe ambiguity, incomplete evidence, or unsupported geometry.

#### Scenario: Return geometry for a measurable bar chart
- **WHEN** the selected image contains supported two-dimensional bars and a reliable baseline
- **THEN** the result identifies each bar's source-pixel geometry, orientation, category and series identity, signed pixel length, and ratio to the shortest valid bar

#### Scenario: Preserve geometry when the baseline is uncertain
- **WHEN** bars are detected but the zero baseline cannot be established reliably
- **THEN** Figura returns the detected geometry and a warning, sets the status to `partial`, and returns null `value_length_px` and `ratio_to_shortest` values rather than inventing measurements

#### Scenario: Return an empty observation when no bars are detected
- **WHEN** the selected image is readable but contains no detectable bar geometry
- **THEN** the tool succeeds with status `no_evidence`, empty `series` and `bars`, null `plot_area_px` and `baseline`, and an explanatory warning

#### Scenario: Report unsupported chart geometry
- **WHEN** the sensor identifies perspective, three-dimensional, or otherwise unsupported bar geometry
- **THEN** Figura returns status `unsupported` with an explanatory warning and does not claim calibrated values

### Requirement: Keep bar measurements as candidate evidence
Bar measurements SHALL remain observations for the Agent to interpret. Figura SHALL NOT convert pixel lengths into semantic chart values without axis calibration, SHALL NOT automatically repeat measurement or block later Agent actions because of a warning, and SHALL NOT expose image overlays, local paths, or raw image bytes in the measurement result. A readable image with uncertain or unsupported geometry SHALL remain a successful observation; source authorization or image-read failures SHALL use the bounded tool error contract.

#### Scenario: Do not infer chart-unit values without calibration
- **WHEN** a bar baseline and geometry are detected but no numeric axis calibration is available
- **THEN** the result contains pixel lengths and relative ratios only, with no chart-unit value

#### Scenario: Leave evidence selection to the Agent
- **WHEN** a measurement result contains warnings or partial evidence
- **THEN** Figura returns the observation without scheduling a repeat measurement or imposing an assembly gate

#### Scenario: Keep image payloads outside measurement results
- **WHEN** the measurement tool returns a result
- **THEN** the durable JSON result contains measurement data only and no image bytes, overlay, or local filesystem path
