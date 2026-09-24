# agent-loop Specification

## ADDED Requirements

### Requirement: Tool batch artifact records remain available to the next model turn

有序工具批次中，每次已完成调用产生的 artifact 记录 SHALL 保留在当前 Agent 执行上下文中，并在批次后续处理及下一次模型请求中可用。应用记录数量上限时 SHALL 保持共享上下文一致，不得因截断操作丢弃此前或后续调用产生的有效记录。

#### Scenario: Multiple calls produce artifact records in one batch
- **WHEN** 同一模型响应中的多个工具调用依序产生 artifact 记录
- **THEN** 批次结束后的模型上下文包含所有仍在有界保留范围内的记录
- **AND** 后续调用不会覆盖或脱离 Agent 的共享执行上下文

#### Scenario: Artifact records exceed the context bound
- **WHEN** 批次产生的 artifact 记录超过保留上限
- **THEN** 系统按既定上限裁剪记录
- **AND** 裁剪后的共享上下文与后续提示使用的记录集合一致
