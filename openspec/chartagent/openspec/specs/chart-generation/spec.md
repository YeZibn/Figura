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

### Requirement: Line charts render categorical x-axis labels

当有效的折线 ChartSpec 提供 `axes.x.categories` 时，生成结果 SHALL 在横轴上显示与
ChartSpec 完全一致的类别文本和顺序，并使每个系列在相同类别位置对齐。类别标签的
可读性布局（包括必要的间距或旋转）不得改变类别顺序、丢失标签，或把类别轴降级为
未解释的数字刻度。没有类别域的折线图 SHALL 继续使用数值横轴。

#### Scenario: Monthly categories are visible in the rendered line chart

- **WHEN** 渲染包含 `Jan` 至 `Jul` 类别的单系列或多系列折线 ChartSpec
- **THEN** 生成图片的横轴显示 `Jan`、`Feb`、`Mar`、`Apr`、`May`、`Jun`、`Jul`
- **AND** 标签顺序与 ChartSpec 一致，折线点按对应类别位置绘制
- **AND** 图片不得仅显示 `0`–`6`、`1`–`7` 等未解释的数字刻度

#### Scenario: Multiple series share the same category positions

- **WHEN** 多个折线系列使用同一组类别域
- **THEN** 每个系列在每个类别位置使用同一横坐标
- **AND** 系列身份、点数和 y 值保持不变

#### Scenario: Numeric x-axis remains numeric

- **WHEN** 折线 ChartSpec 未声明类别域并使用数值 `x`
- **THEN** 生成结果继续按数值横轴绘制和显示
- **AND** 系统不得将数值刻度误替换为不存在的类别文本

### Requirement: Category fidelity is part of deterministic render auditing

对于声明了类别横轴的折线图，生成前后的确定性检查 SHALL 验证类别刻度的数量、文本、
顺序以及数据点到类别位置的映射。任何缺失、错序、错文本或映射不一致 SHALL 产生
可定位的语义/保真问题，并阻止该候选以通过状态发布。

#### Scenario: Missing line tick labels fail the audit

- **WHEN** 渲染器生成了折线，但最终图的横轴类别标签缺失、被数字刻度替代或顺序不同
- **THEN** 审计返回定位到横轴类别或数据映射的结构化失败
- **AND** 候选图不会以 verified 或 published 状态返回

#### Scenario: Correct line category labels pass the audit

- **WHEN** 最终图的类别标签、顺序、数量和所有系列的横坐标映射均与 ChartSpec 一致
- **THEN** 类别保真检查通过
- **AND** 该检查结果与其他语义、布局和 artifact 检查一起参与发布门禁
### Requirement: Source-linked generation propagates task context

对于声明来自附件或 panel 的生成请求，生成工具 SHALL 接收并返回与 ChartSpec 绑定的
`generation_context`，并 SHALL 将 `mode`、`source_scope`、`coverage` 和
`selection_basis` 保留在不可变 chart manifest 中。渲染结果不得只依赖自由文本 source
标签来推断来源范围；验证结果和正式 artifact SHALL 引用相同的 staged chart 身份。

#### Scenario: Transform output keeps its source panel

- **WHEN** Agent 将一个 panel 的一个系列转换成另一种图表类型并请求渲染
- **THEN** 暂存 manifest 仍包含该 panel 的 source scope 和 transform mode
- **AND** 验证及发布路径读取相同的上下文与生成尝试

### Requirement: Render tools return attributable staged output

合法 ChartSpec 渲染 SHALL 产生有界暂存图像和不透明引用，绑定准确 Spec、生成上下文、来源 attachment/panel 与 figure/collection 关系。返回给 Agent 的生成结果 SHALL 明确区分暂存预览与正式 artifact，不得在 JSON 中嵌入图像字节、凭证、原始 provider 内容或本地路径。自动验证及发布遵循 generated-chart-verification 契约。

#### Scenario: Rendered chart awaits verification
- **WHEN** render 产出需要源图语义比较的图像
- **THEN** 工具结果提供暂存引用和有界元数据
- **AND** 不提供正式 artifact 下载身份，系统自动启动适用验证

#### Scenario: Composite figure keeps child attribution
- **WHEN** 一个 figure 渲染多个子图
- **THEN** 暂存记录保留子图语义和来源覆盖
- **AND** 正式产物只在该图像通过所需验证后产生

### Requirement: Generation failure never becomes published output

渲染、暂存、来源绑定、验证或发布任一必需环节失败 SHALL 保持正式 artifact 不可用，并把结构化诊断交给 Agent。修正产生新尝试；原失败图仍可在授权范围内预览但不能被最终成功声明引用。

#### Scenario: Corrected spec creates a new attempt
- **WHEN** Agent 根据失败诊断提交修正后的 ChartSpec
- **THEN** 新渲染拥有新的尝试身份并重新验证
- **AND** 旧失败图保持未发布
