## ADDED Requirements

### Requirement: Checkpoints preserve the active review gate

可恢复 checkpoint SHALL 保存当前审核 subject、审核状态、attempt/candidate 引用、已用预算、问题和唯一允许的下一步动作。恢复流程不得把 reviewing、repair_required 或失败状态升级为已通过。

#### Scenario: Resume after measurement review interruption
- **WHEN** 运行在测量审核或定向重测前中断
- **THEN** checkpoint 保留 attachment、panel、父 attempt 和 repair target
- **AND** resume 不重新拆解已确认面板，也不使用未接受的测量继续 assemble

#### Scenario: Resume after generated chart review interruption
- **WHEN** 候选图已生成但审核结果尚未持久化完成
- **THEN** checkpoint 将审核标记为未完成或不确定
- **AND** resume 不重复发布旧候选，只有在幂等审核结果确认后才可释放门禁

#### Scenario: Recovery cannot skip the gate
- **WHEN** 用户从包含活动审核门禁的 checkpoint 继续运行
- **THEN** 子 run 继承审核门禁和修复预算
- **AND** 只有新的有效审核决定才能进入下一阶段
