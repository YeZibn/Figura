## ADDED Requirements

### Requirement: Main Agent receives a compact current decision context

每轮主 Agent prompt SHALL 在现有四层体系中提供一个有界的当前 decision context，至少表达 current unit、phase、status、scope、当前 evidence/candidate 引用、required next action 和剩余预算。该 context SHALL 引用已有结构化事实，不得复制一份会漂移的自然语言任务合同。

#### Scenario: Agent distinguishes focus from observation

- **WHEN** 当前 unit 已应用 focused scope 但尚未获得 observation
- **THEN** prompt 明确显示 pending observation 和允许的同 scope action
- **AND** 不把 focus applied 描述为已经获得可组装证据

#### Scenario: Agent sees evidence decision lineage

- **WHEN** 当前 attempt 已经有 selected/discarded refs
- **THEN** prompt 显示 decision status、attempt 和允许的后续 assemble/remeasure action
- **AND** Agent 不需要从多条重复事件中猜测当前状态

### Requirement: Decision context declares allowed and blocked actions

动态状态层 SHALL 明确列出当前允许、需要显式确认和被阻塞的动作。普通 warning 可以作为可选行动建议；required repair、scope violation、review gate 和 publication status SHALL 作为代码拥有的约束呈现。

#### Scenario: Required evidence repair is explicit

- **WHEN** generated review 要求同一 panel 的 evidence repair
- **THEN** prompt 显示 same-scope measurement 为允许或必需动作，并阻止跨 panel、直接 assemble 或 publication
- **AND** Agent 可以显式选择完成、放弃或进入 terminal recovery

#### Scenario: Prompt does not turn a warning into an automatic loop

- **WHEN** measurement 只有 warning 且没有 required repair obligation
- **THEN** prompt 将其标为可选决策
- **AND** Agent 未作出选择前不会自动重复调用工具

### Requirement: Prompt context remains aligned with the timeline projection

主 Agent prompt 使用的 decision context 与客户端 timeline 使用相同的 unit、phase、attempt 和 status 标识。提示词 SHALL 不把 review snapshot 或原始工具结果快照当成新的决策转换。

#### Scenario: Model and client agree on the next action

- **WHEN** timeline 显示当前 unit 等待证据选择
- **THEN** prompt 显示相同的 pending unit 和 allowed decision actions
- **AND** 模型输出的后续工具调用可以通过同一 transition 关联回 timeline
