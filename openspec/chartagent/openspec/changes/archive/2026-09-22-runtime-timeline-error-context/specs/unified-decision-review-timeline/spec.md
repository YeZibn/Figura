## ADDED Requirements

### Requirement: Runtime lifecycle events use a bounded compatibility projection

时间线投影 SHALL 按以下优先级处理没有完整 decision-unit 关联的运行事件：先使用既有 `unit_id`，再使用同一 run 内可验证的 process、turn 或 operation 关联，最后将无法安全关联的事件收敛到有界的 legacy/process 容器。系统不得为每一个未关联事件创建独立的顶层 decision unit，也不得根据缺失字段猜测业务父子关系。

#### Scenario: Real run lifecycle events are grouped

- **WHEN** 一个 run 产生 `run_started`、model lifecycle、operation completed 和 terminal events，但其中部分事件没有 `unit_id`
- **THEN** 时间线将它们按可验证的过程上下文或有限 legacy 容器展示
- **AND** 用户不会看到每个普通生命周期事件各自成为“历史记录（关联不可用）”顶层卡片

#### Scenario: Mixed correlated and legacy events remain separate

- **WHEN** 同一个 run 同时包含有 decision-unit 的 measurement/review 事件和无法关联的生命周期事件
- **THEN** 有 decision-unit 的事件保持原有 unit、phase 和 lineage
- **AND** legacy/process 容器只承载无法安全关联的事件，不把它们错误挂到某个 candidate 或 review

### Requirement: Projected failures preserve actionable error context

时间线投影 SHALL 保留错误类别、稳定错误码、provider 状态（如存在）、安全的用户可读原因、是否可重试以及第一失败事件引用。摘要可以截断正文，但不得只保留无上下文的通用“运行失败”文本。

#### Scenario: Provider rejection remains diagnosable

- **WHEN** provider 返回确定性的拒绝并导致 run 终止
- **THEN** 时间线显示 provider 拒绝类别、状态或错误码和脱敏后的原因
- **AND** 用户可以区分它与远端结果未知的网络或超时失败

#### Scenario: Replay does not lose failure details

- **WHEN** 用户刷新、重连或在评测工作台读取同一 run 的历史事件
- **THEN** 投影仍显示相同的错误类别、原因和失败引用
- **AND** 重建不会重新调用 provider 或创建新的 decision unit
