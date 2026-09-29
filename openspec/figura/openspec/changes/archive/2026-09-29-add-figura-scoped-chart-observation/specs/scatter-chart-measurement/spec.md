## MODIFIED Requirements

### Requirement: Measure scatter points from an authorized Attachment or Panel
Figura SHALL register a `measure_scatter` tool accepting exactly `source_kind` (`attachment` or `panel`), an opaque `source_id`, and optional `observation_scope`; it SHALL reject additional arguments. Figura SHALL resolve only an Attachment or Panel present in the target Run's `RunExecutionState` inventory and verify ownership through the corresponding source service before reading image bytes. The tool SHALL analyze the complete selected source when scope is omitted, SHALL NOT require a preceding `load_image` call, and SHALL NOT accept a filesystem path, URL, or image bytes from the model.

`observation_scope` SHALL be an object with no fields other than optional `include` and `exclude` arrays of polygons. Each supplied array SHALL contain 1 through 4 polygons; each polygon SHALL contain 3 through 32 points; each point SHALL be an integer `[x, y]` pair with both coordinates in the inclusive range `0..1000`, normalized to the selected source's width and height. When `include` is absent, the full source is included; when present, the included area is the union of its polygons. The union of `exclude` polygons SHALL be removed from the included area, and exclusions SHALL take precedence where polygons overlap. A supplied scope SHALL contain at least one `include` or `exclude` array. Figura SHALL apply the resulting effective area to point detection, OCR, and label/series association. All returned geometry SHALL remain in the selected source's pixel coordinate system; the observation scope SHALL NOT itself be treated as a calibrated plot area. A scope that produces no observable source pixels SHALL return a bounded structured tool failure. An invalid scope SHALL return a bounded structured tool failure and SHALL NOT fall back to unscoped measurement.

#### Scenario: Measure scatter points from an authorized source
- **WHEN** the model calls `measure_scatter` with an Attachment or Panel available in the target Run's Session-scoped inventory
- **THEN** Figura measures that image and returns point coordinates in the selected source's pixel system without exposing local paths or image bytes

#### Scenario: Reject an unavailable or cross-Session source
- **WHEN** the model supplies an unknown, unreferenced, or cross-Session source ID
- **THEN** Figura returns a bounded structured tool failure and reads no image bytes

#### Scenario: Restrict scatter observation to included polygons
- **WHEN** the model supplies one or more valid `include` polygons
- **THEN** Figura uses only source pixels inside their union for point detection, OCR, and label/series association, and returns geometry in source-pixel coordinates

#### Scenario: Exclude irrelevant regions from scatter observation
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
