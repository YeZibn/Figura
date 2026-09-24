## Why

Figura 的工具目前可以被 Agent 调用，但工具说明、参数描述、附件授权适配、工具分组和结果边界分散在不同模块中，模型很难稳定判断一个工具何时适用、何时不适用，以及返回的视觉证据能否支持后续决策。现在生成图审核已经成为正式生命周期，工具层需要先具备一致、可解释且不改变现有调用名称的契约。

## What Changes

- 扩展轻量工具定义，保留稳定的英文工具名和现有 callable，同时支持中文展示名和工具分组。
- 统一模型可见的 description 为一段完整说明，在同一段文字中覆盖用途、适用场景、不适用场景、返回数据或视觉证据、限制和必要的后续判断。
- 统一所有工具的 JSON Schema 参数说明、必填字段、枚举、范围、数组限制和 `additionalProperties` 约束。
- 将附件工具的授权参数适配整理为一致的 `attachment_id` 契约，避免把本地路径暴露给模型。
- 让 Registry、Agent/OpenAI schema、MCP manifest 和授权包装器使用同一份工具元数据，避免注册后 description 或 schema 不一致。
- 统一工具分组和展示元数据，支持前端或 trace 将工具显示为“中文名称（英文名称）”，但不改变内部 function-calling 名称。
- 补充工具契约、schema、注册一致性和模型可见描述的回归测试。

## Capabilities

### New Capabilities

### Modified Capabilities

- `tool-system`: 统一工具定义、使用边界、参数契约、注册适配和外部工具 schema 暴露。

## Impact

- 影响 `src/chartagent/tools/` 下的 Tool 定义、Registry、结果归一化、内置工具和图表工具注册。
- 影响 Agent 暴露给模型的工具 schema，以及 MCP-shaped manifest 的元数据输出。
- 影响附件授权包装器的参数 schema，但保留现有工具英文名称和调用兼容性。
- 可能为前端和执行 trace 提供工具展示元数据；本 change 不重构 Agent system prompt，也不改变生成图审核状态机或工具结果的核心数据语义。
