## Purpose

为包含多个卡片、图表和文字区域的复杂图片提供一次调用即可消费的语义分区结果，使多模态模型可以先提出区域，再由 SAM 细化边界并生成带稳定名称的局部 crop，供后续图表传感器复用。

## ADDED Requirements

### Requirement: VLM-guided decomposition entry point

The system SHALL expose one model-facing `decompose_chart_image` observation
tool for complex chart images. For a multi-panel image, the tool SHALL accept a
bounded list of model-proposed semantic regions, where each proposal contains a
name, a normalized `[x, y, width, height]` bounding box, and optional role and
chart-type hints. The tool SHALL validate these proposals and SHALL NOT derive
panel topology from OCR or hidden text-clustering heuristics.

#### Scenario: The model proposes a dashboard layout

- **WHEN** the Agent invokes `decompose_chart_image` with an authorized image
  and valid semantic region proposals
- **THEN** the result contains one panel record for each accepted proposal or a
  bounded partial record for a proposal requiring fallback
- **AND** each record preserves the proposal name, role/type hints, and source
  coordinate evidence

#### Scenario: Proposals are absent or invalid

- **WHEN** the Agent invokes the tool without usable semantic region proposals
- **THEN** the result returns a bounded whole-image or advisory partial region
  with a warning
- **AND** the tool does not invent a multi-panel topology from OCR or renderer
  brightness patterns

### Requirement: Panel records preserve semantic identity and source geometry

Each returned panel SHALL have a stable identifier independent of its display
name, a human-readable name, a safe slug, source-image pixel coordinates, and
the original normalized proposal when available. A panel MAY include role and
chart-type hints, but those hints SHALL remain advisory and SHALL NOT be treated
as confirmed chart semantics or values.

#### Scenario: A panel is represented consistently

- **WHEN** a proposed region is represented in structured data, an overlay, and
  a crop handoff
- **THEN** all representations use the same stable panel identifier
- **AND** the source bbox and any polygon map to the original image coordinate
  system

#### Scenario: A VLM name is duplicated or unsafe

- **WHEN** multiple proposals have the same name or a name contains unsafe
  filename characters
- **THEN** the system preserves the display name as bounded metadata
- **AND** it assigns unique stable IDs and sanitized slugs for resource naming
  without using the name as an authorization identifier

### Requirement: SAM refines proposed regions

The system SHALL use an available SAM-family backend to refine each valid
semantic proposal with bounded box/point prompts. A successful result SHALL
expose a mask-derived polygon or bbox, segmentation provenance, and bounded
confidence. SAM SHALL refine the proposed boundary but SHALL NOT rename the
region or override its role or chart-type hint.

#### Scenario: SAM accepts a semantic proposal

- **WHEN** SAM returns a non-empty, in-bounds, coherent mask compatible with a
  proposed panel
- **THEN** the panel records the SAM-derived boundary and provenance
- **AND** the panel remains associated with the VLM-provided identity and name

#### Scenario: SAM is unavailable or produces an invalid mask

- **WHEN** the SAM runtime is unavailable, times out, or returns an empty,
  invalid, or materially conflicting mask
- **THEN** the system preserves the validated VLM bbox as a partial panel
- **AND** it reports a warning, reduced confidence, and the fallback source

### Requirement: Named crops are persisted as reusable visual resources

For every accepted or partial panel with a valid crop frame, the system SHALL
generate a bounded rectangular crop and persist it through the managed visual
observation/resource boundary. The crop SHALL retain its source origin,
dimensions, panel identifier, display name, and opaque resource reference. The
semantic proposal bbox, with bounded padding, SHALL remain the crop frame;
SAM's tight mask SHALL be retained as boundary evidence and SHALL NOT
automatically remove edge titles, axes, legends, or annotations from the crop.

#### Scenario: A panel crop is available for downstream analysis

- **WHEN** a panel has an accepted or partial valid region and crop persistence
  succeeds
- **THEN** the result exposes a stable crop reference and a safe descriptive
  crop name
- **AND** a later chart sensor can request or consume that crop without using a
  local filesystem path

#### Scenario: One crop cannot be persisted

- **WHEN** a crop is too large, undecodable, or exceeds the run resource budget
- **THEN** the panel geometry and provenance remain available
- **AND** the result reports a bounded persistence warning without discarding
  other valid panels or crops

### Requirement: Panel handoff scopes later chart analysis

The decomposition result SHALL expose enough panel context for a later bar,
line, pie, or scatter observation to analyze the named crop locally while
retaining the source-image origin for coordinate mapping and conflict reporting.
The decomposition tool SHALL NOT itself fabricate chart values, calibrated axes,
complete series data, or a valid ChartSpec.

#### Scenario: A chart sensor consumes a panel crop

- **WHEN** a panel has a valid crop reference and an advisory chart-type hint
- **THEN** the Agent can route the crop and its source transform to the
  corresponding specialized sensor
- **AND** the sensor's measurements remain attributable to the panel and source
  image

#### Scenario: A panel is only partially segmented

- **WHEN** a panel is returned with `partial` status or unresolved boundary
  warnings
- **THEN** downstream analysis receives the uncertainty and source evidence
- **AND** the system does not present the panel as a fully verified chart

### Requirement: OCR is not a decomposition dependency

The `decompose_chart_image` operation SHALL NOT run global OCR, local OCR
retry, OCR-to-panel association, or OCR keyword classification. The result
SHALL NOT require `ocr`, `text_ids`, or `unassigned_text_ids` fields in order
to produce usable panel records. The standalone text extraction capability MAY
be called later when small printed text or numeric labels require targeted
evidence.

#### Scenario: Decomposition runs without OCR

- **WHEN** the Agent decomposes a multi-panel image with valid VLM region
  proposals
- **THEN** panel segmentation and crop generation complete without invoking
  OCR
- **AND** the result remains usable for local chart analysis

#### Scenario: Targeted text evidence is needed later

- **WHEN** a later chart-analysis step cannot reliably read a small label or
  value from a panel crop
- **THEN** the Agent may invoke the independent text extraction capability
- **AND** that follow-up does not change the panel topology or crop identity

### Requirement: Decomposition exposes bounded visual evidence and uncertainty

The tool SHALL return structured panel records plus bounded visual evidence
showing panel IDs, names, accepted or partial boundaries, crop status, and
material warnings. It SHALL preserve valid structured data when an overlay or
one crop artifact is unavailable.

#### Scenario: The model inspects the decomposition result

- **WHEN** the tool returns valid panel and crop evidence
- **THEN** the next multimodal model turn can inspect an overlay or crop
  previews using the same panel identifiers as the structured result
- **AND** the evidence preserves source-image dimensions and coordinate mapping

#### Scenario: Visual evidence is incomplete

- **WHEN** an overlay or one visual resource cannot be generated
- **THEN** the result reports the bounded visual-artifact warning
- **AND** other accepted panel records and crop references remain available
