## REMOVED Requirements

### Requirement: Lifecycle events separate execution, review, and publication state

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Generated chart preview references follow candidate publication

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Execution checkpoints and continuation lineage are inspectable

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Candidate lifecycle events share stable scope correlation

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Repair events identify the next permitted phase

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Pending transitions are explicit in the execution trace

**Reason**: 旧候选/审核/发布生命周期和门禁展示契约由提交事实投影取代。
**Migration**: 使用本 capability 的新增要求以及 generated-chart-verification 的结果语义。

### Requirement: Execution events expose decision-unit correlation

**Reason**: 内部恢复游标不进入业务事件，公开事件只需表达已提交事实的关联。
**Migration**: 使用 committed-fact correlation，关联 run、tool call、staged chart、verification 和 artifact。

## ADDED Requirements

### Requirement: Execution events represent committed tool, verification and artifact facts

公开执行事件 SHALL 使用同一 Run 内单调序号及稳定 transition/correlation identity，分别表达工具过程、验证结论、正式 artifact 和终态；未提交的内部结果不得投影为完成。测量质量仍作为工具事实，不建立采用/舍弃事件。验证和发布分别使用已提交结论，不叠加平行状态维度或固定处理阶段。

#### Scenario: Verification and promotion appear once
- **WHEN** 一张图验证通过并正式发布，随后事件被重放
- **THEN** 时间线仍只有一个可归属的验证结果和一个正式产物结果
- **AND** 不从未提交的内部状态推断额外转换

#### Scenario: Failed staged image has bounded context
- **WHEN** 验证失败且暂存预览可用
- **THEN** 事件含有生成尝试、来源范围、issues 与预览引用
- **AND** 不暴露图像字节、私有模型上下文或本地路径

## MODIFIED Requirements

### Requirement: Execution trace groups related tool evidence

The system SHALL preserve one canonical run identifier across Gateway run acceptance, Agent execution, durable memory records, execution events, conversation projection, attachments, visual observations, and generated chart artifacts. Measurement, generation, verification, and artifact events in the user timeline SHALL carry a complete bounded unit envelope. A tool call and result SHALL use the same `unit_id` and `call_id`; each generated image SHALL use committed staged and verification references as stable identity. Producers SHALL reject events that omit required identity or canonical state fields.

The grouping SHALL retain intermediate evidence when the final answer is available, while allowing generated chart artifacts to be displayed as final Run results instead of duplicated as ordinary tool-step content. Tool-result events SHALL retain bounded tool, call, unit, turn, and run identity when result details are truncated.

#### Scenario: Tool call and result form one inspectable step

- **WHEN** a tool call emits a later result with the same call identifier
- **THEN** the client renders one step with running, success, or error state and expandable details
- **AND** both events belong to the same canonical unit

#### Scenario: Missing timeline identity is rejected

- **WHEN** a producer attempts to persist a measurement, generation, verification, or artifact event without required identity or state
- **THEN** it records a bounded protocol error and does not publish the malformed event

### Requirement: Oversized diagnostic results preserve the scope identity

当 tool result、来源绑定诊断或图像验证诊断被截断时，外层事件 SHALL 仍保留 bounded
tool name、call_id、unit identity、来源范围引用和 status；截断只影响诊断正文，不得造成
孤立工具结果或虚构业务状态。

#### Scenario: Truncated measurement remains attributable

- **WHEN** 局部测量结果超过事件正文限制
- **THEN** 客户端仍能知道它属于哪个工具调用、来源范围和验证结果
- **AND** 可以通过授权引用获取完整结果或显示明确的 truncated 状态

### Requirement: Timeline events have one canonical payload shape

每个参与用户时间线的事件类型 SHALL 定义唯一的 envelope 字段形状和状态字段语义。新的 timeline correlation envelope SHALL 使用版本 2 和 `snake_case` 标识字段。工具结果使用 `status`，其他事件使用其 canonical state 字段；生产端遇到冲突字段或不支持的旧别名 SHALL 拒绝事件，客户端不得从别名推断成功、验证通过或发布。

#### Scenario: Verification and artifact events have one state field

- **WHEN** 生产端发出验证、生成或 artifact 事件
- **THEN** 事件只包含该事件类型定义的 canonical 状态字段

### Requirement: Execution history supports deterministic decision projection

持久化 execution history SHALL 保留生成统一时间线所需的顺序、状态和关联字段。历史重放、实时追加和评测读取 SHALL 使用同一事件语义，不得因为不同入口而生成不同的 unit 分组。

#### Scenario: Evaluation reads the same trace contract

- **WHEN** 评测工作台读取一个 case 的 run history
- **THEN** unit、phase、state 和来源关联与普通运行读取时一致
- **AND** 评测层不需要访问原始 SQLite 或重新执行 Agent

### Requirement: Lifecycle events expose bounded process correlation

执行事件 SHALL 在可确定时携带有界的 process、turn 或其他现有运行关联信息，并继续保留 run sequence 作为事实顺序。无法确定关联时，事件仍 SHALL 合法持久化并明确为未关联，不得伪造 unit 或 parent。

#### Scenario: Unsupported legacy protocol is explicit

- **WHEN** 历史事件没有当前协议要求的关联字段
- **THEN** Gateway 或客户端按不支持的历史协议返回有界不可用状态
- **AND** 不从旧 lifecycle 字段迁移或合成缺失的关联信息

### Requirement: Recovery trace exposes a cursor without controlling execution

Run 历史 SHALL 可见有界 resume 资格、不可用原因、父子 Run 关系及下一动作类别；内部执行记录负责恢复控制。SSE 重放 SHALL 继续以 runId:sequence 去重，并且历史缺口 SHALL 明确呈现。

#### Scenario: Child resume remains attributable
- **WHEN** 子 Run 从父 Run 的已提交游标继续
- **THEN** 两个 Run 各自保留事件序号和终态
- **AND** 历史可识别它们的 resume 关系

### Requirement: Execution events expose committed-fact correlation

测量、装配、生成、验证和发布相关的 execution event SHALL 在适用时携带统一的 `unit_id`、`unit_type`、`phase`、`actor`、`parent_unit_id` 和 `transition_id`。字段 SHALL 有界、可序列化，并与 run、staged reference、verification reference、scope 和 call 标识兼容；恢复控制游标不得成为业务时间线事件。

#### Scenario: Cross-domain events share a unit lineage

- **WHEN** 一张图由 measurement tool observation、实际 assembly 输入、渲染、验证和发布产生
- **THEN** 相关事件可以通过 unit 与 parent unit 关联到同一张图
- **AND** 客户端可以区分工具观察、生成、验证、正式 artifact 和终态，而不需要额外 decision 或 gate 事件
