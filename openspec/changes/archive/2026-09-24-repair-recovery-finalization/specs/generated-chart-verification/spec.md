# generated-chart-verification Specification

## ADDED Requirements

### Requirement: Final claims are checked against their current artifact scope

最终回答保护 SHALL 将图表验证和发布声明绑定到回答引用的正式 artifact；没有明确 artifact 标识的通用声明 SHALL 按该 Run 当前输出范围核验。未被回答引用且不属于当前输出范围的历史 attempt 状态 SHALL NOT 使当前成功声明失败，也不得授权对失败 attempt 作出成功声明。

#### Scenario: A prior failed attempt does not block the current published chart
- **WHEN** 当前输出对应的 attempt 已验证通过并正式发布，且更早的无关 attempt 验证失败
- **AND** 最终回答声明当前图表已通过验证或已发布
- **THEN** 保护逻辑依据当前 artifact 的验证与发布记录判断该声明
- **AND** 不因更早 attempt 的失败而替换或拒绝该回答

#### Scenario: A later success does not authorize a failed artifact claim
- **WHEN** 最终回答引用一个验证失败或未发布的 artifact，即使同一 Run 的其他 attempt 已成功
- **THEN** 保护逻辑拒绝针对该 artifact 的成功或发布声明
- **AND** 保留有界的未通过或未发布说明
