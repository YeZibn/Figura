## ADDED Requirements

### Requirement: Bound generation evidence to an effective source scope

测量 evidence SHALL 绑定经过授权和解析的 effective attachment/panel scope。若 scope 由工具根据唯一上下文补全，结果 SHALL 明确记录 requested scope、effective scope 和绑定依据；若 scope 不可解析，系统不得产生可被 assemble 接受的 evidence ref。

#### Scenario: Bound scope produces attributable evidence

- **WHEN** 测量调用在唯一授权 panel 内完成并返回候选
- **THEN** attempt 和 evidence refs 记录该 panel、effective scope 和质量状态
- **AND** assemble 可以定位到同一来源范围而不依赖模型猜测内部身份

#### Scenario: Scope error produces no accepted evidence

- **WHEN** 测量调用的 source scope 缺失、歧义或跨 panel
- **THEN** 质量状态为 scope error 或等价的非证据状态
- **AND** 该调用不得产生 accepted evidence 或推动 candidate 进入 assemble

### Requirement: Scope repair remains a local, attributable action

source scope 修复 SHALL 保持在当前 attachment/panel 和对应 measurement attempt 的边界内。修复错误、重新绑定或放弃 SHALL 记录在同一证据 lineage 下，并 SHALL 不自动扩大搜索范围或自动选择语义角色。

#### Scenario: Rebinding does not widen measurement

- **WHEN** Agent 根据工具 action hint 重新提交同一 panel 的 source context
- **THEN** 新 attempt 明确关联父 attempt 并只读取有效同范围
- **AND** 工具不因为第一次 scope 错误而回退到全图测量
