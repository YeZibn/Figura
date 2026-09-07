## Why

agent 运行时已具备可控的 LLM 调用层（llm-client）与多轮会话层
（conversation-loop）。要让 agent 从"能对话"走向"能做事"，需要一套
工具抽象：把可复用的能力以"工具"形式注册给模型，供 agent 循环在需要时
调用并回填结果。工具系统是 agent loop 的地基，也是项目"为 agent 造器官"
定位中承接能力扩张（如后续图表工具）的第一把手。

## What Changes

- 新增工具抽象，其定义形态**天生贴近 MCP 模型**（将来可低成本暴露给外部
  宿主 agent），本期不搭建 MCP server：
  - `Tool`（dataclass）：`name` / `description` / `parameters`（JSON-Schema）
    / `fn`。元数据与前三个字段解耦，`fn` 纯做执行
  - `ToolRegistry`：`register` / `get` / `list`，以及按 `tool_call` 分发的
    `dispatch`（解析参数 → 调用 `fn` → 结构化返回）
  - 结果序列化约定：工具输出统一转成 JSON 字符串进入历史；不可 JSON 序列化
    或抛异常时，统一返回 `{"error": ...}` 结构（MCP 跨进程错误形状对齐点）
  - 可选薄 converter 骨架：`registry → MCP tool 清单 + callable`，仅留
    结构与示例，不搭建实际 server
- 本 change **只造"手"，不含 loop**：不实现 agent 循环、不校验参数、
  不做权限/缓存/跨进程 MCP server——这些留给 loop 落地后再按需扩展

## Capabilities

### New Capabilities
- `tool-system`: 工具的定义、注册、分发与结果序列化约定，为 MCP 暴露预留
  设计（元数据解耦 + JSON 序列化 + 错误结构化）

### Modified Capabilities
<!-- 无：不改动既有 llm-client / conversation-loop 的 requirements -->

## Impact

- 新增模块：`src/chartagent/tools/`（tool 定义、registry、converter 骨架）
- 复用：无（纯新增；未来由 agent loop 消费）
- 无新增第三方依赖；不改动既有 client/config/conversation
- 新增单测：`tests/test_tools.py`（mock 工具驱动，不依赖真实 LLM）