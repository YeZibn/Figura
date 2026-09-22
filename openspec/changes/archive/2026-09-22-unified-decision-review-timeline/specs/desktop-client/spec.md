## ADDED Requirements

### Requirement: Desktop client renders a grouped decision timeline

普通运行详情 SHALL 将相关 execution events 聚合为 decision units，并按 observe、decide、assemble、render、review、repair、publish 的阶段顺序展示。顶层摘要 SHALL 使用稳定的中文状态，原始工具和事件细节 SHALL 可展开查看。

#### Scenario: User follows one candidate from evidence to publication

- **WHEN** 一个 run 包含测量、证据选择、assemble、render、review 和 publication
- **THEN** 用户可以在一个可展开 unit 中按顺序看到这些阶段
- **AND** 工具结果、模型决策和门禁状态不会被混排成无法解释的事件列表

#### Scenario: Pending unit is visually distinct

- **WHEN** 局部范围已应用但后续 observation 或 evidence decision 尚未完成
- **THEN** UI 显示待完成状态和下一步动作
- **AND** 不使用“已完成”或“已发布”标签替代该状态

### Requirement: Client distinguishes observations, decisions, actions, gates, and publication

时间线 SHALL 使用不同的 presentation role 区分工具观察、Agent 证据决策、系统动作、审核门禁和发布结果。相同 transition 的状态更新不得生成重复的顶层卡片，但原始事件仍可展开。

#### Scenario: Evidence discard is shown as a decision

- **WHEN** Agent 舍弃某个 measurement evidence ref
- **THEN** UI 将其显示为对应 attempt 下的 Agent decision，并保留 reason/basis
- **AND** 不把证据舍弃误显示为工具失败或生成图审核失败

#### Scenario: Review sub-checks are nested

- **WHEN** 一个 candidate review cycle 包含 deterministic audit 和 VLM semantic review
- **THEN** UI 显示一个审核父项和两个子检查
- **AND** 不显示多个重复的审核开始卡片

### Requirement: Collection candidates are grouped without losing child details

当同一 render 产生 collection child candidates 时，客户端 SHALL 以 collection review parent 聚合展示，并允许展开每个 child 的 candidate、attempt、issue、scope 和 publication status。

#### Scenario: Multiple generated images share one parent

- **WHEN** 一次生成返回多个同源 child charts
- **THEN** UI 显示一个生成/审核批次和多个 child 状态
- **AND** 用户可以区分“多个子图”与“同一候选被重复审核”

### Requirement: Timeline details remain read-only and recoverable

展开、刷新和重连时间线 SHALL 只读取已有事件、诊断和安全资源，不得重新触发模型、工具、审核或发布。历史缺失、截断和不可用状态 SHALL 在对应 unit 上明确展示。

#### Scenario: Refresh does not repeat a review

- **WHEN** 用户刷新一个已完成或失败的 run
- **THEN** UI 从历史记录重建相同的 review cycle
- **AND** 不产生新的 VLM invocation 或 publication action
