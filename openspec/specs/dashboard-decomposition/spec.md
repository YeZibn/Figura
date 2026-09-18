# dashboard-decomposition Specification

## Purpose

为包含多个卡片、图表和文字区域的复杂图片提供一次调用即可消费的语义分区结果，使多模态模型可以先提出区域，再由 SAM 细化边界并生成带稳定名称的局部 crop，供后续图表传感器复用。

## Requirements

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
chart-type hints, but those hints SHALL remain advisory and SHALL NOT be
treated as confirmed chart semantics or values.

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

### Requirement: SAM refinement is optional and deterministic panel bounds are the default

The system SHALL validate each VLM-proposed semantic region and use its
validated rectangular bbox, with bounded padding, as the default panel and
analysis scope. A SAM-family backend MAY refine boundary evidence only when an
explicit segmentation mode requests it; SAM availability, checkpoints, or
mask quality MUST NOT be required for a usable decomposition result. Any
optional boundary refinement SHALL preserve the VLM-provided identity, role,
chart-type hint, and rectangular analysis scope unless a separate validated
scope decision is produced.

#### Scenario: Valid VLM proposal produces a panel without SAM

- **WHEN** the Agent provides a valid semantic region and the default
  segmentation mode is used
- **THEN** the tool returns an accepted panel using deterministic rectangular
  bounds and a bounded crop
- **AND** the result does not load or require a SAM checkpoint

#### Scenario: Explicit SAM refinement remains available

- **WHEN** an explicit segmentation mode requests SAM and the optional backend
  returns a valid compatible mask
- **THEN** the panel records the mask-derived boundary as auxiliary evidence
  while preserving the VLM identity and analysis scope

#### Scenario: Optional backend is unavailable

- **WHEN** SAM is not installed, not configured, times out, or returns an
  invalid mask
- **THEN** the tool keeps the validated VLM rectangular panel as a partial or
  accepted result with a bounded warning
- **AND** downstream analysis remains usable without SAM

### Requirement: Named crops and panel scopes are persisted as reusable visual resources

For every accepted or partial panel with a valid rectangular analysis scope,
the system SHALL generate a bounded crop from the validated VLM bbox and
padding, and SHALL retain its source origin, dimensions, panel identifier,
display name, and opaque resource reference when the managed visual boundary
persists it. Optional segmentation boundaries SHALL be retained as provenance
evidence and SHALL NOT silently replace the crop frame or remove edge titles,
axes, legends, or annotations.

#### Scenario: A panel crop and scope are available downstream

- **WHEN** a panel has a valid scope and crop generation succeeds
- **THEN** the result exposes a stable panel identifier, a source-coordinate
  scope, and a bounded crop reference or visual artifact
- **AND** a later chart sensor can resolve the panel identifier to the same
  local analysis scope without using a local filesystem path

#### Scenario: One crop cannot be persisted

- **WHEN** a crop is too large, undecodable, or exceeds the run resource budget
- **THEN** the panel scope and source provenance remain available
- **AND** the result reports a bounded persistence warning without discarding
  other valid panels or preventing source-ROI analysis

### Requirement: Panel handoff scopes later chart analysis

The decomposition result SHALL expose an executable panel handoff for later
bar, line, pie, or scatter observations. The handoff SHALL resolve a stable
panel identifier to a bounded local analysis scope and its source-image
transform. A downstream sensor SHALL be able to consume that scope while
retaining source-image coordinates for attribution and conflict reporting. The
decomposition tool SHALL NOT fabricate chart values, calibrated axes, complete
series data, or a valid ChartSpec.

#### Scenario: A chart sensor consumes a panel scope

- **WHEN** a panel has a valid scope and an advisory chart-type hint
- **THEN** the Agent routes the panel identifier to the corresponding
  specialized sensor
- **AND** the sensor analyzes the bounded local scope and reports the source
  origin and transform used for its measurements

#### Scenario: A sensor determines the inner measurement frame

- **WHEN** a panel scope contains a title, legend, annotations, and a chart
  plot
- **THEN** the sensor uses the panel scope as its search boundary and
  independently determines the chart-specific measurement frame
- **AND** the panel scope is not presented as proof that it is the calibrated
  plot frame

#### Scenario: Panel routing is unavailable

- **WHEN** a requested panel identifier is unknown, stale, or not associated
  with the source attachment
- **THEN** the sensor returns a bounded routing error or an explicitly warned
  source-image fallback according to its contract
- **AND** it does not silently analyze an unrelated panel

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

### Requirement: Decomposition is reuse-first and idempotent

当当前 session 的附件已有有效 PanelHandoff 时，dashboard 拆解入口 SHALL 优先返回已有面板目录，不得因为新 run 或模型历史不完整而重复拆解。只有不存在有效匹配、源图已变化、旧面板失效或用户明确要求重新拆解时，才允许生成新的分区结果。

#### Scenario: Follow-up request reuses existing panels

- **WHEN** 第一次 run 已为附件建立面板，后续 run 请求分析其中一个面板
- **THEN** 系统返回已有 panel ID 和范围
- **AND** 该 run 不重复调用完整 dashboard 拆解

#### Scenario: Explicit re-decomposition creates a revision

- **WHEN** 用户明确要求重新识别区域或现有面板已被标记 stale
- **THEN** 系统允许重新拆解
- **AND** 新结果与旧面板保留可追踪的 revision 或 supersedes 关系
