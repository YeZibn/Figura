## MODIFIED Requirements

### Requirement: Model-guided layout context is explicit

在图表观测需要布局理解时，系统 SHALL 生成或接收一个与源附件和 panel 绑定的布局上下文。上下文 SHALL 区分源图尺寸、panel scope、主绘图区、X/Y 轴区域、刻度标签区域、图例区域和数据标注区域；区域坐标 SHALL 使用明确的源图或 panel 归一化坐标，并保留置信度和证据状态。模型可以在第一次工具调用前提供粗粒度 scope，工具不得把它误称为已校准的测量 frame。

#### Scenario: Initial scope covers a multi-panel chart

- **WHEN** Agent 处理包含多个图表面板、标题、图例和坐标轴的 dashboard
- **THEN** 上下文能够绑定选定 panel，并允许模型为 plot、legend 或 axes 提供局部 scope
- **AND** scope 继承源 attachment 的尺寸和坐标映射

#### Scenario: Layout context supports chart-specific coordinate models

- **WHEN** Agent 处理柱状图、折线图、散点图或饼图
- **THEN** 上下文标识适用的笛卡尔或极坐标布局类型及方向提示
- **AND** 图表传感器可以消费同一上下文而不依赖其他图表传感器的私有逻辑

### Requirement: Layout context separates panel scope, measurement frame, and annotation regions

布局上下文 SHALL 区分用于限定局部分析范围的 panel scope、用于坐标和几何测量的主绘图区，以及用于读取标题、图例、刻度和数据标签的标注区域。panel scope MAY be a coarse rectangular or polygonal region supplied by dashboard decomposition or the model; it SHALL NOT be treated as a calibrated measurement frame unless独立几何证据确认。传感器 SHALL 能够在 panel scope 内独立确定绘图区，并在不污染主绘图区的前提下访问相关标注区域。

#### Scenario: Legend exclusion protects geometry

- **WHEN** 模型在柱状图 scope 中标记顶部 legend 为 exclude 区域
- **THEN** 柱体传感器可以使用 plot 区域测量几何，并保留 legend 区域供语义观察
- **AND** legend 色块不得因为位于 panel 内而自动成为数据柱

#### Scenario: Data labels outside the plot remain available

- **WHEN** 折线或柱状图的数据标签位于主绘图区边界之外
- **THEN** 传感器或 OCR 仍可通过 annotation region 获取这些标签
- **AND** 标签不会被误当作坐标轴或颜色轨迹
