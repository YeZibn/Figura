# Agent：Run 决策与编排

> [返回总览](../figura-implementation-overview.md)。本篇只描述 Agent 的编排责任；Provider 与 Tool 的完整字段分别见[Provider](provider.md)和[Tool](tools.md)，持久执行事实见[Run Runtime](runtime.md)，网页调用和公开投影见[Web 边界](web-boundary.md)。

## 1. 职责与边界

`AgentExecutor` 从当前 `RunState.checkpoint.next_action` 选择一步动作；`AgentRequestBuilder` 调用 Session Memory 投影，将同 Session 较早终态 Run 和当前 Run 的已提交前缀组装为完整 Provider 请求。Agent 协调 Provider、Tool、Runtime 和 Memory 投影，但不拥有它们的事实或另存一份历史。当前 Agent 执行本身是同步、非流式文本/图像 ReAct；Web Gateway 通过有界 `RunDispatcher` 异步调用 `execute(session_id, run_id)`，HTTP handler 不运行模型请求。Agent 没有独立持久模型。

```mermaid
flowchart LR
    Gateway[Web Gateway / RunDispatcher] -->|异步 execute(session_id, run_id)| Agent[AgentExecutor]
    State[Runtime: RunState + Checkpoint] --> Agent[AgentExecutor]
    Agent -->|读取较早的终态 RunState| State
    Agent --> Build[AgentRequestBuilder]
    Build --> Memory[Session Memory Projection]
    Memory -->|所有历史和当前已提交消息| Build
    Build -->|解析当前及历史附件 ID| Attach[Attachment Service]
    Build -->|ProviderRequest| Provider[Provider Boundary]
    Provider -->|ProviderResponse / Failure| Agent
    Agent -->|ToolInvocation| Tool[Tool Runtime]
    Tool -->|ToolExecutionResult| Agent
    Agent -->|提交事实和推进| State
```

## 2. 内部流转

1. **读取动作**：只按 checkpoint 的 `action_kind` 推进 model、provider_attempt、tool_execution、tool_attempt 或 final。终态 Run 原样返回；无法取得 Run 锁时读取当前状态。
2. **读取 Session 历史**：到达 model action 后，Agent 经 RunCoordinator/Store 读取目标 Run 之前的所有 RunState。Runtime 返回同一 SQLite 快照内按 ordinal 连续排列的先前 Run；先前 Run 未终结或历史事实不完整时不返回可 dispatch 的请求。
3. **投影并组装请求**：Session Memory 从较早 Run 的持久事实构建 `SessionHistory`，再投影当前 Run 的输入和已提交前缀。AgentRequestBuilder 按 Session 解析当前和历史附件，保持每条 user 消息的文本先于原序图片，并附加固定系统指令和当前 Registry 工具投影。完整请求使用现有 Provider 校验器；不裁剪、不总结，超限或无法解析时当前 Run 在 attempt claim 前失败。
4. **模型动作**：请求完整且通过校验后，Agent 创建 Provider client，在锁内先由 Runtime claim Provider attempt，再调用 ProviderClient 一次。响应交给 Runtime 提交；明确失败与未知结果分别处理，不自动重发已启动请求。
5. **工具动作**：模型提出的工具调用按原顺序交给 DurableToolExecutor；它通过 ToolRuntime 执行并向 Runtime 追加尝试和结果事实。完整批次提交后 Agent 才继续模型动作；未解决的工具尝试不会自动 replay。
6. **终结**：只有非空文本的 `stop` 响应成为最终答案；无效响应、预算耗尽或确定性失败进入失败终态。每 Run 最多 8 次 Provider attempt、32 个已启动逻辑工具调用。

## 3. 跨领域内容合同

| 输入或输出 | 合同 owner | Agent 的使用方式 |
|---|---|---|
| `RunState`、`ExecutionCheckpoint`、`RunInput` | [Run Runtime](runtime.md#4-完整模型字段) | 读取已提交事实和下一动作，不另建持久副本 |
| `SessionHistory`、`UserMessage`、`AssistantMessage`、`ToolMessage`、`MemoryToolCall` | [Session Memory](session-memory.md#4-完整模型字段) | 消费从同 Session Run 事实重建的完整历史；Message 模型只在请求期间存在 |
| `AttachmentMetadata`、图像解析 | [附件](attachments.md#3-完整模型字段) | 按 Session 和有序 ID 取得调用期图片 |
| `ProviderRequest`、`ProviderResponse` | [Provider](provider.md#4-完整模型字段) | 组装请求、消费规范化结果；字段合同由 Provider 边界定义 |
| `ToolDefinition`、`ToolInvocation`、`ToolExecutionResult` | [Tool](tools.md#4-完整模型字段) | 投影可用工具、提交调用、消费结果 |

当前 `src/figura/agent/` 没有 Agent 自有 dataclass，因而本篇没有为编排过程虚构字段表；网页创建 Run 后由 Gateway Dispatcher 调度，但 Session、Run 生命周期和恢复事实仍归 Runtime。Gateway 组合目前注册空 ToolRegistry，所以网页入口没有生产图表工具。未来若出现独立 Agent 领域值，应先按[维护 skill](../../.codex/skills/figura-implementation-overview/SKILL.md)的归属规则判断。

## 4. 不变量、状态与依据

请求必须从同一 Session 的已提交 Run 事实重建；先前 Run 必须全部终态，且 Session Memory 投影不持久化、不裁剪。图片字节只存在于调用期 Provider 消息；请求的图片、文本和 Schema 等全部 Provider 限制在 attempt claim 前验证。Provider 和工具的不确定外部效果不会因读取或普通执行循环而自动重试。Gateway 入口目前只连接持久执行、附件和 Provider 能力，没有来源/证据或生产图表工具。代码：[AgentExecutor](../../src/figura/agent/executor.py)、[AgentRequestBuilder](../../src/figura/agent/request.py)、[Run Dispatcher](../../src/figura/gateway/dispatcher.py)；主规格：[Agent ReAct](../../openspec/figura/openspec/specs/agent-react-execution/spec.md)、[Session Memory](../../openspec/figura/openspec/specs/session-memory/spec.md)、[Web Gateway](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md)。
