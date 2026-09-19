# chart-generation Specification

## Purpose

Provide a deterministic, validated reverse path that turns Figura's shared ChartSpec data into bounded chart artifacts that an Agent and a user can inspect and reuse.

## Requirements

### Requirement: Valid ChartSpec produces a bounded chart artifact

The system SHALL accept a semantically valid ChartSpec and produce a chart
artifact for bar, line, pie, and scatter chart types. The artifact SHALL
represent the supplied title, labels, series distinctions, and dataset without
inventing, silently dropping, or silently reclassifying semantic data. A
missing categorical value SHALL NOT be rendered as an actual zero. Declared
numeric axis ranges SHALL either be applied to the corresponding axis or be
rejected before rendering. User-visible text containing Chinese characters
SHALL be rendered with a compatible CJK font when one is available, and the
output SHALL use a supported image media type and remain within configured
size and dimension limits.

The generation-facing validation operation and rendering operation SHALL apply
the same structural and chart-type semantic rules. A successful rendering
result SHALL include bounded validation status for semantic, layout, and
artifact checks; a failed check that makes the chart unsafe or semantically
ambiguous SHALL prevent publication of the chart artifact.

#### Scenario: Cartesian ChartSpec is rendered with faithful data

- **WHEN** a valid bar, line, or scatter ChartSpec is submitted for rendering
- **THEN** the system produces an image artifact with the declared chart type,
  title and available axis labels
- **AND** the plotted values, point count, category order, and series
  distinctions correspond to the ChartSpec dataset
- **AND** any declared numeric axis ranges are reflected in the rendered axes
- **AND** Chinese titles, axis labels, tick labels, legends, and data labels
  remain visibly renderable when a compatible CJK font is available

#### Scenario: Missing grouped-bar data is not treated as zero

- **WHEN** a grouped bar ChartSpec declares a category set but a series has no
  value for one of those categories
- **THEN** the system returns a located semantic validation issue and produces
  no chart artifact unless the missing value is explicitly represented by a
  supported missing-data convention
- **AND** it does not publish a zero-height bar that implies an observed zero

#### Scenario: Pie ChartSpec is rendered without axes

- **WHEN** a valid pie ChartSpec contains non-negative categorical values and
  no axes
- **THEN** the system produces an image artifact whose sectors correspond to
  the categories and values
- **AND** the artifact exposes enough legend or label metadata to associate
  each sector with its category
- **AND** Chinese category labels and percentages remain visibly renderable
  when a compatible CJK font is available

#### Scenario: Multi-series data remains distinct

- **WHEN** a valid ChartSpec contains points assigned to multiple series
- **THEN** the generated chart preserves the series distinction in its visual
  encoding and bounded artifact metadata
- **AND** points are not merged solely because they share a category or axis

#### Scenario: Invalid ChartSpec is rejected before rendering

- **WHEN** a ChartSpec is missing required axes, contains invalid points,
  unsupported values, an invalid pie dataset, duplicate categorical points,
  or an invalid numeric axis range
- **THEN** the system returns a bounded structured validation error
- **AND** it produces no chart artifact

#### Scenario: Validation tools agree on generation eligibility

- **WHEN** the same ChartSpec is passed to the generation-facing validation
  operation and the rendering operation
- **THEN** both operations apply the same semantic eligibility rules
- **AND** a spec accepted for rendering is not rejected later for a rule that
  the standalone validation operation omitted

### Requirement: Chinese font availability is diagnosable

The rendering operation SHALL allow a caller to provide a font path override
and SHALL search supported system font families when no override is provided.
When no compatible CJK font can be resolved, the system SHALL still preserve
the existing bounded rendering behavior where possible, while returning an
explicit bounded warning or status that identifies the fallback condition.

#### Scenario: Configured font override is available

- **WHEN** a caller provides a readable supported font path
- **THEN** the renderer uses that font for all generated chart text
- **AND** the result metadata identifies the resolved font as configured

#### Scenario: System CJK font is resolved

- **WHEN** no font override is provided and a supported system CJK font exists
- **THEN** the renderer uses the discovered font for all generated chart text
- **AND** the result metadata identifies the resolved font as system-provided

#### Scenario: No CJK font is available

- **WHEN** neither the configured path nor supported system font families can
  provide a compatible CJK font
- **THEN** the renderer returns a bounded fallback warning or status
- **AND** it does not silently claim that Chinese text was rendered correctly

### Requirement: Agent can request chart generation through the tool boundary

The Agent SHALL be able to request rendering of a ChartSpec through a
registered tool. The tool SHALL return structured chart metadata together with
an attributed visual payload when rendering succeeds. A rendered candidate
whose policy requires semantic review SHALL be submitted automatically to the
internal tool-free VLM review path; the Agent SHALL not choose review tools or
submit a free-form review decision. When a generated chart requires review,
the Agent SHALL treat the rendered image as a preview and SHALL not publish it
or present it as an unqualified final result until the required review gate has
completed and the code-owned `publicationStatus` permits that claim.

#### Scenario: User asks to redraw data recovered from an attached chart

- **WHEN** a user asks the Agent to redraw data recovered from an attached
  chart
- **THEN** the Agent can reuse or assemble a ChartSpec, validate it, request a
  chart candidate, and inspect the candidate through the normal visual
  observation path
- **AND** the system automatically sends the source-linked candidate to the
  internal tool-free VLM reviewer
- **AND** the Agent must wait for the required review result before claiming
  that the generated chart is verified

#### Scenario: Review does not call auxiliary chart tools

- **WHEN** a generated chart candidate enters semantic review
- **THEN** the review path does not invoke OCR, chart sensors, layout inspection,
  geometry measurement, or `review_generated_chart`
- **AND** the VLM receives the source image when available, the candidate image,
  and the immutable ChartSpec as its review context

#### Scenario: Agent inspects generated visual evidence

- **WHEN** a chart-rendering tool returns a valid visual payload
- **THEN** the Agent can receive the generated chart as attributed visual
  evidence on a later model turn and may use the automatic review result to
  accept, retry, or explain the candidate
- **AND** the structured chart and review metadata remain available
  independently

#### Scenario: Rendering failure is recoverable

- **WHEN** rendering fails because the input is invalid or a configured output
  limit is exceeded
- **THEN** the tool returns a bounded structured error or warning
- **AND** the Agent run remains able to revise the request or provide a text
  answer without an uncaught renderer exception

#### Scenario: Review failure is recoverable

- **WHEN** the required review identifies a semantic or fidelity mismatch
- **THEN** the candidate is not published as a valid generated chart
- **AND** the Agent can revise the ChartSpec and request a bounded retry or
  provide a transparent failure explanation without an uncaught exception

#### Scenario: Final answer cannot bypass pending or failed review

- **WHEN** the Agent attempts to finish a run while a generated chart review is
  pending, failed, timed out, or retry-exhausted
- **THEN** the run remains bounded by the review gate or returns an explicit
  non-published result
- **AND** the generated chart is not marked as published

#### Scenario: Completed review is not itself a publication decision

- **WHEN** a review call reaches `reviewStatus=completed`
- **THEN** the Agent and Gateway use the normalized decision and
  `publicationStatus` to determine whether the candidate is publishable
- **AND** a completed review with `decision: fail` or a rejected publication
  status remains unpublished

### Requirement: Generated chart output is bounded and attributable

Every generated chart candidate and published generated chart SHALL expose
bounded metadata that distinguishes its lifecycle state. A candidate SHALL
have an opaque candidate reference, chart type, bounded title, media type,
byte count, dimensions, and the identity of the ChartSpec version it
represents. A published chart SHALL additionally expose its opaque artifact
reference, review status, and bounded review diagnostics. Artifact metadata
SHALL NOT contain local source paths, credentials, raw provider payloads, or
embedded image bytes. Generated output SHALL remain distinguishable from
temporary model-observation images.

#### Scenario: Candidate output is attributable but not final

- **WHEN** rendering produces a chart that passes the applicable deterministic
  renderer and artifact checks but still requires semantic review
- **THEN** the result identifies the output as a review-pending candidate
- **AND** it includes bounded references that associate the candidate with the
  current run and ChartSpec version
- **AND** it does not expose the candidate as a verified final artifact

#### Scenario: Generated output metadata is safe

- **WHEN** a candidate passes all required checks
- **THEN** the published result contains bounded metadata and an opaque
  artifact reference suitable for Gateway and desktop-client retrieval
- **AND** the JSON result contains no raw image bytes or local filesystem path
- **AND** the metadata identifies whether the result was verified cleanly or
  published with an explicit warning

#### Scenario: Pending or failed candidates are not published

- **WHEN** a candidate has pending, failed, expired, or timed-out review state
- **THEN** it cannot be retrieved through the final generated-chart artifact
  route
- **AND** its bounded failure state remains attributable to the run without
  exposing image bytes or local paths

#### Scenario: Output limits and artifact validity are enforced

- **WHEN** the rendered image exceeds the configured byte or dimension limit
  , cannot be fully decoded as the declared image type, or fails an artifact
  integrity check
- **THEN** the system rejects or bounds the output with an explicit reason
- **AND** it does not publish a partial, malformed, or unverified artifact

### Requirement: Rendered chart undergoes a deterministic quality audit

After a ChartSpec has been rendered and before the generated artifact is
returned, the system SHALL audit the in-memory chart and encoded image. The
audit SHALL check that the rendered artists cover the requested data and that
visible titles, labels, tick labels, annotations, legends, and chart content
fit within the fixed output canvas. Layout-only findings MAY be returned as
bounded warnings when the chart remains usable; semantic fidelity failures,
severe clipping, or unreadable output SHALL fail the generation.

#### Scenario: Rendered artists cover the ChartSpec

- **WHEN** a ChartSpec passes pre-render validation and the renderer creates a
  figure
- **THEN** the audit verifies chart-type-specific artist counts and values,
  including bars, line or scatter points, pie sectors, categories, and series
- **AND** a mismatch produces a located validation failure and no published
  chart artifact

#### Scenario: Visible content stays within the canvas

- **WHEN** the renderer has laid out a chart containing titles, axes, labels,
  annotations, or legends
- **THEN** the audit measures their final rendered bounds after a canvas draw
- **AND** content that is clipped or materially outside the fixed canvas
  produces a structured layout failure or warning according to configured
  severity

#### Scenario: Usable layout warning remains explicit

- **WHEN** a chart is renderable but has dense labels, a crowded legend, or
  another bounded readability concern that does not invalidate its data
- **THEN** the system returns the chart with validation status `warning`
- **AND** the result identifies the concern without claiming an unqualified
  validation pass

### Requirement: Generated chart review is a mandatory publication gate

After a generated chart is created, the system SHALL use a post-generation
transition to place the chart in `review_pending` before final publication.
The gate SHALL require the applicable deterministic structural and encoded
artifact safety checks for every generated chart and SHALL require an
automatic internal VLM semantic review when the chart is derived from an
attached source image or otherwise carries an explicit review requirement.
The review VLM SHALL receive the source image when available, the candidate
image, and the immutable ChartSpec without any review or evidence tools.
Neither the Agent nor a caller SHALL bypass a pending or failed gate.

#### Scenario: Post-generation hook enters automatic review state

- **WHEN** a rendering operation produces a generated chart candidate
- **THEN** the post-generation transition records `review_pending` before the
  candidate can become a final generated-chart artifact
- **AND** a semantic-review-required candidate automatically triggers one
  tool-free VLM review call
- **AND** the review state is bound to the run, candidate reference, and
  ChartSpec version

#### Scenario: Safety checks and semantic review are distinct

- **WHEN** any generated chart candidate is created
- **THEN** structural ChartSpec validation, render and layout safety checks, and
  encoded-artifact checks applicable to that candidate complete before
  publication
- **AND** a source-linked or explicitly review-required candidate also receives
  the automatic VLM semantic review
- **AND** neither a safety-check pass nor a VLM pass can be omitted from the
  applicable publication gate

#### Scenario: Source-linked generation requires VLM semantic comparison

- **WHEN** a candidate is generated from an attached source image or from data
  whose semantic provenance requires review
- **THEN** the system requires a VLM comparison of the source image, ChartSpec,
  and candidate image before publication
- **AND** the comparison covers chart type, orientation, categories, series
  identity, values, labels, baseline or geometry relationships, and material
  unresolved ambiguity
- **AND** the comparison path invokes no OCR, CV, geometry, layout, or review
  tool

#### Scenario: Direct data generation uses the applicable review scope

- **WHEN** a candidate is generated only from user-supplied structured data
  with no source-image fidelity claim
- **THEN** the candidate passes all applicable deterministic generation and
  artifact safety checks before publication
- **AND** the result does not claim source-image equivalence when no source
  image was supplied

#### Scenario: VLM review pass promotes the candidate

- **WHEN** all applicable safety checks complete and the internal VLM returns a
  valid non-blocking decision
- **THEN** the candidate transitions to a verified or warning publication state
  according to the decision and review policy
- **AND** only then can the Gateway expose it as a final generated-chart
  artifact

#### Scenario: Recoverable warning remains explicit

- **WHEN** VLM review completes with a bounded non-blocking readability or
  semantic uncertainty warning that policy permits publishing
- **THEN** the chart may be published with review status `warning`
- **AND** the warning is visible in structured metadata and the final run
  projection without being represented as an unqualified pass

#### Scenario: Blocking VLM review failure prevents publication

- **WHEN** VLM review finds missing data, wrong orientation, wrong category
  order, series misidentification, value mismatch, label misassociation,
  baseline misalignment, unreadable critical content, or another configured
  blocking issue
- **THEN** the candidate transitions to `review_failed` and no final artifact
  reference is issued
- **AND** the Agent may submit a corrected ChartSpec for a bounded new
  candidate

#### Scenario: Review state is idempotent and candidate-specific

- **WHEN** the same post-generation event is delivered more than once or an
  internal VLM result is retried
- **THEN** the system does not publish duplicate artifacts or apply a review
  result to a different candidate or ChartSpec version
- **AND** the final state remains attributable to the original run and review
  record

#### Scenario: Timeout and retry limits are bounded

- **WHEN** the internal VLM review call or candidate retry times out or fails
  repeatedly
- **THEN** the system records a bounded review timeout or retry-exhausted state
- **AND** it does not leave an indefinitely pending candidate or publish it as
  verified

### Requirement: Generated candidates retain source and panel attribution

由源图面板生成的 ChartSpec、候选图和发布 artifact SHALL 保留经过校验的 attachment ID、panel ID、PanelHandoff revision 和候选 lineage。自由文本 source 描述不得单独充当源附件证据。

#### Scenario: Candidate is linked to a panel source

- **WHEN** ChartSpec 来自某个 dashboard panel
- **THEN** 候选记录包含该 panel 的结构化归因
- **AND** 审核可以使用同一个已校验的源附件

### Requirement: Failed candidates cannot bypass the review gate

审核未通过的候选 SHALL 保持未发布。修正必须生成新的候选记录；只有通过审核的候选才能进入 published 状态。

#### Scenario: Corrected candidate supersedes a rejected candidate

- **WHEN** 主 Agent 根据审核诊断生成新的 ChartSpec
- **THEN** 新候选关联旧候选并重新经过审核
- **AND** 旧候选仍保持 rejected/unpublished

### Requirement: Same-source child specs render as one composite artifact

生成流程 SHALL 接受一个包含多个独立 ChartSpec 的 figure，并将同一 figure 的子图渲染到一张有界的 composite 图片中。生成结果 SHALL 是一个可归属到该来源键的 artifact，而不是将同源子图默认为互相无关的多张最终图片。

#### Scenario: Q1 and Q2 are visible in one output image

- **WHEN** 一个来源面板包含 Q1 2024 和 Q2 2024 两个饼图子图，且集合覆盖状态为 `complete`
- **THEN** 生成流程输出一张 composite 图片
- **AND** 图片中可分别识别两个子图及其标题、类别和值
- **AND** artifact 元数据包含 figure ID、来源键和子图 ID 列表

#### Scenario: Single ChartSpec still renders as one artifact

- **WHEN** 生成流程收到单个 ChartSpec 而不是 figure 或集合
- **THEN** 系统继续输出原有单图 artifact
- **AND** 不额外创建只有一个子图的多余集合层，除非调用方明确请求集合模式

### Requirement: Composite rendering preserves child semantics

复合渲染 SHALL 分别应用每个子图的图表类型、数据集、类别顺序、系列身份、轴和文本语义。一个子图的缺失值、非法数据或图表类型不得被另一个子图的合法数据掩盖。

#### Scenario: Child chart types remain distinct

- **WHEN** figure 中包含一个 grouped bar ChartSpec 和一个 pie ChartSpec
- **THEN** composite 图片分别以柱状图和饼图表达两个子图
- **AND** 每个子图的数据点数量和类别顺序与其 ChartSpec 一致
- **AND** 不因为使用同一画布而把它们重分类为同一种图表

### Requirement: Figure-level safety and review gate

当 figure 来自源图像或声明需要审核时，生成流程 SHALL 在发布前同时验证 composite 图片、所有子图 ChartSpec、系列覆盖和 artifact 完整性，并 SHALL 以 figure 级上下文执行一次内部 VLM 审核。任一阻断性子图、覆盖、布局或审核问题存在时，系统 SHALL 不发布最终 artifact。

#### Scenario: Review sees the complete figure context

- **WHEN** 一个 source-linked figure 完成 composite 渲染
- **THEN** 审核上下文包含源图像、composite 图片、全部子图 ChartSpec、figure 来源键和覆盖信息
- **AND** 审核能够判断是否所有来源系列都已在最终图片中表示
- **AND** 审核路径不调用 OCR、测量、布局检查或其他图表工具

#### Scenario: One failed child blocks publication

- **WHEN** composite 中任一子图的数据或渲染审计失败，或 figure 覆盖状态不是 `complete`
- **THEN** figure 进入结构化失败或待修复状态
- **AND** 不发行最终 artifact reference
- **AND** 已成功渲染的其他子图不被单独宣称为该 figure 的完整结果

### Requirement: Composite artifact metadata is attributable

复合 artifact SHALL 暴露有界的 figure、来源、子图、布局、覆盖和审核元数据，并 SHALL 保持与现有单图 artifact 的生命周期、媒体类型、尺寸和隐私约束兼容。元数据不得包含本地路径、凭据、原始 provider payload 或图像字节。

#### Scenario: Client can identify child charts in a composite

- **WHEN** composite artifact 被返回给 Gateway 或前端
- **THEN** 客户端可以通过 figure ID、来源键和子图 ID 列表知道图片由哪些 ChartSpec 组成
- **AND** 图片仍按一个最终可展示 artifact 计数
- **AND** 返回内容不暴露本地文件路径或原始图像字节
