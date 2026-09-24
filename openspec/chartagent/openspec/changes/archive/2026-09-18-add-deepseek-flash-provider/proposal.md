## Why

Figura 目前只支持 OpenAI 和 Qwen 两个模型来源。DeepSeek V4.1 Flash 已通过 OpenAI 兼容接口提供原生图像理解、工具调用和 JSON 输出能力，适合用于当前的图表视觉理解与 Agent 工具链；现在接入可以在不改变现有工具协议的前提下增加一个可选模型来源。

接入不能只增加一个环境变量：DeepSeek 思考模式在工具调用的后续请求中要求回传 `reasoning_content`，而 Figura 当前对所有 provider 都会从 assistant history 中移除 reasoning。因此需要把 provider 选择、请求参数和多轮历史行为一起纳入一个完整的兼容方案。

## What Changes

- 增加 `deepseek` provider，并使用官方 API model ID `deepseek-flash`（对应 DeepSeek V4.1 Flash）。
- 增加 DeepSeek provider-scoped 配置，包括 API key、base URL、模型、timeout、重试次数、thinking 开关和 reasoning effort。
- 复用现有 OpenAI-compatible Chat Completions 客户端，支持文本、`image_url`、标准 Tool Calls、流式结果和 JSON 输出请求。
- 为 DeepSeek thinking 模式构造 provider-specific 请求字段，并在带工具的多轮请求中安全携带模型要求的 `reasoning_content`。
- 扩展 Gateway readiness、provider 校验、运行快照、事件元数据和错误边界，使 DeepSeek 与现有 provider 行为一致。
- 扩展桌面端 provider 选择器、健康状态和运行详情，保持 API key、endpoint、model 等配置只由本地 Gateway 管理。
- 增加配置解析、请求构造、视觉输入、Tool Calls、reasoning history、Gateway 和前端回归测试，并更新示例配置和规格文档。

## Capabilities

### New Capabilities

无。本次是对现有模型来源能力的扩展，不新增独立的用户功能域。

### Modified Capabilities

- `llm-client`: 增加 DeepSeek provider 配置、OpenAI-compatible 请求、视觉输入、thinking 参数和工具调用历史兼容行为。
- `provider-selection`: 支持 `deepseek` 作为第三个受控 provider，并保持服务端解析与运行快照语义。
- `python-gateway`: readiness、健康响应、运行请求和安全 provider 校验覆盖 DeepSeek。
- `desktop-client`: provider 选择器和运行元数据显示 DeepSeek，并保持不可用状态可解释。
- `agent-observability`: 明确 DeepSeek 的 reasoning 仅作为 provider-required 的内部请求上下文，不作为用户可见推理或普通持久化对话内容。

## Impact

- 主要代码：`src/chartagent/client/config.py`、`src/chartagent/client/client.py`、Agent 消息历史构造、Gateway protocol/readiness/service、前端 provider 类型与选择器。
- 配置：新增 `DEEPSEEK_*` 环境变量；默认 provider 继续保持现有行为，不自动切换到 DeepSeek。
- API：客户端只能提交 provider 标识 `deepseek`，不能提交 DeepSeek API key、endpoint、model 或 arbitrary request body。
- 依赖：不需要新增 SDK，继续使用现有 OpenAI Python SDK；需要 DeepSeek API key 才能进行真实调用测试。
- 风险：DeepSeek thinking + tools 要求后续请求保留 `reasoning_content`，需要避免破坏当前 Qwen reasoning 隔离和恢复安全边界。
