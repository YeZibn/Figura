# Memory：当前跨 Run 对话投影

> 更新日期：2026-10-02。[返回系统总览](../figura-implementation-overview.md)。依据：当前 `src/figura/memory/` 与 `src/figura/agent/` 工作树实现，以及 [Session Memory 主规格](../../openspec/figura/openspec/specs/session-memory/spec.md)。本文描述已实现的临时投影，不代表独立的长期记忆存储。

## 1. 职责与边界

Session Memory 将同一 Session 中目标 Run 之前的终态 Run 投影为有序对话消息，供后续 Provider 请求使用。它读取 Runtime 持久化的 Run 事实，不拥有这些事实，也不创建消息表、历史副本、摘要、裁剪预算或跨 Session 用户记忆。每次模型动作都从提交事实重新构建完整上下文；超过 Provider 硬限制时，由 Agent 在领取 Provider attempt 前失败。

权威内容仍属于 [Run Runtime](runtime.md)：用户输入来自 `RunInput`，助手内容来自 `ModelResponseFact`，工具调用与结果来自 `ToolCallFact`、`ToolAttemptStartedFact`、`ToolResultFact`。Memory 对象只是一组不可变、调用期投影；附件只保留 ID。Agent 的附件、Panel、OCR、测量、ChartFigure 与 ChartRender 资源目录及图像加载规则由[Agent](agent.md#4-runexecutionstate-资源合同与完整字段)定义，附件与 Panel 的持久模型由[Sources](sources.md)定义；历史附件不会因为进入 Memory 而自动解析为图像字节。

## 2. 模型关系与组件边界

```mermaid
flowchart LR
    Agent[AgentExecutor / AgentRequestBuilder] -->|read_prior_run_states| Coordinator[RunCoordinator]
    Coordinator --> Store[FiguraRunStore]
    Store --> Repo[RunRepository]
    Repo -->|SQLite 一致读快照| Facts[(同一 Session 较早 Run 事实)]
    Facts -->|有序 prior RunState 聚合| Repo
    Repo --> Store --> Coordinator -->|先前 RunState tuple| Agent
    Agent -->|目标 Run 与先前 RunState| Memory[Session Memory 投影]
    Memory -->|SessionHistory 与角色消息| Agent
    Agent -->|Run 输入、已提交工具事实和 Sources 元数据| State[RunExecutionState]
    State -->|六类类型化资源与精简清单| Agent
    Agent -->|最新工具批次的图像资源引用| Reader[RunExecutionImageReader]
    Reader -->|授权解析 Attachment / Panel / ChartRender| Sources[Sources services]
    Reader -->|原图、OCR/测量标注图或 ChartRender PNG| Agent
    Agent -->|完整且通过限制校验的 ProviderRequest| Provider[Provider Boundary]
```

Runtime 在一个 SQLite 读快照内读取目标 Run 的所有较早 ordinal，并验证目标归属、ordinal 连续、先前 Run 均已终结和历史附件归属。Memory 再从这些 RunState 投影消息。`SessionHistory.messages` 只包含目标 Run 之前的消息；当前 Run 的输入和已提交进度由 `project_run_messages` 单独投影，再由 AgentRequestBuilder 拼接。

## 3. 内部流转与失败边界

1. **读取稳定前缀**：Agent 在模型动作中调用 `RunCoordinator.read_prior_run_states(session_id, run_id)`。RunRepository 对目标 Run 做同 Session 校验，在单个 SQLite 读事务中加载所有较小 ordinal 的 RunState；缺失、ordinal 缺口、跨 Session 或先前仍为 running 时不返回部分历史。
2. **投影旧 Run**：`project_session_history` 要求先前 Run ordinal 恰为 `1..target_run.ordinal-1`，且 Session 相同、全部终态。它按 Run ordinal 顺序调用 `project_run_messages`。每个 Run 先生成一条用户消息，再按 ExecutionRecord 顺序生成助手消息；工具调用保留 provider 顺序，且每个工具结果与其原 call ID 配对。
3. **投影当前 Run**：AgentRequestBuilder 同样对当前 Run 已提交前缀调用 `project_run_messages`，将其接在 SessionHistory 后面。最终回答记录只引用已有助手响应，不再产生重复消息。未完成工具批次、无匹配调用的结果、重复/错误来源引用或不受支持的事实会使整次投影失败；不会省略问题消息后继续。
4. **恢复图像和调用期字段**：每条用户消息保留原文本和有序 attachment ID。AgentRequestBuilder 把消息文本与附件 ID 保留在完整对话中；另外从 RunExecutionState 加入完整的类型化资源清单。当前 Run 最新已提交工具批次中成功的 `load_image`、`extract_text`、四种测量和 `render_chart_figure` 结果，按对应资源引用交给 `RunExecutionImageReader`；Reader 解析原图、内存重建 OCR/测量标注图，或读取校验后的 ChartRender PNG，再按工具调用顺序加入紧接着的 Provider 请求。ChartFigure 资源本身不会隐式渲染，必须由模型显式调用渲染工具。历史 Run 图像不会自动重放。已配对完整结果的旧 registry 工具调用允许作为惰性历史进入请求，不重新执行；未解决调用或不完整批次仍拒绝。Provider continuation 不属于 Memory 投影；Agent 从较早 Run 与当前 Run 的私有事实建立 `(run_id, response_record_id)` 索引，只将 provider 相同、格式版本受支持的值附加到精确对应的 assistant。不同 provider 的续接不附加；所选 Provider 要求但缺少兼容值时，prepare 本地失败，不伪造续接或删掉历史。
5. **先准备再领取 attempt**：AgentRequestBuilder 仅组装完整 ProviderRequest；Agent 创建 Provider client 后调用 `prepare` 检查消息、指令、工具、图片及文本/Schema 字节限制，并完成 Provider 专属 payload 准备。通过后才在锁内复查 checkpoint、claim attempt 并 dispatch 已准备请求。Memory 不删旧 Run、不删消息、不总结、不做预算。历史/资源构建失败时不创建 client；超限或缺少必需 continuation 等 prepare 失败时 client 已创建，但不领取 attempt、不发送请求，并由既有 Run 终态保留安全说明。详见[Provider 流转](provider.md#2-内部流转)。

旧 Run 的执行事实不因后续 Run 重写。新消息只有在所属 Run 中提交后，才会在之后的模型动作中被重建；Session Memory 自身没有独立写入、更新或恢复流程。

## 4. 完整模型字段

以下模型均为 `frozen=True` dataclass，按请求临时创建，不序列化到 SQLite，也不通过 Gateway/API 独立公开。Gateway 的 Session 详情另有面向用户的只读对话投影，仅包含持久用户输入和已接受最终答案；它不是本页完整 Agent 上下文，也不公开工具消息、模型中间响应或 continuation，字段见[Web 边界](web.md#4-web-dto-字段)。写入者一栏指内存投影函数；权威位置一栏指字段的持久来源，Memory 对象本身不拥有持久权威。任何投影字段变更都需回到其 Run 源事实，而不是原地修订 Memory 对象。

### MemoryToolCall

工具调用的调用期副本，嵌套在 `AssistantMessage.tool_calls`。投影函数为 `project_run_messages`；AgentRequestBuilder 将其映射为 Provider 的 `ProviderToolCall`。

| 完整字段路径 | 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威位置 | 读取者 → 公开/修订规则 |
|---|---|---|---|---|---|
| `MemoryToolCall.call_id` | `str` | 必填 | 不透明调用 ID；须与其工具结果使用同一 ID | `project_run_messages` → 对应 Run 的 `ToolCallFact.call_id` | AgentRequestBuilder → 仅随 Provider 请求发送；投影不可变，改动须由源事实重建 |
| `MemoryToolCall.tool_name` | `str` | 必填 | 被调用工具的注册名称 | `project_run_messages` → `ToolCallFact.tool_name` | AgentRequestBuilder → Provider 工具调用名；投影不可变，改动须由源事实重建 |
| `MemoryToolCall.arguments_json` | `str` | 必填；`repr=False` | 已提交调用的 JSON 参数文本；不在 dataclass repr 中显示 | `project_run_messages` → `ToolCallFact.arguments_json` | AgentRequestBuilder → Provider 调用参数；不独立公开或修订 |
| `MemoryToolCall.position` | `int` | 必填 | 响应内从 0 开始的调用顺序；投影校验位置连续 | `project_run_messages` → `ToolCallFact.position` | AgentRequestBuilder → Provider 调用顺序；投影不可变，改动须由源事实重建 |
| `MemoryToolCall.registry_version` | `str` | 必填 | 产生该调用的工具 Registry 版本 | `project_run_messages` → `ToolCallFact.registry_version` | AgentRequestBuilder → 已有完整结果配对的旧版本调用可作为历史重放，不重新执行；未解决的旧版本调用拒绝 |

### UserMessage

一个 Run 的不可变用户输入投影。Runtime 的 `Run` 行提供身份与 ordinal，input `ExecutionRecord.payload` 中的 `RunInput` 提供文本和附件 ID。

| 完整字段路径 | 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威位置 | 读取者 → 公开/修订规则 |
|---|---|---|---|---|---|
| `UserMessage.run_id` | `str` | 必填 | 输入所属 Run 的不透明 ID | `project_run_messages` → `Run.run_id` | AgentRequestBuilder → 内部请求来源；不独立公开或修订 |
| `UserMessage.run_ordinal` | `int` | 必填 | Run 在 Session 内从 1 开始的顺序 | `project_run_messages` → `Run.ordinal` | `project_session_history` / AgentRequestBuilder → 历史排序与来源；不独立公开或修订 |
| `UserMessage.source_record_id` | `str` | 必填 | 本用户输入事实的 ExecutionRecord ID | `project_run_messages` → `ExecutionRecord.record_id`（kind 为 input） | AgentRequestBuilder → 内部来源追踪；不独立公开或修订 |
| `UserMessage.text` | `str` | 必填；`repr=False` | 用户提交文本原文 | `project_run_messages` → `RunInput.text` | AgentRequestBuilder → Provider user 内容；不出现在 repr/API，需修改时创建新的 Run 输入 |
| `UserMessage.attachment_ids` | `tuple[str, ...]` | 默认 `()` | 有序附件 ID；这里只存引用，不含图像字节 | `project_run_messages` → `RunInput.attachment_ids` | AgentRequestBuilder → 作为对话文本引用并参与 Panels 清单；只有显式 `load_image` 后才解析图像 |

### AssistantMessage

一个已提交模型响应的角色投影。内容来自 `ModelResponseFact`；工具调用按 `MemoryToolCall` 嵌套。

| 完整字段路径 | 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威位置 | 读取者 → 公开/修订规则 |
|---|---|---|---|---|---|
| `AssistantMessage.run_id` | `str` | 必填 | 响应所属 Run 的不透明 ID | `project_run_messages` → `Run.run_id` | AgentRequestBuilder → 内部来源和 continuation 边界；不独立公开或修订 |
| `AssistantMessage.run_ordinal` | `int` | 必填 | Run 在 Session 内从 1 开始的顺序 | `project_run_messages` → `Run.ordinal` | `project_session_history` / AgentRequestBuilder → 历史顺序；不独立公开或修订 |
| `AssistantMessage.source_record_id` | `str` | 必填 | 来源模型响应 ExecutionRecord ID | `project_run_messages` → `ExecutionRecord.record_id`（kind 为 model_response） | AgentRequestBuilder → 与 run_id 联合定位源响应私有 continuation，兼容时附加到该消息；不独立公开或修订 |
| `AssistantMessage.content` | `str` | 必填；`repr=False` | 已提交的助手文本；不在 dataclass repr 中显示 | `project_run_messages` → `ModelResponseFact.assistant_content` | AgentRequestBuilder → Provider assistant 消息；不经 Memory API 公开或修订 |
| `AssistantMessage.tool_calls` | `tuple[MemoryToolCall, ...]` | 默认 `()` | 当前响应的完整工具调用，按 provider position 排序；无调用时为空 | `project_run_messages` → 与该响应关联的有序 `ToolCallFact` | AgentRequestBuilder → Provider assistant 工具调用；不独立公开或修订 |

### ToolMessage

一个已提交工具结果的模型可读观察。`content` 是从结果事实生成的有界规范 JSON，不包含 handler 异常堆栈或本机执行细节。

| 完整字段路径 | 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威位置 | 读取者 → 公开/修订规则 |
|---|---|---|---|---|---|
| `ToolMessage.run_id` | `str` | 必填 | 工具结果所属 Run 的不透明 ID | `project_run_messages` → `Run.run_id` | AgentRequestBuilder → 内部来源；不独立公开或修订 |
| `ToolMessage.run_ordinal` | `int` | 必填 | Run 在 Session 内从 1 开始的顺序 | `project_run_messages` → `Run.ordinal` | `project_session_history` / AgentRequestBuilder → 历史顺序；不独立公开或修订 |
| `ToolMessage.source_tool_sequence` | `int` | 必填 | 来源结果在 Run 工具事实流中的序号 | `project_run_messages` → `ToolExecutionFact.tool_sequence`（kind 为 tool_result） | AgentRequestBuilder → 内部事实来源；不独立公开或修订 |
| `ToolMessage.tool_call_id` | `str` | 必填 | 对应助手工具调用的 opaque call ID | `project_run_messages` → 匹配的 `ToolCallFact.call_id` | AgentRequestBuilder → Provider tool 消息关联键；不独立公开或修订 |
| `ToolMessage.content` | `str` | 必填；`repr=False` | 通过 `tool_observation` 编码的成功结果或安全失败对象 | `project_run_messages` → 匹配的 `ToolResultFact` | AgentRequestBuilder → Provider tool 观察；不出现在 repr/API，不独立修订 |

### SessionHistory

目标 Run 之前的同 Session 完整历史容器。该投影不含目标 Run 自身的消息；当前 Run 消息由 AgentRequestBuilder 另行追加。

| 完整字段路径 | 类型 | 必填/默认 | 含义与约束 | 写入者 → 权威位置 | 读取者 → 公开/修订规则 |
|---|---|---|---|---|---|
| `SessionHistory.session_id` | `str` | 必填 | 目标 Run 所属 Session 的不透明 ID | `project_session_history` → `target_run.session_id` | AgentRequestBuilder → 附件解析与范围校验；仅内部使用，不独立修订 |
| `SessionHistory.target_run_id` | `str` | 必填 | 当前请求所属的目标 Run ID | `project_session_history` → `target_run.run_id` | AgentRequestBuilder → 确认历史边界；仅内部使用，不独立修订 |
| `SessionHistory.target_run_ordinal` | `int` | 必填 | 目标 Run 在 Session 内的 ordinal | `project_session_history` → `target_run.ordinal` | AgentRequestBuilder → 历史边界和序号校验；仅内部使用，不独立修订 |
| `SessionHistory.messages` | `tuple[MemoryMessage, ...]` | 默认 `()` | 所有 lower-ordinal Run 的 UserMessage、AssistantMessage、ToolMessage；空 tuple 表示首个 Run | `project_session_history` → 每个更早 Run 的 input/response/tool facts | AgentRequestBuilder → 完整 Provider 对话前缀；内部不可变，不独立公开、裁剪或修订 |

`MemoryMessage` 是类型别名 `UserMessage | AssistantMessage | ToolMessage`，自身没有 dataclass 字段。模型定义位于 [`memory/models.py`](../../src/figura/memory/models.py)，投影与校验位于 [`memory/projector.py`](../../src/figura/memory/projector.py)。Runtime 源模型和各来源字段的权威表见[运行时字段合同](runtime.md#4-完整模型字段)。

## 5. 不变量、状态与依据

- Memory 仅包含同一 Session 中目标 Run ordinal 之前的终态 Run；时间戳和数据库行顺序不决定对话顺序。
- 任一历史 Run 无效时整份历史不 dispatch；不通过跳过坏 Run、缺失附件或未完成工具调用来拼装部分对话。
- 附件 ID 仍由所属 Session 校验，图像字节只在对应的成功 `load_image` 后进入下一次 Provider 请求；Memory 对象中无附件字节和本机路径。
- Provider continuation 与源 Run/响应绑定；Memory 投影不含该 payload。Agent 在 Provider 请求边界按 `(run_id, source_record_id)` 私下读取兼容续接，仅附加到对应 assistant；不复制到目标 Run，不混入助手正文、提示资产、工具结果或公开 DTO。
- 完整历史超过 Provider 硬限制时当前 Run 在 Provider attempt claim 前失败；持久 Run 事实与 Memory 投影均不裁剪。
- Run 创建由 Runtime 保证同一 Session 同时最多一个 running Run；幂等重放先于 active Run 检查。完整创建与读取语义见[运行时流程](runtime.md#2-内部流转)。
- Session 整体删除后，源事实与私有续接一并删除，Memory 不另留副本。删除事务和文件恢复见[Web 会话删除](web.md#会话删除与恢复)。

**规格差异：**Session Memory 主规格已允许在 Provider 请求边界重放兼容源续接；Agent ReAct 主规格的旧段落与 `Do not carry continuation across Runs` 场景仍禁止这种重放，与当前代码及 Session Memory 规格冲突。本篇按当前实现说明，并显式保留此差异；本次文档维护没有修改主规格。

代码：[Session Memory 模型](../../src/figura/memory/models.py)、[投影器](../../src/figura/memory/projector.py)、[Agent 请求构建](../../src/figura/agent/request.py)、[历史 Run 快照读取](../../src/figura/runtime/persistence/snapshots.py)。规格：[Session Memory](../../openspec/figura/openspec/specs/session-memory/spec.md)、[Agent ReAct](../../openspec/figura/openspec/specs/agent-react-execution/spec.md)、[Run 核心](../../openspec/figura/openspec/specs/run-execution-core/spec.md)。
