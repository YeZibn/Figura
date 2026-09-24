## MODIFIED Requirements

### Requirement: User can inspect persisted Agent runs

The desktop workspace SHALL display each Agent run as a compact execution group with its status, timestamps when available, and expand/collapse control. Inside the group it SHALL render a chronological user-facing timeline containing meaningful tool, observation, measurement, generation, review, recovery, and failure steps. A tool call and its result SHALL be represented as one logical step, while model-start, model-completion, operation-save, run-start, and resume-start lifecycle events SHALL remain available in the persisted history but SHALL NOT appear as ordinary visible timeline rows. A bounded or truncated tool result SHALL remain part of the corresponding tool step and SHALL NOT become an unknown standalone step when the outer tool identity is available.

#### Scenario: Completed run remains visible after reload

- **WHEN** the user reloads a session containing completed runs
- **THEN** the client restores their run summaries and can expand each one to inspect its persisted user-facing timeline

#### Scenario: Tool status is correlated

- **WHEN** a tool call and its result share a call identifier
- **THEN** the UI shows one logical tool step whose status changes from running to success or failure
- **AND** its arguments, bounded result, and visual evidence are available behind the step disclosure control

#### Scenario: Technical lifecycle events stay hidden

- **WHEN** a run history contains model-start, model-completion, or operation-save events
- **THEN** the ordinary timeline does not render separate rows or cards for those events
- **AND** the run status, tool steps, domain milestones, and terminal error remain understandable without opening raw history

#### Scenario: Truncated result remains in its tool step

- **WHEN** the Gateway marks a tool result body as truncated but preserves the originating tool name and call identifier
- **THEN** the UI keeps the result under the originating tool step
- **AND** it shows an explicit bounded or truncated-state indicator
- **AND** it does not render a separate “unknown tool” step

#### Scenario: Legacy or incomplete history is explicit

- **WHEN** a run has no recoverable events, has an event-history gap, or was interrupted by a Gateway restart
- **THEN** the UI shows an explicit unavailable, incomplete, or interrupted state
- **AND** it does not fabricate missing execution steps or expose a technical lifecycle bucket as the main user-facing process

### Requirement: Desktop client renders a grouped decision timeline

普通运行详情 SHALL 从同一份 execution events 派生内部 decision-unit 关联和面向用户的扁平时间线。内部 unit 仍 SHALL 保留 observe、decide、assemble、render、review、repair、publish 阶段、lineage 和去重语义，但界面顶层只 SHALL 展示可解释的测量、工具、审核、生成、发布、恢复或错误步骤。process、turn、operation 和 legacy 关联不得直接渲染为嵌套的顶层容器；sequence 和原始 payload 仅在按需详情中显示。

#### Scenario: User follows one candidate from evidence to publication

- **WHEN** 一个 run 包含测量、证据选择、assemble、render、review 和 publication
- **THEN** 用户可以在一条连续时间线上按顺序看到这些有业务意义的阶段
- **AND** 工具结果、模型生命周期事件和门禁内部关联不会制造额外的套娃卡片

#### Scenario: Tool invocation is a single visible step

- **WHEN** 一个工具依次产生 tool_call、tool_result 和 visual_observation
- **THEN** UI 将它们合并为一条可折叠工具步骤
- **AND** 用户无需阅读模型轮次或 operation-save 事件即可理解工具是否完成及其结果

#### Scenario: Pending unit is visually distinct

- **WHEN** 局部范围已应用但后续 observation 或 evidence decision 尚未完成
- **THEN** UI 在扁平时间线上显示待完成状态和下一步动作
- **AND** 不使用“已完成”或“已发布”标签替代该状态

### Requirement: Timeline details remain read-only and recoverable

展开、刷新和重连时间线 SHALL 只读取已有事件、诊断和安全资源，不得重新触发模型、工具、审核或发布。用户默认看到面向业务的步骤；技术生命周期字段、sequence、原始 payload 和兼容关联 SHALL 只能通过受限的按需详情读取。历史缺失、截断和不可用状态 SHALL 在对应可见步骤或运行摘要上明确展示。

#### Scenario: Refresh does not repeat a review

- **WHEN** 用户刷新一个已完成或失败的 run
- **THEN** UI 从历史记录重建相同的用户时间线和 review cycle
- **AND** 不产生新的 VLM invocation 或 publication action
