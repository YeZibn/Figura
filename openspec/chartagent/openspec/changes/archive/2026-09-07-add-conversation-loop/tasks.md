## 1. Conversation session (core)

- [x] 1.1 Add `src/chartagent/conversation.py` with a `Conversation` class:
  constructor accepts an `LLMClient`, optional `system`, optional `model`;
  holds `messages` in memory (starting with `[system]` if provided)
- [x] 1.2 Implement `run(text)` that appends a user message, calls
  `client.chat(messages, model=...)`, appends the assistant reply via
  `append_to_history` (content-only), and returns the reply content
- [x] 1.3 Implement `reset()` (history back to initial system prompt) and a
  read-only `history` property exposing the in-memory messages
- [x] 1.4 Export `Conversation` from `chartagent/__init__.py`

## 2. Thin interactive CLI (REPL)

- [x] 2.1 Add `scripts/chat_cli.py`: loads `.env` via `load_environment()`,
  builds an `LLMClient`, creates a `Conversation`, and loops on `input()` →
  `conv.run()` → `print()` until the user exits (empty input / Ctrl-D), with
  errors caught and printed so the loop continues
  - REPL 核心放在 `src/chartagent/cli.py`，`scripts/chat_cli.py` 与 `python -m
    chartagent` 复用它
- [x] 2.2 Wire `python -m chartagent` (or a console entry) so the CLI is
  runnable without invoking the script path directly
  - 新增 `src/chartagent/__main__.py` 入口

## 3. Tests

- [x] 3.1 Add `tests/test_conversation.py` using a fake/stub LLM client:
  assert turns accumulate context across multiple `run()` calls
- [x] 3.2 Assert `reset()` clears history back to the initial system prompt
- [x] 3.3 Assert assistant history entries are content-only (reasoning from a
  stubbed result is never written into history)
- [x] 3.4 Assert the default model is used when a turn does not specify one,
  and a per-turn model override wins when provided
  - 4 项测试随全套单测 21 passed

## 4. Real-endpoint smoke

- [x] 4.1 Run the REPL (or a one-shot script) against the real endpoint via
  `.env`: verify a multi-turn exchange preserves context across turns and that
  assistant history stays reasoning-free, and record the result
  - 真实端点两轮验证：第二轮回"苹果"（上下文累计生效），assistant 历史 2 条
    全 content、无 reasoning 字段