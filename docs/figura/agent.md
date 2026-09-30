# Agent：Run 决策与编排

> [返回总览](../figura-implementation-overview.md)。本篇说明 Agent 编排及其调用期派生运行态；Provider 与 Tool 的完整字段分别见[Provider](provider.md)和[Tool](tools.md)，附件和 Panel 持久模型见[Sources](sources.md)，Run 执行事实见[Run Runtime](runtime.md)，网页调用和公开投影见[Web 边界](web.md)。

## 1. 职责与边界

`AgentExecutor` 从当前 `RunState.checkpoint.next_action` 选择一步动作；`AgentRequestBuilder` 调用 Session Memory 投影，将同 Session 较早终态 Run 和当前 Run 的已提交前缀组装为完整 Provider 请求，并消费 `RunExecutionState` 中的附件、Panel、测量观察和已接受 Figure 摘要。`RunExecutionStateService` 从 Runtime Run 事实、Sources 元数据和已提交工具结果重建状态；测量投影包含四种测量，Figure 投影只包含成功 `assemble_chart_figure` 的摘要，`chart_renders` 只索引引用已接受 Figure 的已提交渲染结果。完整 Figure JSON 仍在普通 Assistant tool-call history 中，不复制进派生状态。运行态本身不持久化。历史消息中的附件 ID 保留为文本引用，历史附件不会自动解析成图像。当前 Run 最新已提交模型响应中的成功 `load_image` 原图、成功 OCR/测量标注图，以及成功 `render_chart_figure` 对应 PNG，会在紧接着的 Provider 请求中按工具调用顺序加入；旧 Run 的渲染 PNG 不会自动重放，模型可再次调用渲染工具取得图像。标注图由 Agent 请求组装器从授权源图像和已提交 JSON 临时重建；渲染 PNG 由 Sources 读取。OCR、测量和渲染 JSON 经 Session Memory 的 ToolMessage 进入模型历史；`RunExecutionState` 的测量/渲染投影用于来源完整性核对和 Gateway 读取，不会复制为额外提示内容。Figure 摘要与 `(run_id, call_id)` 引用进入每次请求的图像/内容清单，完整内容仍来自普通工具调用历史。当前 Agent 执行本身是同步、非流式文本/图像 ReAct；Web Gateway 通过有界 `RunDispatcher` 异步调用 `execute(session_id, run_id)`，HTTP handler 不运行模型请求。Agent 没有独立的持久模型。

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
    ImageState -->|附件、Panel、测量、Figure 与渲染观察| Build
    Build -->|当前 Run 最新批次的源图、OCR/测量标注图与成功渲染 PNG| Sources
    Sources -->|授权源图、调用期 OCR/测量标注图和渲染 PNG| Build
    Build -->|ProviderRequest| Provider[Provider Boundary]
    Provider -->|ProviderResponse / Failure| Agent
    Agent -->|extract_text / measure_* / assemble_chart_figure / render_chart_figure ToolInvocation| Tool[Tool Runtime]
    Tool -->|ChartSpec / ChartFigure 校验与 ChartFigure 绘图| Charts[Charts]
    Tool -->|ToolExecutionResult| Agent
    Agent -->|提交事实和推进| State
```

## 2. 内部流转

1. **读取动作**：只按 checkpoint 的 `action_kind` 推进 model、provider_attempt、tool_execution、tool_attempt 或 final。终态 Run 原样返回；无法取得 Run 锁时读取当前状态。
2. **读取 Session 历史**：到达 model action 后，Agent 经 RunCoordinator/Store 读取目标 Run 之前的所有 RunState。Runtime 返回同一 SQLite 快照内按 ordinal 连续排列的先前 Run；先前 Run 未终结或历史事实不完整时不返回可 dispatch 的请求。
3. **投影并组装请求**：Session Memory 从较早 Run 的持久事实构建 `SessionHistory`，再投影当前 Run 输入和已提交前缀。`RunExecutionStateService` 根据较早终态 Run 和目标 Run 的 RunInput 重建授权附件、已提交 Panel、测量观察、成功 Figure 摘要及 `ChartRenderObservation`；失败/未提交组装、未接受 Figure 引用的渲染不会进入对应投影。AgentRequestBuilder 的提示清单列出附件、Panel 和已接受 Figure 摘要；渲染观察不重复序列化进清单。当前 Run 最新已提交工具批次需要回看的成功 `load_image` 原图、OCR/测量标注图及已校验的渲染 PNG，按调用顺序追加到下一次请求；历史 Run 图片不会自动重放。完整 Figure、工具结果和渲染摘要仍经原有 ToolMessage 历史提供；运行态投影不复制其权威事实。Provider 限制在 attempt claim 前校验；超限时不裁剪。
4. **模型动作**：请求完整且通过校验后，Agent 创建 Provider client，在锁内先由 Runtime claim Provider attempt，再调用 ProviderClient 一次。响应交给 Runtime 提交；明确失败与未知结果分别处理，不自动重发已启动请求。
5. **工具动作**：模型提出的工具调用按原顺序交给 DurableToolExecutor；它通过 ToolRuntime 执行并向 Runtime 追加尝试和结果事实。`assemble_chart_figure` 接受完整 Figure 输入，委托 Charts 校验，再以新鲜同 Session RunExecutionState 核对所有测量引用；任一引用未知、失败、未提交或跨 Session 时整体失败。`render_chart_figure` 只接受已接受的同 Session Figure 引用，通过 Charts 生成 PNG 并委托 Sources 按本次 Run/call 身份保存；通用 ToolResultFact 仅保存摘要。完整批次成功提交后，Agent 可在紧接的 Provider 请求中附加 PNG 图像；既有运行事实以外不再建独立 Figure 或渲染表。未解决的工具尝试不会自动 replay。
6. **终结**：只有非空文本的 `stop` 响应成为最终答案；无效响应、预算耗尽或确定性失败进入失败终态。每 Run 最多 8 次 Provider attempt、32 个已启动逻辑工具调用。

## 3. 跨领域内容合同

| 输入或输出 | 合同 owner | Agent 的使用方式 |
|---|---|---|
| `RunState`、`ExecutionCheckpoint`、`RunInput` | [Run Runtime](runtime.md#4-完整模型字段) | 读取已提交事实和下一动作，不另建持久副本 |
| `SessionHistory`、`UserMessage`、`AssistantMessage`、`ToolMessage`、`MemoryToolCall` | [Session Memory](memory.md#4-完整模型字段) | 消费从同 Session Run 事实重建的完整历史；Message 模型只在请求期间存在 |
| `AttachmentMetadata`、`PanelPoint`、`PanelRecord` | [Sources](sources.md#3-完整模型字段) | 读取 Session 资源；只有已提交分割结果关联的 Panel 才能进入清单 |
| `RunExecutionState`、`AvailableAttachment`、`MeasurementObservation`、Figure 摘要和 `ChartRenderObservation` | [本篇第 4 节](#4-运行时状态字段) | 从 Runtime 与 Sources 事实重建调用期清单；测量结果与 Figure 全文不在状态中复制 |
| `ChartSpecData`、`ChartFigure` 与布局模型 | [Charts](charts.md#4-完整模型字段) | Agent 暴露组装工具；内容字段与纯校验由 Charts 定义 |
| 图像/测量工具、`assemble_chart_figure` 与 `render_chart_figure` | [Tool 图像、测量和画布工具合同](tools.md#7-图表画布组装工具) | Agent 暴露工具定义并协调调用；运行态引用解析、结果字段与恢复类别由 Tool 合同定义 |
| `ProviderRequest`、`ProviderResponse` | [Provider](provider.md#4-完整模型字段) | 组装请求、消费规范化结果；字段合同由 Provider 边界定义 |
| `ToolDefinition`、`ToolInvocation`、`ToolExecutionResult` | [Tool](tools.md#4-完整模型字段) | 投影可用工具、提交调用、消费结果 |

`AvailableAttachment`、`MeasurementObservation`、Figure 摘要与渲染观察模型及 `RunExecutionState` 是当前 Agent 的派生状态 dataclass；只存在于调用期，不是独立持久事实。Session、Run 生命周期以及完整 Figure/渲染调用和结果事实仍归 Runtime；PNG 字节归 Sources 文件存储。网页创建 Run 后由 Gateway Dispatcher 调度。当前工作树 Gateway Registry 为 `figura-web-v6`，包含 `assemble_chart_figure` 与 `render_chart_figure`；Chart rendering change 已归档。完整输入、输出和引用限制分别见[画布组装工具合同](tools.md#7-图表画布组装工具)和[图表渲染工具合同](tools.md#8-图表渲染工具)。

## 4. 运行时状态字段

以下值由 `agent/execution_state.py` 定义并在每次请求构建时重新读取。字段完整列出；Runtime 和 Sources 中的嵌套源模型仍由各自 owner 定义。

### `AvailableAttachment`

Run 图像清单中的一条可访问附件引用，不保存文件或字节。**写入者：**`RunExecutionStateService`。**权威来源：**同 Session 的 RunInput 附件 ID 与 Sources `AttachmentMetadata`。**读取与公开：**Agent/图像工具授权和提示清单；不是独立 Web DTO。[定义](../../src/figura/agent/execution_state.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 构建者 → 权威来源 → 读取/公开 |
|---|---|---|---|---|
| `AvailableAttachment.attachment_id` | `str` | 必传 | 不透明 Attachment ID；按较早 Run ordinal 和输入顺序，再当前 Run 输入顺序去重 | `RunExecutionStateService` → `RunInput.attachment_ids` 与 `AttachmentMetadata.attachment_id` → Agent / 图像工具；清单不单独持久化 |
| `AvailableAttachment.filename` | `str` | 必传 | 来自所属 Session 附件元数据的安全显示文件名 | `RunExecutionStateService` → `AttachmentMetadata.filename` → Agent 图像清单、`load_image`、OCR 和四种测量工具；不含图像内容 |

### `MeasurementObservation`

单个已提交测量结果在调用期状态中的来源索引和结果/错误投影；包括 Cartesian 和 Pie 四种测量。成功时只含 `result`，失败时只含 `error`；四种结果 JSON 的嵌套字段由[Tool 专题](tools.md#6-图像与测量工具合同)定义。独立 OCR 不在该投影内。**构建者：**`RunExecutionStateService.build`。**权威来源：**同 Session 的 `ToolCallFact`、`ToolAttemptStartedFact`、`ToolResultFact`，仅保留目标 Run ordinal 不超过当前目标值且来源属于授权图像清单的已提交结果。**读取与公开：**Agent 请求组装器消费目标 Run 中的成功测量观察生成下一请求的测量标注图；模型从 Session Memory 的 ToolMessage 读取完整工具结果；没有 Web DTO。[定义](../../src/figura/agent/execution_state.py)。

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

### `ChartFigureReference`

Agent Figure 摘要的 opaque 工具调用身份，不是独立 Figure ID。**构建者：**`RunExecutionStateService`。**权威来源：**成功 Figure 的 `ToolCallFact` 所属 Run 与 call ID。**读取与公开：**每次 Provider 请求的 Figure 摘要清单；不另存、不单独公开。[定义](../../src/figura/agent/execution_state.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 构建者 → 权威来源 → 读取/公开 |
|---|---|---|---|---|
| `ChartFigureReference.run_id` | `str` | 必传 | 创建该 Figure 的 Run 不透明 ID | `RunExecutionStateService` → `ToolCallFact` 所属 `RunState.run.run_id` → Agent 提示清单；不单独持久化 |
| `ChartFigureReference.call_id` | `str` | 必传 | 成功 `assemble_chart_figure` 调用的逻辑 ID | `RunExecutionStateService` → `ToolCallFact.call_id` → Agent 提示清单；不单独持久化 |

### `ChartSummary`

Figure 中一个子图的轻量提示摘要，不包含 ChartSpecData 数据集。**构建者：**`RunExecutionStateService`。**权威来源：**已提交 `assemble_chart_figure` 的 ToolResultFact.result。**读取与公开：**Agent 每次请求的 Figure 清单；完整子图内容仍在工具调用参数中。[定义](../../src/figura/agent/execution_state.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 构建者 → 权威来源 → 读取/公开 |
|---|---|---|---|---|
| `ChartSummary.chart_id` | `str` | 必传 | Figure 内唯一的本地子图 ID，匹配 `[A-Za-z0-9_-]{1,64}` | `RunExecutionStateService` → ToolResultFact 子图摘要 → Agent 清单；完整字段见[Charts](charts.md#4-完整模型字段) |
| `ChartSummary.chart_type` | `ChartType` | 必传 | `bar`、`line`、`pie` 或 `scatter` | `RunExecutionStateService` → 子图 ChartSpecData.metadata.chart_type → Agent 清单 |
| `ChartSummary.title` | `str` | 必传 | 子图展示标题，最多 160 字符；默认可为空文本 | `RunExecutionStateService` → 子图 ChartSpecData.metadata.title → Agent 清单 |

### `ChartFigureSummary`

一个成功 Figure 的轻量索引，用于跨 Run 寻址与模型提示；不复制完整 Figure。**构建者：**`RunExecutionStateService`。**权威来源：**同 Session Run 中已配对的成功 assembly ToolCallFact/ToolResultFact。**读取与公开：**Agent 请求图像清单；无独立 Web DTO 或持久副本。[定义](../../src/figura/agent/execution_state.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 构建者 → 权威来源 → 读取/公开 |
|---|---|---|---|---|
| `ChartFigureSummary.figure_ref` | `ChartFigureReference` | 必传 | 由 originating Run ID 与 assembly call ID 构成；字段见本节上表 | `RunExecutionStateService` → ToolCallFact/ToolResultFact 对 → Agent 清单 |
| `ChartFigureSummary.figure_digest` | `str` | 必传 | canonical Figure JSON 的 64 位小写 SHA-256 十六进制摘要 | `RunExecutionStateService` → ToolResultFact.result → Agent 清单；完整内容仍在 ToolCallFact.arguments_json |
| `ChartFigureSummary.title` | `str` | 必传 | Figure 标题，最多 160 字符；可为空 | `RunExecutionStateService` → ToolResultFact.result → Agent 清单 |
| `ChartFigureSummary.charts` | `tuple[ChartSummary, ...]` | 必传 | 1–4 个有序子图摘要，不含 dataset 或 ChartSpec 全文 | `RunExecutionStateService` → ToolResultFact.result.charts → Agent 清单 |

### `ChartRenderObservation`

一个已提交 `render_chart_figure` 结果的调用期观察；只包含受限元数据或安全错误，不含 PNG 字节和文件路径。成功结果不含 `figure_ref`，其嵌套字段在 [Tools](tools.md#8-图表渲染工具) 定义。**构建者：**`RunExecutionStateService.build`。**权威来源：**同 Session 中 ordinal 不超过目标 Run 的 ToolCallFact、ToolAttemptStartedFact、ToolResultFact，以及本投影中的已接受 Figure 索引。**读取与公开：**Agent 校验当前批次 PNG 与事实的一致性，Gateway 构建 Run 渲染摘要；本模型不持久化。[定义](../../src/figura/agent/execution_state.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 构建者 → 权威来源 → 读取/公开 |
|---|---|---|---|---|
| `ChartRenderObservation.run_id` | `str` | 必传 | 发起渲染调用的 Run opaque ID，不是被渲染 Figure 的来源 Run ID | `RunExecutionStateService` → 渲染 ToolCallFact 所属 Run → 调用期观察；不单独持久化 |
| `ChartRenderObservation.call_id` | `str` | 必传 | 模型提出的 `render_chart_figure` 逻辑调用 ID | `RunExecutionStateService` → render ToolCallFact.call_id → 调用期观察；Web 用作该 PNG 的内容路径键 |
| `ChartRenderObservation.attempt_id` | `str` | 必传 | 产生已提交成功/失败结果的工具尝试身份 | `RunExecutionStateService` → 匹配 ToolResultFact.attempt_id 的 ToolAttemptStartedFact → 调用期观察 |
| `ChartRenderObservation.figure_ref` | `ChartFigureReference` | 必传 | 被渲染的已接受 Figure `(run_id, call_id)`；嵌套字段见本节 ChartFigureReference | `RunExecutionStateService` → 严格解析 ToolCallFact.arguments_json → 当前 Session 已接受 Figure 索引；无效/越权引用不投影 |
| `ChartRenderObservation.outcome` | `ToolOutcome` | 必传 | `succeeded` 或 `failed`；决定 result/error 互斥形状 | `RunExecutionStateService` → ToolResultFact.outcome → Agent/Gateway 调用期消费 |
| `ChartRenderObservation.result` | `Mapping[str, object] \| None` | `None` | 成功时包含 `figure_digest`、`image_sha256`、`media_type`、`byte_count`、`width`、`height`，不重复 `figure_ref`；失败时为空 | `RunExecutionStateService` → 成功 ToolResultFact.result 去掉 figure_ref 后冻结 → Agent 校验 PNG 与 Gateway DTO；完整字段归 Tools |
| `ChartRenderObservation.error` | `ToolExecutionError \| None` | `None` | 失败时的安全结构化错误；成功时为空 | `RunExecutionStateService` → 失败 ToolResultFact.error → 调用期状态；完整字段归 Tools |
### `RunExecutionState`

属于目标 Run 的附件/Panel 授权清单、测量观察、成功 Figure 摘要和渲染观察投影，恰有六个顶层字段。Panel 须与成功分割 ToolResultFact 匹配才进入清单；测量结果须来自本 Session 授权附件或已提交 Panel；Figure 须对应同 Session 中成功提交的 assembly 结果；渲染须指向同 Session 已接受 Figure 且自身结果已提交。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 构建者 → 权威来源 → 读取/公开 |
|---|---|---|---|---|
| `RunExecutionState.run_id` | `str` | 必传 | 该清单所属目标 Run 的 opaque ID | `RunExecutionStateService` → `RunState.run.run_id` → Agent 与图像工具；不持久化 |
| `RunExecutionState.available_attachments` | `tuple[AvailableAttachment, ...]` | 必传 | 较早终态 Run 与当前 Run 实际引用附件的有序去重清单 | `RunExecutionStateService` → Runtime RunInput + Sources AttachmentMetadata → Agent；不持久化 |
| `RunExecutionState.panels` | `tuple[PanelRecord, ...]` | 必传 | 当前 Session 中与已提交成功分割事实匹配的 Panel，按 Run 与工具结果顺序排列 | `RunExecutionStateService` → Runtime ToolResultFact + Sources PanelRecord → Agent/图像工具；PanelRecord 源字段见[Sources](sources.md#3-完整模型字段) |
| `RunExecutionState.measurements` | `tuple[MeasurementObservation, ...]` | 必传 | 从 ordinal 不超过目标 Run 的同 Session 工具事实重建；仅含授权来源的 `measure_bars`、`measure_lines`、`measure_scatter`、`measure_pie` 已提交成功结果或失败错误，按 Run ordinal、tool sequence、call position 排序，不截断；`extract_text` 不进入该投影 | `RunExecutionStateService` → Runtime ToolCallFact/ToolAttemptStartedFact/ToolResultFact + 授权附件与 Panel 清单 → 调用期状态；没有独立持久表或 Web DTO |
| `RunExecutionState.chart_figures` | `tuple[ChartFigureSummary, ...]` | 必传 | 同 Session 较早终态 Run 与目标 Run 中成功提交的 Figure 摘要，按 Run ordinal、tool-call 序号和位置排序；失败与未提交调用排除，不截断 | `RunExecutionStateService` → assembly ToolCallFact/ToolResultFact → 调用期状态；完整 Figure 不复制到该字段 |
| `RunExecutionState.chart_renders` | `tuple[ChartRenderObservation, ...]` | 必传 | 当前及较早 Run 中指向同 Session 已接受 Figure 的已提交渲染成功/失败观察，按 Run ordinal、工具事实序号和调用位置排序；未提交结果、无效引用、其他 Session 引用排除，不截断 | `RunExecutionStateService` → render ToolCallFact/ToolAttemptStartedFact/ToolResultFact + `chart_figures` → 调用期投影；PNG 文件不复制到该字段 |

## 5. 不变量、状态与依据

请求必须从同一 Session 的已提交 Run 事实重建；先前 Run 必须全部终态，且 Session Memory 投影不持久化、不裁剪。文本清单列出附件、Panel 和全部成功 Figure 摘要；完整 ChartFigure 只留在原工具调用事实，状态与提示清单不复制 dataset。原图只在当前 Run 最新工具批次相应 `load_image` 成功后进入下一请求，成功 OCR/测量调用生成临时标注图，成功 `render_chart_figure` 读取 Sources 中与结果摘要匹配的 PNG 加入紧接着的请求。已提交 `chart_renders` 作为调用期投影用于完整性核对和 Gateway DTO，不会让旧 Run 的图片自动重放。代码：[AgentExecutor](../../src/figura/agent/executor.py)、[AgentRequestBuilder](../../src/figura/agent/request.py)、[RunExecutionState](../../src/figura/agent/execution_state.py)、[Run Dispatcher](../../src/figura/gateway/dispatcher.py)；Charts 绘制见[Charts](charts.md#5-png-绘制边界)，工具与 PNG 存储见[Tools](tools.md#8-图表渲染工具)，主规格见[Chart rendering](../../openspec/figura/openspec/specs/chart-rendering/spec.md)。
