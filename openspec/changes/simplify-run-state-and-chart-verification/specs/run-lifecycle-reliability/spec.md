## REMOVED Requirements

### Requirement: Recovery blocking remains reserved for unknown outcomes

**Reason**: 旧状态或快照控制契约已由提交事实和单一验证链路替代。
**Migration**: 使用 durable-execution-record 或 generated-chart-verification 的对应要求。

## ADDED Requirements

### Requirement: Explicit recovery distinguishes replayable requests from unknown external effects

运行仍 SHALL 只使用 running、completed、failed、interrupted 四态。恢复资格 SHALL 从有效 checkpoint、授权引用和下一动作的重放契约推导；未提交模型/VLM 请求可以在显式 resume 后重新请求，只有不可核对的外部副作用结果不明时才阻止自动继续。断线重连 SHALL 保持原 Run，resume SHALL 产生可归因子 Run。

#### Scenario: Provider times out before local commit
- **WHEN** 模型请求超时且没有已提交响应
- **THEN** 原 Run 保留明确失败或中断原因
- **AND** 用户显式 resume 后系统可以重新请求，同时说明可能重复费用

#### Scenario: Reconnect does not reissue a model request
- **WHEN** 仅 SSE 连接断开
- **THEN** 客户端按原 Run 的事件序号重连
- **AND** 不创建子 Run 或重复模型调用
