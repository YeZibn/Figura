## Why

ChartAgent 是一个制度化的 agent 项目，最终要实现双向图表能力（读图表 + 生成图表）。但这一切都建立在一个可控、可观测、可插拔的 LLM 调用层之上：没有稳定的 LLM client，后续的 agent loop、工具系统、图表能力都无法可靠落地。

## What Changes

- 引入 LLM Client，对接阿里云兼容模式端点（OpenAI compatible-mode），使用官方 `openai` Python SDK 作为底层 transport。默认 `base_url` 指向阿里云专属部署端点，可用环境变量/`.env` 覆盖。
- **配置分层与显式旋钮**：支持「显式传参 > 环境变量 > 默认值」的配置优先级；思考模型思考开关等明显行为开关作为显式参数，编译为厂商 `extra_body`（如 `enable_thinking`）。不再把厂商非标字段硬编进调用链。
- **归一化输出结构**：所有调用统一返回 `{ content, reasoning, tool_calls[], finish_reason, usage, raw }` 结构，`raw` 保留原始响应兜底，上层无需感知厂商差异。
- **思考模型封装**：从深度思考模型的非标 `reasoning_content` 字段解析推理内容，但只写进观测 trace，绝不回传进多轮历史的 assistant 消息（否则厂商端会返回 400）。
- **历史构造约定**：client 层封装「只把 content 写入 assistant 历史」的约定，规避 reasoning 回传导致的 400。
- **观测日志**：每次调用输出结构化日志（模型、用时、token、finish_reason 等）。
- **重试显式配置**：重试次数、超时等作为显式配置项暴露。
- 通过 `python-dotenv` 加载 `.env`，把 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASH_MODEL` 作为环境配置来源。

## Capabilities

### New Capabilities

- `llm-client`: 跨厂商 OpenAI 兼容端点的可控、可观测 LLM 调用能力，包含配置分层、显式旋钮、归一化输出结构、思考模型推理内容隔离与多轮历史构造约定。

### Modified Capabilities

（无，暂无既有 spec。）

## Impact

- 新增依赖：`openai` 官方 Python SDK、`python-dotenv`。
- 新增模块：LLM client（transport 之上的薄封装层）。
- 新增环境变量约定：`DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`（默认阿里云专属部署端点）、`DASH_MODEL`（默认模型）。
- 影响后续 agent loop / 工具系统的接入面（它们将依赖归一化的输出结构和历史构造约定）。
- 不改变任何现有代码（本项目首个 change，尚无可运行代码）。