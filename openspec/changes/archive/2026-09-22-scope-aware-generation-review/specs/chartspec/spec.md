## ADDED Requirements

### Requirement: ChartSpec assembly carries source scope and coverage semantics

当 `assemble_spec` 装配源图恢复或源 panel 转换结果时，输入 SHALL 支持结构化
`generation_context`，并 SHALL 将 source scope、代表系列、有意省略系列、选择依据和
measurement references 保留到输出或受控 provenance。装配不得用自由文本覆盖这些字段。

#### Scenario: Assembly records selected and omitted series

- **WHEN** Agent 从同一 panel 的 Actual/Target 两个系列中选择 Actual 组装 pie
- **THEN** 输出明确记录 Actual 为 represented、Target 为 intentionally omitted
- **AND** 输出记录选择依据及其对应的测量证据引用

### Requirement: Assembly rejects silent cross-scope or silent omission

当装配请求中的 measurement reference、panel identity、source scope 或 coverage 彼此
不一致时，系统 SHALL 返回定位到字段的结构化问题，不得静默改写 panel、扩大来源范围
或把缺失系列补为零。只有上下文明确允许 requested subset 时，省略系列才可被接受。

#### Scenario: Mismatched panel reference is rejected

- **WHEN** generation context 指向 panel A，但 measurement reference 来自 panel B
- **THEN** assemble_spec 返回 scope mismatch 问题
- **AND** 不产生可进入渲染的 ChartSpec

#### Scenario: Requested subset is accepted with explicit coverage

- **WHEN** transform context 明确只要求一个系列
- **THEN** 未选系列不会阻止装配
- **AND** 其省略状态和 basis=requested_subset 会被保留

