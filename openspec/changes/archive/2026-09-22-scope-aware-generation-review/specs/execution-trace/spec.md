## ADDED Requirements

### Requirement: Candidate lifecycle events share stable scope correlation

候选生成、测量 observation、证据决策、审核、修复和 publication 事件 SHALL 共享
`candidate_id`、`attempt`、`source_scope` 和适用的 `repair_kind`。事件仍 SHALL 保持
工具执行、measurement evidence、chart review 和 publication status 的语义分离。

#### Scenario: Measurement and review are not displayed as one status

- **WHEN** 一个候选经历 measurement_observed、evidence_selected、chart_review_started
  和 generated_chart_rejected
- **THEN** trace 保留每种事件的独立 kind 和状态
- **AND** 关联字段允许客户端把它们归入同一 candidate attempt
- **AND** 任一 measurement 成功不会被解释成 review passed

### Requirement: Repair events identify the next permitted phase

每个审核失败或修复事件 SHALL 携带 bounded repair kind、父 attempt 和允许的下一阶段。
`evidence_needed` 事件 SHALL 能区分“等待主 Agent 决策”和“正在同范围补证据”；
`terminal` 事件 SHALL 表示不得继续。

#### Scenario: Evidence repair is traceable from failure to re-review

- **WHEN** review 失败后主 Agent 进行同范围补测并重新审核
- **THEN** trace 能通过父/子 attempt 连接失败、补测、重新装配和下一次审核
- **AND** 不会把多个 review lifecycle event 误显示为多次独立生成请求

### Requirement: Oversized diagnostic results preserve the scope identity

当 tool result 或 review diagnostic 被截断时，外层事件 SHALL 仍保留 tool name、call_id、
candidate_id、attempt、source scope 和 status；截断只影响诊断正文，不得造成孤立或未知
候选。

#### Scenario: Truncated measurement remains attributable

- **WHEN** 局部测量结果超过事件正文限制
- **THEN** 客户端仍能知道它属于哪个 candidate/panel attempt
- **AND** 可以通过授权引用获取完整结果或显示明确的 truncated 状态

