# durable-execution-record Specification

## ADDED Requirements

### Requirement: A committed final answer resumes as the final action

最终回答 SHALL 作为已提交执行事实与指向该回答的 `final` 下一动作游标一起保存。若进程在回答提交后、Run 完成前中断，显式 resume SHALL 从已提交回答继续，复用其准确内容，不再次请求模型或重放已完成工具。已提交模型响应但尚未写入最终回答事实时，恢复 SHALL 复用该响应并完成最终回答提交。

#### Scenario: Resume after the final answer commit
- **WHEN** 最终回答及其 `final` 游标已经提交，但原 Run 尚未完成
- **AND** 用户显式恢复该 Run
- **THEN** 新子 Run 使用已提交的最终回答完成执行
- **AND** 不发出新的模型请求或重复执行工具

#### Scenario: A model response is committed before finalization
- **WHEN** 无工具调用的模型响应已提交为 final action，但最终回答事实尚未提交
- **THEN** 恢复复用该模型响应并继续最终回答保护和提交
- **AND** 不再次请求模型

#### Scenario: No committed model response exists
- **WHEN** 模型响应尚未提交且 cursor 指向模型动作
- **THEN** 恢复按现有模型动作重放规则继续
- **AND** 系统不声称存在可复用的模型响应或最终回答
