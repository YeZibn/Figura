## Why

我们要逐步搭起一个 agentic 图表的 agent 运行时。add-llm-client 已经提供了
可控的 LLM 调用层（多厂商 OpenAI-compatible、reasoning 隔离、观测日志）。
现在需要一个会话交互层：能进行多轮对话、在内存中持有整段历史，作为后续
工具调用/图表演化循环的上层驱动器，也让开发者立即可在终端上真实试用。

## What Changes

- 新增一个有状态会话类 `Conversation`（编程入口），封装多轮对话：
  - 构造时接收 `LLMClient`、可选 system prompt、可选默认模型
  - `run(text)` 追加 user 消息 → 调用 `LLMClient.chat` → 以 content-only
    规则把 assistant 回复并入历史 → 返回回复内容
  - 历史以 `messages` 列表**全量保存在内存**中，本 change 不做压缩/截断
  - `reset()` 清空历史回到初始 system；只读暴露 `history`
- 新增一个极薄 REPL 壳（占位，几十行），在终端内循环输入 → 调用
  `Conversation.run()` → 打印，供人肉调试；本次不接任何工具

## Capabilities

### New Capabilities
- `conversation-loop`: 多轮对话会话容器，管理内存历史，每轮经 LLMClient
  驱动，支持 system prompt、默认模型、reset 与只读 history

### Modified Capabilities
<!-- 无：不修改既有 llm-client 的 requirements -->

## Impact

- 新增模块：`src/chartagent/conversation.py`（会话类），及一个
  `scripts/chat_cli.py` 极薄 REPL
- 复用：`LLMClient`、`append_to_history`（来自 `chartagent.client`）
- 无新增依赖；不改动既有 client/config
- 新增单测：`tests/test_conversation.py`（mock LLM/客户端驱动）