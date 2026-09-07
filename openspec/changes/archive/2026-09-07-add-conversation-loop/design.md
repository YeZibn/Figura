## Context

基线是已经实现的 LLM client（见已归档的 add-llm-client）：`LLMClient.chat()`
返回归一化 `NormalizedResult`，`append_to_history()` 保证 assistant 历史仅含
content（reasoning 隔离，深思考模型不会因此 400）。当前项目尚无任何交互层，
本 change 在其上新增一个有状态会话层，作为多轮对话的驱动器，也作为后续
工具/图表演化循环的基底。

## Goals / Non-Goals

**Goals**
- 提供一个有状态 `Conversation` 会话：内存持有 `messages`，每轮追加
  user/assistant，向 `LLMClient.chat` 发完整历史
- 提供极薄 REPL 壳（人肉调试可跑）
- 让 README 一类的"真实调用入口"诉求落地（`run()` 即入口）

**Non-Goals**
- 不接入任何工具调用 / 工具循环
- 不做历史压缩、截断、持久化（内存存储，进程退出即丢）
- 不引入独立 Critic 层 / 多轮自我修正
- 不做并行、流式交互 UI

## Decisions

**1. 会话状态归属：会话(Conversation)拥有历史，client 保持无状态。**
Client 已无状态（每 call 一次请求）；本层把 `messages` 作为会话实例字段，
`run()` 内先 append user，再调 `client.chat(messages)`，最后
`append_to_history()`. 这样会话是"历史容器 + 每轮驱动器"，与 client 职责
清晰分离。
- *备选:* 让 client 内置会话状态 → 已基于 add-llm-client 定案拒绝，避免
  多会话/复用场景的职责纠缠。

**2. reasoning 隔离直接复用 `append_to_history()`，会话不碰 reasoning。**
`run()` 用 client 提供的 `append_to_history()` 构造 assistant 历史条目，
自己不再写任何历史构造逻辑。深思考模型的 reasoning 经 client 归一化进入
`result.reasoning`，但仅由调用侧决定是否使用；会话历史永不包含它。
- *备选:* 会话自行拼 assistant message → 重复实现且易漏 reasoning 隔离，
  弃用。

**3. 历史全量保存在内存，做成 list，不压缩不截断。**
按当前的会话/数据规模，全量 message（含可能很长的 history）放内存完全足够，
换来实现最简单、调试最直观。为将来容量管理预留的"截断/落盘"只以设计备注
存在，不在本期实现。
- *备选:* 引入窗口/摘要压缩 → 复杂度无必要，推迟到确有容量问题时。

**4. 交付形态 = 纯编程 API(`Conversation`) + 极薄 REPL。**
`Conversation` 是主体（供后续 import 复用）；REPL 只是几十行的 `scripts/`
壳，循环 `input()` → `conv.run()` → `print()`，不引入任何框架。
- *备选:* 只做 REPL 不抽象类 → 后续复用需重构，弃用；只做 API 不做 REPL
  → 无法立刻在终端试用，本 change 采用两者并存的薄方案。

**5. 出错处理：本轮异常向上抛，REPL 捕获打印后继续。**
`run()` 不做重试（重试已在 client 显式配置层），异常冒泡；REPL 层捕获
并打印错误、允许用户继续下一轮。保持事务访问边界简单。

## Risks / Trade-offs

- [历史内存无限增长] → 本期为明确 Non-Goal，仅在设计备注指出未来可加
  `max_messages` 或截断 hook；当前规模无碍。
- [REPL 多出的少量 UI 代码] → 极薄、置于 `scripts/`，不进入 `src` 核心 API，
  属于可选附件。
- [无工具，Loop 能力受限] → 本 change 有意为之；工具作为后续 change 以
  `run(..., tools=)` 的可选参数叠加，不改变本层主骨架。

## Migration Plan

无存量系统需要迁移；本 change 是纯新增。无回滚负担。

## Open Questions

无。既有范围（纯多轮对话 + 内存历史 + 薄 REPL）已足够明确，可安全实施。