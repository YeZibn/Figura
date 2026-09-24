## ADDED Requirements

### Requirement: Execution events expose decision-unit correlation

测量、装配、生成、审核、修复和发布相关的 execution event SHALL 在适用时携带统一的 `unit_id`、`unit_type`、`phase`、`actor`、`parent_unit_id`、`transition_id` 和 `next_action`。字段 SHALL 是有界、可序列化且与现有 run、candidate、attempt、scope 和 call 标识兼容的。

#### Scenario: Cross-domain events share a unit lineage

- **WHEN** 一个候选由一次测量决策和一次审核修复产生
- **THEN** 相关事件可以通过 unit 和 parent unit 关联到同一 candidate lineage
- **AND** 客户端可以区分 observation、decision、action、gate 和 publication

#### Scenario: Event without applicable parent remains valid

- **WHEN** 一个独立的工具观察没有父决策 unit
- **THEN** 事件可以使用自身的 observation unit 和空 parent
- **AND** 不得伪造一个不存在的 candidate 或 review 关系

### Requirement: Execution history supports deterministic decision projection

持久化 execution history SHALL 保留生成统一时间线所需的顺序、状态和关联字段。历史重放、实时追加和评测读取 SHALL 使用同一事件语义，不得因为不同入口而生成不同的 unit 分组。

#### Scenario: Live and replayed events project identically

- **WHEN** 客户端先读取历史事件，再接收同一 run 的实时事件
- **THEN** 两批事件合并后产生与完整历史读取相同的时间线
- **AND** 不产生重复 unit 或乱序状态

#### Scenario: Evaluation reads the same trace contract

- **WHEN** 评测工作台读取一个 case 的 run history
- **THEN** 事件中的 unit、phase、decision 和 gate 字段与普通运行读取时一致
- **AND** 评测层不需要访问原始 SQLite 或重新执行 Agent

### Requirement: Pending transitions are explicit in the execution trace

带有必需下一动作的事件 SHALL 保留 `required`、允许动作、阻塞动作和 bounded reason。事件序列 SHALL 能区分“动作已请求”“动作已应用”“动作已观察”“动作已决策”和“动作已终止”。

#### Scenario: Applied scope does not imply observed evidence

- **WHEN** trace 收到 measurement focus applied 但没有对应 observation
- **THEN** trace 保留 pending next action
- **AND** run terminal summary 不得把该 focus 当作已完成测量

#### Scenario: Explicit abandonment is terminally visible

- **WHEN** Agent 选择放弃一次可选测量或证据候选
- **THEN** trace 记录 abandonment reason 和被放弃的 unit
- **AND** 后续候选不会引用一个未被选择的 evidence ref

### Requirement: Equivalent transitions are projected idempotently

同一 `run_id`、`unit_id`、`attempt`、`phase` 和 `transition_id` 的重复事件 SHALL 不创建重复的顶层时间线行。去重不得删除原始 event history，也不得隐藏相同 transition 的错误状态。

#### Scenario: Review snapshot does not duplicate review start

- **WHEN** review gate 和 tool result 都携带同一个 review start transition
- **THEN** timeline projection 只生成一个 review start 状态
- **AND** 原始事件仍然按 sequence 保留
