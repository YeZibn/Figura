## ADDED Requirements

### Requirement: Source-linked generation context has one conditional contract

图表测量、assemble 和 render 的模型可见 schema 与运行时校验 SHALL 对 source-linked generation context 使用同一套条件约束：需要来源范围时必须得到有效的 attachment/panel scope；当请求已经唯一指向一个已授权的来源范围时，系统可以绑定该有效范围并返回 `effective_scope`；无法唯一确定时必须返回字段级错误。source-free synthesis SHALL 继续使用明确的非来源 coverage 语义。

#### Scenario: Unique authorized panel binds the effective scope

- **WHEN** 工具请求包含当前 attachment 和唯一已授权 panel，但 generation context 缺少可解析的 source scope
- **THEN** 系统只在该唯一范围内绑定并校验 effective scope
- **AND** 工具结果记录实际范围，主 Agent 不需要重复提交内部文件路径或 mask 字节

#### Scenario: Ambiguous source scope is rejected

- **WHEN** 请求涉及多个 panel、来源不一致或无法从 active handoff 唯一解析 source scope
- **THEN** 工具返回结构化字段错误和 action hint
- **AND** 工具不得静默选择一个 panel 或扩大到整张附件

### Requirement: Scope contract failures are distinguishable from chart failures

工具返回的 source scope/schema 错误 SHALL 使用稳定错误类别并包含 location、reason、effective/expected scope（在安全范围内）和可恢复提示；该错误不得伪装成测量数值为空、render 失败或 review 失败。

#### Scenario: Runtime and schema agree on missing scope

- **WHEN** 模型提交的 JSON 在通用 schema 层可解析，但 source-linked context 在运行时缺少必要范围
- **THEN** 工具按统一 source-scope contract 返回明确错误或安全绑定结果
- **AND** 前端和 execution trace 可以定位到 generation_context.source_scope
