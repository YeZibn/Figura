## 1. Scaffolding

- [x] 1.1 Add `openai` to project dependencies (poetry/pip manifest) and pin a
  current version
- [x] 1.2 Create the client module package and a module docstring describing the
  scope (LLM client only; no agent/tools/charts)
- [x] 1.3 Add unit-test scaffolding so each task below can be verified with a
  test command

## 2. Config layering

- [x] 2.1 Implement a config resolver that merges explicit params > env > defaults
  per key, with `DASHSCOPE_API_KEY` and a default Alibaba compatible-mode
  `base_url` supported as env sources, and a configurable default model
  (`DASH_MODEL`)
- [x] 2.2 Make retry count, timeout, and the thinking toggle explicit typed
  options with sensible defaults
- [x] 2.3 Verify with a unit test that a partially-overridden config keeps the
  remaining values from env/defaults (run test command)

## 3. Normalized output structure

- [x] 3.1 Define the normalized result model `{ content, reasoning, tool_calls,
  finish_reason, usage, raw }`, with empty values for non-applicable fields and
  `raw` preserving the original provider response
- [x] 3.2 Implement normalization over a non-streaming response and over a
  streamed response (aggregating deltas into the same shape)
- [x] 3.3 Verify normalization with unit tests using a provider-response fixture
  (run test command)

## 4. Tool definition calls

- [x] 4.1 Support passing tool definitions into a call and parse SDK-parsed tool
  calls into the normalized `tool_calls` list
- [x] 4.2 Verify propagation end-to-end on a real compatible endpoint that emits a
  tool call, feeding a tool result back into a follow-up message and confirming
  the normalized `tool_calls` round-trips (smoke test)
  - 真实验证通过：模型发起 `get_current_weather` 调用 → record tool result → 续答正确

## 5. Reasoning isolation & history construction

- [x] 5.1 Capture non-standard reasoning output (e.g. Qwen `reasoning_content`)
  into `reasoning`, exposing it to the observation/trace only
- [x] 5.2 Implement the history-construction contract so assistant history entries
  contain only `content`, never reasoning
- [x] 5.3 Verify reasoned replies never appear in subsequent assistant history and
  a follow-up call against a deep-thinking model does not 400 (run test command)
  - 单测已验证历史剥离；真实 400 校验属于 task 7.2 真实链路，待 key 后验证

## 6. Thinking toggle & retry

- [x] 6.1 Ensure the thinking toggle compiles to the provider extension field
  (e.g. `extra_body.enable_thinking`) and the response reflects the toggled
  behavior
- [x] 6.2 Honor an explicit retry count on transient failures before surfacing a
  final error (run test command)
  - 已验证 `max_retries`/`timeout` 作为显式连接参数传传给 SDK

## 7. Observation logs & smoke verification

- [x] 7.1 Emit one structured observation entry per completed call (model, elapsed,
  usage, finish_reason) without logging the API key
- [x] 7.2 Run the three acceptance smoke paths on a real endpoint: (a) plain
  dialogue, (b) tool-defined call with `tool_calls` resolved and passed back,
  (c) deep-thinking model streaming with reasoning/content collected separately,
  and record the results
  - (a) plain ✓ (b) tool_calls 回填 ✓ (c) thinking ✓——真实端点上全部通过
  - 修复了流式 usage：`stream_options.include_usage` 使观测日志返回真实 token 数
  - 注：qwen-max 默认思考直接写入 content，独立 `reasoning_content` 捕获已由单测覆盖

## 8. Environment via `.env` (python-dotenv)

- [x] 8.1 Add `python-dotenv` to project dependencies
  - 加入 pyproject 依赖；环境已装 python-dotenv
- [x] 8.2 Add a `load_environment()` helper (python-dotenv) that loads `.env`
  before config resolution; `.env` holds `DASHSCOPE_API_KEY`,
  `DASHSCOPE_BASE_URL`, and `DASH_MODEL`
  - config.py 新增 `load_environment()`；已导出；smoke 脚本已接入
- [x] 8.3 Point the default `base_url` at the target Alibaba compatible-mode
  deployment (excluded from source as a reusable default) and wire `DASH_MODEL`
  as the default model when a call omits `model`
  - 默认端点改专属 `ws-6x14...`；`resolve_config` 支持 `DASH_MODEL`；单测覆盖
- [x] 8.4 Add `.env` to `.gitignore` so the key/base_url stay out of version
  control
  - 已建 `.gitignore`（排除 `.env`，保留 `.env.example`）与 `.env.example`
- [x] 8.5 Verify on the real endpoint that the deep-thinking model
  (e.g. `qwen3.8-flash`) produces isolated `reasoning_content` that stays out of
  a follow-up assistant history (no provider-side 400) and record the result
  - 专属端点 `qwen3.8-flash` 实测 `reasoning_len=266`，reasoning 被隔离、历史不含 reasoning、后续调用无 400；三条链路全部通过