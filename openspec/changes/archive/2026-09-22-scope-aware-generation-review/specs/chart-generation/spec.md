## ADDED Requirements

### Requirement: Source-linked generation propagates task context

对于声明来自附件或 panel 的生成请求，生成工具 SHALL 接收并返回与 ChartSpec 绑定的
`generation_context`，并 SHALL 将 `mode`、`source_scope`、`coverage` 和
`selection_basis` 保留在 candidate metadata 中。渲染结果不得只依赖自由文本 source
标签来推断来源范围。

#### Scenario: Transform candidate keeps its source panel

- **WHEN** Agent 将一个 panel 的一个系列转换成另一种图表类型并请求渲染
- **THEN** candidate metadata 仍包含该 panel 的 source scope 和 transform mode
- **AND** review/publication path 可以读取相同上下文

### Requirement: Generated chart review uses the declared transformation semantics

当生成候选的任务模式为 `transform` 或 `summarize` 时，生成链路 SHALL 以候选中声明的
目标类型、代表数据和有意省略项作为审核范围；不得以完整源 dashboard 的图表集合替代
候选任务合同。`reconstruct` 才要求按 full-source coverage 检查完整性。

#### Scenario: Right-side source panel is not a transform requirement

- **WHEN** 左侧 panel 被转换成饼图且 generation context 明确只选择左侧 Actual 系列
- **THEN** 候选可以通过审核，即使右侧 panel 没有进入结果
- **AND** 审核仍检查左侧选择和饼图数值是否一致

### Requirement: Evidence repair preserves publication gating

当审核返回 `evidence_needed` 或 `source_rebind` 时，渲染候选 SHALL 保持 preview/rejected
状态，直到修复后的 ChartSpec 重新渲染并完成审核。任何已完成的 deterministic render
检查不得单独将候选变成 published。

#### Scenario: Failed review cannot be bypassed by a render retry

- **WHEN** candidate review 失败后 Agent 只重新渲染但未完成要求的证据或来源修复
- **THEN** 新候选仍处于 review-pending 或 rejected 状态
- **AND** final result 不得声称生成图已验证

