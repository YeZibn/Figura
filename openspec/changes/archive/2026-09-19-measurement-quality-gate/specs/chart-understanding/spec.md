## ADDED Requirements

### Requirement: Chart measurements expose a shared quality contract

柱状图、折线图、饼图和散点图测量工具 SHALL 返回统一的测量质量契约，包含生命周期状态、confidence、warnings、结构化 issues、测量范围、源附件/面板归因和可关联的源尺寸 visual evidence。图表类型专有的 bars、series、sectors 或 points 仍应保留，不得被统一 envelope 覆盖。

#### Scenario: All chart sensors expose comparable quality state

- **WHEN** Agent 调用任一受支持的图表测量工具
- **THEN** 下一轮模型上下文可以用相同字段理解该结果是否 provisional、accepted、partial 或需要重测
- **AND** 结果仍保留对应图表类型的几何证据、坐标约定和 overlay

#### Scenario: Sensor warnings become actionable issues

- **WHEN** 传感器发现基准线、标定、覆盖、关联或不支持样式方面的重大不确定性
- **THEN** 结果同时提供定位、严重性和建议动作的结构化 issue
- **AND** 不得只返回无法驱动后续处理的自由文本 warning

### Requirement: Accepted measurement evidence is distinguishable from partial observation

图表理解链路 SHALL 能够区分已通过质量门禁的测量证据与仅供模型复查的局部或像素观察。低置信度结果仍可被模型查看和融合，但不得在没有明确接受状态时被呈现为完整恢复数据。

#### Scenario: Partial sensor output remains usable but not final

- **WHEN** 传感器检测到部分柱体、折线轨迹、饼图扇区或散点
- **THEN** Agent 可以继续请求补充观察或重新测量
- **AND** 该结果不会被 observation success 状态或普通工具返回包装成完整测量
