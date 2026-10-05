# Provider：模型请求与响应边界

> 更新日期：2026-10-05。[返回总览](../figura-implementation-overview.md)。本篇拥有模型服务的调用期合同、配置、适配与规范化失败；持久 `ProviderAttempt` 和 `ProviderContinuationFact` 由[Run Runtime](runtime.md#4-完整模型字段)定义。

## 1. 职责与边界

`ProviderFactory` 根据 Run 已固定的 provider/model 选择客户端；`ProviderClient` 验证请求并通过 Qwen、DeepSeek、MiMo adapter 与模型服务交互，归一化为 `ProviderResponse` 或 `ProviderFailure`。ProviderProfile 中的凭据和 endpoint 只保留在进程配置。Provider 不决定 Run 生命周期，也不保存 Run 的独立历史。

## 2. 内部流转

1. **可用性与选择**：`ProviderSettings` 为三个 allowlist provider 各保存一份 profile；Factory 对 provider/model、配置及能力进行检查，并可返回安全的 `ProviderAvailability`。Web Gateway 的 health 路由消费该值，只返回 provider ID、固定 model ID、配置是否可用和有界 reason code，不发起 Provider 网络请求；HTTP 字段定义见[Web 边界](web.md#4-web-dto-字段)。
2. **本地准备**：Agent 组装 `ProviderRequest` 并创建固定 provider/model 的 client，然后调用 `prepare(request)`。该方法先校验消息、工具、图像和字节限制，再核对模型并执行 adapter 的 `build_payload`；DeepSeek thinking 工具历史的 continuation 要求也在此阶段检查。它使用统一本地 tokenizer 估算真实输入，并从可选 `ProviderProfile.context_window_tokens` 附上显示分母。有效容量和估算只供 Agent 判断是否做上下文压缩，不作为准入或输出预算。成功返回私有 `_PreparedProviderCall`，不发送网络请求，也不 claim attempt。图片字节、原生 payload 与续接内容仅留在调用期内存。
3. **领取并发送**：Agent 在锁内复查 checkpoint 并提交 ProviderAttempt claim，随后调用同一个 client 的 `dispatch(prepared)`。客户端校验 prepared 的来源 token，然后发送已经准备好的 payload 一次；不重新构造请求。其他 client 创建的 prepared 会被拒绝。Prepared 不可序列化、不持久化、不进入日志或公开 DTO。
4. **响应**：adapter 将模型内容、工具调用、finish reason、usage 与可选 continuation 归一化。公开响应投影省略私有 continuation；Runtime 将其与已提交响应绑定为私有持久事实。Agent 后续可按精确来源响应重建兼容续接，详见[Memory 消费边界](memory.md#3-内部流转与失败边界)。
5. **失败与释放**：配置、输入、远端与传输失败映射到有界 `ProviderFailure`；`outcome_known` 供 Runtime/Agent 区分确定失败与结果未知。本地 prepare 失败不产生 attempt；已领取后的明确/未知失败由 Runtime 提交。client 在调用结束或失败后关闭 transport；Provider 不自行重发已启动请求。

### DeepSeek 续接值的三个状态

adapter 区分服务端实际返回字段与 SDK 默认属性：未返回 `reasoning_content` 时 `ProviderResponse.continuation=None`；实际返回空字符串或显式 null 时创建 continuation，并原样保留 `""` 或 `None`。非字符串且非 null 的值拒绝。流式字符串按顺序拼接，null 片段不贡献文本；仅 null 保持 null，没有实际字段仍保持缺失。Qwen/MiMo 继续仅保留非空续接文本。

当前 DeepSeek adapter 在 thinking 模式且请求含工具定义时，检查请求中的每条 assistant 消息都具有兼容 continuation，包括没有 tool calls 的 assistant；空字符串与 null 是已存在的值，不能被当成缺失，payload 也不把 null 改写为空字符串。公共消息编码器对任何已附加 continuation 原样发送 `reasoning_content`；关闭 thinking 只免除上述强制存在校验。匹配规则是 provider 相同且格式版本为 1，不要求源 Run 与目标 Run 相同；数据仍留在源 Run 私有表中。

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
| ImageBlock.source_ref | Mapping[str, str] 或 None | None；repr=False | Agent 图片的完整 typed ref；直接 Provider 调用可无；不进入 wire | Agent image feedback → 调用期内存 → prepare 私有 manifest，字段见 [Runtime](runtime.md#providerrequestbinding) |
| ImageBlock.observation_kind | str | original | original/annotated/rendered 回看类别；不进入 wire | Agent image feedback → 调用期内存 → prepare manifest |

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
| ProviderContinuation.format_version | int | 必传 | Provider 私有续接格式版本，当前必须为 1 | ProviderClient / adapter → 调用期；提交后转 ProviderContinuationFact → AgentRequestBuilder；私有字段不公开 |
| ProviderContinuation.reasoning_content | str \| None | 必传，无默认 | 私有续接原值；DeepSeek 允许非空、空字符串或显式 null，其他 Provider 要求非空文本；对象不存在才代表字段缺失 | adapter / Agent 按源响应重建 → 调用期；提交后转 ProviderContinuationFact → adapter；不公开、不裁剪或跨响应替换 |

### `_PreparedProviderCall`

ProviderClient 私有的冻结调用封套，`repr=False` 且禁止序列化；不是新增业务实体。由 `prepare` 构造、同 client 的 `dispatch` 消费，不进入 Runtime、API 或通用 Memory。每次模型动作重新准备，不能从 checkpoint 恢复这个对象。[定义](../../src/figura/providers/client.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| `_PreparedProviderCall.owner` | `object` | 必传；`repr=False` | 当前 client 的进程内身份 token；dispatch 必须按对象身份匹配 | ProviderClient.prepare → 私有内存 → 同 client.dispatch；不公开、不持久化或修订 |
| `_PreparedProviderCall.request` | `ProviderRequest` | 必传；`repr=False` | 已通过校验的规范请求，供响应归一化使用 | ProviderClient.prepare → 私有内存 → dispatch/adapter；字段合同见本页，不另存副本 |
| `_PreparedProviderCall.payload` | `Mapping[str, Any]` | 必传；`repr=False` | adapter 已准备的原生请求参数，可含图像和私有续接；作为本次 transport.create 的参数 | adapter.build_payload / prepare → 私有内存 → dispatch/transport；无公开或独立修订入口 |
| `_PreparedProviderCall.descriptor` | `Mapping[str, Any]` | 必传；`repr=False` | 冻结的安全描述：provider/model、endpoint SHA-256、prepared payload（含 timeout）、POST/path 与 endpoint binding 的 canonical SHA-256、resolved options（包括冻结的 phase timeout）与完整 asset manifest | prepare → 私有内存 → Runtime binding；各持久字段见 [Runtime](runtime.md#providerrequestbinding)，不公开 |
| `_PreparedProviderCall.context_estimate` | `ContextEstimate` 或 None | None | 独立输入估算；重试 prepare 跳过，不参与 descriptor 或 payload | prepare → 首次 Runtime binding；只公开数字 |

### 本地上下文估算

本地上下文估算使用实际 prepared payload 的 messages/tools 投影，统一采用 `tiktoken/o200k_base`；图片每次出现近似为 1,024 tokens，不分词 URL/base64。编码缓存初始化失败只禁用估算。该值不参与请求指纹、准入、输出预算或 Provider usage 校准。Agent 在 estimate 有值、context capacity 是正整数且比例达到约 80% 时，才可能发起一条额外摘要请求；此阈值策略由 [Agent](agent.md#上下文压缩与请求投影)拥有。容量缺失或估算失败时不自动压缩。摘要请求仍通过此 Provider 的 `prepare/dispatch`，其普通 Run `ProviderAttempt` 不会被摘要调用占用；摘要自身的 operation/retry 身份由 [Runtime](runtime.md#contextcompactionoperation)持久化。

### ContextEstimate

定义于 `providers/token_estimation.py`，prepare 写入；首次 claim 后由 Runtime binding 保存原快照，Gateway 仅公开两个聚合数字。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ContextEstimate.input_tokens | int | 必传 | 非负输入估算，含文本结构与图像近似 | prepare → binding → Gateway inputTokens |
| ContextEstimate.context_window_tokens | int 或 None | 必传 | 正整数容量或未知，不控制执行 | ProviderProfile → binding → Gateway contextWindowTokens |
| ContextEstimate.estimator_version | str | tiktoken-o200k-v1 | 非空规则版本；调整计量规则时更换 | estimator → binding → 私有读取 |

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

本次 Provider 请求的选项。 **写入者：**AgentRequestBuilder / Provider adapter。**权威位置：**调用期 ProviderRequest。**读取与公开：**Provider adapter；prepare 时解析，复制到 Runtime 私有请求绑定。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderOptions.max_completion_tokens | int \| None | None | 可选单请求输出上限；未设则省略 wire 参数 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；prepare 时解析，复制到 Runtime 私有请求绑定 |
| ProviderOptions.stream | bool | False | 是否流式；当前 Agent 固定 false | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；prepare 时解析，复制到 Runtime 私有请求绑定 |
| ProviderOptions.thinking_mode | bool \| None | None | 本次请求的可选思考模式 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；prepare 时解析，复制到 Runtime 私有请求绑定 |
| ProviderOptions.reasoning_effort | str \| None | None | 本次请求的可选推理强度 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；prepare 时解析，复制到 Runtime 私有请求绑定 |
| ProviderOptions.schema_version | int | 2 | 该值或 payload 的版本号 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；prepare 时解析，复制到 Runtime 私有请求绑定 |

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
| ProviderRequest.asset_contract | Mapping[str, object] 或 None | None；repr=False | 私有 prompt_digest、registry_version、registry_digest；Agent 按完整声明计算，直接 Provider 调用从指令/工具投影计算 | AgentRequestBuilder → 调用期内存 → prepare 私有 manifest；不进入 wire，字段见 Runtime |

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
| ProviderProfile.timeout_seconds | float | 必传 | I/O phase 超时，默认60秒；有限正数，无600秒上限 | ProviderSettings.from_env → 进程配置 → prepare 冻结到私有 binding；每次发送显式传入 SDK |
| ProviderProfile.thinking_mode | bool | 必传 | 从进程配置解析的思考模式布尔值 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.reasoning_effort | str \| None | 必传 | 进程配置中的可选推理强度 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.configuration_error | ProviderFailureCode \| None | None | 配置校验失败码；可空 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |

| ProviderProfile.max_completion_tokens | int \| None | None | 每 Provider 可选默认输出 token 数，正整数；prepare 固定到本次 resolved options | 配置 → 进程内 profile → prepare；不直接公开 |
| ProviderProfile.context_window_tokens | int 或 None | None | 模型显示容量；FIGURA_<PROVIDER>_CONTEXT_WINDOW_TOKENS 的有效正整数，无效或缺失为未知，不影响 availability | 配置 → prepare estimate → 首次 binding → 公开显示分母 |

### ProviderSettings

全部 allowlist provider 的进程配置集合。 **写入者：**ProviderSettings.from_env。**权威位置：**进程内，不入 Run。**读取与公开：**ProviderFactory；profiles 含私有配置。[定义](../../src/figura/providers/config.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderSettings.profiles | Mapping[ProviderId, ProviderProfile] | 必传 | 每个 allowlist ProviderId 对应一份 ProviderProfile | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；profiles 含私有配置 |

### ProviderFailure

归一化的安全 Provider 失败。 **写入者：**ProviderClient / adapter。**权威位置：**调用期；安全 code 可入 Attempt。**读取与公开：**Agent；不包含原始 SDK payload。[定义](../../src/figura/providers/errors.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderFailure.failure_code | ProviderFailureCode | 必传 | 失败时的安全枚举码，不可为空；Attempt 的可空 failure_code 是另一字段 | ProviderClient / adapter → 调用期；安全 code 可入 Attempt → Agent；不包含原始 SDK payload |
| ProviderFailure.outcome_known | bool | 必传 | 是否能确定远端请求结果 | ProviderClient / adapter → 调用期；安全 code 可入 Attempt → Agent；不包含原始 SDK payload |
| ProviderFailure.transient | bool | 必传 | 该失败是否可视为临时 | ProviderClient / adapter → 调用期；安全 code 可入 Attempt → Agent；不包含原始 SDK payload |
| ProviderFailure.safe_message | str | 必传 | 可安全展示的有界失败说明 | ProviderClient / adapter → 调用期；安全 code 可入 Attempt → Agent；不包含原始 SDK payload |
| ProviderFailure.http_status | int \| None | None | 可选 HTTP 状态码 | ProviderClient / adapter → 调用期；安全 code 可入 Attempt → Agent；不包含原始 SDK payload |

| ProviderFailure.retry_after_seconds | float \| None | None | 安全解析 Retry-After 的秒数；非法、非有限或不可表示日期忽略 | 网络分类 → 调用期 → Runtime deadline；不保留原 header/body |
| ProviderFailure.category | str 或 None（构造后为 str） | None → 按 safe code/known/transient/status 推导 | temporary_unsent / temporary_rejected / temporary_unknown / permanent / invalid_response / internal_error | Provider 分类 → 调用期 → Runtime Attempt.failure_category；只保存安全类别 |

### 网络与物理边界

SDK `max_retries=0`、HTTP transport `retries=0`。原始 HTTP 字节流在 SDK JSON 解析前检查 Content-Length 与累计接收量；完整 JSON 严格拒绝重复 keys、非有限值和非法 Unicode。已有直接 stream 也限制 raw SSE 累计字节、单事件 JSON 与规范化整体；Agent 仍为 non-streaming，不给部分 stream 补发。

Provider 的通用 messages/instructions/tools/calls/文本和图片数量上限已删除。结构化请求以图片 media type、byte count、SHA-256 占位计 JSON；真实 data URL 计入 wire fingerprint，图像仍另有 single/total bytes guard。响应正文、全部 tool calls 和 continuation 一并检查。DeepSeek continuation、strict Schema、thinking、vision 能力保持 adapter 的实际合同。

408/429/500/502/503/504 可按已知性进入临时恢复；quota/balance 429、认证、配置、TLS、确定性 DNS、无效响应、length 与内部异常不恢复。Connect/Pool timeout 是可证明 no-send；read/write timeout 和临时断连为 outcome unknown。Runtime 拥有重试次数、deadline 和替代 attempt，Provider 本身每次仅发送一次。未知请求可能已在服务端生成并计费，替代请求无法保证远端 exactly-once。

## 5. 枚举与依据

- `ProviderId`：`qwen`、`deepseek`、`mimo`；固定模型分别为 `qwen3.8-flash`、`deepseek-flash`、`mimo-v2.6-flash`。`InstructionRole`：`system`、`developer`。`MessageRole`：`user`、`assistant`、`tool`。`FinishReason`：`stop`、`tool_calls`、`length`、`content_filter`、`other`。
- `ProviderFailureCode`：`configuration_missing`、`invalid_configuration`、`unsupported_provider`、`unsupported_model`、`invalid_request`、`unsupported_capability`、`provider_rejected`、`provider_unavailable`、`timeout`、`connection_error`、`incomplete_stream`、`invalid_provider_response`、`transport_error`。
- `ContentBlock = TextBlock | ImageBlock`，`MessageContent = str | tuple[ContentBlock, ...]`。Exception 类携带的错误状态由 `ProviderFailure` 或安全错误码表达，不作为另一个持久事实。
- 代码：[模型](../../src/figura/providers/models.py)、[配置](../../src/figura/providers/config.py)、[Client/Factory](../../src/figura/providers/client.py)、[适配器](../../src/figura/providers/adapters/base.py)、[错误](../../src/figura/providers/errors.py)；主规格：[model-provider](../../openspec/figura/openspec/specs/model-provider/spec.md)、[continuation 持久化](../../openspec/figura/openspec/specs/provider-continuation-persistence/spec.md)。
