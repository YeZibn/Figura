# Agent：Run 决策与编排

> [返回总览](../figura-implementation-overview.md)。本篇说明 Agent 编排及其调用期派生运行态；Provider 与 Tool 的完整字段分别见[Provider](provider.md)和[Tool](tools.md)，附件和 Panel 持久模型见[Sources](sources.md)，Run 执行事实见[Run Runtime](runtime.md)，网页调用和公开投影见[Web 边界](web.md)。

## 1. 职责与边界

`AgentExecutor` 从当前 `RunState.checkpoint.next_action` 选择一步动作；`AgentRequestBuilder` 调用 Session Memory 投影，将同 Session 较早终态 Run 和当前 Run 的已提交前缀组装为完整 Provider 请求，并消费 `RunExecutionState` 中的附件、Panel 与测量观察。`RunExecutionStateService` 读取 Runtime Run 事实和 Sources 资源元数据，从已提交的 `measure_bars`、`measure_lines`、`measure_scatter`、`measure_pie` 工具事实重建有授权来源的测量观察；独立 `extract_text` 结果仍是普通工具历史，不加入 `measurements`。清单和图像状态不持久化。历史消息中的附件 ID 保留为文本引用，历史附件不会自动解析成图像。最新已提交工具批次中成功的 `load_image` 原图，以及成功 `extract_text` 和四种测量调用对应的标注图，会在本次请求中按调用顺序加入；标注图由 Agent 请求组装器从授权源图像和已提交 JSON 临时重建。OCR 和测量 JSON 通过 Session Memory 的 ToolMessage 进入模型历史；`measurements` 投影供请求组装器核对测量来源并生成测量回看，不作为重复 JSON 提示注入。当前 Agent 执行本身是同步、非流式文本/图像 ReAct；Web Gateway 通过有界 `RunDispatcher` 异步调用 `execute(session_id, run_id)`，HTTP handler 不运行模型请求。Agent 没有独立的持久模型。

```mermaid
flowchart LR
    Gateway[Web Gateway / RunDispatcher] -->|异步 execute(session_id, run_id)| Agent[AgentExecutor]
    State[Runtime: RunState + Checkpoint] --> Agent[AgentExecutor]
    Agent -->|读取较早的终态 RunState| State
    Agent --> Build[AgentRequestBuilder]
    Build --> Memory[Session Memory Projection]
    Memory -->|所有历史和当前已提交消息| Build
    State -->|当前 / 较早 RunState 与已提交工具事实| ImageState[RunExecutionStateService]
    Sources[Sources: 附件元数据与 Panels] -->|资源元数据与授权读取| ImageState
    ImageState -->|附件、Panel 清单与测量观察| Build
    Build -->|只解析最新批次 load_image、OCR 与成功测量的来源| Sources
    Sources -->|原图和调用期 OCR / 测量标注图| Build
    Build -->|ProviderRequest| Provider[Provider Boundary]
    Provider -->|ProviderResponse / Failure| Agent
    Agent -->|extract_text / measure_* ToolInvocation| Tool[Tool Runtime]
    Tool -->|ToolExecutionResult| Agent
    Agent -->|提交事实和推进| State
```

## 2. 内部流转

1. **读取动作**：只按 checkpoint 的 `action_kind` 推进 model、provider_attempt、tool_execution、tool_attempt 或 final。终态 Run 原样返回；无法取得 Run 锁时读取当前状态。
2. **读取 Session 历史**：到达 model action 后，Agent 经 RunCoordinator/Store 读取目标 Run 之前的所有 RunState。Runtime 返回同一 SQLite 快照内按 ordinal 连续排列的先前 Run；先前 Run 未终结或历史事实不完整时不返回可 dispatch 的请求。
3. **投影并组装请求**：Session Memory 从较早 Run 的持久事实构建 `SessionHistory`，再投影当前 Run 的输入和已提交前缀。RunExecutionStateService 根据较早终态 Run 和目标 Run 的 RunInput，按引用顺序去重附件 ID、补齐安全文件名，并只包含存在成功分割结果事实的 Panel；它还从到目标 Run 为止的已提交工具事实构造有序 `MeasurementObservation`，仅保留来源属于该目标状态授权附件或 Panel 清单的四种测量工具结果。`extract_text` 仍由普通 ToolMessage 表达。AgentRequestBuilder 将图像清单附加为临时 user 消息；再按最新模型响应中的工具调用顺序处理成功 `load_image`、`extract_text` 和测量结果：原图来源去重；OCR 与每个测量调用逐一从授权来源图像和已提交 JSON 生成 PNG 标注图，并附带工具名与 call ID。历史 Run 的原图或早期批次的标注图不会重放。测量观察投影不重复注入 JSON，因为已提交工具结果已由 Session Memory 作为 ToolMessage 提供；投影用于校验测量来源并创建测量回看图。固定系统指令和当前 Registry 工具投影随请求发送。完整请求使用现有 Provider 校验器；不裁剪、不总结，图像无法解析、标注失败或 Provider 限额超出时当前 Run 在 attempt claim 前失败。
4. **模型动作**：请求完整且通过校验后，Agent 创建 Provider client，在锁内先由 Runtime claim Provider attempt，再调用 ProviderClient 一次。响应交给 Runtime 提交；明确失败与未知结果分别处理，不自动重发已启动请求。
5. **工具动作**：模型提出的工具调用按原顺序交给 DurableToolExecutor；它通过 ToolRuntime 执行并向 Runtime 追加尝试和结果事实。完整批次提交后 Agent 才继续模型动作；未解决的工具尝试不会自动 replay。
6. **终结**：只有非空文本的 `stop` 响应成为最终答案；无效响应、预算耗尽或确定性失败进入失败终态。每 Run 最多 8 次 Provider attempt、32 个已启动逻辑工具调用。

## 3. 跨领域内容合同

| 输入或输出 | 合同 owner | Agent 的使用方式 |
|---|---|---|
| `RunState`、`ExecutionCheckpoint`、`RunInput` | [Run Runtime](runtime.md#4-完整模型字段) | 读取已提交事实和下一动作，不另建持久副本 |
| `SessionHistory`、`UserMessage`、`AssistantMessage`、`ToolMessage`、`MemoryToolCall` | [Session Memory](memory.md#4-完整模型字段) | 消费从同 Session Run 事实重建的完整历史；Message 模型只在请求期间存在 |
| `AttachmentMetadata`、`PanelPoint`、`PanelRecord` | [Sources](sources.md#3-完整模型字段) | 读取 Session 资源；只有已提交分割结果关联的 Panel 才能进入清单 |
| `RunExecutionState`、`AvailableAttachment`、`MeasurementObservation` | [本篇第 4 节](#4-运行时状态字段) | 从 Runtime 与 Sources 事实重建图像清单和已提交测量观察；测量观察不新增持久副本，模型从 Session Memory 的 ToolMessage 读取结果 |
| `extract_text`、四种测量工具输入与结果 JSON | [Tool 图像与测量工具合同](tools.md#6-图像与测量工具合同) | Agent 暴露工具定义并协调调用；来源授权、范围字段和各类结果字段由 Tool 合同定义 |
| `ProviderRequest`、`ProviderResponse` | [Provider](provider.md#4-完整模型字段) | 组装请求、消费规范化结果；字段合同由 Provider 边界定义 |
| `ToolDefinition`、`ToolInvocation`、`ToolExecutionResult` | [Tool](tools.md#4-完整模型字段) | 投影可用工具、提交调用、消费结果 |

`AvailableAttachment`、`MeasurementObservation` 与 `RunExecutionState` 是当前 Agent 的派生状态 dataclass；它们只存在于调用期，不是独立持久事实。Session、Run 生命周期和恢复事实仍归 Runtime。网页创建 Run 后由 Gateway Dispatcher 调度。当前工作树的 Gateway Registry 为 `figura-web-v4`，注册 `load_image`、`decompose_chart_image`、`extract_text` 与四种测量工具；该实现尚未提交。完整输入、结果和限制见[Tool 图像与测量工具合同](tools.md#6-图像与测量工具合同)。

## 4. 运行时状态字段

以下值由 `agent/execution_state.py` 定义并在每次请求构建时重新读取。字段完整列出；Runtime 和 Sources 中的嵌套源模型仍由各自 owner 定义。

### `AvailableAttachment`

Run 图像清单中的一条可访问附件引用，不保存文件或字节。**写入者：**`RunExecutionStateService`。**权威来源：**同 Session 的 RunInput 附件 ID 与 Sources `AttachmentMetadata`。**读取与公开：**Agent/图像工具授权和提示清单；不是独立 Web DTO。[定义](../../src/figura/agent/execution_state.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 构建者 → 权威来源 → 读取/公开 |
|---|---|---|---|---|
| `AvailableAttachment.attachment_id` | `str` | 必传 | 不透明 Attachment ID；按较早 Run ordinal 和输入顺序，再当前 Run 输入顺序去重 | `RunExecutionStateService` → `RunInput.attachment_ids` 与 `AttachmentMetadata.attachment_id` → Agent / 图像工具；清单不单独持久化 |
| `AvailableAttachment.filename` | `str` | 必传 | 来自所属 Session 附件元数据的安全显示文件名 | `RunExecutionStateService` → `AttachmentMetadata.filename` → Agent 图像清单、`load_image`、OCR 和四种测量工具；不含图像内容 |

### `MeasurementObservation`

单个已提交测量结果在调用期状态中的来源索引和结果/错误投影；包括 Cartesian 和 Pie 四种测量。成功时只含 `result`，失败时只含 `error`；四种结果 JSON 的嵌套字段由[Tool 专题](tools.md#6-图像与测量工具合同)定义。独立 OCR 不在该投影内。**构建者：**`RunExecutionStateService.build`。**权威来源：**同 Session 的 `ToolCallFact`、`ToolAttemptStartedFact`、`ToolResultFact`，仅保留目标 Run ordinal 之前且来源属于授权图像清单的已提交结果。**读取与公开：**Agent 请求组装器消费目标 Run 中的成功测量观察生成下一请求的测量标注图；模型从 Session Memory 的 ToolMessage 读取完整工具结果；没有 Web DTO。[定义](../../src/figura/agent/execution_state.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 构建者 → 权威来源 → 读取/公开 |
|---|---|---|---|---|
| `MeasurementObservation.run_id` | `str` | 必传 | 产生此测量结果的 Run 不透明 ID | `RunExecutionStateService` → `ToolCallFact` 所属 `RunState` → 调用期投影；不单独持久化或作为 Web DTO |
| `MeasurementObservation.call_id` | `str` | 必传 | 模型提出的逻辑工具调用 ID | `RunExecutionStateService` → 已匹配 `ToolCallFact.call_id` → 调用期投影；模型另从 ToolMessage 历史读取 |
| `MeasurementObservation.attempt_id` | `str` | 必传 | 产生已提交结果或错误的工具尝试 ID | `RunExecutionStateService` → 与 ToolResultFact 匹配的 `ToolAttemptStartedFact.attempt_id` → 调用期投影；不单独持久化 |
| `MeasurementObservation.tool_name` | `str` | 必传 | `measure_bars`、`measure_lines`、`measure_scatter` 或 `measure_pie` | `RunExecutionStateService` → `ToolCallFact.tool_name` → 调用期投影；结果合同由 Tools 定义 |
| `MeasurementObservation.source_kind` | `Literal["attachment", "panel"]` | 必传 | 测量来源种类；必须由严格解析的工具参数给出 | `RunExecutionStateService` → `ToolCallFact.arguments_json` → 调用期投影；来源须在本 Session 授权图像清单内 |
| `MeasurementObservation.source_id` | `str` | 必传 | 被测 Attachment 或 Panel 的不透明 ID；长度 1–128 | `RunExecutionStateService` → `ToolCallFact.arguments_json` → 调用期投影；越权或未解析来源不进入投影 |
| `MeasurementObservation.outcome` | `ToolOutcome` | 必传 | `succeeded` 或 `failed`；二者决定 result/error 的互斥形状 | `RunExecutionStateService` → `ToolResultFact.outcome` → 调用期投影；枚举见[Tools](tools.md#5-枚举非-dataclass-合同与依据) |
| `MeasurementObservation.result` | `Mapping[str, object] \| None` | `None` | 成功时为对应测量工具的完整、有界 JSON 对象；失败时为空 | `RunExecutionStateService` → 成功 `ToolResultFact.result` → 调用期投影；依 `tool_name` 使用[Tool](tools.md#6-图像与测量工具合同)中的柱、线、散点或 Pie 结果合同 |
| `MeasurementObservation.error` | `ToolExecutionError \| None` | `None` | 失败时为结构化错误；成功时为空 | `RunExecutionStateService` → 失败 `ToolResultFact.error` → 调用期投影；错误字段由[Tool](tools.md#4-完整模型字段)定义，不公开本地细节 |

### `RunExecutionState`

属于一个目标 Run 的附件/Panel 授权清单和已提交测量结果投影。Panel 须与成功分割 ToolResultFact 匹配才进入清单；测量结果须来自本 Session 的授权附件或已提交 Panel。投影包括 `measure_bars`、`measure_lines`、`measure_scatter`、`measure_pie`，不包括普通工具观察 `extract_text`。**构建者：**`RunExecutionStateService.build`。**权威来源：**Runtime RunState/RunInput/工具事实、Sources AttachmentMetadata/PanelRecord。**读取与公开：**图像清单供 Agent 请求组装与图像工具；测量投影由请求组装器核对当前 Run 的成功测量来源并重建标注图。整体不持久化，也不是 Web DTO。[定义](../../src/figura/agent/execution_state.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 构建者 → 权威来源 → 读取/公开 |
|---|---|---|---|---|
| `RunExecutionState.run_id` | `str` | 必传 | 该清单所属目标 Run 的 opaque ID | `RunExecutionStateService` → `RunState.run.run_id` → Agent 与图像工具；不持久化 |
| `RunExecutionState.available_attachments` | `tuple[AvailableAttachment, ...]` | 必传 | 较早终态 Run 与当前 Run 实际引用附件的有序去重清单 | `RunExecutionStateService` → Runtime RunInput + Sources AttachmentMetadata → Agent；不持久化 |
| `RunExecutionState.panels` | `tuple[PanelRecord, ...]` | 必传 | 当前 Session 中与已提交成功分割事实匹配的 Panel，按 Run 与工具结果顺序排列 | `RunExecutionStateService` → Runtime ToolResultFact + Sources PanelRecord → Agent/图像工具；PanelRecord 源字段见[Sources](sources.md#3-完整模型字段) |
| `RunExecutionState.measurements` | `tuple[MeasurementObservation, ...]` | 必传 | 从 ordinal 不超过目标 Run 的同 Session 工具事实重建；仅含授权来源的 `measure_bars`、`measure_lines`、`measure_scatter`、`measure_pie` 已提交成功结果或失败错误，按 Run ordinal、tool sequence、call position 排序，不截断；`extract_text` 不进入该投影 | `RunExecutionStateService` → Runtime ToolCallFact/ToolAttemptStartedFact/ToolResultFact + 授权附件与 Panel 清单 → 调用期状态；没有独立持久表或 Web DTO |

## 5. 不变量、状态与依据

请求必须从同一 Session 的已提交 Run 事实重建；先前 Run 必须全部终态，且 Session Memory 投影不持久化、不裁剪。文本清单列出当前 Session 可用附件与已提交 Panel；原图只在最新工具批次相应 `load_image` 成功后进入下一请求，成功 `extract_text` 或测量调用则为该调用生成一张匹配源图和结果 JSON 的临时标注图，二者都不会从上一 Run 或更早批次自动继承。标注图字节不写入工具事实或 `RunExecutionState`。OCR 与测量结果通过 ToolMessage 留在完整 Memory 历史；`RunExecutionState.measurements` 是附加调用期测量投影，不代表通用 Evidence 模型，也不做自动重测或后续动作 gate；笛卡尔坐标只在数值轴线性标定通过时生成，Pie 比例受扇区角度覆盖与边界证据门槛控制。请求的图片、文本和 Schema 等 Provider 限制在 attempt claim 前验证。完整配对的旧 Registry 工具交互可作为惰性历史投影；未解决或不完整批次 fail-closed。Provider 和工具的不确定外部效果不会因普通执行循环自动重试；`decompose_chart_image` 通过幂等本地写确保恢复时 Panel 身份稳定。代码：[AgentExecutor](../../src/figura/agent/executor.py)、[AgentRequestBuilder](../../src/figura/agent/request.py)、[RunExecutionState](../../src/figura/agent/execution_state.py)、[Run Dispatcher](../../src/figura/gateway/dispatcher.py)；Attachment/Panel 持久字段和文件见[Sources](sources.md)；主规格：[Agent ReAct](../../openspec/figura/openspec/specs/agent-react-execution/spec.md)、[Panel Image Observation](../../openspec/figura/openspec/specs/panel-image-observation/spec.md)、[OCR Text Observation](../../openspec/figura/openspec/specs/ocr-text-observation/spec.md)、[Bar Chart Measurement](../../openspec/figura/openspec/specs/bar-chart-measurement/spec.md)、[Line Chart Measurement](../../openspec/figura/openspec/specs/line-chart-measurement/spec.md)、[Scatter Chart Measurement](../../openspec/figura/openspec/specs/scatter-chart-measurement/spec.md)、[Pie Chart Measurement](../../openspec/figura/openspec/specs/pie-chart-measurement/spec.md)、[Session Memory](../../openspec/figura/openspec/specs/session-memory/spec.md)、[Web Gateway](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md)。
