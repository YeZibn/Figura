## REMOVED Requirements

### Requirement: Run and Turn state is dynamic control context

**Reason**: 动态提示词不再承载独立的图表审核 gate 或第二份生命周期状态。
**Migration**: 使用 committed execution facts、staged chart verification 和派生恢复资格。

### Requirement: Review prompt is a separate tool-free contract

**Reason**: 内部审核状态由有界图表验证结论取代。
**Migration**: 使用 generated-chart-verification 的 VLM 输入和输出契约。

### Requirement: Main Agent receives a compact current decision context

**Reason**: 主 Agent 上下文只呈现证据与已提交事实，不维护候选/发布生命周期副本。
**Migration**: 使用 committed staged、verification、artifact 与 measurement 事实。

### Requirement: Decision context declares allowed and blocked actions

**Reason**: 一般修复选择由主 Agent 根据证据决定，不由提示词状态机分派。
**Migration**: 使用代码强制的来源、安全、验证发布和终态约束。

### Requirement: Prompt context remains aligned with the timeline projection

**Reason**: 提示词与客户端共享已提交事实及稳定引用，不再维护第二套验证控制状态。
**Migration**: 使用新的 verification 与 artifact 时间线事件。

## ADDED Requirements

### Requirement: Runtime prompt exposes committed facts without shadow lifecycle state

Run/Turn 状态层 SHALL 提供当前请求、授权来源、selected panel、measurement evidence、最近工具动作、可选下一动作、已提交的 staged chart、verification 与正式 artifact 事实、派生恢复资格、预算和中断状态。它 MUST NOT 提供平行的领域生命周期状态、独立执行门禁、固定修复阶段或完整上下文快照。measurement warning 和验证 repair hint SHALL 是可选诊断，不得自动调度工具。

#### Scenario: Unfinished verification is described from committed facts

- **WHEN** Run 有已暂存但尚未验证的图像
- **THEN** 主 Agent 上下文显示其暂存身份及当前验证事实
- **AND** 不声称图像已通过或已发布，也不维护额外 gate 状态

#### Scenario: Measurement warning remains model selected

- **WHEN** measurement observation 带有 warning 或补测建议
- **THEN** prompt 将其作为有范围的证据和可选诊断
- **AND** 在 Agent 选择前系统不会自动重复调用工具

### Requirement: Semantic verification prompt keeps a bounded tool-free contract

语义验证提示 SHALL 接收暂存图、准确 ChartSpec、授权来源范围及 generation context，不得暴露工具调用。它 SHALL 使用 generated-chart-verification 定义的严格 JSON 结论和有界 issues；repair hint 仅描述诊断，不得要求验证模型选择或执行后续工具。

#### Scenario: Verifier identifies a repair hint without scheduling work

- **WHEN** VLM 找到可修复的标签或数据映射问题
- **THEN** 返回固定字段的验证结论和有界 issue
- **AND** 主 Agent 自主决定是否重测、修正 Spec、重新生成或停止

### Requirement: Prompt and timeline share stable committed references

主 Agent prompt 与客户端时间线 SHALL 使用相同的 run、staged、verification、artifact、collection child 和 source scope 引用。提示词 MAY 包含模型所需的证据说明，但不得引用客户端无法解析的第二套生命周期身份；客户端不得控制模型内部动作。

#### Scenario: Published result matches the visible timeline

- **WHEN** 图表已有已提交的正式 artifact
- **THEN** prompt 和时间线引用相同 artifact 身份与 warning 结果
- **AND** 时间线刷新不会触发验证或发布
