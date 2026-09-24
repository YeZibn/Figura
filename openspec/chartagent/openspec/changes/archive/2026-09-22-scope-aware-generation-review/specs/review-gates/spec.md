## ADDED Requirements

### Requirement: Review outcomes expose a bounded repair kind

审核 gate SHALL 将失败或需要补充的信息归一化为 `spec_only`、`evidence_needed`、
`source_rebind` 或 `terminal`，并将 repair kind 与 candidate attempt 绑定。未识别或越界
的 repair kind SHALL 按 terminal/blocked 处理，而不是继续执行未知动作。

#### Scenario: Review issue selects evidence repair

- **WHEN** 审核认为现有 scope 内的一个值缺少足够证据，但来源 panel 仍然有效
- **THEN** gate 返回 `evidence_needed`
- **AND** 主 Agent 只被允许在同一 scope 内补证据并重新装配

### Requirement: Evidence repair is an in-gate bounded sub-loop

`evidence_needed` SHALL 开启一个有界的审核修复子循环，允许的顺序为
same-scope evidence -> ChartSpec assembly -> render -> VLM review。子循环 SHALL 继承原
候选上下文、受最大 attempt 次数限制，并在每次失败后保留诊断；不得因为首次审核失败
而直接把 Run 标为成功或无上下文结束。

#### Scenario: Successful evidence repair returns to review

- **WHEN** 同一 panel 的补充测量完成且新 ChartSpec 已渲染
- **THEN** gate 再次执行生成图审核
- **AND** 只有新的审核通过才允许 publication

#### Scenario: Repair budget is exhausted

- **WHEN** evidence repair 达到最大 attempt 次数仍未通过
- **THEN** gate 进入 terminal/failed 状态并返回最后一次结构化诊断
- **AND** 候选保持不可发布

### Requirement: Scope violations fail closed

审核修复中的工具调用、装配或来源解析若超出 generation context 的 attachment/panel
scope，gate SHALL 拒绝该动作并记录 scope violation；不得通过扩大 scope 来绕过审核。

#### Scenario: Cross-panel evidence call is blocked

- **WHEN** repair request 从左侧 panel 改为右侧 panel 或整张 dashboard
- **THEN** gate 返回 scope violation
- **AND** 不执行该工具调用且不推进候选状态

