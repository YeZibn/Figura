## Purpose

Provides the Agent with bounded, source-bound text observations from an authorized Attachment or Panel, with an optional region scope for excluding unrelated image content.

## ADDED Requirements

### Requirement: Extract text from an authorized Attachment or Panel
Figura SHALL register an `extract_text` tool accepting exactly `source_kind` (`attachment` or `panel`), an opaque `source_id`, and optional `observation_scope`; it SHALL reject additional arguments. Figura SHALL resolve only an Attachment or Panel present in the target Run's `RunExecutionState` inventory and verify ownership through the corresponding source service before reading image bytes. The tool SHALL NOT require a preceding `load_image` call and SHALL NOT accept a filesystem path, URL, or image bytes from the model. For a readable source, it SHALL return `source_kind`, `source_id`, `image_size` (`width`, `height`), `coordinate_system` (`attachment_px` or `panel_px`), `available`, `truncated`, and `snippets`. Each snippet SHALL contain a stable result-local `snippet_id`, recognized `text`, source-pixel `bbox_px` as `[x, y, width, height]`, and bounded `confidence` in `[0, 1]`. The tool SHALL bound the result to at most 512 snippets and 128 characters per snippet text. `available` SHALL indicate whether OCR completed; a completed OCR pass with no recognized text SHALL return `available: true` and an empty `snippets` list. OCR unavailable or failed for a readable authorized source SHALL return `available: false` and no snippets. Source authorization or image-read failures SHALL use the bounded tool error contract.

#### Scenario: Extract text from an authorized Attachment
- **WHEN** the model calls `extract_text` with an Attachment in the target Run's available attachment inventory
- **THEN** Figura runs OCR on that source and returns source-pixel snippet boxes without exposing local paths or image bytes

#### Scenario: Extract text from an authorized Panel
- **WHEN** the model calls `extract_text` with a Panel in `RunExecutionState.panels`
- **THEN** Figura runs OCR on the independent Panel image and reports coordinates in the Panel pixel system

#### Scenario: Return an empty observation when no text is recognized
- **WHEN** OCR completes for a readable authorized source but recognizes no text
- **THEN** the tool succeeds with `available: true`, `truncated: false`, and an empty `snippets` list

#### Scenario: Report OCR unavailability without fabricating snippets
- **WHEN** OCR cannot complete for a readable authorized source
- **THEN** the tool succeeds with `available: false` and an empty `snippets` list

#### Scenario: Reject an unavailable or cross-Session source
- **WHEN** the model supplies an unknown, unreferenced, or cross-Session Attachment or Panel ID
- **THEN** Figura returns a bounded structured tool failure and reads no image bytes

### Requirement: Bound OCR output and preserve source coordinates
Figura SHALL assign snippet IDs that are unique within one result, retain recognized text only up to the declared per-snippet limit, and set `truncated` to true when OCR output is cut off by the snippet-count or text-length bound. Every returned bounding box SHALL use integer pixels relative to the complete selected source, regardless of whether an observation scope was applied. The tool result SHALL contain no image bytes, overlay, local filesystem path, or unbounded OCR payload.

#### Scenario: Truncate excessive OCR output
- **WHEN** OCR produces more than 512 snippets or a text snippet longer than 128 characters
- **THEN** Figura returns no more than 512 snippets, limits each text value to 128 characters, and sets `truncated: true`

#### Scenario: Keep OCR boxes in selected-source coordinates
- **WHEN** OCR runs on a Panel or on a scoped portion of an Attachment
- **THEN** every `bbox_px` remains relative to the complete selected Panel or Attachment image

#### Scenario: Keep image payloads outside the OCR result
- **WHEN** the OCR tool returns a result
- **THEN** the durable JSON result contains snippet observations only and no image bytes, overlay, or local filesystem path

### Requirement: Apply a validated observation scope to OCR
`extract_text` SHALL accept an optional `observation_scope` object with no fields other than optional `include` and `exclude` arrays of polygons. Each supplied array SHALL contain 1 through 4 polygons; each polygon SHALL contain 3 through 32 points; each point SHALL be an integer `[x, y]` pair with both coordinates in the inclusive range `0..1000`, normalized to the selected source's width and height. When `include` is absent, the full source is included; when present, the included area is the union of its polygons. The union of `exclude` polygons SHALL be removed from the included area, and exclusions SHALL take precedence over inclusions. A supplied scope SHALL contain at least one `include` or `exclude` array. Figura SHALL run OCR using only pixels in the resulting effective area and return boxes in the original source coordinate system. An omitted `observation_scope` SHALL mean the complete source. A scope that produces no observable source pixels SHALL return a bounded structured tool failure. Invalid scope input SHALL return a bounded structured tool failure and SHALL NOT fall back to unscoped OCR.

#### Scenario: Restrict OCR to included polygons
- **WHEN** the model supplies one or more valid `include` polygons
- **THEN** OCR uses only source pixels inside their union and returns only text observations supported by those pixels

#### Scenario: Exclude polygons from OCR
- **WHEN** a valid scope contains both included and excluded polygons
- **THEN** the excluded union is removed from the included area before OCR and takes precedence where polygons overlap

#### Scenario: Use the complete source when scope is omitted
- **WHEN** the model omits `observation_scope`
- **THEN** OCR analyzes the complete selected source

#### Scenario: Reject invalid scope without widening observation
- **WHEN** a scope has too many polygons, an invalid point count, out-of-range coordinates, non-integer coordinates, or no polygon
- **THEN** Figura returns a bounded structured tool failure and does not analyze the full source as a fallback

#### Scenario: Reject an empty effective scope
- **WHEN** valid include and exclude polygons leave no observable source pixels
- **THEN** Figura returns a bounded structured tool failure without running OCR
