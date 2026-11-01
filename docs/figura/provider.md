# Provider：模型请求与响应边界

> 更新日期：2026-10-22。[返回总览](../figura-implementation-overview.md)。本篇拥有模型服务的调用期合同、配置、适配与规范化失败；持久化的 `ProviderRequestRecord`、`ProviderAttempt` 和 `ProviderContinuationFact` 由[Run Runtime](runtime.md#4-完整模型字段)定义。

## 1. 职责与边界

`ProviderFactory` 根据 Run 已固定的 provider/model 选择客户端；`ProviderClient` 验证请求并通过 Qwen、DeepSeek、MiMo adapter 与模型服务交互，归一化为 `ProviderResponse` 或 `ProviderFailure`。ProviderProfile 中的凭据和 endpoint 只保留在进程配置。Provider 不决定 Run 生命周期，也不保存 Run 的独立历史。

## 2. 内部流转

1. **可用性与选择**：`ProviderSettings` 为三个 allowlist provider 各保存一份 profile；Factory 对 provider/model、配置及能力进行检查，并可返回安全的 `ProviderAvailability`。Web Gateway 的 health 路由消费该值，只返回 provider ID、固定 model ID、配置是否可用和有界 reason code，不发起 Provider 网络请求；HTTP 字段定义见[Web 边界](web.md#4-web-dto-字段)。
2. **本地准备**：Agent 组装 `ProviderRequest` 并创建固定 provider/model 的 client，然后调用 `prepare(request)`。该方法先校验消息、工具、图像和字节限制，再核对模型并执行 adapter 的 `build_payload`；DeepSeek thinking 工具历史的 continuation 要求也在此阶段检查。它使用统一本地 tokenizer 估算真实输入，并从可选 `ProviderProfile.context_window_tokens` 附上显示分母。有效容量和估算只供 Agent 判断是否做上下文压缩，不作为准入或输出预算。成功返回私有 `_PreparedProviderCall`，不发送网络请求，也不 claim attempt。图片字节、原生 payload 与续接内容仅留在调用期内存。
3. **领取并发送**：Agent 在锁内复查 checkpoint 并提交 ProviderAttempt claim，随后调用同一个 client 的 `dispatch(prepared)`。客户端校验 prepared 的来源 token，然后发送已经准备好的 payload 一次；不重新构造请求。其他 client 创建的 prepared 会被拒绝。Prepared 不可序列化、不持久化、不进入日志或公开 DTO。
4. **响应**：adapter 逐事件消费 SSE，并累积文本、按 index 组装工具调用、用量、结束原因与 Provider continuation。只有检测到合法终止事件并通过响应校验，才返回完整 `ProviderResponse`；公开响应省略私有 continuation，Runtime 将完整结果与 response record 原子提交。Agent 后续按精确来源响应重建兼容续接，详见[Memory 消费边界](memory.md#3-内部流转与失败边界)。
5. **失败与释放**：配置、输入、远端与传输失败映射到有界 `ProviderFailure`；失败阶段与 `outcome_known` 供 Runtime 区分确定未发送、明确拒绝和结果未知。本地 prepare 失败不产生 attempt；已领取后的流中失败由共享 coordinator 持久化并按冻结策略处理。取消会关闭本地流；SDK、HTTP transport 与 Provider adapter 均不做隐藏重试。

### DeepSeek 续接值的三个状态

adapter 区分服务端实际返回字段与 SDK 默认属性：未返回 `reasoning_content` 时 `ProviderResponse.continuation=None`；实际返回空字符串或显式 null 时创建 continuation，并原样保留 `""` 或 `None`。非字符串且非 null 的值拒绝。流式字符串按顺序拼接，null 片段不贡献文本；仅 null 保持 null，没有实际字段仍保持缺失。Qwen/MiMo 继续仅保留非空续接文本。

当前 DeepSeek adapter 在 thinking 模式且请求含工具定义时，检查请求中的每条 assistant 消息都具有兼容 continuation，包括没有 tool calls 的 assistant；空字符串与 null 是已存在的值，不能被当成缺失，payload 也不把 null 改写为空字符串。公共消息编码器对任何已附加 continuation 原样发送 `reasoning_content`；关闭 thinking 只免除上述强制存在校验。匹配规则是 provider 相同且格式版本为 1，不要求源 Run 与目标 Run 相同；数据仍留在源 Run 私有表中。

### 统一流式响应合同

所有 Provider dispatch 均发送 stream=true。Adapter 将原生碎片归一为 response_started、text_delta、reasoning_delta、tool_call_delta、usage、heartbeat、completed 或 failed。`completed` 只在收到有效终止事件并完成本地校验后产生；EOF、缺失 finish reason、畸形 JSON 或不完整工具参数都不能生成可提交的 ProviderResponse。Agent 只把 text_delta 作为本次 attempt 的临时文本发给 Gateway；reasoning_delta 与 tool_call_delta 保留在 Provider/Agent 内部。完整响应、continuation、工具调用批次和 checkpoint 在同一个 Runtime 提交边界写入。

### Provider 能力声明

ProviderCapabilities 按固定 Provider/model profile 声明 `streaming`、`usage_streaming`、`heartbeat_streaming` 与 `continuation_streaming`。当前适配器须支持 streaming；不支持时在本地准备阶段拒绝，不退回非流式请求。可选事件只在真实收到时记录，不能从沉默推断 Provider 仍在计算。

### ProviderCapabilities 与 ProviderStreamEvent

这两个对象是调用期合同；它们不进入 Runtime 事实。能力来自 ProviderProfile，事件由 adapter 归一化并交给 Agent/Runtime coordinator。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与边界 |
|---|---|---|---|
| ProviderCapabilities.streaming | bool | 必传 | 必须为 true 才允许本次 Provider 调用 |
| ProviderCapabilities.usage_streaming | bool | 必传 | Provider 是否会在流中发送 usage event |
| ProviderCapabilities.heartbeat_streaming | bool | 必传 | Provider/transport 是否可能产生 heartbeat 活动 |
| ProviderCapabilities.continuation_streaming | bool | 必传 | Provider 是否能在 stream 中携带 continuation 内容 |
| ProviderStreamEvent.kind | ProviderStreamEventKind | 必传 | 统一事件种类，见本节枚举；reasoning/tool 参数事件仅内部使用 |
| ProviderStreamEvent.text | str 或 None | None | 可见文本或内部 reasoning 分片；只 text_delta 可投影到临时 assistant 文本 |
| ProviderStreamEvent.call_index | int 或 None | None | 工具调用在当前响应内的稳定索引 |
| ProviderStreamEvent.call_id | str 或 None | None | 工具调用 ID 分片 |
| ProviderStreamEvent.tool_name | str 或 None | None | 工具名分片；不能单独触发工具执行 |
| ProviderStreamEvent.arguments | str 或 None | None | 工具参数 JSON 分片；必须等待完整响应并整体校验 |
| ProviderStreamEvent.usage | ProviderUsage 或 None | None | 可选 Provider 用量快照 |
| ProviderStreamEvent.provider_request_id | str 或 None | None | 有界 Provider 请求身份 |
| ProviderStreamEvent.http_status | int 或 None | None | response_started 或明确失败时的 HTTP 状态 |
| ProviderStreamEvent.failure_code | str 或 None | None | 有界失败原因码；不携带 Provider 原文 |
| ProviderStreamEvent.response_bytes | int 或 None | None | 当前规范化累计响应字节估计 |

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
| ImageBlock.media_type | str | 必传 | 由图片内容验证得到的媒体类型 | AgentRequestBuilder 水合中立媒体 → 调用期内存 → Provider adapter；字节不入 Run 事实或普通日志 |
| ImageBlock.image_bytes | bytes | 必传 | 已验证图像字节，仅调用期内存 | AgentRequestBuilder 水合中立媒体 → 调用期内存 → Provider adapter；字节不入 Run 事实或普通日志 |
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
| `_PreparedProviderCall.descriptor` | `Mapping[str, Any]` | 必传；`repr=False` | 冻结的安全描述：provider/model、endpoint SHA-256、prepared payload、POST/path 与 endpoint identity 的 canonical SHA-256、resolved phase timeouts 与完整 asset manifest | prepare → 私有内存 → Runtime ProviderRequestRecord；各持久字段见 [Runtime](runtime.md#providerrequestrecord)，不公开 |
| `_PreparedProviderCall.context_estimate` | `ContextEstimate` 或 None | None | 独立输入估算；重试 prepare 跳过，不参与 descriptor 或 payload | prepare → 首次 Runtime ProviderRequestRecord；只公开数字 |

`descriptor` 是允许持久化的安全指纹，不是 payload 副本；其顶层结构及嵌套字段如下。Runtime 的 `ProviderRequestRecord` 与 `ContextCompactionOperation` 共同记录这一请求身份，不重复定义字段。

| 完整字段路径 | 类型/默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|
| `_PreparedProviderCall.descriptor.provider_id` | `str`；必传 | 规范 `ProviderId.value` | ProviderClient.prepare → 私有 descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.model_id` | `str`；必传 | 当前 ProviderClient 固定模型身份 | ProviderClient.prepare → 私有 descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.endpoint_binding` | SHA-256 `str`；必传 | 规范 endpoint 的摘要，不保存 URL 原文 | ProviderClient.prepare → 私有 descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.request_fingerprint` | SHA-256 `str`；必传 | 对 method、path、endpoint binding 与完整 prepared payload 的 canonical digest | ProviderClient.prepare → 私有 descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.options` | `Mapping[str, object]`；必传 | 精确包含下列五个已解析选项 | ProviderClient.prepare → 私有 descriptor → Runtime 重建时冻结；不公开 |
| `_PreparedProviderCall.descriptor.options.max_completion_tokens` | `int` 或 `None` | 已解析的单请求 completion 上限 | ProviderClient.prepare → descriptor → Runtime 重建；不公开 |
| `_PreparedProviderCall.descriptor.options.thinking_mode` | `bool` 或 `None` | 已解析的思考模式 | ProviderClient.prepare → descriptor → Runtime 重建；不公开 |
| `_PreparedProviderCall.descriptor.options.reasoning_effort` | `str` 或 `None` | 已解析的推理强度 | ProviderClient.prepare → descriptor → Runtime 重建；不公开 |
| `_PreparedProviderCall.descriptor.options.connect_timeout_seconds` | 有限正 `int`/`float` | 连接阶段超时 | ProviderClient.prepare → descriptor → Runtime 重建；不公开 |
| `_PreparedProviderCall.descriptor.options.write_timeout_seconds` | 有限正 `int`/`float` | 请求发送阶段超时；响应阶段没有总时限 | ProviderClient.prepare → descriptor → Runtime 重建；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest` | `Mapping[str, object]`；必传 | Agent 提供的 asset contract 加 Provider adapter 版本及有序图片指纹 | Agent/ProviderClient.prepare → 私有 descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest.prompt_digest` | SHA-256 `str`；必传 | 实际指令投影摘要 | Agent `asset_contract` 或 Provider 默认投影 → descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest.registry_version` | 非空 `str`；必传 | 当前工具合同版本；摘要请求无工具时使用 `context-compaction-v2` | Agent `asset_contract` 或 Provider 默认值 → descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest.registry_digest` | SHA-256 `str`；必传 | 工具声明投影摘要；摘要请求工具集合为空 | Agent `asset_contract` 或 Provider 默认投影 → descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest.adapter_contract_version` | `int`；当前为 `1` | Provider prepare/wire 适配合同版本 | ProviderClient.prepare → descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest.images` | 有序图片指纹数组；必传，可空 | 仅保存每个图像块的引用与摘要，不保存图像字节；摘要请求为空数组 | ProviderClient.prepare → descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest.images[].source_ref` | `Mapping[str, str]` 或 `None` | 图像资源引用；结构见 [Agent 图像资源引用](agent.md#4-runexecutionstate-资源合同与完整字段) | Agent 图像块 → ProviderClient.prepare → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest.images[].observation_kind` | `str`；默认 `original` | `original`、`annotated` 或 `rendered` | Agent 图像块 → ProviderClient.prepare → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest.images[].media_type` | `str`；必传 | 图像 MIME 类型 | Agent/Sources → ProviderClient.prepare → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest.images[].byte_count` | 正 `int` | 实际附带的图像字节数 | ProviderClient.prepare → descriptor → Runtime 比较；不公开 |
| `_PreparedProviderCall.descriptor.asset_manifest.images[].sha256` | SHA-256 `str`；必传 | 实际附带图像内容摘要 | ProviderClient.prepare → descriptor → Runtime 比较；不公开 |

### 本地上下文估算

本地上下文估算使用实际 prepared payload 的 messages/tools 投影，统一采用 `tiktoken/o200k_base`；图片每次出现近似为 1,024 tokens，不分词 URL/base64。编码缓存初始化失败只禁用估算。该值不参与请求指纹、准入、输出预算或 Provider usage 校准。Agent 在 estimate 有值、context capacity 是正整数且比例达到约 80% 时，才可能发起一条额外摘要请求；此阈值策略由 [Agent](agent.md#上下文压缩与请求投影)拥有。容量缺失或估算失败时不自动压缩。摘要请求与普通 Run 请求使用同一 Provider `prepare/dispatch`、`ProviderRequestRecord` 和 `ProviderAttempt` 合同：摘要请求以 `purpose=context_compaction` 关联 `ContextCompactionOperation`，每个逻辑摘要请求有独立请求记录和最多四次物理发送；operation 只保存请求 ID、冻结的压缩范围与生命周期，不重复维护 attempt 次数或重试身份。恢复沿用冻结的请求 options 与 payload binding。详见 [Runtime](runtime.md#contextcompactionoperation) 与 [Agent](agent.md#上下文压缩与请求投影)。

### ContextEstimate

定义于 `providers/token_estimation.py`，prepare 写入；首次 claim 后由 Runtime ProviderRequestRecord 保存原快照，ProviderRequestRecord 固定原始估算快照，Gateway 仅公开两个聚合数字。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ContextEstimate.input_tokens | int | 必传 | 非负输入估算，含文本结构与图像近似 | prepare → ProviderRequestRecord → Gateway inputTokens |
| ContextEstimate.context_window_tokens | int 或 None | 必传 | 正整数容量或未知，不控制执行 | ProviderProfile → ProviderRequestRecord → Gateway contextWindowTokens |
| ContextEstimate.estimator_version | str | tiktoken-o200k-v1 | 非空规则版本；调整计量规则时更换 | estimator → ProviderRequestRecord → 私有读取 |

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

本次 Provider 请求可由 Agent 调整的选项。流式能力是固定 Provider 合同，不属于可切换选项。**写入者：**AgentRequestBuilder / Provider adapter。**权威位置：**调用期 ProviderRequest。**读取与公开：**Provider adapter；prepare 时解析，由 Runtime ProviderRequestRecord 冻结。[定义](../../src/figura/providers/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ProviderOptions.max_completion_tokens | int \| None | None | 可选单请求输出上限；未设则省略 wire 参数 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；prepare 时解析，由 Runtime ProviderRequestRecord 冻结 |
| ProviderOptions.thinking_mode | bool \| None | None | 本次请求的可选思考模式 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；prepare 时解析，由 Runtime ProviderRequestRecord 冻结 |
| ProviderOptions.reasoning_effort | str \| None | None | 本次请求的可选推理强度 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；prepare 时解析，由 Runtime ProviderRequestRecord 冻结 |
| ProviderOptions.schema_version | int | 2 | 该值或 payload 的版本号 | AgentRequestBuilder / Provider adapter → 调用期 ProviderRequest → Provider adapter；prepare 时解析，由 Runtime ProviderRequestRecord 冻结 |

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
| ProviderProfile.connect_timeout_seconds | float | 10.0 | 连接阶段有限正超时；环境变量 FIGURA_<PROVIDER>_CONNECT_TIMEOUT_SECONDS | ProviderSettings.from_env → 进程配置 → ProviderRequestRecord.options → transport；不公开 |
| ProviderProfile.write_timeout_seconds | float | 30.0 | 请求发送阶段有限正超时；环境变量 FIGURA_<PROVIDER>_WRITE_TIMEOUT_SECONDS | ProviderSettings.from_env → 进程配置 → ProviderRequestRecord.options → transport；不公开 |
| ProviderProfile.thinking_mode | bool | 必传 | 从进程配置解析的思考模式布尔值 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.reasoning_effort | str \| None | 必传 | 进程配置中的可选推理强度 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.configuration_error | ProviderFailureCode \| None | None | 配置校验失败码；可空 | ProviderSettings.from_env → 进程内，不入 Run → ProviderFactory；密钥与 endpoint 不公开 |
| ProviderProfile.capabilities | ProviderCapabilities | streaming enabled; optional stream data false by default | 当前 Provider/model 的流式、usage、heartbeat、continuation 能力声明 | Provider profile → ProviderFactory/adapter；不写入 Run DTO |

| ProviderProfile.max_completion_tokens | int \| None | None | 每 Provider 可选默认输出 token 数，正整数；prepare 固定到本次 resolved options | 配置 → 进程内 profile → prepare；不直接公开 |
| ProviderProfile.context_window_tokens | int 或 None | None | 模型显示容量；FIGURA_<PROVIDER>_CONTEXT_WINDOW_TOKENS 的有效正整数，无效或缺失为未知，不影响 availability | 配置 → prepare estimate → 首次 ProviderRequestRecord → 公开显示分母 |

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

| ProviderFailure.retry_after_seconds | float \| None | None | 安全解析 Retry-After 的秒数；非法、非有限或不可表示日期忽略 | 网络分类 → 调用期 → ProviderRequestRecord retry scheduling；不保留原 header/body |
| ProviderFailure.category | str 或 None（构造后为 str） | None → 按 safe code/known/transient/status 推导 | temporary_unsent / temporary_rejected / temporary_unknown / permanent / invalid_response / internal_error | Provider 分类 → 调用期 → Runtime Attempt.failure_category；只保存安全类别 |

### 网络与物理边界

SDK `max_retries=0`、HTTP transport `retries=0`；请求只走流式 transport。响应 `Content-Length` 与累计字节在消费前受执行载荷上限保护；SSE 使用严格 UTF-8 解码，并逐事件校验 JSON 与累计规范化响应。只有 Provider 终止事件及本地合同校验通过后，才允许提交响应或执行完整工具调用批次。

配置分别提供 connect 与 write 超时，默认 10 秒和 30 秒；请求发送后不设 response/read/total generation timeout。连接仍然存活时保持等待，阶段和最近活动用于诊断；用户可以停止 Run。Heartbeat 更新活动时间，但不代表生成文本。连接关闭、reset、明确错误响应或已确认的传输故障才结束当前 attempt。

请求发送前确认失败属于已知未发送；显式 HTTP 错误属于已知拒绝；请求可能送达后发生超时、EOF 或 stream reset 且没有终止事件时，结果为未知。共享 Runtime coordinator 对同一冻结请求最多调度四次，按退避和有效 `Retry-After` 决定下一次；未知结果重放可能产生重复 Provider 费用，但部分文本或工具调用不会执行。超出总等待时间本身不构成失败。

## 5. 枚举与依据

- `ProviderId`：`qwen`、`deepseek`、`mimo`；固定模型分别为 `qwen3.8-flash`、`deepseek-flash`、`mimo-v2.6-flash`。`InstructionRole`：`system`、`developer`。`MessageRole`：`user`、`assistant`、`tool`。`FinishReason`：`stop`、`tool_calls`、`length`、`content_filter`、`other`。
- `ProviderStreamEventKind`：`response_started`、`text_delta`、`reasoning_delta`、`tool_call_delta`、`usage`、`heartbeat`、`completed`、`failed`。
- `ProviderFailureCode`：`configuration_missing`、`invalid_configuration`、`unsupported_provider`、`unsupported_model`、`invalid_request`、`unsupported_capability`、`provider_rejected`、`provider_unavailable`、`timeout`、`connection_error`、`incomplete_stream`、`invalid_provider_response`、`transport_error`。
- `ContentBlock = TextBlock | ImageBlock`，`MessageContent = str | tuple[ContentBlock, ...]`。Exception 类携带的错误状态由 `ProviderFailure` 或安全错误码表达，不作为另一个持久事实。
- 代码：[模型](../../src/figura/providers/models.py)、[配置](../../src/figura/providers/config.py)、[Client/Factory](../../src/figura/providers/client.py)、[适配器](../../src/figura/providers/adapters/base.py)、[错误](../../src/figura/providers/errors.py)；主规格：[model-provider](../../openspec/figura/openspec/specs/model-provider/spec.md)、[continuation 持久化](../../openspec/figura/openspec/specs/provider-continuation-persistence/spec.md)。

## 原生工具结果图片能力

当前工作树的 ProviderPolicy 显式声明 `supports_tool_result_images`，默认 False。DeepSeek/deepseek-flash 使用 Chat Completions 的原生 TOOL 文本/图片数组；Qwen/qwen3.8-flash 的[当前官方 Chat Completions 合同](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)要求 tool.content 是字符串，不满足本次图片数组合同；MiMo/mimo-v2.6-flash 的精确 TOOL 图片合同及识别仍未确认，两者保持 False。该能力与“凭据配置有效”的 availability 不同：配置可用并不代表可忠实表达图像工具结果。

AgentRequestBuilder 在调用期 asset_contract 声明 requires_tool_result_images；它由 Registry 中 `ToolDefinition.produces_images` 派生。Provider 在首次普通请求 prepare 时就拒绝不支持该能力的工具目录，实际 TOOL ImageBlock 同样校验，不 claim attempt 或 dispatch。这个临时准入标志不扩充持久 manifest 字段，不会改写历史请求审计。各定义的图片声明纳入 Registry 摘要。

通用校验保留完整工具批次和精确 tool_call_id 关联，不再禁止 TOOL 图片。同一批内 call ID 必须唯一；闭合后的后续批次可再次使用相同 opaque ID，资源身份仍由完整 Run/call 引用区分。原生序列化保留角色、调用及内容块顺序，将图旁 TextBlock 与 image_url 放在同一 TOOL content 中。不追加普通 user、不丢图、不换模型/端点或协议。

图片、hint、角色、call ID 和顺序全部进入原 wire request_fingerprint；资产 manifest 仍使用原 source_ref、observation_kind、media_type、byte_count、sha256。具体 image_kind 仅在业务附件及身份文本中表达，manifest 的 observation_kind 按 original/annotated/rendered 粗分类投影。相同逻辑请求重试不改变 body 或媒体；图像变化沿原绑定不匹配规则失败，continuation、流式请求和重试额度保持原合同。

2026-10-21 最小两图识别：DeepSeek 对两条工具结果分别识别红色圆形、蓝色方形且 call ID 正确，实际 usage 输入 717、输出 35、总计 752。Qwen 请求返回 403，不能据此声称支持或不支持；MiMo 未配置有效凭据，未发送。线上支持范围只包括已通过的 DeepSeek；离线测试同时覆盖其余模型的本地能力拒绝。该测试不衡量图表抽取质量或长任务成功率。
