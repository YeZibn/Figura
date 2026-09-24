## ADDED Requirements

### Requirement: User can inspect measurement repair lifecycle

桌面客户端 SHALL 在 Agent 运行时间线中展示测量修复生命周期事件，包括修复请求、修复动作被拒绝和修复预算耗尽。展示 SHALL 保留原始事件类型，并以简体中文说明当前状态；修复事件 SHALL 与普通工具执行、图表审核和最终发布状态区分开。

#### Scenario: Live repair request is visible

- **WHEN** 活跃运行收到 `measurement_repair_required` 事件
- **THEN** 客户端在该运行的实时时间线中显示“需要定向重测”或等价的简体中文状态
- **AND** 事件保留其 run、panel、attempt 和下一动作等受限关联信息
- **AND** 客户端不把该事件显示为测量已经通过

#### Scenario: Rejected or exhausted repair is visible

- **WHEN** 活跃运行收到 `measurement_repair_rejected` 或 `measurement_repair_exhausted` 事件
- **THEN** 客户端显示对应的拒绝或预算耗尽状态和受限原因
- **AND** 时间线仍保留此前的测量和修复请求事件
- **AND** 客户端不把该运行或候选标记为已发布

#### Scenario: Repair history survives reload and reconnect

- **WHEN** 客户端在修复事件之间刷新页面、切换会话或断开后按 sequence 恢复运行历史
- **THEN** 已持久化的修复事件按原顺序显示且每个事件最多出现一次
- **AND** 后续事件不会覆盖或重排已经显示的修复状态
- **AND** 历史缺口仍使用现有的明确不完整状态提示

#### Scenario: Unknown repair-related event remains inspectable

- **WHEN** 客户端收到尚未加入中文标签目录的修复相关事件
- **THEN** 客户端使用安全的原始事件类型作为回退文本并保留事件
- **AND** 不因无法本地化而丢弃、误分类或伪造成功状态
