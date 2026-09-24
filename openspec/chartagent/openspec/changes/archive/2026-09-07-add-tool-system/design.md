## Context

基线已有可控 LLM client（llm-client，已归档）与多轮会话层
（conversation-loop，已归档）：`LLMClient.chat()` 返回 `NormalizedResult`，
`Conversation.run()` 是无工具的多轮入口。项目要想从"对话"走向"做事"，下一
环是把能力以"工具"形态注册给模型，供 agent loop 调用。本 change 只建工具
"手"（定义/注册/分发/序列化），不含 loop，但工具抽象从一开始就按 MCP
暴露预留设计。

## Goals / Non-Goals

**Goals**
- 提供声明式 `Tool`：`name` / `description` / `parameters`(JSON-Schema) /
  `fn`，元数据与可调用解耦
- 提供 `ToolRegistry`：regcc `register` / `get` / `list` / 去重 / 按 tool_call
  分发
- 统一结果序列化：成功 `JSON 字符串`；失败 `{"error": ...}` 结构化返回
- MCP 预留：提供 `registry → MCP tool 清单 + callable` 的薄 converter 骨架，
  不搭 server

**Non-Goals**
- 不实现 agent loop（下个 change）
- 不做参数 JSON-Schema 校验、权限、缓存
- 不搭建/不运行 MCP server（只留转换骨架与样例）
- 不做跨进程远程工具、工具链编排

## Decisions

**1. MCP 预留在本 change 的落地 = "定义形态贴近 MCP + 薄 converter"，而非
搭 MCP server。**
`Tool` 的 `name` / `description` / `parameters` 恰好是 MCP tool 三要素；连
结果也约定 JSON 可序列化（MCP 消息传输前提）。这样将来一句转换即可暴露，
无需重写工具。`fn` 始终是纯执行尾部，不感知 LLM/MCP。
- *备选:* 本期直接搭 FastMCP server → 属于 L3 完整层，本 change 无外部宿主
  消费它，属过度设计，推迟。

**2. dispatch 的返回统一为"可序列化的结果对象"，成败同形。**
`registry.dispatch(name, arguments_json)` 返回一个结果：成功为 JSON 字符串，
失败（未知工具名 / 调用抛异常 / 结果不可序列化）为 `{"error": ...}`。
调用方（未来的 loop）据此回填 history，无需分别处理。
- *备选:* 直接就异常向上抛 → 与"给 LLM 可读"的 agent-friendly 原则相悖，
  弃用。

**3. 未知工具名不抛到调用方，而是走同一错误结构。**
分发时若名字不在 registry，产出结构化错误（而非 KeyError 之类），以便
loop 能把它作为工具结果回灌给模型，让模型自我纠偏。
- *备选:* 抛 KeyError → 会中断 agent 循环，与错误标准化的目标冲突。

**4. 序列化策略：常规返回 `json.dumps`，Dataclass/不可序列化的兜底处理。**
成功结果转 JSON 字符串；若 `fn` 返回值无法 `json.dumps`，捕获并转
`{"error": "serialization_failed"}`。保持协议简单、确定。
- *备选:* 依赖第三方序列化（如 pydantic 深度转储）→ 增依赖且过度，本期用
  标准库。

**5. converter 骨架只做"形状映射"，不做运行。**
`to_mcp_tools()` 输出 `[{name, description, inputSchema}]` 清单 +
`{name: callable}` 包装，供未来 FastMCP 直接消费；转换本身不启动任何 server、
不 IO。本期交付骨架与样例（一个示例工具的映射），验证协议 DO。

## Risks / Trade-offs

- [MCP converter 骨架可能半成品即被忽略] → 明确它是"预留接口 + 验证协议"，
  不是完整 server；用一条单测钉住"registry → MCP 形状映射"即可。
- [工具 c 定义形状过早被认为"完整进画卷"] → 本 change 写清楚三种 Non-Goal
  （校验/权限/远程），防止系统演练注水。
- [不接 loop，工具无可交互验证] → 单测以 mock 驱动覆盖注册/分发/序列化；
  真实 loop 集成放到下一个 change。

## Migration Plan

无存量系统需要迁移；本 change 纯新增模块，不回滚负担。

## Open Questions

无。范围（工具定义/注册/分发/序列化 + MCP 预留骨架，不含 loop）已明确，
可安全实施。