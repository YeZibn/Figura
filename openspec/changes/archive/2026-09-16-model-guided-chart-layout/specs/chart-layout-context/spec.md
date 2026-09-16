## Purpose

为图表观测提供一份可复用、可验证的布局上下文，使模型负责识别图表区域语义，确定性传感器负责在受约束的源图像坐标中完成测量。

## ADDED Requirements

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

布局上下文 SHALL 经过确定性的边界、区域关系、轴方向、颜色轨迹覆盖和置信度校验后，才能作为图表传感器的测量范围。模型提供的区域 SHALL 被视为提示而非真值；校验失败时系统 SHALL 返回部分上下文、降低置信度或拒绝该提示，并保留可检查的源图像证据。

#### Scenario: A valid layout hint constrains observation

- **WHEN** 模型给出位于源图像范围内且与坐标轴、颜色轨迹一致的主绘图区
- **THEN** 系统接受该区域并将其提供给适用的图表观测工具
- **AND** 工具不把区域外的标题、图例或旋转标签当作图表几何

#### Scenario: An implausible layout hint is not trusted

- **WHEN** 模型给出的区域越界、轴关系不一致、与颜色轨迹冲突或置信度低于阈值
- **THEN** 系统不将该提示作为确定性坐标变换的真值
- **AND** 结果保留像素级部分证据并报告布局冲突或校验失败
- **AND** 系统不生成完整的语义数据集或虚构的坐标轴

### Requirement: Layout context separates frame and annotation regions

布局上下文 SHALL 区分用于坐标和几何测量的主绘图区与用于读取标题、图例、刻度和数据标签的标注区域。传感器 SHALL 能够在不污染主绘图区的前提下访问相关标注区域；严格绘图区裁剪不得导致绘图区外的有效数据标签被静默丢弃。

#### Scenario: Data labels outside the plot remain available

- **WHEN** 折线或柱状图的数据标签部分位于主绘图区边界之外
- **THEN** 传感器仍可通过标注区域获取这些标签
- **AND** 标签不会被误当作坐标轴或颜色轨迹

#### Scenario: Legend and axis labels remain semantic metadata

- **WHEN** 图例或旋转坐标轴标签位于颜色轨迹附近
- **THEN** 布局上下文为它们提供独立区域或角色
- **AND** 图表传感器可以使用其文本进行系列/轴关联，而不把文本像素纳入 mark 几何

