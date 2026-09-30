# Tool：能力定义与调用边界

> [返回总览](../figura-implementation-overview.md)。本篇拥有工具定义、注册、调用及结果合同；`ToolCallFact`、`ToolAttemptStartedFact`、`ToolResultFact` 是[Run Runtime](runtime.md#4-完整模型字段)所拥有的持久事实。

## 1. 职责与边界

`ToolRegistry` 保存有序、版本化的 `ToolDefinition`；`ToolRuntime` 解析和验证调用参数，运行同步 handler，验证有界成功结果或返回安全错误。`DurableToolExecutor` 属于 Run 执行边界，负责在调用前后提交事实。当前工作树 Gateway Registry 版本为 `figura-web-v6`，依次包含 `load_image`、`decompose_chart_image`、`extract_text`、四种测量工具、`assemble_chart_figure` 和 `render_chart_figure`。图像、OCR 和测量工具处理 Session 已授权 Attachment/Panel；画布组装工具接收 Charts 域的完整 ChartFigure 并核对测量引用；渲染工具只接收引用已接受 Figure 的 `(run_id, call_id)`。Registry v6 不保留 v5 unresolved-tool 兼容 executor；切换前，旧 v5 Run 必须到达终态。

## 2. 内部流转

1. **注册**：Gateway 组装有序 `ToolDefinition`，检查名称唯一、参数与结果 JSON Schema、描述及总大小。当前工具按 `load_image`、`decompose_chart_image`、`extract_text`、`measure_bars`、`measure_lines`、`measure_scatter`、`measure_pie`、`assemble_chart_figure`、`render_chart_figure` 顺序注册；Registry 对外提供只读版本、定义顺序和按名查找。
2. **模型投影**：Agent 把允许的工具定义映射为 Provider 的 `FunctionTool`；模型只见名称、说明与参数 Schema，不见 handler、结果 Schema 或本地上下文。
3. **调用**：`ToolInvocation` 的 call ID、名称和 JSON 参数进入 `ToolRuntime`；解析拒绝重复键、无效数值与不符合 Schema 的内容。handler 只收到已验证参数及 `ToolContext`。
4. **结果与恢复**：成功时结果必须是有界 JSON 对象；失败时返回 `ToolExecutionError`。图像读取、OCR、测量与 `assemble_chart_figure` 为 `replay_safe`；Panel 分割和 `render_chart_figure` 为 `idempotent_local_write`。组装工具不新建外部资源，只验证、摘要并通过既有 Runtime 工具事实保留 Figure；渲染工具把 PNG 安装到 Sources 私有文件区，ToolResultFact 只保存有界摘要。结果超出既有大小上限时整体拒绝，不静默截断或删减观测。`replay_effect` 决定不确定结果能否安全重放或必须显式协调；ToolRuntime 自身不拥有 Run checkpoint。

## 3. 模型关系与共同规则

`ToolExecutionResult` 根据 `outcome` 在 `result` 与 `error` 之间二选一。`ToolDefinition.parameters_schema` 是模型输入合同，`result_schema` 是内部结果合同。`ToolContext.idempotency_key` 只给需要本地幂等写的 handler 使用。以下逐模型列出全部声明字段。

## 4. 完整模型字段

### ToolContext

传给单次 handler 的已验证执行上下文。 **写入者：**DurableToolExecutor。**权威位置：**调用期内存。**读取与公开：**handler；幂等键与取消信号不公开。[定义](../../src/figura/tools/contracts.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ToolContext.run_id | str | 必传 | 所属 Run 的不透明身份 | DurableToolExecutor → 调用期内存 → handler；幂等键与取消信号不公开 |
| ToolContext.session_id | str | 必传 | 所属 Session 的不透明身份；跨 Session 读取须拒绝 | DurableToolExecutor → 调用期内存 → handler；幂等键与取消信号不公开 |
| ToolContext.call_id | str | 必传 | 模型给出的逻辑工具调用 ID | DurableToolExecutor → 调用期内存 → handler；幂等键与取消信号不公开 |
| ToolContext.cancellation | CancellationSignal | CancellationSignal() | 只读协作取消信号 | DurableToolExecutor → 调用期内存 → handler；幂等键与取消信号不公开 |
| ToolContext.idempotency_key | str \| None | None | 本地幂等写的 SHA-256 十六进制键；可空 | DurableToolExecutor → 调用期内存 → handler；幂等键与取消信号不公开 |

### ToolInvocation

一次工具调用的名称、ID 与 JSON 参数。 **写入者：**Agent / DurableToolExecutor。**权威位置：**调用期；逻辑意图另见 ToolCallFact。**读取与公开：**ToolRuntime。[定义](../../src/figura/tools/contracts.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ToolInvocation.call_id | str | 必传 | 模型给出的逻辑工具调用 ID | Agent / DurableToolExecutor → 调用期；逻辑意图另见 ToolCallFact → ToolRuntime |
| ToolInvocation.name | str | 必传 | 注册的工具名称，1–64 位 ASCII 字母/数字/_/- | Agent / DurableToolExecutor → 调用期；逻辑意图另见 ToolCallFact → ToolRuntime |
| ToolInvocation.arguments_json | str | 必传 | 模型提供的 JSON 参数原文；执行前严格解析 | Agent / DurableToolExecutor → 调用期；逻辑意图另见 ToolCallFact → ToolRuntime |

### ToolExecutionError

可安全传回的有界工具错误。 **写入者：**ToolRuntime / handler。**权威位置：**调用期；可嵌入 ToolResultFact。**读取与公开：**Agent；仅安全字段可投影。[定义](../../src/figura/tools/contracts.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ToolExecutionError.code | str | 必传 | 稳定错误/问题码 | ToolRuntime / handler → 调用期；可嵌入 ToolResultFact → Agent；仅安全字段可投影 |
| ToolExecutionError.message | str | 必传 | 有界安全错误说明 | ToolRuntime / handler → 调用期；可嵌入 ToolResultFact → Agent；仅安全字段可投影 |
| ToolExecutionError.retryable | bool | 必传 | 工具错误是否可重试 | ToolRuntime / handler → 调用期；可嵌入 ToolResultFact → Agent；仅安全字段可投影 |
| ToolExecutionError.field_path | str \| None | None | 可空的有界 JSON Pointer 错误位置 | ToolRuntime / handler → 调用期；可嵌入 ToolResultFact → Agent；仅安全字段可投影 |

### ToolExecutionResult

一次工具调用的成功对象或失败错误。 **写入者：**ToolRuntime。**权威位置：**调用期；随后转 ToolResultFact。**读取与公开：**DurableToolExecutor / Agent。[定义](../../src/figura/tools/contracts.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ToolExecutionResult.call_id | str | 必传 | 模型给出的逻辑工具调用 ID | ToolRuntime → 调用期；随后转 ToolResultFact → DurableToolExecutor / Agent |
| ToolExecutionResult.tool_name | str | 必传 | 工具定义名称 | ToolRuntime → 调用期；随后转 ToolResultFact → DurableToolExecutor / Agent |
| ToolExecutionResult.outcome | ToolOutcome | 必传 | 工具结果的成功或失败状态 | ToolRuntime → 调用期；随后转 ToolResultFact → DurableToolExecutor / Agent |
| ToolExecutionResult.result | Mapping[str, Any] \| None | None | 成功时的有界 JSON 对象；失败时为空 | ToolRuntime → 调用期；随后转 ToolResultFact → DurableToolExecutor / Agent |
| ToolExecutionResult.error | ToolExecutionError \| None | None | 失败时的安全错误；成功时为空 | ToolRuntime → 调用期；随后转 ToolResultFact → DurableToolExecutor / Agent |

### ToolDefinition

单个版本化工具的参数、结果和 handler 合同。 **写入者：**进程启动时组装 ToolRegistry。**权威位置：**进程内 Registry。**读取与公开：**Agent 工具投影与 ToolRuntime；handler 不进模型。[定义](../../src/figura/tools/contracts.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ToolDefinition.name | str | 必传 | 注册的工具名称，1–64 位 ASCII 字母/数字/_/- | 进程启动时组装 ToolRegistry → 进程内 Registry → Agent 工具投影与 ToolRuntime；handler 不进模型 |
| ToolDefinition.description | str | 必传 | 模型可见工具说明 | 进程启动时组装 ToolRegistry → 进程内 Registry → Agent 工具投影与 ToolRuntime；handler 不进模型 |
| ToolDefinition.parameters_schema | Mapping[str, Any] | 必传 | 工具输入参数的有界对象 Schema | 进程启动时组装 ToolRegistry → 进程内 Registry → Agent 工具投影与 ToolRuntime；handler 不进模型 |
| ToolDefinition.result_schema | Mapping[str, Any] | 必传 | 工具成功结果的有界对象 Schema | 进程启动时组装 ToolRegistry → 进程内 Registry → Agent 工具投影与 ToolRuntime；handler 不进模型 |
| ToolDefinition.replay_effect | ReplayEffect \| str | 必传 | 未知效果恢复策略 | 进程启动时组装 ToolRegistry → 进程内 Registry → Agent 工具投影与 ToolRuntime；handler 不进模型 |
| ToolDefinition.handler | ToolHandler | 必传 | 同步处理函数；不进入模型投影 | 进程启动时组装 ToolRegistry → 进程内 Registry → Agent 工具投影与 ToolRuntime；handler 不进模型 |

## 5. 枚举、非 dataclass 合同与依据

- `ReplayEffect`：`replay_safe`、`idempotent_local_write`、`reconcile_required`。`ToolOutcome`：`succeeded`、`failed`。
- `ToolRegistry` 是不可变 Registry：只读 `version`、有序 `definitions`、`by_name` 映射；创建于进程内，调用事实只记录当时的 registry 版本。`CancellationSignal` 只暴露 `is_cancelled()`。`ToolHandler` 是同步处理函数合同，不进入模型投影。
- JSON Schema 的共享 `SchemaIssue` 字段在[共享验证合同](validation.md#3-完整模型字段)定义；本篇只说明 ToolRuntime 怎样消费它。
- 代码：[合同](../../src/figura/tools/contracts.py)、[Registry](../../src/figura/tools/registry.py)、[Runtime](../../src/figura/tools/runtime.py)、[Provider 投影](../../src/figura/tools/provider.py)；主规格：[tool-runtime](../../openspec/figura/openspec/specs/tool-runtime/spec.md)、[durable-tool-execution](../../openspec/figura/openspec/specs/durable-tool-execution/spec.md)。

## 6. 图像与测量工具合同

图像适配器在 [image.py](../../src/figura/tools/implementations/image.py)；文字与测量适配器分别在 [extract_text.py](../../src/figura/tools/implementations/extract_text.py)、[measure_bars.py](../../src/figura/tools/implementations/measure_bars.py)、[measure_lines.py](../../src/figura/tools/implementations/measure_lines.py)、[measure_scatter.py](../../src/figura/tools/implementations/measure_scatter.py) 和 [measure_pie.py](../../src/figura/tools/implementations/measure_pie.py)。共享来源解析、输入/结果 Schema、观察范围与传感器分别见 [measurement_source.py](../../src/figura/tools/implementations/measurement_source.py)、[measurement_schema.py](../../src/figura/tools/implementations/measurement_schema.py) 与 tools/measurements/。Bootstrap 注入 RunExecutionStateService 和 RunExecutionImageReader；Reader 持有 Sources 的 Attachment、Panel 与 ChartRender 服务。handler 先以完整类型化引用查询目标 Run 资源目录，再由 Reader 核对 Session 所有权并读取图像；模型不能提交路径、URL 或图片字节。

OCR 与测量结果是有界 JSON。成功或失败结果随 ToolResultFact 持久化并通过 Session Memory 的 ToolMessage 进入后续对话；Agent 又按 `(kind, run_id, call_id)` 将每次已提交调用重建为独立 `OcrContent` 或 `MeasurementContent`，保留来源、范围、完整结果或安全错误，不创建第二份事实存储。结果不含图像字节、覆盖图或本机路径，也没有单独的测量 Web API。所有 Schema 对象拒绝未声明属性；超出 ToolRuntime 结果大小限制时整体失败，不静默截断字段或观测。

### load_image

只读图像加载工具。成功结果提交后，Agent 在紧接的下一次 Provider 请求里解析原图字节；工具结果本身只记录元数据。

| 合同 | 完整字段与边界 |
|---|---|
| 参数 | source_kind: attachment 或 panel；source_id: string，长度 1–128。额外属性拒绝。 |
| 成功结果 | source_kind、source_id、name、width、height；宽高为 1–100000 的整数。额外属性拒绝。 |
| 执行效果 | replay_safe；来源必须命中目标 Run 的 Session 图像清单。Attachment 名来自净化后的文件名，Panel 名来自 Panel 名。 |

### decompose_chart_image

按模型给出的规范化多边形生成独立 Panel PNG；矩形也使用四点多边形。PanelRecord 和 PanelPoint 的完整字段由 [Sources](sources.md#3-完整模型字段)拥有。

| 合同 | 完整字段与边界 |
|---|---|
| 参数 | attachment_id: string，长度 1–128；panels：1–32 个 Panel 提议。额外属性拒绝。 |
| Panel 提议 | 每项含 name: string（长度 1–256）和 points（3–64 个点）；每个点含整数 x、y，均在 0–1000。 |
| 成功结果 | { panels: [{ panel_id, name, source_attachment_id }] }，与输入同序；ID 为小写 64 位十六进制。不得带点坐标、图像字节或文件路径。 |
| 执行效果 | idempotent_local_write；同一 call-scoped 幂等键恢复时复用 Panel 身份。只检查区域能否安全执行，不判断语义准确度、重叠或图表类型。 |

### 测量来源与内部值

以下 dataclass 仅在工具调用期存在。图像字节不会进入工具结果或持久状态。

#### MeasurementSource

来源适配器解析后的图像值。构建者为 resolve_measurement_source；Attachment 和 Panel 的权威元数据/字节仍属于 [Sources](sources.md)。失败的来源授权在读取字节前拒绝。

| 完整字段路径 | 类型、默认与约束 | 含义 | 写入者 → 权威位置 → 读取者 |
|---|---|---|---|
| MeasurementSource.source_kind | Literal[attachment, panel]，必传 | 来源类型 | 来源解析器 → 调用期内存 → 测量 handler |
| MeasurementSource.source_id | str，必传 | 来源不透明 ID | 来源解析器 → 调用期内存 → 测量 handler |
| MeasurementSource.name | str，必传 | 安全显示名；Attachment 文件名或 Panel 名 | 来源解析器 → Sources 元数据的调用期副本 → 测量 handler |
| MeasurementSource.coordinate_system | Literal[attachment_px, panel_px]，必传 | 后续结果所用像素坐标系 | 来源解析器 → 调用期内存 → handler 写入测量 JSON |
| MeasurementSource.image_bytes | bytes，必传且非空 | 已授权源图像字节 | Attachment/Panel Service → 调用期内存 → 传感器；不持久化、不公开 |

#### OCRSnippet 与 OCRObservation

OCR 既为笛卡尔/Pie 测量提供轴刻度、标签与关联候选，也由 `extract_text` 作为独立的有界文字观察工具暴露；不把原始图片发给 Provider。当前实现每次最多保留 512 个片段，每个文字最多 128 字符；置信度限制在 0–1。OCR 不可用或失败时，独立工具返回 `available: false`，几何测量仍可继续；候选截断会进入测量 warnings。

| 完整字段路径 | 类型、默认与约束 | 含义 | 写入者 → 权威位置 → 读取者 |
|---|---|---|---|
| OCRSnippet.snippet_id | str，无默认 | OCR 顺序生成的片段 ID | OCR recognizer → 调用期内存 → 轴刻度/标签关联 |
| OCRSnippet.text | str，无默认；最多 128 字符 | 去除首尾空白后的 OCR 文本 | OCR recognizer → 调用期内存 → 轴刻度与图例关联 |
| OCRSnippet.bbox_px | tuple[int, int, int, int]，无默认 | 文字框 x、y、width、height；宽高至少为 1 | OCR recognizer → 调用期内存 → 空间关联 |
| OCRSnippet.confidence | float，无默认；0–1 | OCR 置信度 | OCR recognizer → 调用期内存 → 标签/刻度置信度计算 |
| OCRObservation.snippets | tuple[OCRSnippet, ...]，无默认；最多 512 项 | 有界文字框序列 | OCR recognizer → 调用期内存 → 笛卡尔传感器 |
| OCRObservation.available | bool，无默认 | 本次 OCR 调用是否可用；不可用不阻止几何分析 | OCR recognizer → 调用期内存 → 测量传感器 |
| OCRObservation.truncated | bool，默认 False | 超过候选上限时为 True；对应测量结果会增加警告 | OCR recognizer → 调用期内存 → 测量 warnings |

### 五种观察工具的共同输入与范围

`extract_text`、`measure_bars`、`measure_lines`、`measure_scatter` 与 `measure_pie` 共享来源参数和可选 `observation_scope`。柱、线、散点结果在顶层展开 `measurement_schema.py` 的 `MEASUREMENT_PROPERTIES`；它不是一个嵌套输出对象。下表的路径以该 Schema 片段为根，逐项对应三种笛卡尔结果的同名顶层字段或嵌套字段。Pie 使用自己的极坐标结果合同。

所有 JSON 结果字段的权威位置均为对应 ToolResultFact.result；Provider 模型通过 Memory ToolMessage 读取，Agent 的 `MeasurementContent` 资源保留完整成功对象，下一轮请求构建器按资源引用读取成功 OCR/测量对象并重建标注图。source_kind、source_id、coordinate_system 由来源适配器写入，其余共同字段由传感器写入。对象字段均必需，除明示 nullable 外不以缺省代替 null。

#### 来源参数

五个观察工具都接受下列 `source_kind`、`source_id` 和可选范围字段，拒绝额外属性，并且不要求先调用 `load_image`。

| 完整字段路径 | 类型、约束 | 含义 | 写入者 → 权威位置 → 读取者 |
|---|---|---|---|
| SOURCE_PARAMETERS.source_kind | string，枚举 attachment、panel | 选择来源服务 | Provider 模型 → ToolCallFact / ToolInvocation → 来源解析器 |
| SOURCE_PARAMETERS.source_id | string，长度 1–128 | 选定来源的不透明 ID，必须命中 RunExecutionState 授权清单 | Provider 模型 → ToolCallFact / ToolInvocation → 来源解析器；未授权时不读字节 |
| SOURCE_PARAMETERS.observation_scope | 对象，可选；仅允许 include、exclude | 对图像指定本次调用期观察范围；省略时观察完整来源 | Provider 模型 → ToolCallFact.arguments_json / ToolInvocation → handler 校验 → 像素 mask；不写入 RunExecutionState |
| OBSERVATION_SCOPE.include | Polygon 数组，可选；若存在为 1–4 个 Polygon | 多个包含区域的并集；未提供 include 时默认包含全图 | Provider 模型 → ToolCallFact.arguments_json → 范围解析器 |
| OBSERVATION_SCOPE.exclude | Polygon 数组，可选；若存在为 1–4 个 Polygon | 多个排除区域的并集；与 include 重叠时排除优先 | Provider 模型 → ToolCallFact.arguments_json → 范围解析器 |
| OBSERVATION_SCOPE.include[] / OBSERVATION_SCOPE.exclude[] | `ScopePoint[]`；每个 Polygon 含 3–32 个点 | 一个闭合观察多边形；坐标按所选来源图像宽高归一化到 0–1000 | Provider 模型 → ToolCallFact.arguments_json → 原尺寸 mask 构造器 |
| OBSERVATION_SCOPE.include[][] / OBSERVATION_SCOPE.exclude[][] | 整数二元组 `[x, y]`；每项 0–1000 | 一个归一化顶点；额外维度、浮点数和越界值拒绝 | Provider 模型 → ToolCallFact.arguments_json → 原尺寸 mask 构造器 |

范围对象本身若同时缺少 `include` 与 `exclude`、包含未知字段、数组/点数越界或结果掩码不含任何像素，工具返回有界结构化失败，不会回退到全图分析。每个顶点按原始图像尺寸栅格化；处理保留原图尺寸且不裁剪缩放，输出框和几何继续使用完整 Attachment/Panel 坐标。掩码外像素不作为几何、OCR 或标签关联证据；OCR 文字框必须完整落在有效区域内才会保留。

#### extract_text 结果字段

独立 OCR 工具返回受限文字观察；结果整体是 `ToolResultFact.result`，字段由 OCR handler 写入，模型从 ToolMessage 读取，Agent 仅用其授权来源和结果临时重建标注图。对象拒绝未声明字段；OCR 未完成仍是成功的工具结果，使用 `available: false` 和空 snippets 表示，不伪造识别文本。

| 完整字段路径 | 类型、必填与约束 | 含义 | 写入者 → 权威位置 → 读取者 |
|---|---|---|---|
| `extract_text.result.source_kind` | string，必填；`attachment` 或 `panel` | 实际授权来源种类 | 来源适配器 → `ToolResultFact.result` → Memory ToolMessage / 标注器 |
| `extract_text.result.source_id` | string，必填；长度 1–128 | 实际授权来源 ID | 来源适配器 → `ToolResultFact.result` → Memory ToolMessage / 标注器 |
| `extract_text.result.image_size` | object，必填；仅含 `width`、`height` | 完整来源图像尺寸 | OCR handler → `ToolResultFact.result` → Agent / Memory |
| `extract_text.result.image_size.width` | integer，必填；1–100000 | 来源图像宽度，像素 | OCR handler → `ToolResultFact.result` → Agent / Memory |
| `extract_text.result.image_size.height` | integer，必填；1–100000 | 来源图像高度，像素 | OCR handler → `ToolResultFact.result` → Agent / Memory |
| `extract_text.result.coordinate_system` | string，必填；`attachment_px` 或 `panel_px` | `bbox_px` 使用的完整源图坐标系 | 来源适配器 → `ToolResultFact.result` → Agent / Memory |
| `extract_text.result.available` | bool，必填 | 本次 OCR 是否完成；完成但无文字时仍为 true | OCR recognizer → `ToolResultFact.result` → Agent / Memory |
| `extract_text.result.truncated` | bool，必填 | 超过 512 片段或单段 128 字符限制时为 true | OCR recognizer → `ToolResultFact.result` → Agent / Memory |
| `extract_text.result.snippets` | OCRSnippet[]，必填；最多 512 项 | 有序文字及像素框；无识别文字或 OCR 不可用时为空 | OCR recognizer / handler → `ToolResultFact.result` → Memory / 标注器 |
| `extract_text.result.snippets[].snippet_id` | string，必填；长度 1–32；本结果内稳定唯一 | 片段的结果内身份 | OCR recognizer → `ToolResultFact.result` → Memory / 标注器 |
| `extract_text.result.snippets[].text` | string，必填；1–128 字符 | 截断后的 OCR 文本 | OCR recognizer → `ToolResultFact.result` → Memory / 标注器 |
| `extract_text.result.snippets[].bbox_px` | integer[4]，必填；四项各 0–100000，输出宽高至少为 1 | 完整源图中的 `[x, y, width, height]` 文字框 | OCR recognizer → `ToolResultFact.result` → Memory / 标注器 |
| `extract_text.result.snippets[].confidence` | number，必填；0–1 | 识别置信度 | OCR recognizer → `ToolResultFact.result` → Memory |

`available: true` 且 `snippets: []` 表示 OCR 完成但未识别到文本；`available: false` 且 `snippets: []` 表示 OCR 不可用或未能完成。授权失败和图像读取失败走有界结构化工具错误，不伪装成 OCR 空结果。

#### MEASUREMENT_PROPERTIES 共同结果字段

| 完整字段路径 | 类型、必填与约束 | 含义 | 写入者 |
|---|---|---|---|
| MEASUREMENT_PROPERTIES.source_kind | string，必填；attachment 或 panel | 与实际授权来源一致 | 来源适配器 |
| MEASUREMENT_PROPERTIES.source_id | string，必填；长度 1–128 | 实际被测来源 ID | 来源适配器 |
| MEASUREMENT_PROPERTIES.image_size | object，必填；只含 width、height | 解码后的源图尺寸 | 传感器 |
| MEASUREMENT_PROPERTIES.image_size.width | integer，必填；1–100000 | 图像宽度，像素 | 传感器 |
| MEASUREMENT_PROPERTIES.image_size.height | integer，必填；1–100000 | 图像高度，像素 | 传感器 |
| MEASUREMENT_PROPERTIES.coordinate_system | string，必填；attachment_px 或 panel_px | 源图像坐标系 | 来源适配器 |
| MEASUREMENT_PROPERTIES.status | string，必填；measured、partial、no_evidence、unsupported 之一 | 结果完整性，不保证所有字段均有数值 | 传感器 |
| MEASUREMENT_PROPERTIES.plot_area_px | object 或 null，必填 | 候选绘图区；无证据时可空 | 传感器 |
| MEASUREMENT_PROPERTIES.plot_area_px.x | integer，必填；≥0 | 绘图区左上角 x | 传感器 |
| MEASUREMENT_PROPERTIES.plot_area_px.y | integer，必填；≥0 | 绘图区左上角 y | 传感器 |
| MEASUREMENT_PROPERTIES.plot_area_px.width | integer，必填；≥1 | 绘图区宽度 | 传感器 |
| MEASUREMENT_PROPERTIES.plot_area_px.height | integer，必填；≥1 | 绘图区高度 | 传感器 |
| MEASUREMENT_PROPERTIES.axes | object，必填；恰含 x、y | 横轴与纵轴观察 | 笛卡尔轴处理 |
| MEASUREMENT_PROPERTIES.axes.{x,y} | object，必填；恰含下列六字段 | 单条轴观察；花括号仅表示分别展开为 axes.x 和 axes.y | 笛卡尔轴处理 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.kind | string，必填；numeric、categorical、unknown 之一 | 轴类别 | 笛卡尔轴处理 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.label_text | string 或 null，必填 | OCR 关联的轴标题 | OCR/轴关联 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.label_confidence | number 或 null，必填；当前计算值在 0–1 | 轴标题关联置信度 | OCR/轴关联 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.points_px | 恰含两个 PixelPoint 的数组或 null，必填 | 拟合轴段端点；PixelPoint 的坐标均为 0–100000 的数值 | 笛卡尔轴处理 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.points_px[] | number[2]，条件存在；每项恰含 x、y | 单个像素坐标点 | 笛卡尔轴处理 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.ticks | TickObservation 数组，必填 | 与该轴关联的 OCR 刻度或类别文字 | OCR/轴关联 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.ticks[].id | string，必填；长度 1–64 | 结果内稳定刻度 ID | OCR/轴关联 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.ticks[].text | string，必填；长度 1–128 | OCR 原文 | OCR |
| MEASUREMENT_PROPERTIES.axes.{x,y}.ticks[].value | number 或 null，必填 | 可解析的数值刻度；类别文字为 null | 数值文本解析 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.ticks[].bbox_px | integer[4]，必填；每项 0–100000 | OCR 框 [x, y, width, height] | OCR |
| MEASUREMENT_PROPERTIES.axes.{x,y}.ticks[].point_px | number[2]，必填；每项 0–100000 | 刻度框中心在图像坐标中的位置 | OCR/轴关联 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.ticks[].confidence | number，必填；0–1 | OCR 置信度 | OCR |
| MEASUREMENT_PROPERTIES.axes.{x,y}.calibration | Calibration 或 null，必填 | 线性轴拟合结果；无法拟合时为 null | 笛卡尔轴处理 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.calibration.slope | number，条件必填 | 每像素单位变化率 | 线性拟合 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.calibration.intercept | number，条件必填 | 线性拟合截距 | 线性拟合 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.calibration.residual_value | number，必填于对象；≥0 | 数值刻度拟合的均方根残差 | 线性拟合 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.calibration.support_count | integer，必填于对象；≥2 | 参与拟合的不同数值刻度数 | 线性拟合 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.calibration.support_span_px | number，必填于对象；≥0 | 刻度在轴上的像素跨度 | 线性拟合 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.calibration.confidence | number，必填于对象；0–1 | 标定置信度 | 线性拟合 |
| MEASUREMENT_PROPERTIES.axes.{x,y}.calibration.calibrated | bool，必填于对象 | 是否通过标定门槛；false 时不生成该轴的图表单位坐标 | 线性拟合 |
| MEASUREMENT_PROPERTIES.confidence | object，必填；恰含四项 | 总体、几何、标定、关联置信度 | 测量传感器 |
| MEASUREMENT_PROPERTIES.confidence.overall | number，必填；0–1 | 总体置信度 | 测量传感器 |
| MEASUREMENT_PROPERTIES.confidence.geometry | number，必填；0–1 | 几何检测置信度 | 测量传感器 |
| MEASUREMENT_PROPERTIES.confidence.calibration | number，必填；0–1 | 轴标定置信度 | 测量传感器 |
| MEASUREMENT_PROPERTIES.confidence.association | number，必填；0–1 | 类别、系列或刻度关联置信度 | 测量传感器 |
| MEASUREMENT_PROPERTIES.warnings | string 数组，必填；整体受 ToolRuntime 大小上限约束 | 歧义、缺失或不支持情况 | 测量传感器 |
| MEASUREMENT_PROPERTIES.warnings[] | string，必填；每项最多 256 字符 | 单条有界警告 | 测量传感器 |

共享 Calibration 只使用至少两个不同数值、不同轴位置的 OCR 刻度拟合。当前通过门槛要求刻度支持跨度至少 40 px、均方根残差不超过 max(1.5, 数值跨度的 8%)、置信度至少 0.35。门槛未通过时保留像素几何与刻度观察，数值坐标为 null。对象与数组元素的严格 Schema 见 [measurement_schema.py](../../src/figura/tools/implementations/measurement_schema.py) 和各工具 adapter。

### measure_bars

处理授权来源中的垂直、水平及候选斜向柱形。保留柱体像素几何；图表单位 value 仅在基线和值轴线性标定有效时产生。类别 tick 与 legend 文字属于 OCR 关联候选，警告不会自动触发重测。

共同 source 参数见上节；结果含 MEASUREMENT_PROPERTIES 的全部字段，再加下表字段。所有 result 对象拒绝额外属性；除 stack 明确可选外，表中字段均必需。全部 JSON 字段写入 ToolResultFact.result；柱传感器负责几何与计算值，轴关联值使用共享笛卡尔处理；Agent Memory ToolMessage 消费结果，`MeasurementContent` 资源按调用引用完整保留结果，overlay renderer 仅在后续请求中临时生成图像。

| 完整字段路径 | 类型、必填与约束 | 含义 | 写入者 |
|---|---|---|---|
| measure_bars.result.orientation | string，必填；vertical、horizontal、oblique、unknown 之一 | 柱体方向 | 柱传感器 |
| measure_bars.result.bar_mode | string，必填；single、grouped、stacked、unknown 之一 | 柱体分组模式 | 柱传感器 |
| measure_bars.result.baseline | object 或 null，必填 | 零基线拟合 | 柱传感器 |
| measure_bars.result.baseline.points_px | 两个 PixelPoint 的数组，条件必填 | 基线端点 | 柱传感器 |
| measure_bars.result.baseline.points_px[] | integer[2]，条件存在；每项 0–100000 | 基线的一个像素点 | 柱传感器 |
| measure_bars.result.baseline.axis | string，条件必填；x 或 y | 基线所在轴 | 柱传感器 |
| measure_bars.result.baseline.slope | number，条件必填 | 基线斜率 | 柱传感器 |
| measure_bars.result.baseline.intercept | number，条件必填 | 基线截距 | 柱传感器 |
| measure_bars.result.baseline.residual_px | number，条件必填；≥0 | 基线像素拟合残差 | 柱传感器 |
| measure_bars.result.baseline.confidence | number，条件必填；0–1 | 基线置信度 | 柱传感器 |
| measure_bars.result.series | SeriesObservation 数组，必填 | 颜色系列 | 柱传感器/图例关联 |
| measure_bars.result.series[].id | string，必填；长度 1–32 | 结果内系列 ID | 柱传感器 |
| measure_bars.result.series[].color | string，必填；小写 #rrggbb | 系列颜色 | 柱传感器 |
| measure_bars.result.series[].label | string 或 null，必填；最多 128 字符 | OCR 关联的图例文字 | 图例关联 |
| measure_bars.result.series[].label_confidence | number 或 null，必填；非空值 0–1 | 图例关联置信度 | 图例关联 |
| measure_bars.result.bars | BarObservation 数组，必填 | 柱体候选，按结果顺序排列 | 柱传感器 |
| measure_bars.result.bars[].id | integer，必填；≥1 | 结果内柱 ID | 柱传感器 |
| measure_bars.result.bars[].category_index | integer，必填；≥1 | 一基类别序号 | 柱传感器 |
| measure_bars.result.bars[].category_label | string 或 null，必填；非空值最多 128 字符 | 类别轴 OCR 文本 | 类别关联 |
| measure_bars.result.bars[].category_tick_id | string 或 null，必填；非空值最多 64 字符 | 关联的结果内类别刻度 ID | 类别关联 |
| measure_bars.result.bars[].series_id | string，必填；长度 1–32 | 对应 series[].id | 柱传感器 |
| measure_bars.result.bars[].geometry | BarGeometry，必填 | 柱体像素边界 | 柱传感器 |
| measure_bars.result.bars[].geometry.bbox_px | integer[4]，必填；每项 0–100000 | [x, y, width, height] 外接框 | 柱传感器 |
| measure_bars.result.bars[].geometry.polygon_px | 四个 PixelPoint 的数组，必填 | 矩形四角 | 柱传感器 |
| measure_bars.result.bars[].geometry.polygon_px[] | integer[2]；每项 0–100000 | 一个矩形角点 | 柱传感器 |
| measure_bars.result.bars[].measure | object，必填；恰含三项 | 柱长、比例和校准图表值 | 柱传感器 |
| measure_bars.result.bars[].measure.value_length_px | number 或 null，必填 | 相对基线的有符号像素长度 | 柱传感器 |
| measure_bars.result.bars[].measure.ratio_to_shortest | number 或 null，必填；非空值 ≥1 | 相对最短有效柱的长度比例 | 柱传感器 |
| measure_bars.result.bars[].measure.value | number 或 null，必填 | 标定通过后的图表单位数值；未标定或基线无效时为 null | 柱传感器 |
| measure_bars.result.bars[].stack | object 或 null，可选 | 堆叠段总量观察；非堆叠柱可省略此键 | 柱传感器 |
| measure_bars.result.bars[].stack.segment_index | integer，条件必填；≥1 | 堆叠类别中的一基段序号 | 柱传感器 |
| measure_bars.result.bars[].stack.total_length_px | number 或 null，条件必填；非空值 ≥0 | 堆叠总像素长度 | 柱传感器 |
| measure_bars.result.bars[].stack.total_geometry | BarGeometry，条件必填 | 堆叠总量几何，字段同 bars[].geometry | 柱传感器 |
| measure_bars.result.bars[].stack.total_value | number 或 null，条件必填 | 标定通过后的堆叠总数值 | 柱传感器 |

### measure_lines

处理授权来源中的多颜色折线。trace 保存一个或多个彼此独立的折线片段，不补齐中断段；存在显式 marker 时按 marker 输出点，没有 marker 时只在可关联的 x 轴刻度采样。图表单位 x、y 坐标分别要求对应轴标定通过；分类 x 轴保留类别标签而不伪造数值。

结果含 MEASUREMENT_PROPERTIES 的全部字段和 series。所有 JSON 字段写入 ToolResultFact.result；折线传感器写入轨迹、采样点与几何字段，颜色和 legend label 由颜色/图例关联处理。Memory ToolMessage 是模型读取方式，Agent 以 `MeasurementContent` 资源保留完整调用结果，覆盖图只在下一请求调用期生成。

| 完整字段路径 | 类型、必填与约束 | 含义 | 写入者 |
|---|---|---|---|
| measure_lines.result.series | LineSeries 数组，必填 | 多颜色曲线系列 | 折线传感器 |
| measure_lines.result.series[].id | string，必填；长度 1–32 | 结果内系列 ID | 折线传感器 |
| measure_lines.result.series[].color | string，必填；小写 #rrggbb | 系列颜色 | 折线传感器 |
| measure_lines.result.series[].label | string 或 null，必填；非空值最多 128 字符 | OCR 关联图例标签 | 图例关联 |
| measure_lines.result.series[].label_confidence | number 或 null，必填；非空值 0–1 | 标签关联置信度 | 图例关联 |
| measure_lines.result.series[].trace | PixelPoint[][]，必填；每条 polyline 至少两点 | 保留缺口的轨迹片段；不跨缺口连接 | 折线传感器 |
| measure_lines.result.series[].trace[][] | number[2]，条件存在；坐标各 0–100000 | 轨迹上的像素点 [x,y] | 折线传感器 |
| measure_lines.result.series[].points | LinePoint 数组，必填 | marker 或轴刻度采样观察 | 折线传感器 |
| measure_lines.result.series[].points[].id | string，必填；长度 1–64 | 结果内点 ID | 折线传感器 |
| measure_lines.result.series[].points[].position_px | number[2]，必填；坐标各 0–100000 | 点的来源像素位置 | 折线传感器 |
| measure_lines.result.series[].points[].x_value | number 或 null，必填 | x 轴数值标定通过后的坐标 | 折线传感器 |
| measure_lines.result.series[].points[].y_value | number 或 null，必填 | y 轴数值标定通过后的坐标 | 折线传感器 |
| measure_lines.result.series[].points[].x_tick_id | string 或 null，必填；非空值最多 64 字符 | 关联的 x 轴刻度 | 折线传感器 |
| measure_lines.result.series[].points[].x_category_label | string 或 null，必填；非空值最多 128 字符 | 分类 x 轴文字，不作为数值坐标 | 折线传感器 |
| measure_lines.result.series[].points[].source | string，必填；marker 或 axis_tick_sample | 该点来自显式标记或轴刻度采样 | 折线传感器 |
| measure_lines.result.series[].points[].confidence | number，必填；0–1 | 点观察置信度 | 折线传感器 |

### measure_scatter

检测授权来源中的可见散点和颜色系列。x、y 数值独立受对应轴标定门槛控制。merged、occluded、dense、overlap 只描述可见的不确定区域，不推断隐藏点的精确数量。

结果含 MEASUREMENT_PROPERTIES 的全部字段和 series。所有 JSON 字段写入 ToolResultFact.result；散点传感器写入点位置、半径、标定坐标和不确定标志，颜色/图例关联写入系列字段。Memory ToolMessage 是模型读取方式，Agent 以 `MeasurementContent` 资源保留完整调用结果，覆盖图只在下一请求调用期生成。

| 完整字段路径 | 类型、必填与约束 | 含义 | 写入者 |
|---|---|---|---|
| measure_scatter.result.series | ScatterSeries 数组，必填 | 可见颜色系列 | 散点传感器 |
| measure_scatter.result.series[].id | string，必填；长度 1–32 | 结果内系列 ID | 散点传感器 |
| measure_scatter.result.series[].color | string，必填；小写 #rrggbb | 系列颜色 | 散点传感器 |
| measure_scatter.result.series[].label | string 或 null，必填；非空值最多 128 字符 | OCR 关联图例标签 | 图例关联 |
| measure_scatter.result.series[].label_confidence | number 或 null，必填；非空值 0–1 | 标签关联置信度 | 图例关联 |
| measure_scatter.result.series[].points | ScatterPoint 数组，必填 | 可见点候选 | 散点传感器 |
| measure_scatter.result.series[].points[].id | string，必填；长度 1–64 | 结果内点 ID | 散点传感器 |
| measure_scatter.result.series[].points[].position_px | number[2]，必填；坐标各 0–100000 | 来源像素位置 [x,y] | 散点传感器 |
| measure_scatter.result.series[].points[].x_value | number 或 null，必填 | x 轴标定通过后的图表坐标 | 散点传感器 |
| measure_scatter.result.series[].points[].y_value | number 或 null，必填 | y 轴标定通过后的图表坐标 | 散点传感器 |
| measure_scatter.result.series[].points[].x_tick_id | string 或 null，必填；非空值最多 64 字符 | 最近的 x 轴刻度关联 | 散点传感器 |
| measure_scatter.result.series[].points[].y_tick_id | string 或 null，必填；非空值最多 64 字符 | 最近的 y 轴刻度关联 | 散点传感器 |
| measure_scatter.result.series[].points[].radius_px | number 或 null，必填；非空值 ≥0 | 可见组件的像素半径估计 | 散点传感器 |
| measure_scatter.result.series[].points[].confidence | number，必填；0–1 | 点检测置信度 | 散点传感器 |
| measure_scatter.result.series[].points[].flags | string 数组，必填；每项为 merged、occluded、dense、overlap 之一 | 可见重叠、融合或密集不确定性 | 散点传感器 |

### measure_pie

测量授权来源中的普通二维圆形饼图。结果采用源图坐标中的圆心/半径和极坐标扇区，不创建笛卡尔轴，也不从 OCR 标签、颜色或图形外观反推源数据值。`ratio` 只表示 `sweep_angle_deg / 360`：总角度覆盖至少 0.80 且扇区平均径向边界支持至少 0.56 时才为非空；整体状态为 `measured` 还要求所有已检测扇区比例非空、扇区总角度与 360 度相差不超过 12 度、非空比例之和与 1.0 相差不超过 0.035。证据不足时保留可见角度并以 `partial`、空比例和警告表达不确定性；透视、3D、爆炸、椭圆及甜甜圈形状以 `unsupported` 表达。观察范围同时限制几何、OCR 与标签关联。结果 Schema 拒绝额外字段。

| 完整字段路径 | 类型、必填与约束 | 含义 | 写入者 → 权威位置 → 读取者 |
|---|---|---|---|
| `measure_pie.result.source_kind` | string，必填；`attachment` 或 `panel` | 实际授权来源种类 | 来源适配器 → `ToolResultFact.result` → Memory / Agent 投影 |
| `measure_pie.result.source_id` | string，必填；长度 1–128 | 实际授权来源 ID | 来源适配器 → `ToolResultFact.result` → Memory / Agent 投影 |
| `measure_pie.result.image_size` | object，必填；仅含 `width`、`height` | 完整来源图像尺寸 | Pie 传感器 → `ToolResultFact.result` → Memory / Agent |
| `measure_pie.result.image_size.width` | integer，必填；1–100000 | 来源图像宽度，像素 | Pie 传感器 → `ToolResultFact.result` → Memory / Agent |
| `measure_pie.result.image_size.height` | integer，必填；1–100000 | 来源图像高度，像素 | Pie 传感器 → `ToolResultFact.result` → Memory / Agent |
| `measure_pie.result.coordinate_system` | string，必填；`attachment_px` 或 `panel_px` | 圆心、半径相关位置所用源图坐标系 | 来源适配器 → `ToolResultFact.result` → Memory / 标注器 |
| `measure_pie.result.status` | string，必填；`measured`、`partial`、`no_evidence`、`unsupported` 之一 | 可支持的扇区观察完整性 | Pie 传感器 → `ToolResultFact.result` → Agent / Memory |
| `measure_pie.result.plot_region` | object 或 null，必填 | 可识别的圆形区域；无法建立时为 null | Pie 传感器 → `ToolResultFact.result` → Memory / 标注器 |
| `measure_pie.result.plot_region.center_px` | number[2]，条件必填；每项 0–100000 | `[x, y]` 圆心；`x` 向右、`y` 向下 | Pie 传感器 → `ToolResultFact.result` → Memory / 标注器 |
| `measure_pie.result.plot_region.radius_px` | number，条件必填；`0 < value ≤ 100000` | 源图像像素半径 | Pie 传感器 → `ToolResultFact.result` → Memory / 标注器 |
| `measure_pie.result.sectors` | PieSector[]，必填；最多 512 项 | 按起始角升序排列的可见扇区 | Pie 传感器 → `ToolResultFact.result` → Memory / Agent / 标注器 |
| `measure_pie.result.sectors[].id` | integer，必填；1–512 | 本结果中的扇区 ID | Pie 传感器 → `ToolResultFact.result` → Memory / 标注器 |
| `measure_pie.result.sectors[].start_angle_deg` | number，必填；`0 ≤ value < 360` | 扇区起始角；0 度朝图像 12 点方向，顺时针增加 | Pie 传感器 → `ToolResultFact.result` → Memory / 标注器 |
| `measure_pie.result.sectors[].sweep_angle_deg` | number，必填；`0 < value ≤ 360` | 扇区覆盖角度 | Pie 传感器 → `ToolResultFact.result` → Memory / 标注器 |
| `measure_pie.result.sectors[].ratio` | number 或 null，必填；非空值 0–1 | 有足够角度覆盖和边界证据时的角度占比 | Pie 传感器 → `ToolResultFact.result` → Agent / Memory |
| `measure_pie.result.sectors[].color` | string 或 null，必填；非空值匹配 `#RRGGBB` | 扇区近似颜色，不代表数据值 | Pie 传感器 → `ToolResultFact.result` → Agent / Memory / 标注器 |
| `measure_pie.result.sectors[].label_text` | string 或 null，必填；非空值最多 128 字符 | 与扇区关联的 OCR 文字 | OCR / 扇区关联 → `ToolResultFact.result` → Agent / Memory / 标注器 |
| `measure_pie.result.sectors[].label_confidence` | number 或 null，必填；非空值 0–1 | OCR 标签与扇区的关联置信度 | 扇区关联 → `ToolResultFact.result` → Agent / Memory |
| `measure_pie.result.sectors[].confidence` | number，必填；0–1 | 扇区几何/分割置信度 | Pie 传感器 → `ToolResultFact.result` → Agent / Memory |
| `measure_pie.result.confidence` | object，必填；恰含 `overall`、`geometry`、`segmentation`、`association` | 饼图结果的分维度置信度 | Pie 传感器 → `ToolResultFact.result` → Agent / Memory |
| `measure_pie.result.confidence.overall` | number，必填；0–1 | 综合置信度 | Pie 传感器 → `ToolResultFact.result` → Agent / Memory |
| `measure_pie.result.confidence.geometry` | number，必填；0–1 | 圆形几何识别置信度 | Pie 传感器 → `ToolResultFact.result` → Agent / Memory |
| `measure_pie.result.confidence.segmentation` | number，必填；0–1 | 扇区分割和覆盖置信度 | Pie 传感器 → `ToolResultFact.result` → Agent / Memory |
| `measure_pie.result.confidence.association` | number，必填；0–1 | OCR 标签关联置信度 | Pie 传感器 → `ToolResultFact.result` → Agent / Memory |
| `measure_pie.result.warnings` | string[]，必填；最多 32 项，每项最多 256 字符 | OCR 不可用、证据缺口或不支持形状等限制 | Pie 传感器 → `ToolResultFact.result` → Agent / Memory |

### 观察标注图与失败边界

视觉反馈不是新的工具结果或持久模型。AgentRequestBuilder 只检查当前 Run 最新模型响应对应的完整已提交工具批次，并以类型化资源引用调用 Agent 的 RunExecutionImageReader：成功 `load_image` 的同一来源去重后读取原图；每个成功 `extract_text` 和四种测量资源从授权源图及完整结果重建标注图；成功 render 资源读取经摘要验证的私有 PNG。混合批次仍按调用顺序；更早批次和旧 Run 的图像不再附加。OCR/测量标注 PNG 在调用期生成，不写 ToolResultFact、RunExecutionState、Panel 或 Web DTO。

来源 ID 未授权时 handler 在读取图像字节前返回有界工具失败。可读图像但没有候选时以 `no_evidence` 成功返回；不支持或证据不足以 `partial`/`unsupported` 和 warnings 表达。独立 OCR 不可用时返回 `available: false`，不会阻止笛卡尔或 Pie 几何候选；标注源图缺失、图像尺寸与提交结果不符、覆盖图无效或请求图片超限时，Agent 在 Provider attempt claim 前失败。ToolDefinition 与输入/结果 Schema 由各工具适配器及共享 Schema 定义；主规格见 [OCR](../../openspec/figura/openspec/specs/ocr-text-observation/spec.md)、[柱状图](../../openspec/figura/openspec/specs/bar-chart-measurement/spec.md)、[折线图](../../openspec/figura/openspec/specs/line-chart-measurement/spec.md)、[散点图](../../openspec/figura/openspec/specs/scatter-chart-measurement/spec.md)和[饼图](../../openspec/figura/openspec/specs/pie-chart-measurement/spec.md)。

## 7. 图表画布组装工具

`assemble_chart_figure` 的输入是一个完整 ChartFigure JSON 对象，不再增加包装字段。完整图表、布局、子图和 MeasurementRef 字段只在[Charts 专题](charts.md#4-完整模型字段)定义；此处记录工具执行、跨域校验和持久边界。代码见[工具 handler](../../src/figura/tools/implementations/assemble_chart_figure.py)、[Gateway Registry 装配](../../src/figura/bootstrap.py)和[RunExecutionState 投影](../../src/figura/agent/execution_state.py)。ChartFigure 字段合同见[已同步主规格](../../openspec/figura/openspec/specs/chart-figure-assembly/spec.md)；关联 change 已归档至[实施方案](../../openspec/figura/openspec/changes/archive/2026-09-29-add-figura-chart-figure-assembly/design.md)。

### 调用流转

1. ToolRuntime 先以 `CHART_FIGURE_SCHEMA` 拒绝缺失字段、额外字段、类型不符及越界输入；handler 再用 Charts codec 解析 canonical Figure，并运行 `validate_chart_figure` 验证唯一 chart ID、布局和全部嵌套 ChartSpecData。
2. handler 为本次调用读取新鲜的同 Session `RunExecutionState`，并按 `ToolResourceRef("measurement", run_id, call_id)` 精确查询。每个 `measurement_refs` 必须命中已提交成功的 MeasurementContent；支持先前终态 Run，也支持目标 Run 中已经先提交的结果。不存在、失败、尚未提交、未授权来源或其他 Session 的引用都会使整份 Figure 失败，并返回相应的 JSON Pointer `field_path`。引用为空表示该子图没有选择测量，不从文本或数据值推断引用。
3. 全部校验通过后，工具返回摘要。任一子图或引用失败时没有部分成功结果；ToolRuntime 将有界错误结果交给 DurableToolExecutor，执行事实仍由 Runtime 提交。

### 成功结果合同

成功结果恰含下列字段；对象不允许额外属性。Charts 与引用数组顺序保留。字段写入者为 handler，权威位置先是调用期 ToolExecutionResult，随后是 Runtime `ToolResultFact.result`；Agent 只将其需要的摘要构造成调用期 Figure 投影。

| 完整字段路径 | 类型、必填与约束 | 含义 |
|---|---|---|
| `assemble_chart_figure.result.figure_ref` | object，必填；恰含 `run_id`、`call_id` | 成功组装工具调用的稳定身份；Figure 不另生成 ID |
| `assemble_chart_figure.result.figure_ref.run_id` | string，必填且非空 | 当前执行 Run ID |
| `assemble_chart_figure.result.figure_ref.call_id` | string，必填且非空 | 当前模型逻辑工具调用 ID |
| `assemble_chart_figure.result.figure_digest` | string，必填；64 位小写十六进制 | 完整 ChartFigure 规范 JSON 的 SHA-256 |
| `assemble_chart_figure.result.title` | string，必填；最多 160 字符 | Figure 标题；输入省略时为空文本 |
| `assemble_chart_figure.result.charts` | object 数组，必填；1–4 项 | 与 ChartFigure.charts 同序的子图摘要 |
| `assemble_chart_figure.result.charts[].chart_id` | string，必填；匹配 `[A-Za-z0-9_-]{1,64}` | Figure 内子图身份 |
| `assemble_chart_figure.result.charts[].chart_type` | string，必填；`bar`、`line`、`pie`、`scatter` 之一 | 来自对应子图 ChartSpecData.metadata |
| `assemble_chart_figure.result.charts[].title` | string，必填；最多 160 字符，可为空 | 来自对应子图 ChartSpecData.metadata.title |

完整 ChartFigure JSON 保存在成功或失败调用对应的 `ToolCallFact.arguments_json`；只有成功提交的 `ToolResultFact` 会让该 `(run_id, call_id)` 成为已接受 Figure。摘要由 `ToolResultFact.result` 提供给 Agent。没有 Figure 表、新 fact kind、独立 Figure ID 或可变更新；单独的 `render_chart_figure` 按 Figure 引用生成 PNG，完整 PNG 生命周期见下一节。digest 用于后续渲染从历史调用参数恢复并核对内容。选中的测量引用只表达模型选择，不证明子图数据与测量数值完全一致。

## 8. 图表渲染工具

`render_chart_figure` 将同一 Session 已成功组装的 ChartFigure 绘制为一张 PNG。模型输入只包含引用，不传图表数据、尺寸、主题或颜色；工具结果只有有限摘要，没有图像字节、路径或新的 Figure/render ID。处理由 Tool handler 协调：[Charts](charts.md#5-png-绘制边界)负责纯绘制，[Sources](sources.md#4-存储失败与访问边界)负责私有文件存取，Runtime 仍持久化通用工具事实，Agent 重建运行态，Web 负责预览路由。

实现见[render handler](../../src/figura/tools/implementations/render_chart_figure.py)、[Charts renderer](../../src/figura/charts/chartfigure/rendering.py)、[Sources 存储服务](../../src/figura/sources/chart_renders.py)、[Registry 装配](../../src/figura/bootstrap.py)和[Agent 请求组装](../../src/figura/agent/request.py)。合同见[Chart rendering 主规格](../../openspec/figura/openspec/specs/chart-rendering/spec.md)，change 已归档于[实施方案](../../openspec/figura/openspec/changes/archive/2026-09-29-add-figura-chart-rendering/design.md)。

### 输入字段

输入必须是恰含 `figure_ref` 的对象，`figure_ref` 必须恰含以下两个字段；不允许额外字段。工具不能接受模型指定输出文件或渲染选项。

| 完整字段路径 | JSON 类型 | 必填/约束 | 含义与校验 |
|---|---|---|---|
| `render_chart_figure.arguments.figure_ref` | object | 必填；无额外属性 | 被渲染的 Figure 工具调用引用 |
| `render_chart_figure.arguments.figure_ref.run_id` | string | 必填；1–128 字符 | 组装 Figure 的 Run opaque ID |
| `render_chart_figure.arguments.figure_ref.call_id` | string | 必填；1–256 字符 | 成功 `assemble_chart_figure` 调用的逻辑 ID |

**解析与授权：**handler 从目标 Run 的新鲜资源目录按 `ToolResourceRef("chart_figure", run_id, call_id)` 读取已接受 Figure。ChartFigureContent 已由 Agent 从已提交 assembly 调用参数完整重建并核对 canonical digest；handler 使用其中的完整 ChartFigure 交给 Charts 绘图，不再实现一条独立的 Runtime 事实查找路径。未知、失败、未提交、跨 Session、内容损坏或摘要不一致时返回有界失败，不创建可见产物。

### 成功结果字段

返回对象恰含下表字段，Tool Runtime 以结果 JSON Schema 再次校验。写入者为 render handler；调用期间先位于 ToolExecutionResult，成功提交后权威事实是 Run Runtime 的 ToolResultFact.result。PNG 字节不进入该对象或 Run 事实。

| 完整字段路径 | JSON 类型 | 必填/约束 | 含义、写入与读取 |
|---|---|---|---|
| `render_chart_figure.result.figure_ref` | object | 必填；恰含 `run_id`、`call_id` | 原样返回被渲染 Figure 引用；Agent 用它匹配接受状态 |
| `render_chart_figure.result.figure_ref.run_id` | string | 必填；1–128 字符 | 被渲染 Figure 的来源 Run ID |
| `render_chart_figure.result.figure_ref.call_id` | string | 必填；1–256 字符 | 被渲染 Figure 的 assembly call ID |
| `render_chart_figure.result.figure_digest` | string | 必填；64 位小写十六进制 | 完整规范 Figure JSON 的 SHA-256；须匹配接受 Figure |
| `render_chart_figure.result.image_sha256` | string | 必填；64 位小写十六进制 | PNG 内容 SHA-256；Agent 与 Gateway 读取文件时核对 |
| `render_chart_figure.result.media_type` | string | 必填；固定 `image/png` | 文件媒体类型；Web 返回 `image/png` |
| `render_chart_figure.result.byte_count` | integer | 必填；1–`MAX_IMAGE_BYTES` | 存储 PNG 的精确字节数，`MAX_IMAGE_BYTES` 为 24 MiB 减 64 字节 |
| `render_chart_figure.result.width` | integer | 必填；1–1280 | PNG 像素宽度 |
| `render_chart_figure.result.height` | integer | 必填；1–1962 | PNG 像素高度 |

### 持久化、重放与回看

1. Tool handler 通过 Charts 纯函数生成 PNG；Sources 使用渲染调用 `(run_id, call_id)` 派生文件名，并原子安装、校验并返回已存内容和尺寸。相同调用重放时复用既有文件并从原字节重新得到相同摘要，不创建重复文件。
2. DurableToolExecutor 随后提交普通 ToolResultFact；工具调用参数保留 Figure 引用，成功结果只保存上表摘要。没有新增 Runtime fact kind、Figure 表、render ID 或渲染元数据表。
3. Agent 资源目录以 `ToolResourceRef("chart_render", run_id, call_id)` 收录已提交渲染结果；ChartRenderContent 将 `figure_ref` 与 result/error 分开，成功 metadata 不重复存放该引用。完整状态字段归[Agent](agent.md#4-runexecutionstate-资源合同与完整字段)。未提交结果、无效引用或其他 Session 的文件不能通过运行态/Web 投影读取。
4. AgentRequestBuilder 对当前 Run 最新工具响应中的成功 render call 再读取 PNG，校验字节数、尺寸、媒体类型及 SHA-256，将图像追加到紧接着的 Provider 请求。后续 Run 不会自动重放旧 PNG 图像；模型可再次调用渲染工具按引用读取生成图。

| 错误码 | 触发边界 | 对外行为 |
|---|---|---|
| `figure_reference_not_found` | 引用不是当前 Session 的已接受 Figure | 安全失败，不访问产物 |
| `figure_unavailable` / `execution_state_unavailable` | Run 事实或状态暂时不可读 | 有界失败；仅明确存储错误可重试 |
| `figure_integrity_error` | Figure 参数无法解析、校验失败或 digest 不符 | 有界完整性失败，不返回 PNG |
| `chart_render_failed` | ChartFigure 无法生成合规 PNG | 有界渲染失败 |
| `chart_render_storage_failed` | Sources 无法写入或校验 PNG | 有界存储失败；仅 `STORAGE_ERROR` 标记可重试 |

`render_chart_figure` 的 `replay_effect` 是 `idempotent_local_write`。文件可以先于 ToolResultFact 安装；在结果未成功提交时它仍是不可从 Agent/Web 读取的孤儿，重放同一调用会验证并复用原文件。工具不会用新内容覆盖损坏或冲突的既有文件。
将 Registry 从 `figura-web-v5` 提升为 `figura-web-v6` 会使尚无结果的 v5 工具调用不能在 v6 下继续执行。部署切换前应先让 v5 Run 到达终态；该变更不添加 v5 兼容 executor。
