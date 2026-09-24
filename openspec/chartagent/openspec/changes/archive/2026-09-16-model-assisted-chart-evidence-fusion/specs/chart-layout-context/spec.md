## MODIFIED Requirements

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
