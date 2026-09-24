## Purpose

为源图驱动的生成链路建立统一、可传递且可审核的任务上下文，使主 Agent、测量工具、ChartSpec 装配、生成候选和审核始终针对同一个来源范围与任务目标做决策。

## ADDED Requirements

### Requirement: Source-linked generation has an explicit task contract

当生成结果来自用户附件或其面板时，系统 SHALL 为每个候选保存结构化的
`generation_context`，至少包含 `mode`、`source_scope`、`coverage`、
`selection_basis` 和有界的 `goal_summary`。`mode` SHALL 为
`reconstruct`、`transform`、`summarize` 或 `synthesize` 之一；直接提供且不声称
来源还原的 ChartSpec 可以使用 `synthesize` 或标记为 `not_applicable`。

#### Scenario: Panel transform declares its scope and omission

- **WHEN** 用户要求把 dashboard 左侧 panel 的 Actual 系列转换成饼图
- **THEN** 候选上下文将 `mode` 记录为 `transform`
- **AND** `source_scope` 只引用该附件中的左侧 panel
- **AND** `coverage` 将 Actual 标为 `represented`，将未选中的 Target 标为
  `intentionally_omitted`
- **AND** 审核不得因为右侧 panel 未出现在候选中而判定缺失

#### Scenario: Full reconstruction declares full coverage

- **WHEN** 用户要求重建附件中的完整图表或指定 panel 的全部系列
- **THEN** 候选上下文将 `mode` 记录为 `reconstruct`
- **AND** `coverage.basis` 为 `full_source`
- **AND** 未表示的源系列会使上下文处于 `partial` 或触发结构化问题，而不能被静默忽略

### Requirement: Generation context is immutable for a candidate attempt

候选创建后，系统 SHALL 将其 `generation_context` 与 candidate identity 和 ChartSpec
版本绑定。后续审核、修复和发布 SHALL 使用同一版本上下文；若来源 panel、任务模式或
覆盖决策发生变化，系统 SHALL 创建新的 candidate attempt，而不是覆盖旧上下文。

#### Scenario: Repair does not rewrite the original intent

- **WHEN** 一个候选因证据不足需要补测
- **THEN** 修复 attempt 继承原候选的任务模式与来源范围
- **AND** 只能追加新的证据引用或明确的用户/Agent 选择
- **AND** 原候选的上下文和失败原因仍可读取

### Requirement: Review scope is resolved from the task contract

系统 SHALL 根据 `source_scope` 获取审核使用的原图局部区域；当 panel handoff 可用时，
审核 SHALL 使用其授权 bbox/裁剪，而不得默认加载整张 dashboard。无法解析来源范围时，
系统 SHALL 返回 `source_scope_unavailable`，并 SHALL 阻止候选发布，除非任务模式明确为
不依赖源图的 `synthesize`。

#### Scenario: Scoped review does not inspect unrelated panels

- **WHEN** 一个 transform 候选只绑定左侧 panel
- **THEN** VLM 审核输入包含左侧 panel 的来源裁剪、候选图和 generation context
- **AND** 不把右侧 panel 的内容作为该候选的缺失项

#### Scenario: Stale panel handoff cannot widen scope silently

- **WHEN** panel handoff 的 attachment hash 不匹配或 panel 已失效
- **THEN** 系统返回可恢复的 stale/scope-unavailable 状态
- **AND** 不得静默回退到整张附件并继续发布

### Requirement: Review repair kind controls the next allowed action

审核结果 SHALL 返回有界的 `repair_kind`：`spec_only`、`evidence_needed`、
`source_rebind` 或 `terminal`。代码拥有的门禁 SHALL 根据该值决定下一步：
`spec_only` 只允许修正 ChartSpec；`evidence_needed` 允许在同一来源范围内补充证据后
重新装配；`source_rebind` 只允许重新确认附件或 panel；`terminal` 不允许自动继续。
所有修复完成前候选 SHALL 保持不可发布。

#### Scenario: Evidence-needed repair is bounded to the same panel

- **WHEN** 审核指出左侧 panel 的一个系列值需要补充证据
- **THEN** 主 Agent 可以调用带相同 attachment/panel scope 的测量或 OCR 工具
- **AND** 调用其他 panel 或扩大到整张附件的工具请求被拒绝或返回结构化越界错误
- **AND** 新证据完成后必须重新装配并重新审核

#### Scenario: Terminal review failure does not silently end as success

- **WHEN** 审核返回 `terminal` 或修复次数耗尽
- **THEN** Run 返回明确的未发布状态和可定位诊断
- **AND** 不得把候选图作为已验证结果交给用户

### Requirement: Scope and coverage decisions are observable

系统 SHALL 在候选、测量 attempt、审核和发布事件中保留稳定的
`candidate_id`、`attempt`、`source_scope`、`coverage` 和 `repair_kind` 关联字段。
这些字段 SHALL 区分工具观察、Agent 证据决策、审核结论和 publication status，且不得
用单个“成功/失败”事件替代完整关联。

#### Scenario: One candidate has correlated evidence and review events

- **WHEN** 一个候选先测量、再发生 evidence-needed 修复并最终审核
- **THEN** 所有相关事件可以通过 candidate/attempt 关联到同一任务合同
- **AND** 客户端或审计程序可以区分原始观察、补充证据、审核和发布状态

### Requirement: Legacy source-free generation remains bounded

不带 `generation_context` 的旧版直接 ChartSpec SHALL 继续支持生成；但当该候选声称
来自用户附件却缺少任务模式或来源范围时，系统 SHALL 将上下文标记为 unknown/legacy，
采用保守的审核与发布策略，不得假定其代表整张附件或自动补齐来源范围。

#### Scenario: Direct ChartSpec remains compatible

- **WHEN** 调用方直接提交一个合法的 ChartSpec 且没有 source-linked 声明
- **THEN** 系统可以按现有单图路径生成
- **AND** 不要求伪造 attachment、panel 或 measurement provenance

