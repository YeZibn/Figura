## Context

当前工具定义集中在 `Tool(name, description, parameters, fn)`，但不同工具的 description、参数字段说明和边界约束质量不一致。附件图表工具还会在注册阶段动态替换 `image_path`，使模型看到的 schema 与工具原始定义分散在两个位置。Agent/OpenAI schema、MCP-shaped manifest 和授权包装器因此存在元数据重复或漂移的风险。

本 change 需要保持现有英文工具名、function-calling 参数命名、工具 callable 和 `ToolResult` 兼容，同时让模型从一段完整 description 中获得更可靠的工具选择信息，并为前端和 trace 提供稳定的中文展示名称。

## Goals / Non-Goals

**Goals:**

- 保留轻量 `Tool` 核心结构，并增加可选的展示名称和分组信息。
- 统一工具 description 的写法，使同一段文字同时表达用途、适用场景、不适用场景、输出证据和限制。
- 统一参数 schema 的字段描述、边界、枚举、数组限制和附加字段策略。
- 让附件授权包装器只暴露 `attachment_id`，并保持工具身份与其他元数据一致。
- 让 Agent 工具 schema 与 MCP manifest 从同一份规范化元数据生成。
- 提供稳定的工具展示目录，允许前端显示“中文名称（英文名称）”。

**Non-Goals:**

- 不修改现有工具英文名称、函数调用协议或历史事件中的 `tool_name`。
- 不把工具定义扩展为复杂的工作流、依赖图、自动编排或模型决策引擎。
- 不在本 change 中重构 Agent system prompt。
- 不改变 `ToolResult` 的核心数据、图片证据传输方式或生成图审核生命周期。
- 不要求前端在本 change 中完成全部生命周期事件的中文化；本 change 只提供可供其使用的目录数据。

## Decisions

### 1. 保留 Tool 的核心字段，增加少量展示元数据

继续以 `name`、`description`、`parameters` 和 `fn` 作为工具的最小契约，新增可选的 `display_name` 和 `group`。可选字段提供默认值，保证已有外部测试和简单工具构造仍然可用。

选择这一方案是因为它能改善模型选择和展示，而不需要引入新的层级化定义对象。将用途、适用边界、限制、输入输出和执行策略全部拆成十多个字段会增加维护成本，并且容易让模型同时面对多套相互矛盾的说明。

### 2. 以一段完整 description 作为唯一模型说明来源

每个工具的 `description` 由工具作者直接维护为一段完整说明，按“用途、适用场景、不适用场景、返回内容、限制或后续判断”的顺序组织。Agent 和 MCP surface 直接使用这段说明，不再依赖额外的 `use_when`、`avoid_when` 字段，也不在不同注册路径中重复拼接文案。

这样可以让模型只面对一份完整工具说明，同时避免工具定义字段继续膨胀和导出路径产生重复文案。

### 3. 参数 schema 仍是输入约束的唯一权威

模型可见的参数边界放在 JSON Schema 中，description 只解释字段含义和授权边界。必填字段、枚举、范围、数组项结构、最大数量和 `additionalProperties` 不依赖 description 中的隐含约定。

对于附件工具，定义层可以保留内部 callable 所需的路径适配信息，但注册给 Agent 的公开 schema 只包含 `attachment_id`。授权包装器从共享元数据生成公开工具，替换输入契约和绑定 callable，不复制一整套工具说明。

### 4. 从统一导出器生成 Agent 和 MCP 元数据

Agent 的 OpenAI function schema 和 MCP-shaped manifest 都通过同一套规范化操作读取 `Tool` 元数据。两者可以保留各自协议的外层字段，但 name、canonical description 和 input schema 必须来自同一份定义。

选择统一导出器而不是让每个调用方自行读取字段，是为了防止新增工具只更新一条暴露路径。展示名称和分组属于本地 presentation metadata，不覆盖稳定英文 name 或标准协议字段。

### 5. 使用独立的轻量 ToolCatalog 提供展示信息

工具展示目录按稳定英文名索引中文名称、可选英文名称和分组。未知工具回退到英文 name，不阻断事件或工具调用。目录不参与工具执行授权，也不作为模型判断工具可用性的唯一来源。

## Risks / Trade-offs

- [模型 description 变长] → 对 description 和展示字段设置长度上限，测试导出的 schema 保持有界。
- [旧工具 description 与新规范不一致] → 分阶段更新内置工具、图表工具和审核工具，并增加覆盖所有已注册工具的契约测试。
- [授权包装器与原始定义发生漂移] → 包装器从原始工具元数据派生，只允许替换授权所需的 schema 字段和 callable，并测试 name、用途说明和 guidance 保持一致。
- [展示目录漏记新工具] → 未知工具必须安全回退到稳定英文名；目录完整性测试覆盖当前注册工具，并允许未来工具先以 fallback 工作。
- [MCP surface 对本地展示字段支持有限] → 标准 name、description 和 input schema 始终保持兼容，额外 presentation metadata 只保留在本地 manifest 对象，不强行写入非标准协议字段。

## Migration Plan

1. 扩展 `Tool` 元数据模型和统一 description/schema 导出器，保持旧构造方式可用。
2. 更新内置、附件、图表生成和审核工具的 description 与参数 schema。
3. 更新授权注册包装器、Agent schema 和 MCP manifest，使其复用统一导出逻辑。
4. 增加工具目录和契约测试，确认所有当前注册工具均有有效说明、参数 schema 和展示 fallback。
5. 运行 Python 测试、严格 OpenSpec 校验和 `git diff --check`。

回滚时可以保留新增字段但停止使用规范化导出器，旧的四字段 Tool 构造和英文工具名仍可继续工作；不需要数据迁移。
