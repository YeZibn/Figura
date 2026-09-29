# scatter-chart-measurement Specification

## Purpose

Provides source-bound point geometry and cautiously calibrated coordinates for supported two-dimensional scatter charts, preserving series identity and visible uncertainty for Agent interpretation.

## Requirements

### Requirement: Measure scatter points from an authorized Attachment or Panel
Figura SHALL register a `measure_scatter` tool accepting exactly `source_kind` (`attachment` or `panel`) and an opaque `source_id`. Figura SHALL resolve only an Attachment or Panel present in the target Run's `RunExecutionState` inventory and verify ownership through the corresponding source service before reading image bytes. The tool SHALL analyze the selected source, SHALL NOT require a preceding `load_image` call, and SHALL NOT accept a filesystem path, URL, or image bytes from the model.

#### Scenario: Measure scatter points from an authorized source
- **WHEN** the model calls `measure_scatter` with an Attachment or Panel available in the target Run's Session-scoped inventory
- **THEN** Figura measures that image and returns point coordinates in the selected source's pixel system without exposing local paths or image bytes

#### Scenario: Reject an unavailable or cross-Session source
- **WHEN** the model supplies an unknown, unreferenced, or cross-Session source ID
- **THEN** Figura returns a bounded structured tool failure and reads no image bytes

### Requirement: Return scatter geometry and calibrated coordinates
For a readable selected source, `measure_scatter` SHALL return a bounded JSON object with the common measurement fields `source_kind`, `source_id`, `image_size`, `coordinate_system`, `status`, `plot_area_px`, `axes`, `series`, `confidence`, and `warnings`. Axis and tick observations SHALL use the same field contract as `bar-chart-measurement`. Each series SHALL contain `id`, `color`, nullable `label`, nullable `label_confidence`, and `points`. Each point SHALL contain `id`, `position_px`, nullable `x_value`, nullable `y_value`, nullable `x_tick_id`, nullable `y_tick_id`, nullable `radius_px`, bounded `confidence`, and `flags`. A numeric coordinate SHALL be non-null only when its corresponding axis is calibrated. `flags` SHALL identify visible uncertainty such as `merged`, `occluded`, `dense`, or `overlap`; Figura SHALL NOT claim an exact count of hidden or inseparable points. The top-level confidence SHALL contain bounded `overall`, `geometry`, `calibration`, and `association` values. Warnings SHALL describe uncertainty, incomplete evidence, or unsupported geometry.

#### Scenario: Return calibrated scatter coordinates
- **WHEN** a supported scatter chart has detectable points and both numeric axes pass linear calibration
- **THEN** the result returns each detected point's pixel position, calibrated x/y coordinates, series identity, and confidence

#### Scenario: Preserve points when one axis is uncalibrated
- **WHEN** points are detected but only one numeric axis passes calibration
- **THEN** Figura returns pixel positions, includes values only for the calibrated axis, sets other coordinate values to null, and reports `partial` with a warning

#### Scenario: Report dense or overlapping observations without inventing hidden points
- **WHEN** markers overlap, merge visually, or occur in a dense region
- **THEN** Figura marks affected observations with uncertainty flags, reports warnings, and does not invent an exact hidden-point count

#### Scenario: Report unsupported scatter geometry
- **WHEN** the selected chart uses strong perspective, 3D, nonlinear axes, or a broken axis
- **THEN** Figura returns `partial` or `unsupported`, preserves available pixel observations, and does not claim unsupported calibrated values

### Requirement: Keep scatter measurements as candidate evidence
Scatter measurements SHALL remain observations for the Agent to interpret. OCR labels, point detections, and overlap flags SHALL be treated as fallible evidence, and Figura SHALL NOT automatically repeat measurement or block later Agent actions because of a warning. The durable JSON result SHALL NOT contain overlays, image bytes, or local paths.

#### Scenario: Leave series and evidence selection to the Agent
- **WHEN** a result contains multiple series, ambiguous point associations, or warnings
- **THEN** Figura returns the supported observations and leaves their interpretation and selection to the Agent

#### Scenario: Do not emit uncalibrated numeric coordinates
- **WHEN** a detected point lies on an uncalibrated numeric axis
- **THEN** the corresponding chart-unit coordinate is null while the pixel position remains available
