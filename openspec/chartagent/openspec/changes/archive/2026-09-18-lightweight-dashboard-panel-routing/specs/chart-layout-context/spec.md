## MODIFIED Requirements

### Requirement: Layout context separates panel scope, measurement frame, and annotation regions

布局上下文 SHALL 区分用于限定局部分析范围的 panel scope、用于坐标和几何测量的主绘图区，以及用于读取标题、图例、刻度和数据标签的标注区域。panel scope MAY be a coarse rectangular region produced by dashboard decomposition; it SHALL NOT be treated as a calibrated measurement frame unless independent validation accepts it. 传感器 SHALL 能够在 panel scope 内独立确定绘图区，并在不污染主绘图区的前提下访问相关标注区域；严格绘图区裁剪不得导致绘图区外的有效数据标签被静默丢弃。

#### Scenario: A dashboard panel is scoped before its plot is known

- **WHEN** decomposition provides a valid panel scope but no inner plot frame
- **THEN** the layout context preserves the panel scope and marks the
  measurement frame as unresolved or partial
- **AND** the chart sensor can search within the panel scope without treating
  the whole card as calibrated geometry

#### Scenario: Data labels outside the plot remain available

- **WHEN** 折线或柱状图的数据标签部分位于主绘图区边界之外
- **THEN** 传感器仍可通过标注区域获取这些标签
- **AND** 标签不会被误当作坐标轴或颜色轨迹

#### Scenario: Legend and axis labels remain semantic metadata

- **WHEN** 图例或旋转坐标轴标签位于颜色轨迹附近
- **THEN** 布局上下文为它们提供独立区域或角色
- **AND** 图表传感器可以使用其文本进行系列/轴关联，而不把文本像素纳入 mark 几何

## ADDED Requirements

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
