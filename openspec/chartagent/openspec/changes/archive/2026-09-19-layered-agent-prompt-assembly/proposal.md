## Why

当前主 Agent 的行为规则、工具说明、工具产物和运行状态混在一个稳定系统提示词与历史消息中，导致提示词难以维护，模型也不总能区分“应该遵守的规则”和“本次运行产生的事实”。这会放大重复拆解、整图测量、审核恢复不清晰等问题。现在需要建立一个中文、Markdown 驱动、分层但不过度拆分的 Prompt 装配体系。

## What Changes

- 新增四层 Prompt 装配契约：静态职责、动态工具、过程产物、Run/Turn 动态状态。
- 将主 Agent 的自然语言行为规则迁移为中文 Markdown 资源，并通过统一 loader 装配。
- 从现有 `ToolRegistry` 动态生成工具能力上下文；工具名称、参数 Schema 和状态枚举保持现有协议。
- 将 dashboard 面板、局部 crop、观测结果、ChartSpec、生成候选和审核结果统一建模为可追踪的过程产物上下文。
- 将 active source、selected panel、当前阶段、待办动作、review gate、恢复状态和预算作为代码生成的动态运行上下文。
- 为主 Agent 规定固定的层级优先级、装配顺序、来源标记和上下文边界。
- 保留原生工具消息和多模态图片传输，避免把结构化产物重新压扁成不可验证的自由文本。
- 将提示词自然语言统一为简体中文；保留工具名、JSON 字段、ChartSpec 字段和状态枚举的英文协议。
- 不改变图表算法、工具调用签名、ChartSpec Schema、审核 JSON 合同或前端协议。

## Capabilities

### New Capabilities

- `layered-prompt-assembly`: 为主 Agent 提供四层 Prompt 资源、动态上下文、过程产物索引和确定性的装配边界。

### Modified Capabilities

- `agent-loop`: 将稳定单一系统提示词扩展为静态职责、动态工具、过程产物和 Run/Turn 状态的分层模型，同时保持工具循环和审核门禁行为。
- `tool-system`: 工具能力上下文从注册表派生，模型可见的自然语言说明使用中文，但稳定工具身份和参数协议不变。

## Impact

- 主要影响 `src/chartagent/runtime/prompts.py`、`src/chartagent/agent/loop.py`、`src/chartagent/agent/review_gate.py`、`src/chartagent/memory/context.py`、`src/chartagent/multimodal.py`、工具描述和新的 Prompt 资源目录。
- 需要增加 Prompt loader、版本和层级装配测试，以及 dashboard panel 复用、局部测量和审核恢复的 Agent 回归场景。
- 不新增运行时服务或外部依赖；Markdown 资源需要随 Python 包发布。
- 当前实现工作区的其他未提交代码不属于本 change 的范围。
