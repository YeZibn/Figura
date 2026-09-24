# Tasks

## 1. Agent REPL (`src/chartagent/cli.py`)

- [x] 1.1 新增 `run_agent_repl(*, model=None, system="You are a helpful assistant.") -> int`：
  - `load_environment()`；构造 `LLMClient()`；`ToolRegistry()` + `register_builtins(registry)`
  - 构造 `Agent(client, registry, system=system, model=model)`（`model` 经 `**chat_kwargs` 转发给 `chat`）
  - 循环：读一行 → `agent.run(line)` → 打印回复；空行 / Ctrl-D / KeyboardInterrupt → 返回 0
  - 异常保持在循环内（打印 `[error]` 后继续），与现有 chat REPL 一致
- [x] 1.2 在 `cli(argv)` 解析 `--agent` 标志：命中时调用 `run_agent_repl`，否则保持
      现有 `run_repl`（`Conversation` 为默认不改变行为）；`--model` 两路均透传。

## 2. Wiring / entry points

- [x] 2.1 确认 `scripts/chat_cli.py` 与 `src/chartagent/__main__.py` 仍只调用
      `cli.cli()`，`--agent` 标志自动生效，无需改动。
- [x] 2.2（可选）如 `cli` 需同时暴露 `--system` 之类透传，随 1.2 一并补上；否则跳过。

## 3. Unit tests（mock，不依赖真实 LLM）

- [x] 3.1 新增/扩展 CLI 会话测试（复用 fake client 或 patch 构造点）覆盖：
  - `--agent` 时构建的工具 registry 已含 4 个 built-in 工具
  - 默认（无 `--agent`）走 `Conversation` 路径，不改变既有行为
  - 空行输入令 REPL 返回 0 退出（用伪造 `input` 或 `monkeypatch`）
- [x] 3.2 `Agent` 构造参数（system / model 转发）在 agent shell 组装时正确生效
      （断言 fake client 收到的 model 就位）。

## 4. 冒烟与全量回归

- [x] 4.1 跑通 `pytest -q` 全量（新增 CLI 测试 + 既有 所有回归全绿）。
- [x] 4.2 手动冒烟一条命令：`PYTHONPATH=src python -m chartagent --agent` 能进入
      工具型 REPL（可选，依 `.env` 命中断点）。