## MODIFIED Requirements

### Requirement: Checkpoints preserve the active review gate

可恢复 checkpoint SHALL 保存活动 generated-chart review 的 subject、审核状态、attempt/candidate 引用、已用预算、问题和允许的下一步动作。measurement observation 不属于独立 review gate；checkpoint 对测量仅保存重建当前 measurement session/attempt 所需的来源、refs、scope 和质量事实。恢复不得将 generated-chart reviewing、repair_required 或失败状态升级为已通过。

#### Scenario: Resume after a measurement tool call

- **WHEN** 运行在测量工具调用前中断，或测量完成后尚未进入下一模型轮次
- **THEN** checkpoint 保存足以恢复当前 session/current attempt 的 bounded 来源范围和结果事实
- **AND** resume 不重新拆解已确认面板、不重复已经完成的测量，也不等待或要求 measurement decision

#### Scenario: Resume after generated chart review interruption

- **WHEN** 候选图已生成但审核结果尚未持久化完成
- **THEN** checkpoint 将审核标记为未完成或不确定
- **AND** resume 不重复发布旧候选，只有在幂等审核结果确认后才可释放该审核状态

#### Scenario: Recovery cannot skip a generated-chart review

- **WHEN** 用户从包含活动 generated-chart review 状态的 checkpoint 继续运行
- **THEN** 子 run 继承该审核状态和修复预算
- **AND** 只有新的有效审核结果才能进入下一阶段
