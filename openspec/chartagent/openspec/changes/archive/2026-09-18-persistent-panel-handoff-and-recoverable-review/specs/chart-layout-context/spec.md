## ADDED Requirements

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
