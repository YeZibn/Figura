# Agent：Run 决策与编排

> [返回总览](../figura-implementation-overview.md)。本篇只描述 Agent 的编排责任；Provider 与 Tool 的完整字段分别见[Provider](provider.md)和[Tool](tools.md)，图像清单和 Panel 生命周期见[Panels](panels.md)，持久执行事实见[Run Runtime](runtime.md)，网页调用和公开投影见[Web 边界](web.md)。

## 1. 职责与边界

`AgentExecutor` 从当前 `RunState.checkpoint.next_action` 选择一步动作；`AgentRequestBuilder` 调用 Session Memory 投影，将同 Session 较早终态 Run 和当前 Run 的已提交前缀组装为完整 Provider 请求，并从 `RunExecutionState` 添加附件/Panel 清单。历史消息中的附件 ID 保留为文本引用，历史附件不会自动解析成图像。只有最新已提交工具批次中成功的 `load_image` 结果会在本次请求里解析为图像块。Agent 协调 Provider、Tool、Runtime、Memory 和 Panels 投影，但不拥有它们的事实或另存一份历史。当前 Agent 执行本身是同步、非流式文本/图像 ReAct；Web Gateway 通过有界 `RunDispatcher` 异步调用 `execute(session_id, run_id)`，HTTP handler 不运行模型请求。Agent 没有独立持久模型。

```mermaid
flowchart LR
    Gateway[Web Gateway / RunDispatcher] -->|异步 execute(session_id, run_id)| Agent[AgentExecutor]
    State[Runtime: RunState + Checkpoint] --> Agent[AgentExecutor]
    Agent -->|读取较早的终态 RunState| State
    Agent --> Build[AgentRequestBuilder]
    Build --> Memory[Session Memory Projection]
    Memory -->|所有历史和当前已提交消息| Build
    Build -->|RunExecutionState 清单| Panels[Panels projection]
    Build -->|只解析最近成功 load_image 的附件| Attach[Attachment Service]
    Build -->|只解析最近成功 load_image 的 Panel| Panels
    Build -->|ProviderRequest| Provider[Provider Boundary]
    Provider -->|ProviderResponse / Failure| Agent
    Agent -->|ToolInvocation| Tool[Tool Runtime]
    Tool -->|ToolExecutionResult| Agent
    Agent -->|提交事实和推进| State
```

## 2. 内部流转

1. **读取动作**：只按 checkpoint 的 `action_kind` 推进 model、provider_attempt、tool_execution、tool_attempt 或 final。终态 Run 原样返回；无法取得 Run 锁时读取当前状态。
2. **读取 Session 历史**：到达 model action 后，Agent 经 RunCoordinator/Store 读取目标 Run 之前的所有 RunState。Runtime 返回同一 SQLite 快照内按 ordinal 连续排列的先前 Run；先前 Run 未终结或历史事实不完整时不返回可 dispatch 的请求。
3. **投影并组装请求**：Session Memory 从较早 Run 的持久事实构建 `SessionHistory`，再投影当前 Run 的输入和已提交前缀。RunExecutionStateService 根据较早终态 Run 和目标 Run 的 RunInput，按引用顺序去重附件 ID、补齐安全文件名，并只包含存在成功分割结果事实的 Panel。AgentRequestBuilder 将清单附加为临时 user 消息；再读取最新已提交工具批次中成功 `load_image` 的资源，按工具调用顺序去重并生成一条 user 图像消息。它不会自动读取所有历史图像。固定系统指令和当前 Registry 工具投影随请求发送。完整请求使用现有 Provider 校验器；不裁剪、不总结，超限或无法解析时当前 Run 在 attempt claim 前失败。
4. **模型动作**：请求完整且通过校验后，Agent 创建 Provider client，在锁内先由 Runtime claim Provider attempt，再调用 ProviderClient 一次。响应交给 Runtime 提交；明确失败与未知结果分别处理，不自动重发已启动请求。
5. **工具动作**：模型提出的工具调用按原顺序交给 DurableToolExecutor；它通过 ToolRuntime 执行并向 Runtime 追加尝试和结果事实。完整批次提交后 Agent 才继续模型动作；未解决的工具尝试不会自动 replay。
6. **终结**：只有非空文本的 `stop` 响应成为最终答案；无效响应、预算耗尽或确定性失败进入失败终态。每 Run 最多 8 次 Provider attempt、32 个已启动逻辑工具调用。

## 3. 跨领域内容合同

| 输入或输出 | 合同 owner | Agent 的使用方式 |
|---|---|---|
| `RunState`、`ExecutionCheckpoint`、`RunInput` | [Run Runtime](runtime.md#4-完整模型字段) | 读取已提交事实和下一动作，不另建持久副本 |
| `SessionHistory`、`UserMessage`、`AssistantMessage`、`ToolMessage`、`MemoryToolCall` | [Session Memory](memory.md#4-完整模型字段) | 消费从同 Session Run 事实重建的完整历史；Message 模型只在请求期间存在 |
| `AttachmentMetadata`、图像解析 | [附件](sources.md#3-完整模型字段) | Tool 和请求组装按 Session 读取；仅显式加载的图片进入当前请求 |
| `RunExecutionState`、`AvailableAttachment`、`PanelRecord` | [Panels](panels.md#3-完整字段合同) | 投影可用图像清单；仅把最新已提交工具批次明确加载的图片放进本次 Provider 请求 |
| `ProviderRequest`、`ProviderResponse` | [Provider](provider.md#4-完整模型字段) | 组装请求、消费规范化结果；字段合同由 Provider 边界定义 |
| `ToolDefinition`、`ToolInvocation`、`ToolExecutionResult` | [Tool](tools.md#4-完整模型字段) | 投影可用工具、提交调用、消费结果 |

当前 `src/figura/agent/` 没有 Agent 自有 dataclass，因而本篇没有为编排过程虚构字段表；网页创建 Run 后由 Gateway Dispatcher 调度，但 Session、Run 生命周期和恢复事实仍归 Runtime。Gateway 当前注册 `load_image` 与 `decompose_chart_image` 两个图像工具；完整输入、结果和限制见[Tool 图像工具合同](tools.md#6-图像工具合同)。

## 4. 不变量、状态与依据

请求必须从同一 Session 的已提交 Run 事实重建；先前 Run 必须全部终态，且 Session Memory 投影不持久化、不裁剪。文本清单会列出完整的当前 Session 可用附件与已提交 Panel；原图像字节只在对应 `load_image` 成功并提交后进入下一次请求，且不会从上一 Run 或更早工具批次自动继承。请求的图片、文本和 Schema 等全部 Provider 限制在 attempt claim 前验证。Provider 和工具的不确定外部效果不会因读取或普通执行循环而自动重试；`decompose_chart_image` 通过幂等本地写确保恢复时 Panel 身份稳定。代码：[AgentExecutor](../../src/figura/agent/executor.py)、[AgentRequestBuilder](../../src/figura/agent/request.py)、[Run Dispatcher](../../src/figura/gateway/dispatcher.py)；Panel 投影、文件与 RunExecutionState 见[Panels](panels.md)；主规格：[Agent ReAct](../../openspec/figura/openspec/specs/agent-react-execution/spec.md)、[Session Memory](../../openspec/figura/openspec/specs/session-memory/spec.md)、[Web Gateway](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md)。
