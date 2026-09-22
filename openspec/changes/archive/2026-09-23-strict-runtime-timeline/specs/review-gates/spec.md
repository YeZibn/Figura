## MODIFIED Requirements

### Requirement: A candidate attempt has one canonical review cycle

每个 generated candidate attempt SHALL 对外表现为一个 canonical review cycle，且
只能使用一个 canonical review identity。审核开始、最终审核结果和发布状态必须
由同一审核协调链路产生；内部 deterministic audit、semantic VLM review、状态
快照和修复分类 SHALL 继续可追踪，但不得再发出 `chart_review_started` 或
`chart_review_completed` 兼容事件。默认用户时间线 SHALL 只显示一次审核开始和
一个最终审核结果；失败结果 SHALL 显示原因。

#### Scenario: Internal checks produce one visible review summary

- **WHEN** 候选先通过确定性质量检查，再等待或执行 semantic VLM review
- **THEN** gate 维持同一个 review identity
- **AND** 默认客户端不把内部检查显示为多个 subcheck、英文事件或重复审核步骤

#### Scenario: Canonical review events are the only lifecycle source

- **WHEN** 生成候选进入审核、修复或完成发布
- **THEN** 系统只产生 `review_started`、一个终态 `review_completed` 或 `review_failed`，以及必要的 publication transition
- **AND** 不会同时产生另一套 `chart_review_*` 生命周期

#### Scenario: Replayed state does not reopen a completed cycle

- **WHEN** 相同 candidate attempt 的 completed review snapshot 被重复提交
- **THEN** gate 返回已有 review state
- **AND** 不重复执行审核、重新打开 publication gate 或创建新的 review identity
