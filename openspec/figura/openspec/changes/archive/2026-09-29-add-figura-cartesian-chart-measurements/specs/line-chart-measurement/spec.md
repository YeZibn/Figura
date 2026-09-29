## Purpose

Provides source-bound pixel traces and cautiously calibrated point observations for supported two-dimensional line charts, allowing the Agent to use visual measurements without treating uncertain pixels or OCR as exact chart data.

## ADDED Requirements

### Requirement: Measure lines from an authorized Attachment or Panel
Figura SHALL register a `measure_lines` tool accepting exactly `source_kind` (`attachment` or `panel`) and an opaque `source_id`. Figura SHALL resolve only an Attachment or Panel present in the target Run's `RunExecutionState` inventory and verify ownership through the corresponding source service before reading image bytes. The tool SHALL analyze the selected source, SHALL NOT require a preceding `load_image` call, and SHALL NOT accept a filesystem path, URL, or image bytes from the model.

#### Scenario: Measure lines from an authorized Attachment or Panel
- **WHEN** the model calls `measure_lines` with an Attachment or Panel available in the target Run's Session-scoped inventory
- **THEN** Figura measures that image and returns coordinates in the selected source's pixel system without exposing local paths or image bytes

#### Scenario: Reject an unavailable or cross-Session source
- **WHEN** the model supplies an unknown, unreferenced, or cross-Session source ID
- **THEN** Figura returns a bounded structured tool failure and reads no image bytes

### Requirement: Return line geometry and supported point observations
For a readable selected source, `measure_lines` SHALL return a bounded JSON object with the common measurement fields `source_kind`, `source_id`, `image_size`, `coordinate_system`, `status`, `plot_area_px`, `axes`, `series`, `confidence`, and `warnings`. Axis and tick observations SHALL use the same field contract as `bar-chart-measurement`. Each line series SHALL contain `id`, `color`, nullable `label`, nullable `label_confidence`, `trace`, and `points`. `trace` SHALL preserve one or more pixel polylines so gaps are not silently bridged. Each point SHALL contain `id`, `position_px`, nullable `x_value`, nullable `y_value`, nullable `x_tick_id`, nullable `x_category_label`, `source` (`marker` or `axis_tick_sample`), and bounded `confidence`. A numeric coordinate SHALL be non-null only when its corresponding axis is calibrated; a categorical x observation SHALL retain its category label and tick identity without inventing a numeric x value. The top-level confidence SHALL contain bounded `overall`, `geometry`, `calibration`, and `association` values. Warnings SHALL identify incomplete, ambiguous, fragmented, or unsupported evidence.

#### Scenario: Return a line trace with calibrated marker points
- **WHEN** a supported line chart has detectable traces, marker points, and calibrated numeric axes
- **THEN** the result returns source-pixel polylines and marker points with calibrated coordinates and their series identities

#### Scenario: Sample a line only at supported axis ticks
- **WHEN** a line has no explicit markers but the x-axis has identifiable tick positions
- **THEN** Figura may return sampled points at those tick positions and SHALL identify each point source as `axis_tick_sample`

#### Scenario: Preserve a trace when numeric calibration fails
- **WHEN** a line trace is detected but one or both numeric axes cannot be calibrated
- **THEN** Figura retains the trace and pixel point positions, sets unavailable coordinate values to null, and returns `partial` with an explanatory warning

#### Scenario: Preserve gaps and report unsupported line geometry
- **WHEN** a trace is fragmented or the selected chart uses strong perspective, 3D, nonlinear axes, or a broken axis
- **THEN** Figura preserves separate observed trace fragments where available, does not bridge missing segments or claim unsupported calibrated values, and reports `partial` or `unsupported` with warnings

### Requirement: Keep line measurements as candidate evidence
Line measurements SHALL remain observations for the Agent to interpret. OCR labels and geometry SHALL be treated as fallible evidence, and Figura SHALL NOT automatically repeat a measurement, select a preferred series, or block later Agent actions because of a warning. The durable JSON result SHALL NOT contain overlays, image bytes, or local paths.

#### Scenario: Leave series and evidence selection to the Agent
- **WHEN** the result contains multiple series, uncertain labels, or warnings
- **THEN** Figura returns all supported observations and leaves their interpretation and selection to the Agent

#### Scenario: Do not emit uncalibrated numeric points
- **WHEN** a detected line point lies on an uncalibrated numeric axis
- **THEN** the corresponding chart-unit coordinate is null while the source-pixel position remains available
