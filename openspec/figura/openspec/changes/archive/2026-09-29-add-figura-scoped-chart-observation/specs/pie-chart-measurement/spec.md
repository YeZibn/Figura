## Purpose

Provides source-bound geometric observations for supported two-dimensional circular pie charts, allowing the Agent to use sector ratios while preserving uncertainty and unsupported-chart boundaries.

## ADDED Requirements

### Requirement: Measure pie sectors from an authorized Attachment or Panel
Figura SHALL register a `measure_pie` tool accepting exactly `source_kind` (`attachment` or `panel`), an opaque `source_id`, and optional `observation_scope`; it SHALL reject additional arguments. Figura SHALL resolve only an Attachment or Panel present in the target Run's `RunExecutionState` inventory and verify ownership through the corresponding source service before reading image bytes. The tool SHALL NOT require a preceding `load_image` call and SHALL NOT accept a filesystem path, URL, or image bytes from the model. For a readable selected source, the result SHALL contain `source_kind`, `source_id`, `image_size` (`width`, `height`), `coordinate_system` (`attachment_px` or `panel_px`), `status` (`measured`, `partial`, `no_evidence`, or `unsupported`), `plot_region`, `sectors`, `confidence`, and `warnings`. A non-null `plot_region` SHALL contain `center_px` and `radius_px`; it SHALL be null when no plot region can be established. Each sector SHALL contain an integer result-local `id`, `start_angle_deg`, `sweep_angle_deg`, nullable `ratio`, nullable `color` as `#RRGGBB`, nullable `label_text` (at most 128 characters), nullable `label_confidence`, and bounded `confidence`. Sectors SHALL be ordered clockwise from the smallest `start_angle_deg`. Angles SHALL use degrees with zero at the image's 12-o'clock direction and increase clockwise; `start_angle_deg` SHALL be in `[0, 360)` and `sweep_angle_deg` in `(0, 360]`. A non-null `ratio` SHALL equal `sweep_angle_deg / 360`, be in `[0, 1]`, and SHALL be emitted only when total angular coverage is at least `0.80` and the sector's mean radial boundary support is at least `0.56`; otherwise it SHALL be null. Status SHALL be `measured` only when every detected sector has a ratio, total observed sector sweep differs from `360` degrees by no more than `12` degrees, and the sum of non-null ratios differs from `1.0` by no more than `0.035`. It SHALL be `partial` when sectors are detected but any ratio or total-coverage condition is not met, `no_evidence` when no pie sectors are detected, and `unsupported` when detected geometry is outside the supported chart scope. `confidence` SHALL contain bounded `overall`, `geometry`, `segmentation`, and `association` values in `[0, 1]`. Pixel geometry SHALL use the selected source's coordinate system. `warnings` SHALL describe ambiguity, incomplete evidence, or unsupported geometry. Source authorization or image-read failures SHALL use the bounded tool error contract.

#### Scenario: Return sectors and ratios for a supported pie chart
- **WHEN** the selected source contains a supported circular pie chart with complete sector-boundary evidence
- **THEN** Figura returns its source-pixel plot region, ordered sector angles, supported ratios, confidence, and warnings

#### Scenario: Preserve sector geometry when ratios are uncertain
- **WHEN** sectors are detected but complete circular coverage or sector-boundary evidence is insufficient
- **THEN** Figura returns available sector angles with null ratios, sets status to `partial`, and explains the uncertainty in `warnings`

#### Scenario: Return no evidence when no pie sectors are detected
- **WHEN** the selected source is readable but contains no supported pie geometry
- **THEN** the tool succeeds with status `no_evidence`, null `plot_region`, empty `sectors`, and an explanatory warning

#### Scenario: Report unsupported pie geometry
- **WHEN** the selected chart is perspective-distorted, three-dimensional, exploded, elliptical, donut-shaped, or otherwise unsupported
- **THEN** Figura returns status `unsupported` with an explanatory warning and does not claim sector ratios

#### Scenario: Reject an unavailable or cross-Session source
- **WHEN** the model supplies an unknown, unreferenced, or cross-Session Attachment or Panel ID
- **THEN** Figura returns a bounded structured tool failure and reads no image bytes

### Requirement: Keep pie measurements as candidate evidence
Pie measurements SHALL remain observations for the Agent to interpret. Figura SHALL derive a sector ratio only from angular coverage of the observed full pie and SHALL NOT infer source data values from labels, colors, or OCR. It SHALL NOT automatically repeat measurement or block later Agent actions because of a warning. The durable JSON result SHALL NOT contain overlays, image bytes, or local paths.

#### Scenario: Do not infer source values from sector appearance
- **WHEN** a pie sector has a visible label or color but its angular share is uncertain
- **THEN** Figura leaves `ratio` null and does not convert the label or color into a numeric source value

#### Scenario: Leave evidence selection to the Agent
- **WHEN** a pie result contains warnings or partial evidence
- **THEN** Figura returns the observation without scheduling a repeat measurement or imposing an assembly gate

#### Scenario: Keep image payloads outside pie results
- **WHEN** the pie measurement tool returns a result
- **THEN** the durable JSON result contains measurement data only and no image bytes, overlay, or local filesystem path

### Requirement: Apply a validated observation scope to pie measurement
`measure_pie` SHALL accept an optional `observation_scope` object with no fields other than optional `include` and `exclude` arrays of polygons. Each supplied array SHALL contain 1 through 4 polygons; each polygon SHALL contain 3 through 32 points; each point SHALL be an integer `[x, y]` pair with both coordinates in the inclusive range `0..1000`, normalized to the selected source's width and height. When `include` is absent, the full source is included; when present, the included area is the union of its polygons. The union of `exclude` polygons SHALL be removed from the included area, and exclusions SHALL take precedence over inclusions. A supplied scope SHALL contain at least one `include` or `exclude` array. Figura SHALL apply the resulting effective area to pie geometry detection, OCR, and label association while preserving source-pixel coordinates. An omitted `observation_scope` SHALL mean the complete source. A scope that produces no observable source pixels SHALL return a bounded structured tool failure. Invalid scope input SHALL return a bounded structured tool failure and SHALL NOT fall back to unscoped measurement.

#### Scenario: Restrict pie observation to included polygons
- **WHEN** the model supplies one or more valid `include` polygons
- **THEN** pie geometry detection, OCR, and label association use only evidence from their union

#### Scenario: Exclude irrelevant regions from pie observation
- **WHEN** a valid scope contains both included and excluded polygons
- **THEN** the excluded union is removed from the included area before measurement and takes precedence where polygons overlap

#### Scenario: Use the complete source when scope is omitted
- **WHEN** the model omits `observation_scope`
- **THEN** Figura analyzes the complete selected source

#### Scenario: Reject invalid scope without widening observation
- **WHEN** a scope has too many polygons, an invalid point count, out-of-range coordinates, non-integer coordinates, or no polygon
- **THEN** Figura returns a bounded structured tool failure and does not measure the full source as a fallback

#### Scenario: Reject an empty effective scope
- **WHEN** valid include and exclude polygons leave no observable source pixels
- **THEN** Figura returns a bounded structured tool failure without measuring the source
