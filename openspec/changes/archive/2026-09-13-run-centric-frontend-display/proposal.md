## Why

当前前端把消息、执行轨迹和生成图表分别渲染，用户难以判断一次请求对应的完整处理过程和最终产物。初步完成 Run 级展示后发现，Gateway Run 与 Agent Memory Run 使用了两个不同的 ID，导致前端无法关联提问和回答，最终把它们追加到 Run 之后；本变更需要同时修正 Run 身份链路和前端展示。

## What Changes

- 以一次 Agent Run 为前端展示单位，固定组织用户请求、执行过程和最终结果。
- 让 Gateway 创建的 `runId` 成为一次运行的唯一身份，并传递给 Agent Runtime 和 Agent Memory，避免同一运行生成第二个 ID。
- 使用统一的 `runId` 关联用户消息、助手回答、执行事件、附件和生成产物。
- 将生成图表从执行轨迹的普通时间线项移动到最终结果区域，同时在轨迹中保留生成事件提示。
- 保留执行过程的展开/收起能力，并在运行完成、刷新或历史恢复后维持同一 Run 结构。
- 对无法关联到 Run 的历史消息保留兼容展示，避免旧数据消失；新产生的数据不得因身份不一致进入孤立消息区域。
- 增加 Gateway、Agent Runtime、Memory 与前端之间的 Run 身份集成测试。

## Capabilities

### New Capabilities

无。本变更整理并固化已有前端行为，不引入独立的新领域能力。

### Modified Capabilities

- `desktop-client`: 调整会话消息区域的 Run 级组织、最终结果优先级、统一身份关联和历史兼容展示要求。
- `execution-trace`: 明确一次运行必须使用同一个规范 Run 身份关联执行历史、消息和产物，以及执行轨迹与最终回答、生成图表之间的边界。

## Impact

- 前端展示逻辑：`frontend/src/App.tsx`。
- Mock 客户端中的 Run 消息 ID 和演示数据：`frontend/src/api/mockClient.ts`。
- Run 容器、执行过程和最终结果区域样式：`frontend/src/styles/global.css`。
- Gateway Run 生命周期与历史投影：`src/chartagent/gateway/runs.py`、`src/chartagent/gateway/service.py`、`src/chartagent/gateway/projection.py`。
- Agent Runtime、Agent Memory 的 Run 创建与关联：`src/chartagent/runtime.py`、`src/chartagent/agent.py`、`src/chartagent/memory/sqlite.py`。
- 集成测试：`tests/test_gateway.py` 及相关前端验证脚本。
- OpenSpec 主规格将通过本 change 的 delta spec 同步更新；不涉及新的 Tauri 功能。
