# `add-figura-model-client` · Provider 基础层

> 返回 [Figura 实现内容索引](../../figura-implementation-content.md)。

> 最近更新：2026-09-26。实施状态：已实现。OpenSpec 状态：主规格已同步、change 已归档。

## 1. 概览与决定

**来源与基线**

- 问题来源：Figura 需要与 ChartAgent 解耦的统一模型调用边界；模型组合以用户确认结果为准。
- 代码证据：[providers package](../../../src/figura/providers/)、[models.py](../../../src/figura/providers/models.py)、[config.py](../../../src/figura/providers/config.py)、[client.py](../../../src/figura/providers/client.py)、[validation.py](../../../src/figura/providers/validation.py)、[adapters](../../../src/figura/providers/adapters/)、[transport.py](../../../src/figura/providers/transport.py)。
- 主规格：[model-provider](../../../openspec/figura/openspec/specs/model-provider/spec.md)。
- 归档 change：[proposal](../../../openspec/figura/openspec/changes/archive/2026-09-26-add-figura-model-client/proposal.md)、[design](../../../openspec/figura/openspec/changes/archive/2026-09-26-add-figura-model-client/design.md)、[tasks](../../../openspec/figura/openspec/changes/archive/2026-09-26-add-figura-model-client/tasks.md)。
- 参考材料：架构草案、ChartAgent、供应商官方资料只作参考；Figura 决定以用户确认、主规格和代码为准。Figura store 当前无活动 change。
- Provider 官方资料链接沿用原方案记录：[Qwen 模型能力](https://help.aliyun.com/zh/model-studio/vision-model)、[Qwen OpenAI 兼容地址](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、[Qwen Chat 参数](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)、[DeepSeek 视觉输入](https://api-docs.deepseek.com/guides/vision/)、[DeepSeek 思考与工具](https://api-docs.deepseek.com/guides/thinking_mode/)、[MiMo 模型](https://mimo.mi.com/models/en-US/mimo-v2.6-flash)、[MiMo 图片输入](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding)、[MiMo Chat API](https://mimo.mi.com/docs/en-US/api/chat)、[MiMo 思考续接](https://mimo.mi.com/docs/en-US/usage-guide/passing-back-reasoning_content)。链接来自既有设计记录；实现事实以当前源码为准。

**目标与范围**

- 目标：提供统一、显式选择、有界且可归一化的同步模型调用入口；隔离供应商在 role、thinking、image、tool、stream 和 continuation 上的差异。
- 可观察结果：调用方显式提交 provider/model 和 ProviderRequest，得到统一 ProviderResponse 或安全 ProviderCallError；mock 与 SDK transport 共用同一合同。
- 包含：qwen/qwen3.8-flash、deepseek/deepseek-flash、mimo/mimo-v2.6-flash；配置和 availability；文本/图像/函数工具合同；三个 provider policy；stream aggregation；内存 continuation 往返；失败分类。
- 不包含：Run 执行循环或持久化、continuation durable storage、AttachmentRef 读取授权、ToolRegistry、Prompt/Agent、Gateway/SSE、CLI、UI、自动 fallback、真实图表质量评估。
- 前置条件：部署环境配置 provider profile；上游只传已授权图片字节；调用方显式选择 provider/model。

**决定与依据**

| 主题 | 决定/事实 | 决策状态 | 实施状态与证据 | 影响字段/组件 |
|---|---|---|---|---|
| Provider/model | qwen/qwen3.8-flash；deepseek/deepseek-flash；mimo/mimo-v2.6-flash | 已确认 | 已实现；用户决定、models.py、主规格 | ProviderId、MODEL_IDS、Factory |
| Endpoint | Qwen需部署指定HTTPS地域/workspace URL；DeepSeek默认https://api.deepseek.com；MiMo默认https://api.xiaomimimo.com/v1，Token Plan需成对URL/key | 已确认 | 配置规则已实现；Qwen部署值由环境提供；config.py、既有官方资料 | ProviderProfile.base_url、部署配置 |
| 显式选择 | 不按 key 推断，不自动换 provider | 已确认 | 已实现；client.py、主规格 | Factory.create |
| 外部协议 | OpenAI-compatible Chat Completions | 已确认 | 已实现；transport.py、adapters、主规格 | Policy/Transport |
| 配置与思考 | 服务端环境配置；thinking 默认开启；effort 按 provider 限制 | 已确认 | 已实现；config.py、adapters | ProviderProfile/Options |
| Schema 不兼容 | 明确拒绝，不静默削弱约束 | 已确认 | 已实现；validation.py、adapters | FunctionTool |
| Retry/fallback | SDK max_retries=0；Provider 不 retry、不 fallback | 已确认 | 已实现；transport.py/client.py | ProviderFailure |
| continuation | provider-scoped 私有内存数据；持久化交后续 change | 已确认 | 边界已实现，持久化未实现；models.py、主规格 | ProviderContinuation |
| 模型质量 | mock 合同通过不证明真实图表质量 | 已确认 | 真实服务/eval尚未验证 | 后续 evaluation |

## 2. 实现合同

### 组件与职责

| 组件/源码 | 职责 | 输入 | 输出 | 调用依赖 | 状态/证据 |
|---|---|---|---|---|---|
| config.py · ProviderSettings/Profile | 环境解析、固定 model 绑定、配置与本地可用性 | FIGURA_<PROVIDER>_* | profiles/availability | ProviderFactory | 已实现；config.py |
| client.py · ProviderFactory | availability 与显式创建 client | provider_id/model_id | Availability tuple 或 ProviderClient | settings、policy、transport factory | 已实现；client.py |
| client.py · ProviderClient | 请求校验、payload 构造、发送、normalize、错误分类 | ProviderRequest | ProviderResponse/ProviderCallError | validation、policy、transport | 已实现；client.py |
| validation.py | 角色、消息顺序、tool 配对、图片、Schema 和上限校验 | ProviderRequest | 接受或安全输入错误 | client/adapters | 已实现；validation.py |
| adapters/base.py · ProviderPolicy | 共用 payload、normalize、stream 聚合和 usage | Request/Profile/raw result | 通用 payload/response | provider-specific policy | 已实现；base.py |
| adapters/qwen.py、deepseek.py、mimo.py | 各家 role/thinking/effort/continuation/strict 差异 | Request/Profile | 供应商 payload/统一 response | ProviderPolicy | 已实现；三个 adapter |
| transport.py · OpenAISDKTransport | provider-scoped SDK client；禁用 SDK retries | Profile/payload | raw response/stream | OpenAI SDK | 已实现；transport.py |
| models.py、errors.py | immutable data contracts 与固定错误分类 | typed values | typed result/error | 所有 provider 组件 | 已实现；对应文件 |

### 字段与数据合同

本节字段逐行对应当前实现，未另注时状态均为已实现；末列路径为代码证据。ProviderSettings、请求、响应和错误只在进程内存；仅请求内容发送给所选供应商。以下每行只描述一个字段。

#### 配置与 availability 字段

| 字段路径 | 类型/必填/可空/默认/边界 | 来源、owner、读写时机 | 生命周期/存储/暴露 | 校验、错误和证据 |
|---|---|---|---|---|
| FIGURA_<PROVIDER>_API_KEY | 可选字符串；空白视为缺失 | 部署环境；from_env 读取 | Profile 期间内存；secret | 不进 repr/availability/log；config.py |
| FIGURA_<PROVIDER>_BASE_URL | 可选 HTTPS 字符串；≤2048 chars | 部署环境；config/transport 读取 | Profile 期间内存；原始 URL 不公开 | 无 userinfo/password/query/fragment；config.py |
| FIGURA_<PROVIDER>_TIMEOUT_SECONDS | 可选 float 字符串；默认60；0<x≤600 | 部署环境；config 读取、SDK 使用 | Profile 期间内存 | 非法时回退60并记 invalid_configuration；config.py |
| FIGURA_<PROVIDER>_THINKING_MODE | 可选 bool 字符串；默认true | 部署环境；config/adapter 读取 | Profile 期间内存 | 接受 true/false/yes/no/on/off/1/0；非法回退 true 并记错；config.py |
| FIGURA_<PROVIDER>_REASONING_EFFORT | 可选字符串；默认None；Qwen: none/minimal/low/medium/high/xhigh/max；DeepSeek另有ultra；MiMo禁用 | 部署环境；config/policy 读取 | Profile 期间内存 | provider allowlist、与 thinking 一致性校验；config.py/adapters |
| ProviderSettings.profiles | Mapping[ProviderId, ProviderProfile]；必需；覆盖全部3种provider | from_env/注入创建；Factory读取 | immutable mapping；进程内 | 键、provider_id、model_id 必须匹配；config.py |
| ProviderProfile.provider_id | ProviderId；必需，非空 | config parser 创建；Factory/client读取 | immutable profile | 只能是 qwen/deepseek/mimo；config.py/models.py |
| ProviderProfile.model_id | str；必需，固定映射 | MODEL_IDS/config parser | immutable profile | 不匹配 provider allowlist 则拒绝；config.py |
| ProviderProfile.api_key | str或None；值可空 | 环境解析；transport读取 | 内存，不持久化 | secret；repr隐藏；缺失则 unavailable；config.py |
| ProviderProfile.base_url | str或None；Qwen必填，DeepSeek/MiMo有默认 | 环境/默认值解析；transport读取 | 内存，不持久化 | HTTPS限制同上；不出现在availability；config.py |
| ProviderProfile.timeout_seconds | float；必需；默认60，≤600且>0 | 环境解析；SDK创建时读取 | 内存配置 | 非法设置 configuration_error；config.py |
| ProviderProfile.thinking_mode | bool；必需；默认true | 环境解析；policy读取 | 内存配置 | 与 reasoning_effort 交叉校验；config.py/adapters |
| ProviderProfile.reasoning_effort | str或None；默认None | 环境解析；policy读取 | 内存配置 | Qwen/DeepSeek枚举校验；MiMo不支持；adapters |
| ProviderProfile.configuration_error | ProviderFailureCode或None；默认None | config parser/policy 写 | availability/create时读取 | 只投影固定 reason_code；config.py |
| ProviderAvailability.provider_id | ProviderId；必需 | profile.availability生成 | 即时本地投影 | 可公开；allowlist固定；config.py/models.py |
| ProviderAvailability.model_id | str；必需 | profile生成 | 即时本地投影 | 可公开；固定模型；config.py |
| ProviderAvailability.available | bool；必需 | profile/policy计算 | 不持久化 | 仅代表本地配置，不代表远端探活；client.py |
| ProviderAvailability.reason_code | str或None；默认None | config/policy生成 | 不持久化 | 固定安全代码，不含key/URL/body；config.py |

#### 请求字段

| 字段路径 | 类型/必填/可空/默认/边界 | 来源、owner、读写时机 | 生命周期/存储/暴露 | 校验、错误和证据 |
|---|---|---|---|---|
| ProviderRequest.provider_id | ProviderId或str；必需 | caller创建；client/validator读取 | 单次内存请求 | 显式值须匹配client；models.py/validation.py |
| ProviderRequest.model_id | str；必需；固定model id | caller创建；client/policy读取 | 单次请求，随response返回 | provider和client双重allowlist；models.py |
| ProviderRequest.instructions | tuple[InstructionBlock]；必需；≤32块 | Prompt caller提供 | 单次内存并发送 | role限制；总文本≤1MiB；validation.py |
| ProviderRequest.messages | tuple[ProviderMessage]；必需；≤256条 | caller提供；validator/adapter读取 | 单次内存并发送 | role/order/tool配对/image校验；validation.py |
| ProviderRequest.options | ProviderOptions；必需 | caller提供；validator/policy读取 | 单次内存并发送 | schema version、采样上限逐项校验；models.py |
| ProviderRequest.tools | tuple[FunctionTool]；默认空；≤64个 | ToolRegistry/上游caller提供 | 单次内存并发送 | schema subset校验，总文本计入1MiB；validation.py |
| InstructionBlock.role | InstructionRole；必需；system/developer | Prompt caller设置 | 单次request | Qwen/DeepSeek映射system，MiMo保留developer；models.py/adapters |
| InstructionBlock.content | str；必需 | Prompt caller设置 | 单次内存并发送 | 必须是文本；计入总文本上限；validation.py |
| TextBlock.text | str；必需 | caller消息 | 单次内存并发送 | 类型校验；计入1MiB总文本；validation.py |
| ImageBlock.media_type | str；必需；jpeg/png/gif/webp | 已授权上游附件resolver | 单次内存 | 非白名单拒绝；不含路径；validation.py |
| ImageBlock.image_bytes | 非空bytes；单张≤24MiB−64；总≤32MiB；最多16张 | 已授权上游提供；adapter编码 | 请求结束即释放；不落盘 | 高敏；repr/log隐藏；仅user role；validation.py |
| ProviderMessage.role | MessageRole；必需；user/assistant/tool | caller设置；validator读取 | 单次请求 | role决定字段权限；models.py/validation.py |
| ProviderMessage.content | str或tuple[TextBlock/ImageBlock]；默认空字符串 | caller设置；adapter读取 | 单次请求并发送 | 仅支持显式block；validation.py |
| ProviderMessage.tool_calls | tuple[ProviderToolCall]；默认空；assistant每条≤64 | assistant history/caller | 单次请求 | 仅assistant；call_id不可重复；validation.py |
| ProviderMessage.tool_call_id | str或None；默认None | caller工具回复 | 单次请求 | 仅tool role；必须关联待完成call；validation.py |
| ProviderMessage.continuation | ProviderContinuation或None；默认None | provider response回传 | 单次请求；内存 | 私有repr隐藏；provider scope/version校验；validation.py |
| ProviderToolCall.call_id | 非空str；provider响应≤256 chars | provider normalize | request/response内存 | tool history唯一；base.py/validation.py |
| ProviderToolCall.name | str；1–64；字母/数字/_/- | provider normalize或tool definition | request/response内存 | regex校验；base.py/validation.py |
| ProviderToolCall.arguments | str；response≤1Mi chars | provider normalize/caller history | request/response内存 | 不执行、不可信任；base.py |
| ProviderContinuation.provider_id | ProviderId；必需 | adapter创建 | 多轮之间短暂内存 | 必须匹配client；models.py/validation.py |
| ProviderContinuation.format_version | int；当前1 | adapter创建 | 多轮之间短暂内存 | 不支持版本拒绝；base.py/validation.py |
| ProviderContinuation.reasoning_content | str；response≤1Mi chars | provider raw reasoning | 多轮之间短暂内存 | repr/public projection/log隐藏；base.py |
| FunctionTool.name | str；必需；1–64 [A-Za-z0-9_-] | ToolRegistry/上游caller | 单次request并发送 | 格式错误拒绝；validation.py |
| FunctionTool.parameters | Mapping；必需；顶层object；深度≤16、properties≤256 | ToolRegistry/上游caller | 单次request并发送 | allowlisted JSON Schema；不兼容即拒绝；validation.py |
| FunctionTool.description | str；默认空；≤8192 chars | ToolRegistry/上游caller | 单次request并发送 | 类型/长度验证；validation.py |
| FunctionTool.strict | bool或None；默认None | ToolRegistry/上游caller | 单次request并映射 | Qwen拒绝；DeepSeek需Beta endpoint且所有tool strict；MiMo strict subset；validation.py/adapters |
| ProviderOptions.max_completion_tokens | int；必需；1–131072 | caller设置 | 单次request | 越界 invalid_request；validation.py |
| ProviderOptions.stream | bool；默认false | caller设置；client读取 | 单次request | 严格bool；validation.py |
| ProviderOptions.thinking_mode | bool或None；默认None，继承profile | caller/profile；policy读取 | 单次request | 严格类型；与effort组合校验；validation.py |
| ProviderOptions.reasoning_effort | str或None；默认None | caller/profile；policy读取 | 单次request | provider-specific allowlist；adapters |
| ProviderOptions.schema_version | int；默认1，仅支持1 | caller/type definition | 单次request | 未知版本 invalid_request；models.py/validation.py |

#### 响应与错误字段

| 字段路径 | 类型/必填/可空/默认/边界 | 来源、owner、读写时机 | 生命周期/存储/暴露 | 校验、错误和证据 |
|---|---|---|---|---|
| ProviderUsage.prompt_tokens | int或None；默认None；0–2³¹−1 | SDK normalize | 单次response内存 | 非法值转None；base.py |
| ProviderUsage.completion_tokens | int或None；默认None；0–2³¹−1 | SDK normalize | 单次response内存 | 非法值转None；base.py |
| ProviderUsage.total_tokens | int或None；默认None；0–2³¹−1 | SDK normalize | 单次response内存 | 非法值转None；base.py |
| ProviderResponse.provider_id | ProviderId；必需 | 已选择client/policy | 单次response内存 | 固定provider；base.py |
| ProviderResponse.model_id | str；必需 | 已校验request | 单次response内存 | 固定allowlist model；base.py |
| ProviderResponse.assistant_content | str；必需；≤1Mi chars | SDK normalize | 单次response内存 | 非字符串/超限 protocol error；base.py |
| ProviderResponse.tool_calls | tuple[ProviderToolCall]；必需；≤64 | SDK normalize | 单次response内存 | 顺序保留；调用方再验证；base.py |
| ProviderResponse.finish_reason | FinishReason；必需；stop/tool_calls/length/content_filter/other | SDK normalize | 单次response内存 | 未知值归other；base.py |
| ProviderResponse.usage | ProviderUsage或None；默认None | SDK normalize | 单次response内存 | 仅保留有界计数；base.py |
| ProviderResponse.provider_response_id | str或None；默认None；1–256 chars才保留 | SDK normalize | 单次response内存 | 不合格丢弃；base.py |
| ProviderResponse.continuation | ProviderContinuation或None；默认None | raw reasoning normalize | 单次response内存 | repr/to_public_dict排除；base.py/models.py |
| ProviderFailure.failure_code | ProviderFailureCode；必需 | config/client/policy | 单次错误对象 | 固定枚举；errors.py/client.py |
| ProviderFailure.outcome_known | bool；必需 | SDK/protocol mapper | 单次错误对象 | 区分明确拒绝/结果未知；client.py |
| ProviderFailure.transient | bool；必需 | SDK/protocol mapper | 单次错误对象 | 不触发自动retry；client.py |
| ProviderFailure.safe_message | str；必需；固定文案 | mapper生成 | 单次错误对象 | 不透传SDK消息/body；errors.py/client.py |
| ProviderFailure.http_status | int或None；默认None；保留范围100–599 | APIStatusError | 单次错误对象 | 有状态码时作为有限metadata；client.py |
| ProviderCallError.failure | ProviderFailure；必需 | ProviderClient分类后构造 | 单次exception内存 | 异常message使用failure.safe_message；errors.py |
| ProviderProtocolError.code | ProviderFailureCode；默认invalid_provider_response | adapter normalize构造 | 单次exception内存 | 不含raw response；errors.py |
| ProviderProtocolError.outcome_known | bool；默认true，可按错误覆盖 | adapter normalize构造 | 单次exception内存 | client.py据此生成ProviderFailure；errors.py/client.py |
| ProviderProtocolError.transient | bool；默认false，可按错误覆盖 | adapter normalize构造 | 单次exception内存 | 不触发自动retry；errors.py/client.py |

枚举范围：ProviderId=qwen/deepseek/mimo；InstructionRole=system/developer；MessageRole=user/assistant/tool；FinishReason=stop/tool_calls/length/content_filter/other。未知 provider/model/role/schema key/content type 拒绝；未知 finish_reason 映射 other。错误合同见“API、事件与错误合同”。

### API、事件与错误合同

| API | 调用者 | 输入 | 返回 | 校验与副作用 | 幂等/顺序/协议 |
|---|---|---|---|---|---|
| ProviderSettings.from_env(environ?) | app composition | optional env mapping | 三份profile | 配置错误保留为code；只建内存对象 | 无网络；config.py |
| ProviderFactory.availability() | internal/UI projection caller | 无 | provider/model/available/reason_code | 只读本地设置；不探活 | 无副作用；client.py |
| ProviderFactory.create(provider_id, model_id) | internal caller | 显式两字段 | ProviderClient | allowlist/config校验；仅此时建transport | 不fallback；client.py |
| ProviderClient.complete(request) | Agent/上层caller | ProviderRequest | ProviderResponse/ProviderCallError | 本地校验→build→一次发送→normalize | 无retry；Chat Completions；client.py |
| ProviderClient.close() | client owner | 无 | 无 | 关闭transport | 释放SDK资源；client.py |
| CompletionTransport.create(payload) | ProviderClient | policy payload | raw result/stream | SDK errors由client分类 | SDK max_retries=0；transport.py |

外部映射：Qwen developer→system、preserve_thinking；DeepSeek developer→system、thinking.type/effort；MiMo保留developer、thinking.type、不支持effort。三家图像都编码为Base64 data URL。Tool Schema不兼容则拒绝。无Provider事件、HTTP API或持久副作用。

**错误、重试与恢复**

| 错误/code | 触发点 | 结果已知 | 暂时性 | 安全重试依据 | 已提交状态 | 安全消息/恢复owner |
|---|---|---|---|---|---|---|
| configuration_missing/invalid_configuration | profile/policy配置校验 | 已知未发送 | 否 | 修配置后显式建client | 无副作用 | 固定reason；deployment owner |
| unsupported_provider/unsupported_model | Factory/request validation | 已知未发送 | 否 | 修正选择 | 无副作用 | 固定错误；caller |
| invalid_request/unsupported_capability | local validation/policy | 已知未发送 | 否 | 修字段/能力后再调用 | 无副作用 | 固定消息；caller/ToolRegistry |
| provider_rejected | 明确4xx，408除外；429的outcome仍known但transient=true | 已知拒绝 | 通常否；429是 | Provider不重试；上层按限流策略决定 | 无本地写入 | 安全消息/status；caller |
| provider_unavailable | HTTP 408/5xx | 未知 | 是 | 不自动重试 | 远端可能已处理 | 暂时不可用的安全消息；未来Run policy |
| timeout/connection_error | 网络/超时 | 未知 | 是 | 不可自动安全重试 | 远端可能已处理 | 安全分类；未来Run policy |
| transport_error | SDK未分类transport error | 未知 | 是 | 不自动重试/fallback | 无Provider持久记录 | 安全分类；未来Run policy |
| incomplete_stream | stream未完整结束 | 未知 | 可能 | 不自动重发 | 不返回成功response | 固定协议消息；Provider/Run owner |
| invalid_provider_response | raw response不符合schema/边界 | response已到但不可用 | 通常否 | 不自动重发 | 无本地状态 | 固定安全消息；Provider owner |

全量ProviderFailureCode：configuration_missing、invalid_configuration、unsupported_provider、unsupported_model、invalid_request、unsupported_capability、provider_rejected、provider_unavailable、timeout、connection_error、incomplete_stream、invalid_provider_response、transport_error。SDK原始异常和响应正文不对外暴露。

### 安全、隐私与资源上限

| 数据/资源 | 合法来源/owner | 可读组件 | 传输/存储/保留 | 日志/API投影 | 上限与拒绝 | 证据 |
|---|---|---|---|---|---|---|
| API key | 部署环境 | config/transport | 请求认证；进程内 | repr/availability/log不含key | 缺失则unavailable | config.py/transport.py |
| Base URL | 部署环境 | config/policy/transport | SDK endpoint；进程内 | availability不返回原值 | HTTPS、无userinfo/query/fragment、≤2048 | config.py |
| prompt/message/schema文本 | caller/Prompt/ToolRegistry | validation/adapter/transport | 发给被选provider；不本地持久化 | 禁止记录raw payload | instruction≤32、message≤256、tool≤64、总文本≤1MiB | validation.py |
| image bytes | 上游授权的附件resolver | validation/adapter/transport | request期内存，出站Base64 | repr/log不含图像字节 | 格式白名单；单张≤24MiB−64；≤16张；总≤32MiB | models.py/validation.py |
| tool arguments | provider输出或caller历史 | adapter/上层 | 一次调用内存 | 不自动执行 | 每项≤1Mi chars；每条assistant≤64 calls | base.py/validation.py |
| continuation reasoning | provider输出 | adapter/明确的上层owner | 内存往返；不持久化 | repr/public dict/log排除 | 单项≤1Mi chars；请求合计≤1MiB文本 | models.py/base.py |
| failure details | SDK/provider mapper | caller | error object内存 | 只投影code/status/safe_message | 不含raw exception/body | errors.py/client.py |
| response text/metadata | SDK normalize | caller | response内存 | SDK raw不保留 | 文本≤1Mi chars、ID≤256 chars、usage≤2³¹−1 | base.py |

**版本、兼容与迁移**

- ProviderOptions.schema_version 当前为1；未知版本以 invalid_request 拒绝。
- ProviderContinuation.format_version 当前为1，并校验 provider scope。
- Python dataclass 是内部API；无HTTP API version、Provider event version或持久化 schema。
- 不适用：Provider请求、响应、profile、continuation均不在本change持久化，因此无数据库 migration/旧数据 downgrade。
- ProviderProfile没有profile_version；Run持有provider/model不等于持有完整policy快照。


## 3. 核心流程

### 状态与事务

| 实体 | 状态转换 | 触发/前置 | 事务边界 | 并发/终态规则 | 失败影响/证据 |
|---|---|---|---|---|---|
| Profile | env→immutable profile | from_env/注入设置 | 无数据库事务 | 进程配置期间固定 | 配置错误投影reason code；config.py |
| Client | not-created→open→closed | 显式create/close | 无数据库事务 | 由caller持有并关闭；并发保证未声明 | 不留下持久状态；client.py |
| Completion | validated→sent→response/failure | complete(request) | 单次同步网络请求 | 不重发未知结果、不fallback | 上层决定恢复；client.py |
| Continuation | response内存态→后续request→释放 | 显式多轮续接 | 仅内存 | provider_id/format_version一致 | 不匹配拒绝；models.py/validation.py |

不适用：Provider change没有Session/Run/持久状态/事务；这不代表上层已具备恢复语义。

**端到端流转**

1. Factory从环境建立固定 profiles；availability只投影本地状态。
2. Caller显式传provider/model创建client；不根据可用key猜选择。
3. Caller调用complete；先校验options、message/tool配对、image和schema。失败时不触网。
4. 对应policy构造payload；transport发送一次。stream只有在收齐后才normalize为完整response。
5. 成功返回ProviderResponse；失败返回安全ProviderCallError。Continuation不出现在公开投影。
6. 不执行tool、不存Run/response、不持久化continuation；上层后续负责权限、执行、存储和恢复。

~~~mermaid
sequenceDiagram
    participant Caller
    participant Factory
    participant Client
    participant Policy
    participant Transport
    Caller->>Factory: create(provider_id, model_id)
    Factory-->>Caller: ProviderClient
    Caller->>Client: complete(ProviderRequest)
    Client->>Policy: validate and map
    Policy->>Transport: one Chat Completions call
    Transport-->>Policy: response or stream
    Policy-->>Client: normalized response
    Client-->>Caller: ProviderResponse or safe error
~~~

## 4. 实现对照

只保留历史草案中仍影响当前合同或后续决策的差异；与当前代码一致的历史字段不重复列出，完整字段合同见第 2 节。

| 字段/组件/行为 | 初始草案/计划 | 当前代码 | 主规格/OpenSpec | 差异/影响 | 后续owner/证据 |
|---|---|---|---|---|---|
| api_key_source | 初始Profile字段草案 | 未实现 | 不要求该字段 | 无配置来源审计 | 配置change；config.py/归档proposal |
| profile_version | 草案建议版本化请求翻译与恢复策略 | 未实现 | 不要求profile快照 | 不能凭Run的provider/model恢复旧policy | Run/recovery owner |
| availability.status | 草案字段名status | available bool + reason_code | 主规格只定义安全本地availability | 不做网络探活 | Provider API；models.py/spec |
| ProviderCall/options | 草案抽象调用与options | ProviderRequest + ProviderOptions | 主规格要求bounded request | 以代码合同为准 | models.py |
| image input | 草案未来由受管attachment引用解析 | 只接收上游授权的内存bytes | 主规格强调授权图像输入 | 附件层未实现 | Attachment change |
| continuation durable ref | 草案方向为可控引用 | 仅内存对象 | 主规格明确持久化属于后续 | Run恢复前须有private store | Provider/Run integration |
| Run选择冻结 | Provider草案计划将来写入Run | Run change已保存requested/actual provider/model | Run主规格已同步 | 创建Run仍不调用Provider | Execution integration |
| 真实模型质量 | 计划需评估图表任务 | 无真实服务/eval证据 | 主规格不声称质量过关 | mock通过不可替代图表评估 | evaluation owner |
| ProviderProfile.max_completion_tokens | 初始设想放入profile | 由每次请求的ProviderOptions.max_completion_tokens承载 | 主规格要求每次调用有界 | 与profile分离，调用方可逐请求设定 | models.py/validation.py |
| Run.provider_profile_version | 草案提出将provider策略版本冻结到Run | 未实现；Run只存requested/actual provider/model | 主规格不要求完整profile snapshot | 不能用Run字段重建历史provider策略 | Run/recovery owner |
| FunctionTool.strict | 草案希望统一要求strict schema | 支持有界strict子集；按provider能力映射或拒绝 | 主规格要求不静默削弱Schema约束 | 各供应商能力差异需由adapter显式处理 | adapters/validation.py |
| continuation_payload | 草案名为provider私有原样续接 | 实现为ProviderContinuation，内存往返且不持久化 | 主规格将持久化留给后续change | durable resume前需定义受控存储和引用校验 | Provider/Run integration |

## 5. 验证与交接

### 验证

#### 计划验证

| 目标 | 精确命令/操作 | 预期 | 边界 |
|---|---|---|---|
| provider配置、适配器、错误和normalize合同 | conda run -n agent python -m pytest -q tests/test_figura_provider.py | focused mock tests全部通过 | 不等于真实供应商调用/图表质量 |
| 主规格 | 对 Figura model-provider 执行 OpenSpec strict validation | spec requirements/scenarios通过 | 静态规格校验 |
| 文档差异 | git diff --check -- docs/figura-implementation/changes/add-figura-model-client.md | 无空白错误 | 文档范围 |

#### 已观察验证

| 日期 | 实际命令/操作 | 实际结果 | 覆盖边界/来源 |
|---|---|---|---|
| 2026-09-26，既有实现记录 | conda run -n agent python -m pytest -q tests/test_figura_provider.py | 15项通过 | mock/provider adapters；本次未重跑 |
| 2026-09-26，既有实现记录 | model-provider strict validation | 通过；具体CLI命令未保留 | 不补造命令；本次确认主规格/归档存在 |
| 本次回填 | 只读检查Provider代码、主规格、归档工件和文档结构 | 未运行应用测试 | 不是Provider行为验证 |

### 交接

- 后续依赖：Run Provider执行、continuation私有存储和引用校验、Attachment授权/读取、ToolRegistry、Prompt assembly、Gateway/CLI/UI。
- 待确认：默认provider owner；Qwen部署地域/workspace URL；MiMo套餐与URL/key配对；profile_version是否需要持久化；真实评估后是否调整thinking默认策略。
- 未实现：Provider tool执行循环、Run response持久化、continuation durable ref、真实图表评估、上层安全retry。
- 交接：Run execution core已提供持久化底座；下一 change 先处理continuation存储和unknown-outcome恢复。
