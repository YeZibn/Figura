# chart-layout-context Specification

## Purpose

为图表观测提供一份可复用、可验证的布局上下文，使模型负责识别图表区域语义，确定性传感器负责在受约束的源图像坐标中完成测量。

## Requirements

### Requirement: Model-guided layout context is explicit

在图表观测需要布局理解时，系统 SHALL 生成一个与源附件绑定的布局上下文。上下文 SHALL 包含源图像尺寸、图表方向、主绘图区、X/Y 轴区域、刻度标签区域、图例区域和数据标注区域；区域坐标 SHALL 使用相对于源图像的归一化坐标，并保留每个区域的置信度和证据状态。

#### Scenario: Layout context covers a rotated-label line chart

- **WHEN** Agent 处理包含标题、图例、旋转日期刻度、双序列折线和数据标签的图表
- **THEN** 布局上下文识别主绘图区与标题、图例、刻度和数据标注区域的边界
- **AND** 旋转的日期标签被归入 X 轴刻度区域，而不是被当作斜坐标轴
- **AND** 上下文保留源图像尺寸和归一化区域坐标

#### Scenario: Layout context supports chart-specific coordinate models

- **WHEN** Agent 处理柱状图、折线图、散点图或饼图
- **THEN** 上下文标识适用的笛卡尔或极坐标布局类型及其方向提示
- **AND** 图表传感器可以消费同一布局上下文而不依赖其他图表传感器的私有逻辑
- **AND** 饼图的中心/半径区域与笛卡尔图表的轴区域保持可区分

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

布局上下文 SHALL 区分用于限定局部分析范围的 panel scope、用于坐标和几何测量的主绘图区，以及用于读取标题、图例、刻度和数据标签的标注区域。panel scope MAY be a coarse rectangular region produced by dashboard decomposition; it SHALL NOT be treated as a calibrated measurement frame unless independent validation accepts it. 传感器 SHALL 能够在 panel scope 内独立确定绘图区，并在不污染主绘图区的前提下访问相关标注区域；严格绘图区裁剪不得导致绘图区外的有效数据标签被静默丢弃。

#### Scenario: Data labels outside the plot remain available

- **WHEN** 折线或柱状图的数据标签部分位于主绘图区边界之外
- **THEN** 传感器仍可通过标注区域获取这些标签
- **AND** 标签不会被误当作坐标轴或颜色轨迹

#### Scenario: Legend and axis labels remain semantic metadata

- **WHEN** 图例或旋转坐标轴标签位于颜色轨迹附近
- **THEN** 布局上下文为它们提供独立区域或角色
- **AND** 图表传感器可以使用其文本进行系列/轴关联，而不把文本像素纳入 mark 几何

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
