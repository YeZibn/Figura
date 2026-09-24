## ADDED Requirements

### Requirement: Checkpoints retain source and panel references

可恢复 checkpoint SHALL 在安全引用范围内保存 active attachment、panel ID、PanelHandoff revision、当前候选 ID、审核状态、已用修复次数和下一步意图。checkpoint 不得声称尚未提交的拆解、测量、审核或发布已完成。

#### Scenario: Interrupted scoped analysis can resume
- **WHEN** 一个 panel-scoped 工具已完成并在下一次模型调用前中断
- **THEN** checkpoint 保留该 panel ID 和已提交的工具结果
- **AND** resume 不需要重新拆解，也不重复执行已确认完成的工作

### Requirement: Review recovery is resumable but bounded

checkpoint SHALL 区分 source binding、spec correction、review retry 和 retry exhausted 状态，并 SHALL 防止恢复过程无限重复同一候选或同一失败动作。

#### Scenario: Resume after a semantic review failure
- **WHEN** 候选审核失败且仍有修复预算
- **THEN** checkpoint 指向结构化审核诊断和修正下一步
- **AND** resume 创建新的候选链路而不是重复发布旧候选
