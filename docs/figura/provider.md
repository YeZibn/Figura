# Provider：模型请求与响应边界

> [返回总览](../figura-implementation-overview.md)。本篇拥有模型服务的调用期合同、配置、适配与规范化失败；持久 `ProviderAttempt` 和 `ProviderContinuationFact` 由[Run Runtime](runtime.md#4-完整模型字段)定义。

## 1. 职责与边界

`ProviderFactory` 根据 Run 已固定的 provider/model 选择客户端；`ProviderClient` 验证请求并通过 Qwen、DeepSeek、MiMo adapter 与模型服务交互，归一化为 `ProviderResponse` 或 `ProviderFailure`。ProviderProfile 中的凭据和 endpoint 只保留在进程配置。Provider 不决定 Run 生命周期，也不保存 Run 的独立历史。

## 2. 内部流转

1. **可用性与选择**：`ProviderSettings` 为三个 allowlist provider 各保存一份 profile；Factory 对 provider/model、配置及能力进行检查，并可返回安全的 `ProviderAvailability`。Web Gateway 的 health 路由消费该值，只返回 provider ID、固定 model ID、配置是否可用和有界 reason code，不发起 Provider 网络请求；HTTP 字段定义见[Web 边界](web-boundary.md#4-web-dto-字段)。
2. **请求**：Agent 提交 `ProviderRequest`，包含指令、按角色排列的消息、可选工具投影和选项。消息内容可为字符串或有序 TextBlock/ImageBlock。图片字节只在调用期；超界请求在远端调用前被拒绝。
3. **响应**：adapter 将模型内容、工具调用、finish reason、usage 与可选 continuation 归一化。公开响应投影省略私有 continuation；Runtime 将其与已提交响应绑定为私有持久事实。
4. **失败**：配置、输入、远端与传输失败映射到有界 `ProviderFailure`；`outcome_known` 供 Runtime/Agent 区分确定失败与结果未知。Provider 不能自行重发已被 Runtime claim 的请求。

## 3. 模型关系与共同规则

`ProviderRequest.instructions` 的元素是 `InstructionBlock`；`messages` 的元素是 `ProviderMessage`；`ProviderMessage.content` 可以是字符串或有序 `TextBlock | ImageBlock`；`tools` 的 `FunctionTool` 是[ToolDefinition](tools.md#4-完整模型字段)的模型可见投影。以下逐模型列出全部声明字段，默认值是 Python 构造默认。调用期模型不自动成为 Run 的权威事实。

## 4. 完整模型字段

### InstructionBlock

一次请求中的高优先级指令块。 **写入者：**AgentRequestBuilder。**权威位置：**调用期 ProviderRequest。**读取与公开：**Provider adapter；不单独持久化。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| InstructionBlock.role | InstructionRole | 必传 | 消息或指令角色；枚举见本页 | AgentRequestBuilder → 调用期 ProviderRequest → Provider adapter；不单独持久化 |
| InstructionBlock.content | str | 必传 | 该角色的指令文本；不是多模态消息内容 | AgentRequestBuilder → 调用期 ProviderRequest → Provider adapter；不单独持久化 |

### TextBlock

多模态消息中的文本块。 **写入者：**AgentRequestBuilder。**权威位置：**调用期 ProviderMessage。**读取与公开：**Provider adapter；输入原文另见 RunInput。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| TextBlock.text | str | 必传 | 消息内的文本块；当前初始用户块来自 RunInput.text | AgentRequestBuilder → 调用期 ProviderMessage → Provider adapter；输入原文另见 RunInput |

### ImageBlock

多模态消息中的已解析图像字节。 **写入者：**FiguraAttachmentService / AgentRequestBuilder。**权威位置：**调用期内存。**读取与公开：**Provider adapter；字节不入 Run 事实或普通日志。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ImageBlock.media_type | str | 必传 | 由图片内容验证得到的媒体类型 | FiguraAttachmentService / AgentRequestBuilder → 调用期内存 → Provider adapter；字节不入 Run 事实或普通日志 |
| ImageBlock.image_bytes | bytes | 必传 | 已验证图像字节，仅调用期内存 | FiguraAttachmentService / AgentRequestBuilder → 调用期内存 → Provider adapter；字节不入 Run 事实或普通日志 |

### ProviderToolCall

归一化模型工具调用。 **写入者：**ProviderClient / adapter。**权威位置：**调用期 ProviderResponse；提交后投影 ToolCallFact。**读取与公开：**Agent；原始参数仅内部使用。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderToolCall.call_id | str | 必传 | 模型给出的逻辑工具调用 ID | ProviderClient / adapter → 调用期 ProviderResponse；提交后投影 ToolCallFact → Agent；原始参数仅内部使用 |
| ProviderToolCall.name | str | 必传 | 模型返回的工具名称 | ProviderClient / adapter → 调用期 ProviderResponse；提交后投影 ToolCallFact → Agent；原始参数仅内部使用 |
| ProviderToolCall.arguments | str | 必传 | Provider 返回的工具参数 JSON 文本 | ProviderClient / adapter → 调用期 ProviderResponse；提交后投影 ToolCallFact → Agent；原始参数仅内部使用 |

### ProviderContinuation

Provider 私有续接数据。 **写入者：**ProviderClient / adapter。**权威位置：**调用期；提交后转 ProviderContinuationFact。**读取与公开：**AgentRequestBuilder；私有字段不公开。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderContinuation.provider_id | ProviderId | 必传 | 规范化 provider 身份 | ProviderClient / adapter → 调用期；提交后转 ProviderContinuationFact → AgentRequestBuilder；私有字段不公开 |
| ProviderContinuation.format_version | int | 必传 | Provider 私有续接格式版本 | ProviderClient / adapter → 调用期；提交后转 ProviderContinuationFact → AgentRequestBuilder；私有字段不公开 |
| ProviderContinuation.reasoning_content | str | 必传 | Provider 私有推理续接文本；不进入公开投影 | ProviderClient / adapter → 调用期；提交后转 ProviderContinuationFact → AgentRequestBuilder；私有字段不公开 |

### ProviderMessage

一次 Provider 请求中的角色消息。 **写入者：**AgentRequestBuilder。**权威位置：**调用期 ProviderRequest。**读取与公开：**Provider adapter；从执行事实重建。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderMessage.role | MessageRole | 必传 | 消息或指令角色；枚举见本页 | AgentRequestBuilder → 调用期 ProviderRequest → Provider adapter；从执行事实重建 |
| ProviderMessage.content | MessageContent | '' | 字符串或有序 TextBlock/ImageBlock；内容块完整字段见同页 | AgentRequestBuilder → 调用期 ProviderRequest → Provider adapter；从执行事实重建 |
| ProviderMessage.tool_calls | tuple[ProviderToolCall, ...] | () | 有序工具调用；可为空 | AgentRequestBuilder → 调用期 ProviderRequest → Provider adapter；从执行事实重建 |
| ProviderMessage.tool_call_id | str \| None | None | tool 角色消息对应的调用 ID | AgentRequestBuilder → 调用期 ProviderRequest → Provider adapter；从执行事实重建 |
| ProviderMessage.continuation | ProviderContinuation \| None | None | Provider 私有续接；仅在适用历史消息中存在 | AgentRequestBuilder → 调用期 ProviderRequest → Provider adapter；从执行事实重建 |

### FunctionTool

模型可见的工具声明。 **写入者：**ToolRegistry 投影。**权威位置：**调用期 ProviderRequest。**读取与公开：**Provider adapter；handler 不在此对象。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| FunctionTool.name | str | 必传 | 名称；具体语义随模型而定 | ToolRegistry 投影 → 调用期 ProviderRequest → Provider adapter；handler 不在此对象 |
| FunctionTool.parameters | Mapping[str, Any] | 必传 | 模型可见参数 JSON Schema | ToolRegistry 投影 → 调用期 ProviderRequest → Provider adapter；handler 不在此对象 |
| FunctionTool.description | str | '' | 模型可见工具说明 | ToolRegistry 投影 → 调用期 ProviderRequest → Provider adapter；handler 不在此对象 |
| FunctionTool.strict | bool \| None | None | Provider 工具严格模式选项；可空 | ToolRegistry 投影 → 调用期 ProviderRequest → Provider adapter；handler 不在此对象 |

### ProviderOptions

本次 Provider 请求的选项。 **写入者：**AgentRequestBuilder / Provider adapter。**权威位置：**调用期 ProviderRequest。**读取与公开：**Provider adapter；不作为 Run 独立事实。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderOptions.max_completion_tokens | int | 必传 | 本次输出 token 上限 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；不作为 Run 独立事实 |
| ProviderOptions.stream | bool | False | 是否流式；当前 Agent 固定 false | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；不作为 Run 独立事实 |
| ProviderOptions.thinking_mode | bool \| None | None | 本次请求的可选思考模式 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；不作为 Run 独立事实 |
| ProviderOptions.reasoning_effort | str \| None | None | 本次请求的可选推理强度 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；不作为 Run 独立事实 |
| ProviderOptions.schema_version | int | 1 | 该值或 payload 的版本号 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；不作为 Run 独立事实 |

### ProviderRequest

一次模型调用的完整规范化请求。 **写入者：**AgentRequestBuilder。**权威位置：**调用期内存。**读取与公开：**ProviderClient；不得记录图片字节或密钥。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderRequest.provider_id | ProviderId \| str | 必传 | 规范化 provider 身份 | AgentRequestBuilder → 调用期内存 → ProviderClient；不得记录图片字节或密钥 |
| ProviderRequest.model_id | str | 必传 | 固定或响应中的模型身份 | AgentRequestBuilder → 调用期内存 → ProviderClient；不得记录图片字节或密钥 |
| ProviderRequest.instructions | tuple[InstructionBlock, ...] | 必传 | 有序 system/developer 指令块 | AgentRequestBuilder → 调用期内存 → ProviderClient；不得记录图片字节或密钥 |
| ProviderRequest.messages | tuple[ProviderMessage, ...] | 必传 | 有序角色消息；由已提交事实重建 | AgentRequestBuilder → 调用期内存 → ProviderClient；不得记录图片字节或密钥 |
| ProviderRequest.options | ProviderOptions | 必传 | 本次请求的 ProviderOptions | AgentRequestBuilder → 调用期内存 → ProviderClient；不得记录图片字节或密钥 |
| ProviderRequest.tools | tuple[FunctionTool, ...] | () | 本次可用的工具投影 | AgentRequestBuilder → 调用期内存 → ProviderClient；不得记录图片字节或密钥 |

### ProviderUsage

规范化 token 用量。 **写入者：**ProviderClient / adapter。**权威位置：**响应调用期；可嵌入 ModelResponseFact。**读取与公开：**Agent/诊断；可空计数不推断为零。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderUsage.prompt_tokens | int \| None | None | 输入 token 计数；可空 | ProviderClient / adapter → 响应调用期；可嵌入 ModelResponseFact → Agent/诊断；可空计数不推断为零 |
| ProviderUsage.completion_tokens | int \| None | None | 输出 token 计数；可空 | ProviderClient / adapter → 响应调用期；可嵌入 ModelResponseFact → Agent/诊断；可空计数不推断为零 |
| ProviderUsage.total_tokens | int \| None | None | 总 token 计数；可空 | ProviderClient / adapter → 响应调用期；可嵌入 ModelResponseFact → Agent/诊断；可空计数不推断为零 |

### ProviderResponse

一次模型调用的规范化结果。 **写入者：**ProviderClient / adapter。**权威位置：**调用期；随后提交执行事实。**读取与公开：**Agent；公开投影省略 continuation。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderResponse.provider_id | ProviderId | 必传 | 规范化 provider 身份 | ProviderClient / adapter → 调用期；随后提交执行事实 → Agent；公开投影省略 continuation |
| ProviderResponse.model_id | str | 必传 | 固定或响应中的模型身份 | ProviderClient / adapter → 调用期；随后提交执行事实 → Agent；公开投影省略 continuation |
| ProviderResponse.assistant_content | str | 必传 | 模型文本内容；需按响应规则判断可否终结 | ProviderClient / adapter → 调用期；随后提交执行事实 → Agent；公开投影省略 continuation |
| ProviderResponse.tool_calls | tuple[ProviderToolCall, ...] | 必传 | 有序工具调用；可为空 | ProviderClient / adapter → 调用期；随后提交执行事实 → Agent；公开投影省略 continuation |
| ProviderResponse.finish_reason | FinishReason | 必传 | 归一化结束原因 | ProviderClient / adapter → 调用期；随后提交执行事实 → Agent；公开投影省略 continuation |
| ProviderResponse.usage | ProviderUsage \| None | None | token 用量；可空且各计数也可空 | ProviderClient / adapter → 调用期；随后提交执行事实 → Agent；公开投影省略 continuation |
| ProviderResponse.provider_response_id | str \| None | None | Provider 返回的可选响应 ID | ProviderClient / adapter → 调用期；随后提交执行事实 → Agent；公开投影省略 continuation |
| ProviderResponse.continuation | ProviderContinuation \| None | None | 私有续接值；可空且不进入公开响应 | ProviderClient / adapter → 调用期；随后提交执行事实 → Agent；公开投影省略 continuation |

### ProviderAvailability

某 provider/model 的可用性查询结果。 **写入者：**ProviderFactory。**权威位置：**调用期投影。**读取与公开：**内部调用方；只公开安全 reason_code。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderAvailability.provider_id | ProviderId | 必传 | 规范化 provider 身份 | ProviderFactory → 调用期投影 → 内部调用方；只公开安全 reason_code |
| ProviderAvailability.model_id | str | 必传 | 固定或响应中的模型身份 | ProviderFactory → 调用期投影 → 内部调用方；只公开安全 reason_code |
| ProviderAvailability.available | bool | 必传 | 该配置当前是否可用 | ProviderFactory → 调用期投影 → 内部调用方；只公开安全 reason_code |
| ProviderAvailability.reason_code | str \| None | None | 不可用时的安全原因码 | ProviderFactory → 调用期投影 → 内部调用方；只公开安全 reason_code |

### ProviderProfile

一个 provider 的进程配置。 **写入者：**ProviderSettings.from_env。**权威位置：**进程内，不入 Run。**读取与公开：**ProviderFactory；密钥与 endpoint 不公开。[定义](../../src/figura/providers/config.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderProfile.provider_id | ProviderId | 必传 | 规范化 provider 身份 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.model_id | str | 必传 | 固定或响应中的模型身份 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.api_key | str \| None | 必传 | 私有 API 凭据；不入 Run/日志/公开投影 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.base_url | str \| None | 必传 | 经校验的私有 Provider endpoint | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.timeout_seconds | float | 必传 | Provider 超时秒数 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.thinking_mode | bool | 必传 | 从进程配置解析的思考模式布尔值 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.reasoning_effort | str \| None | 必传 | 进程配置中的可选推理强度 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.configuration_error | ProviderFailureCode \| None | None | 配置校验失败码；可空 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |

### ProviderSettings

全部 allowlist provider 的进程配置集合。 **写入者：**ProviderSettings.from_env。**权威位置：**进程内，不入 Run。**读取与公开：**ProviderFactory；profiles 含私有配置。[定义](../../src/figura/providers/config.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderSettings.profiles | Mapping[ProviderId, ProviderProfile] | 必传 | 每个 allowlist ProviderId 对应一份 ProviderProfile | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；profiles 含私有配置 |

### ProviderFailure

归一化的安全 Provider 失败。 **写入者：**ProviderClient / adapter。**权威位置：**调用期；安全 code 可入 Attempt。**读取与公开：**Agent；不包含原始 SDK payload。[定义](../../src/figura/providers/errors.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderFailure.failure_code | ProviderFailureCode | 必传 | 安全失败码；成功或未定时为空 | ProviderClient / adapter → 调用期；安全 code 可入 Attempt → Agent；不包含原始 SDK payload |
| ProviderFailure.outcome_known | bool | 必传 | 是否能确定远端请求结果 | ProviderClient / adapter → 调用期；安全 code 可入 Attempt → Agent；不包含原始 SDK payload |
| ProviderFailure.transient | bool | 必传 | 该失败是否可视为临时 | ProviderClient / adapter → 调用期；安全 code 可入 Attempt → Agent；不包含原始 SDK payload |
| ProviderFailure.safe_message | str | 必传 | 可安全展示的有界失败说明 | ProviderClient / adapter → 调用期；安全 code 可入 Attempt → Agent；不包含原始 SDK payload |
| ProviderFailure.http_status | int \| None | None | 可选 HTTP 状态码 | ProviderClient / adapter → 调用期；安全 code 可入 Attempt → Agent；不包含原始 SDK payload |

## 5. 枚举与依据

- `ProviderId`：`qwen`、`deepseek`、`mimo`；固定模型分别为 `qwen3.8-flash`、`deepseek-flash`、`mimo-v2.6-flash`。`InstructionRole`：`system`、`developer`。`MessageRole`：`user`、`assistant`、`tool`。`FinishReason`：`stop`、`tool_calls`、`length`、`content_filter`、`other`。
- `ProviderFailureCode`：`configuration_missing`、`invalid_configuration`、`unsupported_provider`、`unsupported_model`、`invalid_request`、`unsupported_capability`、`provider_rejected`、`provider_unavailable`、`timeout`、`connection_error`、`incomplete_stream`、`invalid_provider_response`、`transport_error`。
- `ContentBlock = TextBlock | ImageBlock`，`MessageContent = str | tuple[ContentBlock, ...]`。Exception 类携带的错误状态由 `ProviderFailure` 或安全错误码表达，不作为另一个持久事实。
- 代码：[模型](../../src/figura/providers/models.py)、[配置](../../src/figura/providers/config.py)、[Client/Factory](../../src/figura/providers/client.py)、[适配器](../../src/figura/providers/adapters/base.py)、[错误](../../src/figura/providers/errors.py)；主规格：[model-provider](../../openspec/figura/openspec/specs/model-provider/spec.md)、[continuation 持久化](../../openspec/figura/openspec/specs/provider-continuation-persistence/spec.md)。
