# Agent：Run 决策与编排

> [返回总览](../figura-implementation-overview.md)。本篇说明 Agent 编排及其调用期派生运行态；Provider 与 Tool 的完整字段分别见[Provider](provider.md)和[Tool](tools.md)，附件和 Panel 持久模型见[Sources](sources.md)，Run 执行事实见[Run Runtime](runtime.md)，网页调用和公开投影见[Web 边界](web.md)。

## 1. 职责与边界

`AgentExecutor` 从当前 `RunState.checkpoint.next_action` 选择一步动作；`AgentRequestBuilder` 调用 Session Memory 投影，将同 Session 较早终态 Run 和当前 Run 的已提交前缀组装为完整 Provider 请求，并读取 Agent 所拥有的 `RunExecutionState` 资源目录。`RunExecutionStateService` 从 Runtime 的 Run 输入、工具调用/尝试/结果事实和 Sources 元数据重建附件、Panel、OCR、测量、ChartFigure 与 ChartRender 六类资源；目录仅有 `run_id`、有序 `resources` 两个字段，不持久化。工具结果的完整 JSON 仍位于普通 ToolMessage 历史，资源目录提供可寻址内容及精简索引。每次请求还由 Agent 生成三层有序 SYSTEM 指令：稳定规则、当前工具目录、目标 Run 资源目录；静态规则不混入用户/运行数据，动态层由其权威运行时对象重建，也不写入 Run 事实。图片读取由 `RunExecutionImageReader` 统一执行：先核对目标目录内的类型化引用，再由 Sources 解析授权附件、Panel 或已存 PNG；OCR/测量标注图在内存中重建，ChartFigure 本身要求显式调用渲染工具。历史消息中的附件 ID 保留为文本引用，历史 Run 的图像不会自动重放。当前 Run 最新已提交工具批次中的成功 `load_image` 原图、OCR/测量标注图和 `render_chart_figure` PNG，会在紧接着的 Provider 请求中按调用顺序加入。当前 Agent 执行本身是同步、非流式文本/图像 ReAct；Web Gateway 通过有界 `RunDispatcher` 异步调用 `execute(session_id, run_id)`，HTTP handler 不运行模型请求。Agent 没有独立的持久模型。

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
    ImageState -->|类型化资源目录| Build
    Build -->|最新批次的图像资源引用| Reader[RunExecutionImageReader]
    Reader -->|经目录授权的源图与私有 PNG| Sources
    Reader -->|校验后的调用期图像字节| Build
    Build -->|三层 SYSTEM 指令 + 完整历史 + 最新批次图像| Provider[Provider Boundary]
    Provider -->|ProviderResponse / Failure| Agent
    Agent -->|extract_text / measure_* / assemble_chart_figure / render_chart_figure ToolInvocation| Tool[Tool Runtime]
    Tool -->|ChartSpec / ChartFigure 校验与 ChartFigure 绘图| Charts[Charts]
    Tool -->|ToolExecutionResult| Agent
    Agent -->|提交事实和推进| State
```

## 2. 内部流转

1. **读取动作**：只按 checkpoint 的 `action_kind` 推进 model、provider_attempt、tool_execution、tool_attempt 或 final。终态 Run 原样返回；无法取得 Run 锁时读取当前状态。
2. **读取 Session 历史**：到达 model action 后，Agent 经 RunCoordinator/Store 读取目标 Run 之前的所有 RunState。Runtime 返回同一 SQLite 快照内按 ordinal 连续排列的先前 Run；先前 Run 未终结或历史事实不完整时不返回可 dispatch 的请求。
3. **投影并组装请求**：Session Memory 从较早 Run 的持久事实构建 `SessionHistory`，再投影当前 Run 输入和已提交前缀。`RunExecutionStateService` 按授权 Run 前缀重建统一类型化目录；附件按首次引用排序，Panel 仅在成功分割结果提交后出现，OCR/测量保留每次观察，Figure 保存完整已接受值，渲染保存安全元数据或错误。`AgentRequestBuilder` 把模型指令组装为三层：静态规则、当前注册工具目录、目标 Run 资源目录。资源提示列出各类资源的类型化引用与精简说明，不重复完整工具结果；动态资源值以 JSON 数据编码，明确作为不可信证据处理；完整结果仍由 ToolMessage 提供。当前 Run 最新已提交工具批次需要回看的图像由 `RunExecutionImageReader` 按资源引用读取，成功 OCR/测量标注图在内存重建，ChartFigure 必须先经过显式渲染；历史 Run 图片不会自动重放。Provider 限制在 attempt claim 前校验；超限时不裁剪。
4. **模型动作**：请求完整且通过校验后，Agent 创建 Provider client，在锁内先由 Runtime claim Provider attempt，再调用 ProviderClient 一次。响应交给 Runtime 提交；明确失败与未知结果分别处理，不自动重发已启动请求。
5. **工具动作**：模型提出的工具调用按原顺序交给 DurableToolExecutor；它通过 ToolRuntime 执行并向 Runtime 追加尝试和结果事实。`assemble_chart_figure` 接受完整 Figure 输入，委托 Charts 校验，再以新鲜同 Session RunExecutionState 核对所有测量引用；任一引用未知、失败、未提交或跨 Session 时整体失败。`render_chart_figure` 只接受已接受的同 Session Figure 引用，通过 Charts 生成 PNG 并委托 Sources 按本次 Run/call 身份保存；通用 ToolResultFact 仅保存摘要。完整批次成功提交后，Agent 可在紧接的 Provider 请求中附加 PNG 图像；既有运行事实以外不再建独立 Figure 或渲染表。未解决的工具尝试不会自动 replay。
6. **终结**：只有非空文本的 `stop` 响应成为最终答案；无效响应、预算耗尽或确定性失败进入失败终态。每 Run 最多 8 次 Provider attempt、32 个已启动逻辑工具调用。

### 提示分层与代码职责

当前工作树中，每次模型请求恰有三个有序 `InstructionBlock(SYSTEM)`。这些是 `ProviderRequest.instructions` 的调用期内容，不是 Memory 消息、Run 字段或持久 Prompt 模型。

| 顺序 | 来源 | 内容与边界 |
|---|---|---|
| 1. 稳定规则 | `agent/prompting/assets/agent.md`、`evidence.md`、`workflow.md`、`response.md`，由 `loader.py` 按固定顺序载入 | 中文职责、证据处理、工作流程与回答规则；不包含本次用户输入、工具状态或资源值 |
| 2. 当前工具目录 | 本次请求的 `ToolRegistry`，由 `tools.py` 投影 | 只列出同一 Registry 中按注册顺序排列的名称和描述；参数、必填项和值域以同请求 `ProviderRequest.tools` 的原生 Schema 为准 |
| 3. Run 资源目录 | 本次请求所用的 `RunExecutionState`，由 `execution.py` 投影 | 用 JSON 索引 Attachment、Panel、OCR、Measurement、ChartFigure 和 ChartRender 的类型化引用与精简状态；完整结果仍在对应历史 ToolMessage，不重复进目录 |

资源目录里的文件名、标题、OCR 片段和工具观察均作为数据而非指令。工具目录说明也不能扩展或覆盖原生工具 Schema。三个指令块在每次请求重建，不保存到 Run facts；Provider 的 `InstructionBlock` 字段合同仍由[Provider 专题](provider.md#4-完整模型字段)拥有。

`observations.py` 负责与上述三层指令分开的最新已提交工具批次图像选择和 Provider 图像消息构造，并委托 `RunExecutionImageReader` 读取获准资源。`AgentRequestBuilder` 留作组合边界，负责组装 Memory 历史、三层指令与观察消息、Provider tools/options，并在 attempt claim 前调用请求限制校验。

| 文件 | 职责 |
|---|---|
| [request.py](../../src/figura/agent/request.py) | 协调 Memory、Runtime 资源目录、Registry、分层指令、观察图像和 Provider 请求校验 |
| [prompting/loader.py](../../src/figura/agent/prompting/loader.py) 与 [assets](../../src/figura/agent/prompting/assets/) | 载入四份稳定中文 Markdown 规则 |
| [prompting/tools.py](../../src/figura/agent/prompting/tools.py) | 从当前 ToolRegistry 生成工具名称/描述目录 |
| [prompting/execution.py](../../src/figura/agent/prompting/execution.py) | 从 RunExecutionState 生成六类资源的 JSON 索引 |
| [prompting/observations.py](../../src/figura/agent/prompting/observations.py) | 选择上一完整工具批次的图像观察并构造 Provider 消息 |

## 3. 跨领域内容合同

| 输入或输出 | 合同 owner | Agent 的使用方式 |
|---|---|---|
| `RunState`、`ExecutionCheckpoint`、`RunInput` | [Run Runtime](runtime.md#4-完整模型字段) | 读取已提交事实和下一动作，不另建持久副本 |
| `SessionHistory`、`UserMessage`、`AssistantMessage`、`ToolMessage`、`MemoryToolCall` | [Session Memory](memory.md#4-完整模型字段) | 消费从同 Session Run 事实重建的完整历史；Message 模型只在请求期间存在 |
| `AttachmentMetadata`、`PanelPoint`、`PanelRecord` | [Sources](sources.md#3-完整模型字段) | 读取 Session 资源；只有已提交分割结果关联的 Panel 才能进入清单 |
| `RunExecutionState`、类型化引用与资源内容模型 | [本篇第 4 节](#4-runexecutionstate-资源合同与完整字段) | Agent 按 Runtime 已提交前缀与 Sources 资源重建调用期目录；字段和不变量由 Agent 拥有，嵌套值链接至 Sources、Tools、Charts owner |
| `ChartSpecData`、`ChartFigure` 与布局模型 | [Charts](charts.md#4-完整模型字段) | Agent 暴露组装工具；内容字段与纯校验由 Charts 定义 |
| 图像/测量工具、`assemble_chart_figure` 与 `render_chart_figure` | [Tool 图像、测量和画布工具合同](tools.md#7-图表画布组装工具) | Agent 暴露工具定义并协调调用；运行态引用解析、结果字段与恢复类别由 Tool 合同定义 |
| `ProviderRequest`、`ProviderResponse` | [Provider](provider.md#4-完整模型字段) | 组装请求、消费规范化结果；字段合同由 Provider 边界定义 |
| `ToolDefinition`、`ToolInvocation`、`ToolExecutionResult` | [Tool](tools.md#4-完整模型字段) | 投影可用工具、提交调用、消费结果 |

资源目录与内容均为 Agent 派生状态 dataclass，只在调用期重建，不是独立持久事实。Runtime 仍拥有 Run 生命周期、完整工具调用/尝试/结果事实；Sources 拥有附件/Panel 元数据和图像文件。网页创建 Run 后由 Gateway Dispatcher 调度。当前工作树 Gateway Registry 为 `figura-web-v6`，包含 `assemble_chart_figure` 与 `render_chart_figure`；Chart rendering change 已归档。资源模型详见本篇第 4 节与[run-execution-resources 主规格](../../openspec/figura/openspec/specs/run-execution-resources/spec.md)。完整输入、输出和引用限制分别见[画布组装工具合同](tools.md#7-图表画布组装工具)和[图表渲染工具合同](tools.md#8-图表渲染工具)。

## 4. RunExecutionState 资源合同与完整字段

`RunExecutionStateService` 将目标 Run 的当前已提交前缀、较早终态 Run 和 Sources 权威资源重建为调用期目录。目录严格只有 `run_id` 与有序 `resources` 两个字段；每条 `ExecutionResource` 严格只有 `ref` 与 `content`。类型由 `ref.kind` 判别，图片字节、文件路径和第二份耐久结果存储均不进入目录。完整行为合同见[run-execution-resources 主规格](../../openspec/figura/openspec/specs/run-execution-resources/spec.md)。

每个资源模型说明中的“字段流转”适用于其表内全部字段，字段行继续明确具体类型、构造默认、语义约束与字段特有的读取规则；嵌套模型的完整字段仍由其 owner 专题定义。

### 引用联合类型与目录操作

`ResourceRef = ImageResourceRef | ToolResourceRef`；`ImageResourceKind = Literal["attachment", "panel"]`，`ToolResourceKind = Literal["ocr", "measurement", "chart_figure", "chart_render"]`，`ResourceKind` 是上述 kind 的并集。图片资源由 opaque `id` 标识；工具资源由类型、来源 Run 与逻辑调用 ID 联合标识，所以不同 Run 即使复用 `call_id` 也不冲突。`RunExecutionState.list(kind=None)` 返回稳定顺序的全量资源或按 kind 筛选结果；`get(ref)` 只按完整引用精确查找，缺失时返回有界 not-found `RunError`。

### `ImageResourceRef`

图片资源身份；Attachment 与 Panel 的身份由 Sources 生成并保持不透明。**字段流转：**`RunExecutionStateService` 从 Run 输入和已验证的 Sources 记录构建；Sources ID 是身份权威，Panel 还要求已提交成功分割事实；`AgentRequestBuilder`、`RunExecutionImageReader` 与图像工具读取；资源目录不作为整体公开。**定义：**[execution_resources.py](../../src/figura/agent/execution_resources.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `ImageResourceRef.kind` | `Literal["attachment", "panel"]` | 必传 | 区分两种 Sources 图片资源，并与对应内容类型匹配；目录重建 → ImageReader 与图像工具；不单独持久化 |
| `ImageResourceRef.id` | `str` | 必传 | 非空 opaque Attachment ID 或 Panel ID；目录精确授权键，不包含文件名或路径 |

### `ToolResourceRef`

调用产物的稳定身份。**字段流转：**`RunExecutionStateService` 从匹配的工具事实构建；Run ID、call ID 和工具类型以 `ToolCallFact`/`ToolResultFact` 为权威；Agent 请求索引、工具引用校验及 Web 的安全渲染摘要读取；不直接公开。**定义：**[execution_resources.py](../../src/figura/agent/execution_resources.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `ToolResourceRef.kind` | `Literal["ocr", "measurement", "chart_figure", "chart_render"]` | 必传 | 选择唯一资源内容模型；值域由 `ToolResourceKind` 固定 |
| `ToolResourceRef.run_id` | `str` | 必传 | 非空来源 Run opaque ID；与 `call_id` 联合区分 Session 内不同 Run 的产物 |
| `ToolResourceRef.call_id` | `str` | 必传 | 非空逻辑工具调用 ID；来自 `ToolCallFact.call_id`，不单独持久化 |

### `AttachmentContent`

Sources 附件元数据在 Run 资源目录中的只读引用；图片字节仍由 Sources 文件服务持有。**字段流转：**`RunExecutionStateService` 从 SessionSnapshot 的附件元数据构建；Sources `attachments` 记录权威；请求清单、`load_image` 与 ImageReader 读取；仅经现有附件 DTO 投影安全元数据，不公开整个资源目录。完整源模型见[Sources](sources.md#3-完整模型字段)。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `AttachmentContent.session_id` | `str` | 必传 | 所属 Session；构建时须与目标 Session 相同，用于来源授权 |
| `AttachmentContent.filename` | `str` | 必传 | 安全显示文件名；Provider 文本清单与 `load_image` 成功结果读取 |
| `AttachmentContent.media_type` | `str` | 必传 | Sources 已确认的图像媒体类型；ImageReader 对照实际文件 |
| `AttachmentContent.byte_count` | `int` | 必传；正整数 | Sources 元数据记录的精确字节数；ImageReader 对照实际字节长度 |
| `AttachmentContent.created_at` | `str` | 必传 | Sources 的 UTC 创建时间文本；只读目录元数据 |

### `PanelContent`

只有分割成功结果已提交、且 Sources PanelRecord 与工具结果完全一致后才构造。**字段流转：**`RunExecutionStateService` 以成功 `decompose_chart_image` 事实和 Sources PanelRecord 配对构建；PanelRecord 是元数据权威，成功结果是进入目录的提交门槛；请求清单、图像观察工具、ImageReader 和 Panel Web 投影读取；不会公开整个资源目录。多边形坐标的完整值语义见[Sources 的 PanelPoint](sources.md#3-完整模型字段)。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `PanelContent.session_id` | `str` | 必传 | 所属 Session；ImageReader 每次解析前核对 |
| `PanelContent.run_id` | `str` | 必传 | 创建 Panel 的 Run opaque ID；须与成功分割结果及 Sources 记录相同 |
| `PanelContent.source_attachment_id` | `str` | 必传 | 被分割源 Attachment 的 opaque ID；来源字段由 PanelRecord 权威 |
| `PanelContent.name` | `str` | 必传 | Panel 显示名；须与模型提议和 Sources 记录一致 |
| `PanelContent.points` | `tuple[PanelPoint, ...]` | 必传 | 完整有序归一化多边形；元素字段与坐标边界归[Sources](sources.md#3-完整模型字段)，资源目录不改写几何 |

### `OcrContent`

单次已提交 OCR 调用的完整只读资源。**字段流转：**`RunExecutionStateService` 从 ToolCallFact、ToolAttemptStartedFact 和 ToolResultFact 重建；调用/尝试/结果事实是权威；Agent 请求索引与 `RunExecutionImageReader` 读取；完整结果另经 Memory ToolMessage 进入 Provider 上下文，不向 Web 公开。结果 schema 的全部嵌套字段由[Tools：extract_text 结果合同](tools.md#6-图像与测量工具合同)拥有；安全错误由[ToolExecutionError](tools.md#4-完整模型字段)拥有。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `OcrContent.attempt_id` | `str` | 必传 | 与匹配 ToolResultFact 对应的已启动工具尝试 ID |
| `OcrContent.source_ref` | `ImageResourceRef \| None` | 必传，可空 | 被扫描 Attachment/Panel 的类型化引用；成功时必有且须授权，失败时无法解析或无来源可为空 |
| `OcrContent.observation_scope` | `Mapping[str, object] \| None` | 必传，可空 | 调用使用的规范化 include/exclude polygon；成功无显式范围时为空表示整图，失败无效范围为空；完整范围合同归 Tools |
| `OcrContent.outcome` | `ToolOutcome` | 必传 | 仅 `succeeded` 或 `failed`；决定 result/error 互斥形状 |
| `OcrContent.result` | `Mapping[str, object] \| None` | `None` | 成功时为完整有界 OCR JSON，失败时为空；字段合同归 Tools，不在此复制或重算 |
| `OcrContent.error` | `ToolExecutionError \| None` | `None` | 失败时的安全结构化错误，成功时为空；字段合同归 Tools |

### `MeasurementContent`

单次柱、线、散点或饼图测量调用的完整只读资源。**字段流转：**`RunExecutionStateService` 从 ToolCallFact、ToolAttemptStartedFact 和 ToolResultFact 重建；调用/尝试/结果事实是权威；Agent 请求索引、ImageReader 与 `assemble_chart_figure` 的引用校验读取；完整结果另经 Memory ToolMessage 进入 Provider 上下文，不向 Web 公开。结果 JSON 按 `tool_name` 对应 Tools 中的完整测量 schema；它保留重复测量，不把结果折叠为图像级状态。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `MeasurementContent.attempt_id` | `str` | 必传 | 与匹配 ToolResultFact 对应的已启动工具尝试 ID |
| `MeasurementContent.tool_name` | `str` | 必传 | 限于 `measure_bars`、`measure_lines`、`measure_scatter`、`measure_pie` |
| `MeasurementContent.source_ref` | `ImageResourceRef \| None` | 必传，可空 | 被测 Attachment/Panel 引用；成功时必有且须授权，失败时不授权图像读取 |
| `MeasurementContent.observation_scope` | `Mapping[str, object] \| None` | 必传，可空 | 规范化 include/exclude polygon；成功无范围表示整图，失败无效范围为空；完整合同归 Tools |
| `MeasurementContent.outcome` | `ToolOutcome` | 必传 | 仅 `succeeded` 或 `failed`；决定 result/error 互斥形状 |
| `MeasurementContent.result` | `Mapping[str, object] \| None` | `None` | 成功时保留对应工具的全部有界 JSON 结果，失败时为空；完整字段见[Tools](tools.md#6-图像与测量工具合同) |
| `MeasurementContent.error` | `ToolExecutionError \| None` | `None` | 失败时的安全结构化错误，成功时为空；完整字段见[Tools](tools.md#4-完整模型字段) |

### `ChartFigureResult`

已接受画布的完整值与校验摘要。**字段流转：**`RunExecutionStateService` 从成功装配调用参数及匹配结果重建；原始 ChartFigure 以 `ToolCallFact.arguments_json` 为权威、接受状态以成功 ToolResultFact 为门槛；Agent 资源索引、后续渲染和 Gateway 标题摘要读取；完整资源不经 Web DTO 公开。ChartFigure 的嵌套字段只在[Charts](charts.md#4-完整模型字段)定义。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `ChartFigureResult.figure` | `ChartFigure` | 必传 | 从原始 assemble ToolCallFact 参数完整恢复的不可变 ChartFigure；必须通过 Charts 语义校验 |
| `ChartFigureResult.figure_digest` | `str` | 必传 | 规范 JSON 的 SHA-256；构造时须与 `figure` 实际 digest 相同 |

### `ChartFigureContent`

成功装配时含完整 ChartFigureResult，失败时只含安全错误。Figure 身份由外层 `ToolResourceRef` 给出。**字段流转：**由 `RunExecutionStateService` 从已提交的装配事实重建；运行事实权威；Agent 请求与渲染 handler 消费，Gateway 只投影与成功渲染关联的有限摘要；资源本身不公开。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `ChartFigureContent.attempt_id` | `str` | 必传 | 已提交装配结果对应的尝试 ID |
| `ChartFigureContent.outcome` | `ToolOutcome` | 必传 | 仅 `succeeded` 或 `failed` |
| `ChartFigureContent.result` | `ChartFigureResult \| None` | `None` | 成功时必有完整 Figure 与 digest；失败时为空 |
| `ChartFigureContent.error` | `ToolExecutionError \| None` | `None` | 失败时必有安全错误；成功时为空 |

### `ChartRenderContent`

渲染调用的已提交结果及其被渲染 Figure 引用；PNG 字节不进入该内容。**字段流转：**`RunExecutionStateService` 从已提交的渲染 ToolCallFact/ToolResultFact 重建；渲染摘要以 ToolResultFact 为权威，PNG 字节以 Sources 私有文件为权威；Agent ImageReader 与 Gateway 安全摘要投影读取，只有有限摘要和经授权的内容路由公开。成功元数据字段由[render 工具结果合同](tools.md#8-图表渲染工具)定义。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `ChartRenderContent.attempt_id` | `str` | 必传 | 已提交渲染结果对应的尝试 ID |
| `ChartRenderContent.figure_ref` | `ToolResourceRef \| None` | 必传，可空 | 被渲染 Figure 的完整类型化引用；kind 必须为 `chart_figure`；成功时必有 |
| `ChartRenderContent.outcome` | `ToolOutcome` | 必传 | 仅 `succeeded` 或 `failed`；结果与错误互斥 |
| `ChartRenderContent.result` | `Mapping[str, object] \| None` | `None` | 成功时恰含完整已提交渲染 metadata；失败时为空；字段归 Tools |
| `ChartRenderContent.error` | `ToolExecutionError \| None` | `None` | 失败时的安全结构化错误，成功时为空 |

### `ExecutionResource`

目录中的不可变资源信封；`ref.kind` 必须与 content 变体一致。**字段流转：**`RunExecutionStateService` 在装配目录时创建；身份与内容分别服从各自 owner 的权威；AgentRequestBuilder、ImageReader、工具 handler 和 Gateway projection 按需消费；不作为 API 对象直接公开。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `ExecutionResource.ref` | `ResourceRef` | 必传 | `ImageResourceRef` 或 `ToolResourceRef`；唯一目录键，不能只按 ID 跨类型查找 |
| `ExecutionResource.content` | `ResourceContent` | 必传 | 与引用 kind 对应的六种 content 之一；所有映射/序列深冻结 |

### `RunExecutionState`

目标 Run 的调用期资源目录。附件先按较早 Run 到当前 Run 的首次输入引用排序；Panel 与工具资源按 Run ordinal、工具事实序号、调用位置和多 Panel 结果位置排序。只读取给定的先前终态 Run 和当前 Run 已提交前缀，Session snapshot 仅提供 Sources 元数据，不能推进当前 Run 前缀。**字段流转：**`RunExecutionStateService` 构建；Runtime 事实和 Sources 记录仍各自权威；AgentRequestBuilder、工具 handler、ImageReader 与 Gateway 的安全渲染摘要构造器消费；RunExecutionState 不经 Gateway 公开，也不持久化。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 |
|---|---|---|---|
| `RunExecutionState.run_id` | `str` | 必传 | 当前目标 Run 的 opaque ID；由 RunExecutionStateService 从目标 RunState 确定 |
| `RunExecutionState.resources` | `tuple[ExecutionResource, ...]` | 必传 | 所有符合前缀和同 Session 授权条件的资源；引用唯一且顺序确定，不含图片字节/路径或额外副本 |

### `RunExecutionImageReader`

此 Agent 服务只接受目标 Session、RunExecutionState 与完整类型化资源引用。Attachment/Panel 由 Sources owner 验证并读取；OCR/测量标注在内存重建；ChartRender PNG 按 ToolResultFact 的摘要校验；ChartFigure 返回显式 render-required，不隐式触发写入工具。所有必要图像在 Provider attempt claim 前完成读取和 Provider 限制检查。

## 5. 不变量、状态与依据

资源目录是调用期派生视图，不扩展 Runtime RunState，也没有独立持久化。完整历史仍来自同 Session 已提交 Run 事实；提示索引列出全部六类资源的类型化引用与精简名称/状态，不复制完整 OCR、测量、Figure 或 render JSON。原图仅在最新已提交工具批次成功 `load_image` 后回看；OCR/测量标注根据已提交结果临时重建；ChartRender PNG 在 Sources 读取并校验。跨 Session、目标 Run 前缀外、失败观察或缺失/损坏文件不能授予图像访问；所有图像与 Provider 限制在 attempt claim 前校验。代码：[AgentExecutor](../../src/figura/agent/executor.py)、[AgentRequestBuilder](../../src/figura/agent/request.py)、[资源合同](../../src/figura/agent/execution_resources.py)、[资源重建](../../src/figura/agent/execution_state.py)、[统一图片读取](../../src/figura/agent/execution_images.py)、[Run Dispatcher](../../src/figura/gateway/dispatcher.py)；完整合同见[run-execution-resources 主规格](../../openspec/figura/openspec/specs/run-execution-resources/spec.md)。

分层提示的实现位于当前工作树，并已同步进主规格：活动 change [`add-figura-layered-prompts`](../../openspec/figura/openspec/changes/add-figura-layered-prompts/) 的任务为 16/16，尚未归档；[agent-react-execution 主规格](../../openspec/figura/openspec/specs/agent-react-execution/spec.md)现已规定三个有序 SYSTEM 指令层。这里的“已完成”表示当前工作树实现与主规格合同一致，不表示 change 已归档或代码已提交。
