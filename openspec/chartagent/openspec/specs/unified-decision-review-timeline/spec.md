# unified-decision-review-timeline Specification

## Purpose

从已提交的工具、验证、artifact 和终态事实构建可展开的用户时间线；时间线只投影执行事实，不控制恢复、审核或发布。
## Requirements

### Requirement: Runtime facts do not become visible decision gates

measurement scope、issues、质量信息和模型后续实际选择 SHALL 作为工具结果及实际工具调用中的事实呈现。默认前端 SHALL NOT 将 measurement decision、repair queue、focus transition 或 evidence selection/discard 投影为要求模型关闭的状态单元；只有工具执行、候选生成、generated-chart review 和终态错误形成对应时间线步骤。

#### Scenario: Measurement warning remains inside the tool result

- **WHEN** 测量返回 warning 或局部补充线索
- **THEN** 用户可在测量工具结果中查看该信息
- **AND** 时间线不额外显示 measurement decision pending 或自动重测步骤

#### Scenario: Review failure remains actionable and concise

- **WHEN** 生成审核失败
- **THEN** 时间线显示审核失败和原因
- **AND** 模型后续选择的实际工具调用按正常工具步骤展示

#### Scenario: Model-selected local retest appears as a normal tool call

- **WHEN** 主 Agent 根据不确定性显式再次调用带 scope/target 的测量工具
- **THEN** 时间线展示这次新的测量工具调用和结果
- **AND** 不将其重包装成 repair queue 或 evidence decision 生命周期

### Requirement: Projected failures preserve actionable error context

时间线投影 SHALL 保留错误类别、稳定错误码、provider 状态（如存在）、安全的用户可读原因、是否可重试以及第一失败事件引用。摘要可以截断正文，但不得只保留无上下文的通用“运行失败”文本。

#### Scenario: Provider rejection remains diagnosable

- **WHEN** provider 返回确定性的拒绝并导致 run 终止
- **THEN** 时间线显示 provider 拒绝类别、状态或错误码和脱敏后的原因
- **AND** 用户可以区分它与远端结果未知的网络或超时失败

#### Scenario: Replay does not lose failure details

- **WHEN** 用户刷新、重连或在评测工作台读取同一 run 的历史事件
- **THEN** 投影仍显示相同的错误类别、原因和失败引用
- **AND** 重建不会重新调用 provider 或创建新的 decision unit

### Requirement: Timeline groups committed execution facts without owning state

用户时间线 SHALL 从 Run 的工具、验证、artifact 和终态事件确定性投影；它不得控制 checkpoint、审核或发布。相同 run 与 transition identity 的重放 SHALL 去重，旧候选/审核/发布状态字段不得形成新的顶层生命周期单元。工具结果与原始有界证据仍可展开。

#### Scenario: Duplicate verification event is replayed
- **WHEN** 同一个验证完成事件通过 SSE 与历史补偿重复到达
- **THEN** 用户只看到一次验证结果
- **AND** 任何发布动作不会由前端投影触发

### Requirement: Collection outcomes remain individually inspectable

同一次生成的 collection SHALL 通过稳定 parent、figure、child 和尝试身份分组；每个子图的验证结论、来源范围、issues、预览及正式产物 SHALL 独立保留。失败原因 SHALL 可定位而不能被父级汇总覆盖。

#### Scenario: One child fails and one passes
- **WHEN** collection 的两个子图有不同验证结果
- **THEN** 父级显示集合流程，展开后显示各子图真实结果
- **AND** 失败子图不会显示兄弟图的正式 artifact
