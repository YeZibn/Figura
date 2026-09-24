# Tasks

## 1. Agent core (`src/chartagent/agent.py`)

- [x] 1.1 新增 `class Agent`，构造签名
      `Agent(client, registry, *, system=None, max_steps=10, **client_kwargs)`，
      内部持有 `self._messages: list[ChatCompletionMessageParam]`。
- [x] 1.2 提供 `run(user_input) -> str`：追加 user 消息后进入循环：
      - 调用 `client.chat(messages, tools=<openai tool schemas>, **client_kwargs)`
      - 若 `result.tool_calls` 非空 → 执行工具步；
      - 否则 → 追加 assistant content-only 条目并返回 `result.content` 作为终止。
- [x] 1.3 实现工具步：把注册工具转成 OpenAI `tools` schema（name；
      description；parameters），循环串行执行每个 `ToolCall`，经
      `dispatch(registry, call.name, call.arguments)` 取 JSON 观测，追加
      `{"role":"tool","tool_call_id":id,"content":obs}`；并追加带 `tool_calls`
      的 assistant 条目（content + tool_calls 原样保留，**不含 reasoning**）。
- [x] 1.4 新增 `reset()` 清空历史（保留 system）；`max_steps` 达到时停止并返回
      明确的中止消息（如 `*stopped: max_steps reached*`），不上抛。

## 2. History construction helpers（`src/chartagent/agent.py` 或独立模块）

- [x] 2.1 构造 assistant 条目，把 `NormalizedResult` 的 `content` 与 `tool_calls`
      （转回 OpenAI `function` 结构）写入一条 assistant 消息；
      明确不写入 `reasoning`。
- [x] 2.2 `Tool` → OpenAI tool schema 的转换，与 `tool-system` 的转换保持同一语义
      （可复用/对齐 `mcp_converter` 思路）。

## 3. Package wiring

- [x] 3.1 在 `src/chartagent/__init__.py` 导出 `Agent` 及 agent 相关的 tool-schema
      转换函数。
- [x] 3.2 确保 `register_builtins` 已注册的工具可直接作为 `Agent` 的工具来源
      （`registry.list()` 即可，无额外隔离需改）。

## 4. Unit tests（mock 驱动，不依赖真实 LLM）

- [x] 4.1 新增 `tests/test_agent.py`，用注入的 fake `LLMClient`（可控返回序列）覆盖：
  - 单步可直接返回：无 tool_calls → 返回该轮 content
  - 多步工具循环：模型先给 `read_file`+`parse_json` 等调用，再给终止轮，断言
    `dispatch` 的观测正确进入历史、最终返回终止轮 content
  - 工具失败回填：`dispatch` 返回 `{"error":...}` 时观测仍是该错误串、循环继续
  - `max_steps` 达上限返回中止消息（fake 永远返回 tool_calls）
  - `reset()` 后历史不含先前轮次
  - assistant 历史条目不含 `reasoning`、且含 `tool_calls`
- [x] 4.2 全部经真实（或 mock）`ToolRegistry` + `register_builtins` 组合走通。

## 5. 冒烟与全量回归

- [x] 5.1 跑通 `pytest -q` 全量（新增 agent 测试 + 既有 client/conversation/tool
      回归全绿）。
- [x] 5.2 写一个 mock 冒烟片段（tests 或 scripts/）：`register_builtins` +
      fake client，演示 agent 用只读工具完成一个"读文件→解析→总结"任务的最小闭环
      （可选，不强制接真实端点）。