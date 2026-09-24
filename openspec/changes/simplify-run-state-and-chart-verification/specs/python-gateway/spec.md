## REMOVED Requirements

### Requirement: Gateway preserves generated-chart review lifecycle integrations

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

### Requirement: Gateway exposes safe run recovery and explicit resume

**Reason**: 旧候选、门禁或完整恢复状态契约已由提交执行事实与单一图表验证替代。
**Migration**: 使用 durable-execution-record、generated-chart-verification 及本 capability 的新增要求。

## ADDED Requirements

### Requirement: Gateway exposes staged preview and verified artifact separately

Gateway SHALL 按 session、Run 和不透明引用授权提供暂存图预览及已发布图表资源。暂存图 SHALL 不可通过正式 artifact 下载接口获取；仅匹配的已提交验证结果可以发布正式 artifact。Gateway SHALL 返回有界、脱敏的图像元数据与诊断，并在持久化集成缺失时失败关闭。

#### Scenario: Failed staged image can be inspected
- **WHEN** 授权用户请求一个验证失败但仍在保留期内的暂存图
- **THEN** Gateway 可返回该预览和有界失败原因
- **AND** 正式 artifact 接口不返回它

#### Scenario: Missing persistence fails closed
- **WHEN** 图像或准确 ChartSpec 无法持久暂存
- **THEN** Gateway 返回明确存储错误
- **AND** 不调用发布或把结果显示成已验证

### Requirement: Gateway exposes derived resume eligibility and explicit child runs

Gateway SHALL 由终态、有效 checkpoint、授权引用和下一动作重放契约推导可恢复性及有界原因，不持久维护独立 RecoveryStatus 状态机。现有显式 resume 接口 SHALL 保留 idempotency key、session 授权、父子 Run 归因与父 Run 终态；仅断线重连仍按原 Run 的序号读取事件。

#### Scenario: Valid resume starts a child
- **WHEN** 用户显式恢复一个具有有效安全游标的终态 Run
- **THEN** Gateway 创建或幂等返回具有 resume 归因的新 Run
- **AND** 父 Run 状态和历史不变

#### Scenario: Invalid reference rejects resume
- **WHEN** checkpoint 引用已过期或属于其他 session
- **THEN** Gateway 返回稳定、安全的不可恢复原因
- **AND** 不启动 Agent 工作
