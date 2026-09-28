# Tool：能力定义与调用边界

> [返回总览](../figura-implementation-overview.md)。本篇拥有工具定义、注册、调用及结果合同；`ToolCallFact`、`ToolAttemptStartedFact`、`ToolResultFact` 是[Run Runtime](runtime.md#4-完整模型字段)所拥有的持久事实。

## 1. 职责与边界

`ToolRegistry` 保存有序、版本化的 `ToolDefinition`；`ToolRuntime` 解析和验证调用参数，运行同步 handler，验证有界成功结果或返回安全错误。`DurableToolExecutor` 属于 Run 执行边界，负责在调用前后提交事实。当前工作树中的 Figura Gateway Registry 版本为 `figura-web-v2`，按顺序包含 `load_image`、`decompose_chart_image` 和 `measure_bars`。柱状图测量使用无路径输入的像素传感器；图表生成工具尚未实现。

## 2. 内部流转

1. **注册**：Gateway 组装有序 `ToolDefinition`，检查名称唯一、参数与结果 JSON Schema、描述及总大小。当前工具按 `load_image`、`decompose_chart_image`、`measure_bars` 顺序注册；Registry 对外提供只读版本、定义顺序和按名查找。
2. **模型投影**：Agent 把允许的工具定义映射为 Provider 的 `FunctionTool`；模型只见名称、说明与参数 Schema，不见 handler、结果 Schema 或本地上下文。
3. **调用**：`ToolInvocation` 的 call ID、名称和 JSON 参数进入 `ToolRuntime`；解析拒绝重复键、无效数值与不符合 Schema 的内容。handler 只收到已验证参数及 `ToolContext`。
4. **结果与恢复**：成功时结果必须是有界 JSON 对象；失败时返回 `ToolExecutionError`。图像读取和 `measure_bars` 为 `replay_safe`；Panel 分割为 `idempotent_local_write`，同一 call-scoped 幂等键恢复时复用原 Panel ID。测量没有外部副作用，恢复重放会重新读取授权图像源并运行像素传感器。`replay_effect` 决定不确定结果能否安全重放或必须显式协调；ToolRuntime 自身不拥有 Run checkpoint。

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

图像工具实现在 [`tools/implementations/image.py`](../../src/figura/tools/implementations/image.py)，测量适配器在 [`tools/implementations/measure_bars.py`](../../src/figura/tools/implementations/measure_bars.py)，纯像素传感器在 [`tools/measurements/bars.py`](../../src/figura/tools/measurements/bars.py)。[Bootstrap](../../src/figura/bootstrap.py) 注入 Agent 运行态、Attachment Service 与 Panel Service。handler 先用运行态清单授权资源，再通过 Sources 服务解析图像；结果为 Runtime 持久 `ToolResultFact` 的有界 JSON，不包含图像字节或本机路径。Panel 模型与文件由[Sources 专题](sources.md)拥有；附件、Panel 和测量投影由[Agent](agent.md#4-运行时状态字段)重建。

### `load_image`

只读图像加载工具。成功结果记入 Run 后，Agent 在紧接的下一次 Provider 请求里读取图像字节；工具结果本身只记录元数据。

| 合同 | 完整字段与边界 |
|---|---|
| 参数 | `source_kind: 'attachment' \| 'panel'`；`source_id: string`，1–128 字符。额外属性拒绝。 |
| 成功结果 | `source_kind`、`source_id`、`name`、`width`、`height`；宽高为 1–100000 的整数。额外属性拒绝。 |
| 执行效果 | `replay_safe`；授权必须命中本 Run 的 Session 图像清单。Attachment 图片名来自附件文件名，Panel 图片名来自 Panel 名。 |

### `decompose_chart_image`

按模型给出的规范化多边形生成独立 Panel PNG；所有矩形也用四点多边形表达。详细 `PanelRecord` 和 `PanelPoint` 字段见[Sources 完整模型字段](sources.md#3-完整模型字段)。

| 合同 | 完整字段与边界 |
|---|---|
| 参数 | `attachment_id: string`，1–128 字符；`panels`：1–32 个 Panel 提议。额外属性拒绝。 |
| Panel 提议 | 每项含 `name: string`（1–256 字符）和 `points`（3–64 个点）；每个点含整数 `x`、`y`，取值均为 0–1000。 |
| 成功结果 | `{ panels: [{ panel_id, name, source_attachment_id }] }`，保持输入次序；ID 是小写 64 位十六进制。不得加入点坐标、图片字节或文件路径。 |
| 执行效果 | `idempotent_local_write`；ID 从工具的 call-scoped 幂等键和 Panel 序号确定。只检查多边形及资源能安全执行，不校验语义准确度、重叠或图表类型。 |

### `measure_bars`

对整个授权附件或 Panel 图像运行纯像素传感器。它不要求先调用 `load_image`，也不接受路径、URL 或图像字节作为模型参数。来源先匹配 `RunExecutionState` 清单，再由 Attachment/Panel Service 验证 Session 所有权并读取私有字节；传感器只得到字节并返回 JSON 几何。失败的来源读取或解码映射为有界、可重试的 `ToolExecutionError`，不泄露本机路径。成功结果进入 `ToolResultFact`；Session Memory 之后以 ToolMessage 提供该结果。没有独立测量表或可修改的 measurement record；Agent 的 `MeasurementObservation` 是调用期索引投影，见[Agent 专题](agent.md#4-运行时状态字段)。

| 输入路径 | 类型与必填 | 语义和约束 | 写入者 → 权威位置 → 读取/公开 |
|---|---|---|---|
| `measure_bars.arguments.source_kind` | `string`，必填 | `attachment` 或 `panel` | Provider 模型 → 经 ToolRuntime Schema 校验的 `ToolInvocation` → handler 用它选择 Sources 服务；保留在 ToolCallFact 参数中 |
| `measure_bars.arguments.source_id` | `string`，必填 | 不透明 ID，1–128 字符；必须命中同 Session 的可用附件或 Panel 清单 | Provider 模型 → ToolCallFact 参数 → handler 与 Sources 服务；未授权时不读取图像 |

参数对象只允许以上两项；额外属性拒绝。工具定义及参数 Schema 位于[测量适配器](../../src/figura/tools/implementations/measure_bars.py)。

#### 完整成功结果字段

以下是成功 JSON Schema 的全部字段，非 Python dataclass。除明确标为可选的 `bars[].stack` 外，表列字段均必填；`null` 是字段值而不是字段缺省。每个输出字段由测量 handler 产生并随成功 `ToolResultFact.result` 成为权威持久内容，再通过 Session Memory 的 ToolMessage 进入后续模型历史；没有独立 API DTO 或就地修改规则。来源适配器写入 `source_kind`、`source_id` 和 `coordinate_system`，像素传感器写入其余测量字段。

| 完整字段路径 | 类型、必填与约束 | 含义 | 写入者 → 权威位置 → 读取/公开 |
|---|---|---|---|
| `measure_bars.result.source_kind` | `string`，必填；`attachment` \| `panel` | 与已授权输入来源类型一致 | Sources 适配器 → ToolResultFact.result → Agent ToolMessage；不独立修订 |
| `measure_bars.result.source_id` | `string`，必填；1–128 字符 | 实际测量的来源不透明 ID | Sources 适配器 → ToolResultFact.result → Agent ToolMessage；不暴露路径 |
| `measure_bars.result.image_size` | 对象，必填 | 被测源图像尺寸，恰含宽、高 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.image_size.width` | 整数，必填；1–100000 | 图像宽度，像素 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.image_size.height` | 整数，必填；1–100000 | 图像高度，像素 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.coordinate_system` | `string`，必填；`attachment_px` \| `panel_px` | 坐标绑定到整个 Attachment 或独立 Panel 图像 | Sources 适配器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.status` | `string`，必填；`measured` \| `partial` \| `no_evidence` \| `unsupported` | 观测完整性；不表示已校准图表数值 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.orientation` | `string`，必填；`vertical` \| `horizontal` \| `oblique` \| `unknown` | 检测到的柱体主方向 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bar_mode` | `string`，必填；`single` \| `grouped` \| `stacked` \| `unknown` | 检测到的单系列、分组或堆叠形态 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.plot_area_px` | 对象或 `null`，必填 | 候选绘图区像素边界；无证据时为 `null` | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.plot_area_px.x` | 整数，条件必填；≥0 | 绘图区左上 x 坐标 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.plot_area_px.y` | 整数，条件必填；≥0 | 绘图区左上 y 坐标 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.plot_area_px.width` | 整数，条件必填；≥1 | 绘图区宽度 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.plot_area_px.height` | 整数，条件必填；≥1 | 绘图区高度 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.baseline` | 对象或 `null`，必填 | 可拟合的零基线；不能可靠建立时为 `null` | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.baseline.points_px` | 两个像素点组成的数组，条件必填 | 基线两端点 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.baseline.points_px[]` | `[x, y]` 整数二元组；各值 0–100000 | 每个基线点的坐标 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.baseline.axis` | `string`，条件必填；`x` \| `y` | 拟合基线对应的轴 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.baseline.slope` | 数值，条件必填 | 拟合线斜率 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.baseline.intercept` | 数值，条件必填 | 拟合线截距 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.baseline.residual_px` | 数值，条件必填；≥0 | 基线拟合残差，像素 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.baseline.confidence` | 数值，条件必填；0–1 | 基线拟合置信度 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.series` | 数组，必填；元素为对象 | 检测到的颜色系列；不推断语义标签 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.series[].id` | `string`，必填；1–32 字符 | 结果内稳定的系列 ID | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.series[].color` | `string`，必填；小写 `#rrggbb` | 检测到的系列颜色 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars` | 数组，必填；元素为对象 | 按结果顺序排列的柱体候选 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].id` | 整数，必填；≥1 | 结果内柱体 ID | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].category_index` | 整数，必填；≥1 | 一基类别序号 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].series_id` | `string`，必填；1–32 字符 | 对应 `series[].id` | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].geometry` | 对象，必填；恰含 bbox 与四角多边形 | 柱体像素几何 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].geometry.bbox_px` | 四整数数组，必填；各值 0–100000 | `[x, y, width, height]` | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].geometry.polygon_px` | 四点数组，必填 | 柱体矩形的四角，使用来源坐标系 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].geometry.polygon_px[]` | `[x, y]` 整数二元组；各值 0–100000 | 一个四角多边形顶点 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].measure` | 对象，必填；恰含长度与比例 | 像素测量值，不含图表单位 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].measure.value_length_px` | 数值或 `null`，必填 | 相对基线的有符号像素长度；基线不确定时为 `null` | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].measure.ratio_to_shortest` | 数值 ≥1 或 `null`，必填 | 相对最短有效柱的长度比例；不能测量时为 `null` | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].stack` | 对象或 `null`，可选 | 堆叠柱段的补充总量几何；非堆叠柱可省略 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].stack.segment_index` | 整数，条件必填；≥1 | 堆叠类别中的一基段序号 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].stack.total_length_px` | 数值 ≥0 或 `null`，条件必填 | 堆叠总长；没有可靠基线时为 `null` | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.bars[].stack.total_geometry` | 几何对象，条件必填 | 堆叠总量外接框及四角；字段结构同 `bars[].geometry` | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.confidence` | 对象，必填；恰含四项 | 置信度集合 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.confidence.overall` | 数值，必填；0–1 | 总体置信度 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.confidence.geometry` | 数值，必填；0–1 | 几何检测置信度 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.confidence.baseline` | 数值，必填；0–1 | 基线置信度 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.confidence.association` | 数值，必填；0–1 | 柱体与系列关联置信度 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.warnings` | 字符串数组，必填 | 不确定、证据不完整或不支持几何的说明；不自动阻断 Agent | 像素传感器 → ToolResultFact.result → Agent ToolMessage |
| `measure_bars.result.warnings[]` | `string`，必填 | 一条测量警告文本 | 像素传感器 → ToolResultFact.result → Agent ToolMessage |

成功结果顶层及所有嵌套对象拒绝未声明字段。主要数值均处于来源图像像素坐标；即使有可靠基线，也不将长度换算成图表单位。主规格：[bar-chart-measurement](../../openspec/figura/openspec/specs/bar-chart-measurement/spec.md)。
