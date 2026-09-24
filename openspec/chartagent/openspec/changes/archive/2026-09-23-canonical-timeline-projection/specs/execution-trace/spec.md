## ADDED Requirements

### Requirement: Timeline events have one canonical payload shape

每个参与用户时间线的事件类型 SHALL 定义唯一的 envelope 字段形状和状态字段语义。新的 timeline correlation envelope SHALL 使用版本 2；envelope 标识字段 SHALL 使用当前运行事件协议约定的 `snake_case`。同一事件类型不得把 `state/status`、snake/camel 字段名或 Gate 别名作为可互换输入。不同公开 DTO（例如 Run summary）可以继续使用其既有字段约定，但不得把 DTO 别名注入事件 envelope。`tool_result` 的工具执行状态使用 `status`，其他生命周期状态使用该事件类型定义的 canonical 字段；生产端遇到同一语义的冲突或别名字段 SHALL 拒绝该时间线事件，不得选择一个值继续发布。

#### Scenario: Lifecycle event has one state field

- **WHEN** 生产端发出审核、生成或发布生命周期事件
- **THEN** 事件只包含该事件类型定义的 canonical 状态字段
- **AND** 客户端无需从另一个状态别名推断状态

#### Scenario: Tool result uses its declared execution status

- **WHEN** 生产端发出 `tool_result`
- **THEN** 外层事件使用该事件类型规定的工具执行状态字段，并保留 tool/call/unit/run 关联
- **AND** 不额外写入一个含义重复的生命周期状态别名

#### Scenario: Gate snapshots do not create parallel lifecycle events

- **WHEN** 权威审核状态变化并更新 Gateway 的 Gate 查询投影
- **THEN** 系统通过审核/发布业务事件表达相关领域转移
- **AND** 不另外发出 `review_gate_required` 或 `review_gate_updated` 镜像事件

#### Scenario: Conflicting aliases are rejected

- **WHEN** 一个时间线事件同时包含同一语义的多个字段，或仅提供该事件类型不支持的别名
- **THEN** 生产端记录有界协议错误并拒绝该事件进入可见事件历史
- **AND** 不通过优先级或“第一个非空值”静默选择状态

#### Scenario: Unsupported history protocol is explicit

- **WHEN** 客户端读取无法识别的时间线协议版本或字段形状
- **THEN** Gateway/客户端返回明确的不可用或不支持状态
- **AND** 不把该历史事件转换成成功、通过或已发布状态
