## 1. 配置命名与解析

- [x] 1.1 在 `src/chartagent/client/config.py` 将 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL` 设为规范环境变量，并保留 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASH_MODEL` 的逐项低优先级回退。
- [x] 1.2 将无配置时的默认 endpoint 调整为标准 OpenAI API base URL，并保持显式参数、`.env` 加载和 `CHARTAGENT_ENV_FILE` 的现有优先级行为。
- [x] 1.3 修正 timeout、max retries 等数值解析，使显式或环境中的 `0` 不会被 `or` 逻辑替换为默认值；同步更新配置对象字段和帮助文本。
- [x] 1.4 更新 `.env.example` 及项目中与模型配置相关的文档，优先展示 `OPENAI_*`，并标注旧 DashScope 变量的兼容回退用途。

## 2. Chat Completions 客户端

- [x] 2.1 在 `LLMClient` 的公开参数和配置对象中用 `reasoning_effort` 替换 `enable_thinking`，用 `max_completion_tokens` 替换 `max_tokens`，并迁移所有仓库内调用方。
- [x] 2.2 重构请求构造，使请求始终使用 `model`、`messages`、`stream`，按需添加 `tools`、`stream_options.include_usage`、`reasoning_effort`、`max_completion_tokens`，且标准路径不生成 `extra_body.enable_thinking`。
- [x] 2.3 保持非流式和流式结果的标准字段归一化，兼容读取可选 `reasoning_content`/推理 delta，保留 tool calls、finish reason、usage 和原始响应/响应分片。
- [x] 2.4 为观测日志增加经过限制和脱敏的 token usage 摘要，确保不写入 API key、原始 provider 响应、请求消息或其他凭据材料。
- [x] 2.5 保持工具调用后的 assistant/tool 历史格式和 reasoning 隔离行为不变，并确认 Gateway 消费的 `NormalizedResult` 和事件协议无需调整。

## 3. 调用方与连接验证

- [x] 3.1 更新 `scripts/smoke_llm_client.py` 及其他 smoke 脚本的环境变量提示、参数帮助和思考调用，使用 OpenAI 标准配置与 `reasoning_effort`。
- [x] 3.2 检查 Agent、runtime、CLI 和 Gateway 的所有 client.chat 调用，清理旧 `enable_thinking`/`max_tokens` 参数或文档引用，不改变 Gateway/桌面端外部协议。
- [x] 3.3 在配置了 OpenAI 中转站时，用 `conda run -n agent` 执行一次显式模型、普通对话、工具调用和流式 usage 的真实 smoke 验证，并记录中转站不支持可选字段时的明确错误。（普通请求、`reasoning_effort`、流式 usage 和首轮工具调用已通过；后续工具请求收到中转站 `503 Service temporarily unavailable`。）

## 4. 自动化测试与验证

- [x] 4.1 更新 `tests/test_llm_client.py` 的配置测试，覆盖 canonical 优先级、DashScope 兼容回退、标准默认 endpoint 和 zero retry/timeout 边界。
- [x] 4.2 增加请求契约测试，断言标准字段、工具定义、`reasoning_effort`、`max_completion_tokens` 和流式 `include_usage`，并断言不会发送 `extra_body` 或 `max_tokens`。
- [x] 4.3 更新响应归一化、reasoning 隔离、工具调用、原始响应和观测日志测试，覆盖没有文本 reasoning 但存在 usage 的标准响应及流式 usage-only 分片。
- [x] 4.4 使用 `conda run -n agent pytest` 执行完整 Python 测试，并运行 `openspec validate standardize-openai-api --type change --strict`；修复失败项后确认变更状态全部完成。（使用 `conda run -n agent python -m pytest`，182 项全部通过。）
