## Why

Gateway 当前将图表暂存、验证记录、图表发布、执行结果读取、暂存结果读取和执行记录提交拆成 7 个独立 callback，分别穿过 runtime factory、Agent 和验证流程。这个注入面容易漏接或产生不一致的运行时组合；现在执行记录与恢复边界已稳定，适合把这些依赖收成一个明确的 durable execution 接口，并删除旧 callback 入口。

## What Changes

- 新增类型化的 `DurableExecutionPort`，统一承载图表暂存、验证持久化、图表发布、已提交执行结果读取、暂存图表按引用读取、暂存工作按 work key 读取，以及执行步骤提交。
- Gateway 为每个 Run 构造一个绑定当前 Run、session、history store 的 port，并将同一个对象传入 runtime、Agent 编排器和生成图验证流程。
- **BREAKING（内部 Python 接口）** 一次性移除 7 个 callback 参数、逐层转发字段和基于旧参数的兼容入口；同步迁移所有生产调用点与测试，不保留别名、适配器或双轨实现。
- 保持当前 durable execution 行为：执行记录与 cursor 的原子提交、按稳定 work key 复用结果、恢复引用校验、暂存图校验及发布失败关闭。
- Gateway 始终要求完整的 `DurableExecutionPort`。不使用 Gateway 持久化的本地 Agent 运行可以不提供该 port，继续按现有非持久化模式运行。

## Capabilities

### New Capabilities

无。本 change 不引入新的系统能力。

### Modified Capabilities

无。本 change 只调整内部依赖注入和所有权，不改变可观察行为，因此使用 `skip_specs: true`。

## Impact

- 主要影响 `src/chartagent/gateway/service.py`、`src/chartagent/runtime/factory.py`、`src/chartagent/agent/loop.py`、`src/chartagent/agent/orchestrator.py`、`src/chartagent/agent/turn.py`、`src/chartagent/agent/tool_execution.py` 和 `src/chartagent/verification/flow.py`。
- 更新 Agent、Gateway、验证和执行记录测试中的注入方式，测试完整 port 契约及恢复链路。
- 不改变 HTTP/SSE 协议、SQLite schema、提示词、图表验证策略或前端行为。
