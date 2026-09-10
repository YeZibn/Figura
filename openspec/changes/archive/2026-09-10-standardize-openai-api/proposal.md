## Why

当前 LLM 客户端虽然调用的是 OpenAI SDK 的 Chat Completions 接口，但请求参数、思考模式和环境变量仍以 Qwen/DashScope 扩展为中心。切换到 OpenAI 中转站后，这些非标准字段会造成兼容性和行为差异，也让模型、网关和开发者难以判断实际使用的协议。现在统一为 OpenAI 标准 Chat Completions 格式，可以保留现有 Agent 的工具循环，同时让不同 OpenAI 兼容服务之间更容易切换和验证。

## What Changes

- 将客户端的主请求契约统一为 OpenAI Chat Completions 标准字段：`messages`、`tools`、`stream`、`stream_options.include_usage`、`reasoning_effort` 和 `max_completion_tokens`。
- 将当前 Qwen 专用的 `extra_body.enable_thinking` 从主调用路径移除，思考强度改由显式的标准 `reasoning_effort` 参数控制；继续兼容服务可能返回的推理元数据，但不把它写回多轮 assistant 历史。
- 将 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL` 设为规范配置名，并保留 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASH_MODEL` 作为兼容回退，明确配置优先级和迁移行为。
- 将 `max_tokens` 替换为 `max_completion_tokens`，并修正显式 `0` 类配置值被默认值覆盖的问题。
- 保持现有标准化返回结构、工具调用循环、流式事件和 Gateway HTTP/SSE 契约不变；原始响应继续保留在 `raw` 中供兼容适配和诊断使用。
- 增加针对标准请求字段、标准配置命名、推理元数据、流式 usage、工具调用和重试配置的单元测试及可执行的连接验证。
- **BREAKING**：新的客户端调用不再承诺发送 `extra_body.enable_thinking`；依赖该 Qwen 专用字段的行为必须迁移到 `reasoning_effort` 或显式 provider 扩展配置。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `llm-client`: 将连接配置、请求字段、推理参数和 token 限制统一为 OpenAI 标准 Chat Completions 契约，同时保留旧环境变量和非标准响应字段的兼容读取。

## Impact

- 主要影响 `src/chartagent/client/config.py`、`src/chartagent/client/client.py` 及对应测试和 smoke 脚本。
- `.env.example`、运行文档和模型参数帮助文本需要采用 `OPENAI_*` 规范命名，并说明旧 DashScope 变量的回退顺序。
- Python SDK 仍使用现有 OpenAI 客户端依赖；本次不引入 Responses API，也不改变 Gateway 的外部请求/事件协议。
- 使用旧 `enable_thinking` 或 `max_tokens` 参数的内部调用方需要迁移到新的标准参数。
