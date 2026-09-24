# run-checkpoint-recovery Specification

## ADDED Requirements

### Requirement: Resume validates each cursor in its run lineage

恢复 SHALL 将每个 cursor 的 `entry_cursor` 与该 Run 自己拥有的已提交执行记录数量核对，并单独校验每一层父 Run 引用及父游标。只有所有 lineage 边界都有效且完整时，系统才可组合扁平执行前缀供恢复使用。有效的子 Run checkpoint SHALL 可继续作为新 resume 子 Run 的来源。

#### Scenario: Resume continues from a child run
- **WHEN** 用户恢复一个本身由 resume 创建、且具有有效本地 cursor 和父级 cursor 的中断 Run
- **THEN** 系统分别验证该 Run 与每个祖先的本地执行前缀
- **AND** 新子 Run 使用完整的已提交 lineage 恢复
- **AND** 祖先 Run 的终态和事件保持不变

#### Scenario: A broken ancestor prefix blocks recovery
- **WHEN** lineage 中任一 Run 的本地游标越界、父级引用无效或已提交记录不完整
- **THEN** resume 返回有界的不可用结果
- **AND** 不启动 Agent 执行
