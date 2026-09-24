## Context

Figura 当前通过一个 OpenAI-compatible Chat Completions client 统一调用
OpenAI relay 和 Qwen，并在 Agent 中保留 tool calls、tool results 和用户消息
组成的多轮上下文。provider 解析、Gateway readiness、运行快照和桌面端选择器
目前都把 provider 集合限定为 `openai` 与 `qwen`。

DeepSeek V4.1 Flash 的官方 API ID 是 `deepseek-flash`，接口地址是
`https://api.deepseek.com`。它支持图片、标准 Tool Calls 和 JSON Output，但
thinking + tools 模式要求后续请求回传上轮的 `reasoning_content`。这与当前
“统一移除 reasoning 后再写入 assistant history”的安全策略存在 provider-specific
差异。

## Goals / Non-Goals

**Goals:**

- 在不引入新的 SDK 或工具协议的前提下增加可选 `deepseek` provider。
- 复用现有 Chat Completions、多模态 `image_url`、工具分发、流式收集和运行观测链路。
- 将 DeepSeek thinking 参数与 Qwen thinking 参数隔离。
- 让 DeepSeek 工具调用多轮请求携带必要的 `reasoning_content`，同时不把它暴露到普通答案、桌面 transcript 或无界 trace。
- 保持 OpenAI/Qwen 的现有默认行为、配置隔离和 provider 快照语义不变。
- 在缺少 DeepSeek 配置时只报告 unavailable，不影响 Gateway 启动和其他 provider。

**Non-Goals:**

- 不切换默认 provider，不修改现有 OpenAI 或 Qwen 的默认模型。
- 不引入 DeepSeek 专用 SDK，不改用 Responses API，不重写现有 tool schema。
- 不修改 SAM、dashboard decomposition、图表传感器或 test1 的视觉上下文压缩策略。
- 不在本次 change 中实现 Files API；本地图片继续使用现有的受控 base64 `image_url` 路径。

## Decisions

### 1. 继续使用统一的 OpenAI-compatible Chat Completions client

在配置层增加 DeepSeek 的 provider 分支，在同一个 client 中解析 endpoint、模型和
provider-specific request body。这样可以保留既有的流式 delta 收集、标准工具调用
解析、trace 边界和错误处理。

备选方案是引入 DeepSeek 专用 SDK，或为 DeepSeek 单独建立 Agent loop；这会复制
工具调用、重试和生命周期逻辑，也会让 provider 之间的行为难以对齐，因此不采用。

### 2. 使用官方 DeepSeek 配置和模型 ID

DeepSeek 的默认配置固定为：

```text
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

用户界面可以显示“DeepSeek（V4.1 Flash）”，但传输和运行快照使用
`provider=deepseek`、`model=deepseek-flash`。API key、endpoint 和 model 仍只从
Gateway 所在进程的环境解析。

### 3. 为 thinking 参数建立 provider-specific request translation

请求构造保持公共字段：`model`、`messages`、`stream`、`tools`、可选的
`max_completion_tokens`。provider-specific 字段由配置分支添加：

```text
Qwen:
  extra_body = {"enable_thinking": true}

DeepSeek:
  extra_body = {"thinking": {"type": "enabled"}}
  reasoning_effort = low/high/max（配置存在时）
```

DeepSeek thinking 默认值、关闭方式和 effort 值在配置层明确化；不把 Qwen 的
`enable_thinking` 发送给 DeepSeek，也不把 DeepSeek 的 `thinking` 发送给 Qwen。

### 4. 将 DeepSeek reasoning replay 限定为内部模型上下文

将当前“assistant history entry”拆成两个概念：

```text
模型请求消息：
  content + tool_calls +（DeepSeek tool follow-up 必需的 reasoning_content）

普通记录/用户可见 transcript：
  content + bounded tool-call metadata，不含 reasoning_content
```

在同一 Agent run 内，DeepSeek 的 assistant 消息可以在内存中保留
`reasoning_content`，以满足后续工具请求。若需要从 checkpoint 恢复，checkpoint
可以保留受控、长度受限的 provider-private message context；该字段不得进入普通
assistant record、final answer、run event 或默认 trace。

Qwen 和 OpenAI 继续沿用当前 reasoning 隔离策略。provider 选择必须在构造 history
entry 时显式传入，不能通过检测任意字段自动推断，避免 reasoning 跨 provider 泄漏。

### 5. 保持图片只出现在 user 消息

现有 `build_user_content` 和 `build_tool_observation_content` 已将原图及工具生成
图片放入 `role=user` 的内容块，使用标准 `image_url`。DeepSeek 的图片约束与这条
路径一致，因此不改变多模态消息协议；只需要为 DeepSeek 增加单图和工具后多图回归
测试。

### 6. 端到端 provider 扩展而非前端直连

新增 provider 必须同时扩展：

```text
config resolve
  → client/readiness
  → Gateway validation and snapshot
  → run events/history
  → frontend selector and mock health
  → OpenSpec and regression tests
```

前端只发送 `deepseek` 标识。健康检查只返回 ready/unavailable、provider 和模型名
等安全元数据，不返回 key、原始 endpoint 或 DeepSeek 错误正文。

## Risks / Trade-offs

- **[reasoning_content 历史不完整]** → DeepSeek thinking + tools 的后续请求可能 400；增加非流式和流式多轮 Tool Call 测试，并将 provider-private history path 与 Qwen path 分离。
- **[reasoning 泄漏到持久化或 trace]** → 将模型请求消息、普通记录和 trace payload 分层构造；对 provider-private 字段执行长度限制和默认排除。
- **[DeepSeek model ID 与产品名称不同]** → `.env.example`、健康状态和运行详情同时展示官方 ID 与中文产品标签的映射。
- **[图片消息角色不兼容]** → 测试要求所有 DeepSeek 图片只位于 user content；禁止把图片塞入 system 或 assistant history。
- **[thinking 增加延迟与 token 消耗]** → 暴露 DeepSeek 独立 timeout、retry、thinking 和 effort 配置；默认 provider 不变，未配置时不影响其他来源。
- **[多 provider 分支增加维护成本]** → 保持公共消息、tool schema、normalized result 和 observation contract，限制差异只存在于配置、request translation 和 reasoning history adapter。

## Migration Plan

1. 先合并 provider/config/client/Gateway/frontend 和测试代码；默认仍使用现有 provider。
2. 在本地 `.env` 中配置 `DEEPSEEK_API_KEY`，通过 health/readiness 确认 DeepSeek 可用；不提交 key。
3. 先运行纯文本和单图请求，再运行单次工具调用，最后运行 thinking + 多轮工具调用和图表分区链路。
4. 验证已有 OpenAI/Qwen 测试及前端 mock 流程不变。
5. 回滚时删除或清空 `DEEPSEEK_API_KEY` 即可使 provider 变为 unavailable；不需要数据迁移，已有 run 的 provider/model 快照保持可读。

## Open Questions

- DeepSeek 真实账号的峰值限流和项目级配额需要在真实 smoke test 时确认；不影响本次接口设计。
- 是否将 DeepSeek 设为某类视觉任务的默认 provider，留待接入后的真实图表评估决定，本次不改变默认值。
