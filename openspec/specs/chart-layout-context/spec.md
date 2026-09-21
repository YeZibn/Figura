# chart-layout-context Specification

## Purpose

为图表观测提供一份可复用、可验证的布局上下文，使模型负责识别图表区域语义，确定性传感器负责在受约束的源图像坐标中完成测量。

## Requirements

### Requirement: Model-guided layout context is explicit

在图表观测需要布局理解时，系统 SHALL 生成或接收一个与源附件和 panel 绑定的布局上下文。上下文 SHALL 区分源图尺寸、panel scope、主绘图区、X/Y 轴区域、刻度标签区域、图例区域和数据标注区域；区域坐标 SHALL 使用明确的源图或 panel 归一化坐标，并保留置信度和证据状态。模型可以在第一次工具调用前提供粗粒度 scope，工具不得把它误称为已校准的测量 frame。

#### Scenario: Initial scope covers a multi-panel chart

- **WHEN** Agent 处理包含多个图表面板、标题、图例和坐标轴的 dashboard
- **THEN** 上下文能够绑定选定 panel，并允许模型为 plot、legend 或 axes 提供局部 scope
- **AND** scope 继承源 attachment 的尺寸和坐标映射

#### Scenario: Layout context supports chart-specific coordinate models

- **WHEN** Agent 处理柱状图、折线图、散点图或饼图
- **THEN** 上下文标识适用的笛卡尔或极坐标布局类型及方向提示
- **AND** 图表传感器可以消费同一布局上下文而不依赖其他图表传感器的私有逻辑

### Requirement: Layout hints are validated before measurement

布局上下文 SHALL 经过确定性的边界、区域关系、轴方向、颜色轨迹覆盖和置信度校验后，才能作为图表传感器的可选测量辅助范围。模型提供的区域 SHALL 被视为软布局先验而非真值；校验失败、证据不足或与独立像素检测冲突时，系统 SHALL 返回部分上下文、降低置信度或拒绝该提示，并保留独立源图像证据。布局上下文 SHALL NOT 阻止传感器在未采用该先验的情况下独立检测绘图区、坐标轴或基准线。

#### Scenario: Valid layout hint assists observation

- **WHEN** 模型给出位于源图像范围内且与坐标轴、颜色轨迹一致的主绘图区
- **THEN** 系统接受该区域作为适用传感器的辅助信息
- **AND** 工具不把区域外的标题、图例或旋转标签当作图表几何
- **AND** 工具仍可保留与该提示独立得到的像素几何结果

#### Scenario: An implausible layout hint is not trusted

- **WHEN** 模型给出的区域越界、轴关系不一致、与颜色轨迹冲突或置信度低于阈值
- **THEN** 系统不将该提示作为确定性坐标变换或唯一测量范围
- **AND** 结果保留像素级部分证据并报告布局冲突或校验失败
- **AND** 系统不生成完整的语义数据集或虚构的坐标轴

#### Scenario: Partial layout does not suppress independent detection

- **WHEN** 布局提示只有绘图区、只有一条轴，或其状态为 partial
- **THEN** 传感器可以使用其明确有效的辅助字段
- **AND** 传感器不得因为该提示缺失或部分有效而跳过独立的轴、标记或基准线检测
- **AND** 最终结果明确标出布局提示对测量的限制

#### Scenario: Layout inspection is demand-driven

- **WHEN** 模型能够从源图像可靠判断布局且当前任务不需要额外区域提示
- **THEN** Agent 可以不调用 `inspect_chart_layout`
- **AND** 图表恢复流程仍然有效

### Requirement: Layout context separates panel scope, measurement frame, and annotation regions

布局上下文 SHALL 区分用于限定局部分析范围的 panel scope、用于坐标和几何测量的主绘图区，以及用于读取标题、图例、刻度和数据标签的标注区域。panel scope MAY be a coarse rectangular or polygonal region supplied by dashboard decomposition or the model; it SHALL NOT be treated as a calibrated measurement frame unless独立几何证据确认。传感器 SHALL 能够在 panel scope 内独立确定绘图区，并在不污染主绘图区的前提下访问相关标注区域。

#### Scenario: Legend exclusion protects geometry

- **WHEN** 模型在柱状图 scope 中标记顶部 legend 为 exclude 区域
- **THEN** 柱体传感器可以使用 plot 区域测量几何，并保留 legend 区域供语义观察
- **AND** legend 色块不得因为位于 panel 内而自动成为数据柱

#### Scenario: Data labels outside the plot remain available

- **WHEN** 折线或柱状图的数据标签位于主绘图区边界之外
- **THEN** 传感器仍可通过标注区域获取这些标签
- **AND** 标签不会被误当作坐标轴或颜色轨迹

### Requirement: Panel analysis scope preserves source mapping

When a chart sensor receives a panel identifier from dashboard decomposition,
the system SHALL resolve it to a bounded source-image analysis scope and a
local-to-source coordinate transform. The scope SHALL be usable without a
derived filesystem path, and all emitted geometry SHALL remain attributable to
the original attachment and source coordinates.

#### Scenario: Panel scope is resolved for a sensor

- **WHEN** a valid panel identifier is supplied with its source attachment
- **THEN** the sensor receives the corresponding bounded scope and source
  origin
- **AND** the sensor does not scan unrelated dashboard panels by default

#### Scenario: Local geometry is mapped back to the source

- **WHEN** a sensor detects a mark, axis, or frame in the local panel scope
- **THEN** the serialized result preserves source-image coordinates using the
  declared transform
- **AND** overlays use the same source coordinate convention

#### Scenario: Scope resolution is invalid

- **WHEN** the panel identifier is missing, stale, or bound to another source
  attachment
- **THEN** the system reports a bounded routing or authorization warning
- **AND** it does not invent a transform or silently use an unrelated scope

### Requirement: Panel scope is resolved before chart measurement

系统 SHALL 提供统一的面板范围解析行为，将 panel ID 解析为包含必要标题、图例、坐标轴和数据标注的局部 PanelScope，并保留局部坐标到源图坐标的可逆映射。PanelScope SHALL 与内部的 MeasurementFrame 区分。

#### Scenario: A sensor receives a panel scope

- **WHEN** 图表传感器收到有效 panel ID
- **THEN** 它获得局部图像范围、源图尺寸和坐标变换
- **AND** 它可以在 PanelScope 内独立确定实际绘图区

### Requirement: Invalid panel references are rejected explicitly

当 panel ID 不属于当前 session、attachment 或 source context 时，系统 SHALL 返回结构化范围错误，不得退回整张 dashboard 作为隐式范围。

#### Scenario: Unknown panel does not fall back to full image

- **WHEN** 模型传入不存在或不属于当前附件的 panel ID
- **THEN** 工具调用失败并说明 panel scope 不可用
- **AND** 工具不得在整张源图上继续测量
