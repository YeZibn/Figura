## ADDED Requirements

### Requirement: Chart measurements accept bounded focus targets

柱状图、折线图、饼图和散点图测量工具 SHALL 接受可选的受控 focus target，在已授权的 panel scope 内针对指定区域或字段进行重测。工具 SHALL 保持原有源图坐标约定，并返回目标区域、局部尺寸、源图尺寸和局部到源图的映射；focus target 不得扩大到相邻 panel 或未授权附件。

#### Scenario: Bar measurement focuses on a baseline region

- **WHEN** Agent 为当前 panel 提交包含 baseline 目标区域的定向测量请求
- **THEN** 工具只在该 panel 与 target 的交集内优先复查基准线和相关柱体边缘
- **AND** 结果仍包含可转换到源图坐标的 baseline、scope 和 visual evidence

#### Scenario: All chart types retain their own geometry

- **WHEN** focus target 分别请求折线、饼图或散点图的轴、扇区或点区域复查
- **THEN** 对应工具返回自身的 trace、sector 或 point 字段及统一质量契约
- **AND** 定向测量不得把其他图表类型的字段或检测器结果混入当前结果

#### Scenario: Invalid focus target falls back safely

- **WHEN** target 超出 panel、坐标格式无效或无法映射到源图
- **THEN** 工具返回有界的 target/routing 错误或明确的 panel 级 fallback 警告
- **AND** 不得把全图结果伪装成目标区域的精确重测

### Requirement: Targeted observations preserve the complete evidence contract

定向重测 SHALL 保留与普通测量相同的图表专属数据、质量状态、视觉 overlay、来源归因和局部到源图映射。目标区域仅用于缩小搜索范围和表达修复意图，不得跳过坐标、覆盖、关联或视觉证据审计。

#### Scenario: Partial target evidence remains partial

- **WHEN** target 内只能确认部分柱体、折线点、扇区或散点
- **THEN** 工具保留已确认的像素证据并标记覆盖缺口
- **AND** 不得因为 target 较小而自动将结果标记为完整 `accepted`
