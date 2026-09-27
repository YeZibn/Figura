# Tool：能力定义与调用边界

> [返回总览](../figura-implementation-overview.md)。本篇拥有工具定义、注册、调用及结果合同；`ToolCallFact`、`ToolAttemptStartedFact`、`ToolResultFact` 是[Run Runtime](runtime.md#4-完整模型字段)所拥有的持久事实。

## 1. 职责与边界

`ToolRegistry` 保存有序、版本化的 `ToolDefinition`；`ToolRuntime` 解析和验证调用参数，运行同步 handler，验证有界成功结果或返回安全错误。`DurableToolExecutor` 属于 Run 执行边界，负责在调用前后提交事实。当前 Registry 基础设施已实现，但无 Figura 生产图表工具集合。

## 2. 内部流转

1. **注册**：进程组装有序 `ToolDefinition`，检查名称唯一、参数与结果 JSON Schema、描述及总大小。Registry 对外提供只读版本、定义顺序和按名查找。
2. **模型投影**：Agent 把允许的工具定义映射为 Provider 的 `FunctionTool`；模型只见名称、说明与参数 Schema，不见 handler、结果 Schema 或本地上下文。
3. **调用**：`ToolInvocation` 的 call ID、名称和 JSON 参数进入 `ToolRuntime`；解析拒绝重复键、无效数值与不符合 Schema 的内容。handler 只收到已验证参数及 `ToolContext`。
4. **结果与恢复**：成功时结果必须是有界 JSON 对象；失败时返回 `ToolExecutionError`。`replay_effect` 决定不确定结果能否安全重放或必须显式协调；ToolRuntime 自身不拥有 Run checkpoint。

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
- JSON Schema 的共享 `SchemaIssue` 字段在[共享验证合同](shared-validation.md#3-完整模型字段)定义；本篇只说明 ToolRuntime 怎样消费它。
- 代码：[合同](../../src/figura/tools/contracts.py)、[Registry](../../src/figura/tools/registry.py)、[Runtime](../../src/figura/tools/runtime.py)、[Provider 投影](../../src/figura/tools/provider.py)；主规格：[tool-runtime](../../openspec/figura/openspec/specs/tool-runtime/spec.md)、[durable-tool-execution](../../openspec/figura/openspec/specs/durable-tool-execution/spec.md)。
