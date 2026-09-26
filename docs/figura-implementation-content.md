# Figura 实现内容记录

> 状态：`add-figura-model-client` 的 Provider 基础层代码和 mock coverage 已落地；`tests/test_figura_provider.py` 15 项通过，未执行旧项目全量测试。
>
> 用途：逐项记录准备实际实现的范围、字段、协议、取舍和待确认问题。每开始一个 change，先核对本记录与现有代码，再形成该 change 的 proposal、spec、design 和 tasks；实现后回填实际结果。总体架构稿是参考材料，不能因其已有字段就视为最终决定。
>
> 相关文档：[Provider change proposal](../openspec/figura/openspec/changes/add-figura-model-client/proposal.md) · [架构设计草稿](figura-architecture-design.md)。此前引用的 Change 实施路线图当前不在 `docs/` 工作区中，暂不据此推导依赖。

## 记录规则

- **已确认**：本轮讨论中用户明确接受的范围或具体模型。后续如修改，在此记录新决定及影响的 change。
- **暂定**：为了使方案完整而提出的实施建议，正式编写 OpenSpec 工件时需逐项核定。
- **待确认**：会影响字段、兼容性或开发顺序，但目前还没有决定的事项。
- **已实现**：只有代码落地并核对后才使用；仅写在设计稿或 OpenSpec 中不算已实现。
- 本文件记录跨 change 的当前实施意图；正式行为合同写入 Figura OpenSpec。两者出现差异时，明确记录差异并一起修订，不默默以旧设计稿覆盖新决定。

## 当前实施顺序

| 顺序 | 内容 | 状态 | 后续交接 |
|---|---|---|---|
| 先行 | 三 Provider 的配置、调用协议和适配器基础层 | 已实现；mock coverage 15 项通过 | `add-figura-model-client` 负责独立 Python 调用，不等待 RunCoordinator。 |
| 后续 | 将请求值解析并冻结到 Run，保存模型响应及私有续接引用 | 暂定，未实现 | 与 Run/ExecutionRecord、RunCoordinator 和 Agent loop 的 change 衔接。 |
| 后续 | 真实 ToolRegistry、附件授权读取、Prompt 装配、CLI/Gateway/前端选择器 | 暂定，未实现 | 分别由后续 change 负责，不合并进首个 Provider change。 |

`src/figura/providers/` 是 Figura 自有实现；本文件不把 ChartAgent v1 的 provider 客户端算作 Figura 已实现功能。

## 01 · Provider 基础层

**OpenSpec change：** [`add-figura-model-client`](../openspec/figura/openspec/changes/add-figura-model-client/proposal.md)。下方“实际实现结果”记录代码合同；如与前面的提案草案有差异，以代码与该节的实现事实为准，再同步修订 OpenSpec。

### 目标与边界

**已确认**

1. 首版仅提供 `qwen`、`deepseek`、`mimo` 三个 provider，各固定一个 API 模型 ID。不按密钥存在与否猜测 provider，不在调用中自动切换到别家。
2. 服务端持有密钥、接口地址、模型映射及请求策略；请求方最多表达想用哪个已配置 provider/model。解析出的实际选择在未来创建 Run 时冻结。
3. 支持 Figura 需要的文本、图像和原生 function tool calls；先定义独立的客户端合同，后续再接入受管附件、ToolRegistry 和 Run。
4. 将思考内容作为 provider 私有续接数据处理，不放进普通答复、公开运行事件或无界日志。多轮工具调用时按各家协议回传。
5. 超时和传输错误区分“暂时性故障”与“远端结果未知”；SDK 不得自行进行不受控的隐式重试。工具 Schema 不兼容时明确失败，不静默放宽。

**本 change 暂不负责**：具体图表工具、Agent 循环、Prompt 文案、Run/SQLite 写入、附件持久化、前端选择器、视觉审核器调用和自动跨 provider 故障转移。这些边界不妨碍 Provider 层先用内存中的图片及示例工具合同完成独立接线。

### 固定模型与官方接口

| `provider_id` | 首版唯一 `model_id` | 服务端接口配置 | 与本次实现直接相关的差异 |
|---|---|---|---|
| `qwen` | `qwen3.8-flash` | `base_url` 需按百炼账号的地域和工作空间配置；不把旧 DashScope 地址当成所有环境的固定值 | 有 Qwen 自己的思考参数和 `preserve_thinking` 行为；图像、工具及流式能力需按该模型适配。 |
| `deepseek` | `deepseek-flash` | 官方 OpenAI 兼容地址 `https://api.deepseek.com`，仍允许服务端显式配置 | 思考模式配合 `tools` 时，后续请求要完整回传相关历史 `reasoning_content`。 |
| `mimo` | `mimo-v2.6-flash` | 小米按量 API 示例地址 `https://api.xiaomimimo.com/v1`；若选 Token Plan，密钥和地址须成对配置 | 图片可用 Base64 data URL；思考与多轮工具调用需回传历史 `reasoning_content`；思考模式下自定义 `temperature`/`top_p` 不生效，`tool_choice` 不依赖强制模式。 |

以上是 API 名称，不是 UI 展示名。三个模型是否都对 Figura 图表样本达到可接受效果，必须在后续真实评估中判断；“官方支持图像和工具调用”不等于图表分析质量已经验证。

资料：[Qwen 模型能力](https://help.aliyun.com/zh/model-studio/vision-model)、[Qwen 接口地址](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、[Qwen Chat 参数](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)、[DeepSeek 视觉输入](https://api-docs.deepseek.com/guides/vision/)、[DeepSeek 思考与工具](https://api-docs.deepseek.com/guides/thinking_mode/)、[MiMo 模型](https://mimo.mi.com/models/en-US/mimo-v2.6-flash)、[MiMo 图片输入](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding)、[MiMo Chat API](https://mimo.mi.com/docs/en-US/api/chat)、[MiMo 思考续接](https://mimo.mi.com/docs/en-US/usage-guide/passing-back-reasoning_content)。

### 字段与数据归属

下表保留实现前的字段草案，不能当作当前代码合同。具体落地字段见后面的“实际实现结果”；尚未进入 Provider 层的 Run 字段继续留给后续 change。

| 对象 / 生命周期 | 字段 | 类型与规则 | 状态 |
|---|---|---|---|
| `ProviderId` / 静态 | `qwen \| deepseek \| mimo` | 严格枚举；未知值在发起请求前拒绝 | 已确认 |
| `ProviderProfile` / 进程配置 | `provider_id`, `model_id`, `base_url`, `api_key_source` | provider/model 配对固定；建议用 `FIGURA_QWEN_API_KEY`、`FIGURA_DEEPSEEK_API_KEY`、`FIGURA_MIMO_API_KEY`；Qwen 要显式配置地域匹配的 `FIGURA_QWEN_BASE_URL`，DeepSeek/MiMo 可覆盖各自默认 URL | 范围已确认；变量名与解析实现暂定 |
| `ProviderProfile` / 进程配置 | `timeout_seconds`, `thinking_mode`, `reasoning_effort`, `max_completion_tokens` | 有界且按模型验证；MiMo 首版只需思考开关，不承诺 effort 档位；思考模式不发送无效的采样参数 | 暂定 |
| `ProviderProfile` / 初始策略 | `thinking_mode=true`；`reasoning_effort` 未配置时省略 | proposal/design 暂定建议三个模型显式启用思考；可由服务端配置关闭，不做前端选项；应用层必须提供有界 `max_completion_tokens` | 提案建议，待评审 |
| `ProviderProfile` / 进程配置 | `profile_version` | 标识会影响请求翻译与续接规则的配置版本；供未来 Run 审计及恢复时校验 | 暂定，是否持久化待确认 |
| `ProviderAvailability` / 安全投影 | `provider_id`, `model_id`, `status`, `reason_code` | `status` 表示本地配置可用性，不能声称已验证网络或账号余额；不得包含密钥、原始 URL 或异常正文 | 暂定 |
| `RunInput` / 未来初始事实 | `requested_provider?`, `requested_model?` | 记录原始请求选项；客户端不能以此覆盖密钥和接口地址；首版交互可只开放 provider 选择 | 已确认方向，落库属于后续 change |
| `Run` / 未来不可变快照 | `provider`, `model` | 创建 Run 时解析出实际 API provider/model 后写入；在一次 Run 中不变 | 已确认方向，落库属于后续 change |
| `Run` / 未来不可变快照 | `provider_profile_version?` | 如果加入，必须能定位当时的请求翻译和续接规则；并不保证供应商的同名模型别名指向不变权重 | 待确认 |
| `ProviderCall` / 单次内存对象 | `provider_id`, `model_id`, `messages[]`, `tools[]`, `options` | 不从当前目录路径、环境密钥或未授权附件引用直接构造公开请求；由上游提供已授权输入 | 暂定 |
| `ProviderCall.options` / 单次内存对象 | `schema_version`, `thinking_mode`, `reasoning_effort?`, `max_completion_tokens`, `stream` | 白名单字段；各适配器验证支持情况；不接受任意 `extra_body` | 暂定 |
| `ProviderMessage` / 单次内存对象 | `role`, `content[]`, `tool_calls[]?`, `tool_call_id?` | 保持 user/assistant/tool 的顺序和配对；`content` 只接受明确定义的文本或图片块 | 暂定 |
| `ResolvedImageInput` / 单次内存对象 | `media_type`, `image_bytes` | 未来由授权的附件/产物 ref 读取；只在发送前短暂持有并编码，不将 Base64 写进执行事实或日志 | 暂定 |
| `ProviderToolSchema` / 单次内存对象 | `name`, `description`, `parameters`, `strict_requested?` | 来源是后续 ToolRegistry；不兼容的 JSON Schema 或 strict 要求直接拒绝，模型返回的参数仍由服务端校验 | 已确认方向，字段名暂定 |
| `ModelResponse` / 单次结果 | `assistant_content`, `tool_calls[]`, `finish_reason`, `usage?`, `provider_response_id?` | `tool_calls[]` 保留原有顺序、`call_id`、名称和原始参数字符串；不返回完整 SDK `raw` 对象供持久化 | 暂定 |
| `ModelResponse` / 私有结果 | `continuation_payload?` | 保存后续请求必须精确回传的 provider 私有内容，含格式版本；未来持久化时只保存受控 `continuation_payload_ref` | 已确认方向，具体封装暂定 |
| `ProviderFailure` / 单次错误 | `failure_code`, `http_status?`, `outcome_known`, `transient`, `safe_message` | 安全分类而非原始异常正文；`transient=true` 不自动推出“可立即重发” | 已确认方向，字段名暂定 |

**字段流转：** `RunInput.requested_*` → 服务端解析 `ProviderProfile` → `Run.provider/model` 快照 → 单次 `ProviderCall` → `ModelResponse` → 未来的 `model_response` ExecutionRecord。Provider 基础层阶段只落实其中与独立调用相关的部分，不为尚未出现的 Run 写占位记录。

### 实际实现结果（2026-09-26）

本节以 `src/figura/providers/` 当前代码为准。实现没有新增 Run、AttachmentStore、ToolRegistry、Gateway、CLI 或前端依赖。

| 对象 | 实际字段 / API | 规则与数据边界 |
|---|---|---|
| `ProviderId`、`MODEL_IDS` | `qwen`, `deepseek`, `mimo` → `qwen3.8-flash`, `deepseek-flash`, `mimo-v2.6-flash` | 枚举和只读映射；factory 必须同时接收 `provider_id` 与 `model_id`，不按已配置密钥推断或切换。 |
| `ProviderProfile` | `provider_id`, `model_id`, `api_key`, `base_url`, `timeout_seconds`, `thinking_mode`, `reasoning_effort`, `configuration_error` | 由 `ProviderSettings.from_env()` 读取；`api_key`、`base_url` 不进入 repr 或 availability。Profile 没有 `api_key_source` 或持久化版本字段。 |
| Provider 环境变量 | `FIGURA_<PROVIDER>_API_KEY`, `FIGURA_<PROVIDER>_BASE_URL`, `FIGURA_<PROVIDER>_TIMEOUT_SECONDS`, `FIGURA_<PROVIDER>_THINKING_MODE`, 可选 `FIGURA_<PROVIDER>_REASONING_EFFORT` | Qwen 必须配置 HTTPS `BASE_URL`；DeepSeek 默认 `https://api.deepseek.com`；MiMo 默认 `https://api.xiaomimimo.com/v1`。MiMo Token Plan 使用成对的自定义 `FIGURA_MIMO_BASE_URL` 和对应 `FIGURA_MIMO_API_KEY`。超时默认为 60 秒、上限 600 秒；三个 thinking 默认值均为 `true`。 |
| `ProviderAvailability` | `provider_id`, `model_id`, `available`, `reason_code` | 只反映本地配置，不发网络请求；reason code 不包含密钥、URL 或异常正文。代码字段是 `available`，不是草案中的 `status`。 |
| `ProviderRequest` | `provider_id`, `model_id`, `instructions`, `messages`, `options`, `tools` | 一次性内存输入；options 必填。不存在调用方可传入的 `extra_body`、密钥、端点或任意 SDK 参数。 |
| `ProviderOptions` | `max_completion_tokens`, `stream`, `thinking_mode?`, `reasoning_effort?`, `schema_version=1` | `max_completion_tokens` 范围为 1–131072；`thinking_mode=None` 时继承 Profile 配置；effort 由各 provider 验证，MiMo 不支持 effort。 |
| `InstructionBlock` | `role: system\|developer`, `content` | 按输入顺序放在 conversation 前。Qwen、DeepSeek 将 developer 内容映射到 system；MiMo 保留 developer role。 |
| `ProviderMessage` | `role: user\|assistant\|tool`, `content`, `tool_calls`, `tool_call_id?`, `continuation?` | 顺序保留；tool reply 必须关联前序 assistant tool call；图像只能在 user 消息中。 |
| `TextBlock`、`ImageBlock` | `text`; `media_type`, `image_bytes` | 图片仅接受 JPEG、PNG、GIF、WebP；每张上限约 24 MiB、每请求最多 16 张且原始字节总量不超过 32 MiB。字节只在发出请求时编码为 Base64 data URL；repr 不显示图片字节。 |
| `FunctionTool` | `name`, `description`, `parameters`, `strict?` | 仅 function tools；名称遵循 provider 的 1–64 字符规则。允许关键字为 `type`, `properties`, `required`, `additionalProperties`, `items`, `enum`, `description`, `title`, 数值/长度/数组边界、`pattern`, `uniqueItems`, `anyOf`, `const`；未知关键字直接拒绝，不删除约束。Qwen strict 调用当前明确拒绝；DeepSeek strict 需 Beta base URL、本请求全部函数 strict 且符合严格子集；MiMo strict 也只接受严格子集。 |
| `ProviderToolCall` / `ProviderContinuation` | Tool call: `call_id`, `name`, `arguments`; continuation: `provider_id`, `format_version`, `reasoning_content` | 调用顺序和原始参数字符串保留。Continuation 带 provider scope 和格式版本，reasoning 文本从 repr 与 public projection 排除。DeepSeek/MiMo thinking 模式下，只要请求带 tools，历史中的每条 assistant 消息都必须带 continuation。 |
| `ProviderResponse` | `provider_id`, `model_id`, `assistant_content`, `tool_calls`, `finish_reason`, `usage?`, `provider_response_id?`, `continuation?` | 非流式和流式统一成此结构；usage 只保留有界的 prompt/completion/total 数字；finish reason 被归一到固定枚举。`to_public_dict()` 不含 continuation，也不保留 SDK raw 对象。 |
| `ProviderFailure` | `failure_code`, `http_status?`, `outcome_known`, `transient`, `safe_message` | code 枚举为 `configuration_missing`, `invalid_configuration`, `unsupported_provider`, `unsupported_model`, `invalid_request`, `unsupported_capability`, `provider_rejected`, `provider_unavailable`, `timeout`, `connection_error`, `incomplete_stream`, `invalid_provider_response`, `transport_error`。不包含 SDK 原始异常或响应正文。4xx（408 除外）属于已知拒绝；408、5xx、timeout、连接中断和未完整结束的 stream 属于远端结果未知；任何类别都不由 Provider 自动重试。 |

请求上限另包括 256 条消息、32 个 instruction blocks、64 个 tools、单条 assistant 消息最多 64 个 tool calls，以及文本/Schema/历史参数/continuation 合计最多 1 MiB。OpenAI SDK transport 对每个 Provider 使用各自 URL、key、timeout，并设置 `max_retries=0`。

公开调用入口是 `ProviderFactory.from_env()`、`availability()`、`create(provider_id, model_id)` 和 `ProviderClient.complete(ProviderRequest)`。Availability 只读取配置；只有显式创建 provider/model client 后，`complete()` 才可能发起一次请求。同步 SDK transport 和 mock transport 共用同一适配器与结果合同。

### 适配器规则

1. 统一使用 OpenAI 兼容的 Chat Completions 作为本次接线协议；Qwen 将 developer instructions 映射为 system 并映射 `preserve_thinking`，DeepSeek 映射 `thinking.type` 和可选 effort，MiMo 保留 developer role、映射 `thinking.type` 且拒绝 effort。三个 provider 各自负责请求翻译和响应归一化；调用方不能传供应商专属 body。是否以后采用 Responses API 属于另一项协议决策。
2. 本 change 接收上游已授权的内存图片字节，不读取 AttachmentRef 或本地路径；适配器在发送前编码 Base64 data URL。当前采用 JPEG/PNG/GIF/WebP 白名单和保守字节/数量上限，后续附件层仍负责授权和加载。
3. `thinking_mode` 由服务端默认策略或内部请求选项决定并显式发送。Qwen 设置 `preserve_thinking`；DeepSeek、MiMo 在 thinking 模式且带 tools 的请求中要求每条 assistant 历史消息都携带可恢复 continuation。普通答复、repr 和 public projection 不包含该私有 payload。
4. 三家共用归一化的 `ToolCall` 结构，保留模型给出的 ID、名称、参数字符串和顺序。`tool_choice` 先采用模型自行选择；尤其不能假设 MiMo 会执行“强制调用指定工具”。
5. Provider 适配器只接受实现中明确的 Schema 子集；Qwen function strict 当前不支持，DeepSeek strict 还要求显式配置 Beta endpoint；不静默删除 `required`、`enum` 或其他约束。ToolRegistry 后续仍负责领域工具及其权威 Schema。
6. 流式响应在适配器内归并成完整 `ProviderResponse`；未归并完成的片段会被判为结果未知，不作为成功响应返回。此 change 不生成进度事件。
7. 关闭 SDK 隐式重试（`max_retries=0`），Provider 也不实现重试或切换。4xx（408 除外）归为已知拒绝；408、5xx、timeout、连接中断和未完整 stream 属于结果未知。Run 级安全重试策略留给后续生命周期 change。

### 本次完成点与后续交接

| 完成点 | 交付边界 |
|---|---|
| 三个固定模型可经同一调用接口分别构造请求、归一化文本/图片/工具响应 | Provider 基础层 |
| 思考与工具多轮所需内容可以作为私有续接数据往返，不进入公开对象 | Provider 基础层；受控持久化由后续 ArtifactStore/ExecutionRecord change 接管 |
| 配置缺失、模型不在名单、Schema 不兼容、明确拒绝和结果未知均有安全分类 | Provider 基础层 |
| Run 创建时记录请求值、实际值及必要版本，恢复时读取私有续接 ref | 后续 Run/ExecutionRecord 与 RunCoordinator change |
| 九个图表工具、附件授权、实际图表质量比较和 UI 选择 | 各自后续 change |

### 待确认事项

1. Figura 默认 provider 留给后续应用/Run 层决定；本 change 的客户端要求调用方显式传 provider。
2. 部署时的 Qwen 地域/workspace URL，以及 MiMo 按量 API 或 Token Plan 的 URL/key 配对由部署配置提供，不写入本地或持久 Run 字段。
3. 三模型默认启用 thinking 的策略已实现为 server-side 环境配置（默认 true）；后续实际图表评估可以推动调整。
4. `provider_profile_version` 未在本 change 实现。是否写入持久 Run，以及旧版本配置不可再取得时的 resume 行为，留给 Run/恢复 change。
5. 当前实现没有完成真实 provider 请求或 Figura 图表质量评估；mock coverage 15 项通过，首次接通凭据后还需按需做有界 smoke/eval。

## 后续条目的记录模板

每开始一个 change，在本文件新增一节：**目标与非目标 → 当前代码事实 → 已确认决策 → 字段表（类型、可空性、所有者、写入时机）→ 输入/输出与错误 → 持久化和公开边界 → 完成点 → 与其他 change 的交接 → 待确认及实际实现结果**。已有架构稿可以帮助发现候选字段，但须逐项验证，不能直接整段照搬。
