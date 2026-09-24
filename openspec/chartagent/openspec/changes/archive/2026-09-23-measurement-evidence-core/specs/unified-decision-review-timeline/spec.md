## MODIFIED Requirements

### Requirement: Timeline preserves raw evidence and decision lineage

系统 SHALL 在可用的内部 execution trace 和评测详情中保留工具调用、工具结果、图片引用、measurement/evidence refs、attempt、scope、质量诊断、审核问题、修复结果及实际 assembly 引用。默认用户时间线 SHALL 聚焦工具过程、生成候选和审核结果；measurement 候选使用与否从实际 assembly 输入读取，不生成独立 measurement decision 事件或待处理卡片。

#### Scenario: Evidence use remains auditable without a decision event

- **WHEN** Agent 使用一次 measurement observation 中的部分 refs 完成装配
- **THEN** 内部 trace 可以关联 observation、实际 assembly refs 和生成结果
- **AND** 默认时间线不创建“测量决策”、选择/舍弃或待处理步骤

#### Scenario: Measurement result remains inspectable when unused

- **WHEN** 某次 measurement observation 未被后续 assembly 引用
- **THEN** 可用的工具结果仍可按普通运行详情查看
- **AND** 不推导 abandoned、discarded 或未完成的 measurement 状态

#### Scenario: Detail is unavailable

- **WHEN** 原始工具结果因历史保留、大小或权限原因不可完整读取
- **THEN** 时间线保留工具或审核步骤并显示 detail unavailable/truncated 原因
- **AND** 不伪造内容或成功状态

### Requirement: Runtime facts do not become visible decision gates

measurement scope、issues、质量信息和模型后续实际选择 SHALL 作为工具结果及实际工具调用中的事实呈现。默认前端 SHALL NOT 将 measurement decision、repair queue、focus transition 或 evidence selection/discard 投影为要求模型关闭的状态单元；只有工具执行、候选生成、generated-chart review 和终态错误形成对应时间线步骤。

#### Scenario: Measurement warning remains inside the tool result

- **WHEN** 测量返回 warning 或局部补充线索
- **THEN** 用户可在测量工具结果中查看该信息
- **AND** 时间线不额外显示 measurement decision pending 或自动重测步骤

#### Scenario: Model-selected local retest appears as a normal tool call

- **WHEN** 主 Agent 根据不确定性显式再次调用带 scope/target 的测量工具
- **THEN** 时间线展示这次新的测量工具调用和结果
- **AND** 不将其重包装成 repair queue 或 evidence decision 生命周期

#### Scenario: Review failure remains actionable and concise

- **WHEN** 生成审核失败
- **THEN** 时间线显示审核失败和原因
- **AND** 模型后续选择的实际工具调用按正常工具步骤展示
