# run-checkpoint-recovery Specification

## Purpose

为异步 Agent Run 提供唯一、受限的已提交执行记录和下一动作游标，使显式继续执行复用已确认结果，并按动作副作用契约安全重放。
## Requirements

### Requirement: Resume creates an attributable child run

The system SHALL allow an explicit resume only for a run with a valid
recoverable checkpoint. Resume SHALL create a new run identity and a new
idempotency identity, retain the original run's terminal state, and record a
bounded parent relationship with continuation kind `resume`. Repeating the same
resume intent SHALL resolve to the same child run without starting another
recovery execution.

#### Scenario: Recoverable interrupted run is resumed

- **WHEN** a user explicitly resumes an interrupted run with an available
  checkpoint
- **THEN** the system creates a new running child run
- **AND** the child identifies the prior run as its resume parent

#### Scenario: Parent terminal state remains immutable

- **WHEN** a resume child is created or completes
- **THEN** the original interrupted, failed, or completed run remains unchanged
- **AND** new execution events belong only to the child run

#### Scenario: Duplicate resume intent is replayed

- **WHEN** the client repeats a resume request with the same session, parent,
  checkpoint, and idempotency key
- **THEN** the system returns the original child run and current state
- **AND** it does not create a second child execution

### Requirement: A checkpoint contains one committed cursor and next action

可恢复 checkpoint SHALL 只指向已提交执行记录前缀，保存版本、当前 turn、下一动作种类和该动作所需的有界授权引用。下一动作 SHALL 为 model、tool、verify、promote 或 final；不得另存完整消息、待处理工具列表、审核 gate、修复阶段或 measurement session 快照。

#### Scenario: Resume at a verified boundary
- **WHEN** 暂存图和来源已提交而验证尚未提交
- **THEN** checkpoint 指向 verify 和相同暂存引用
- **AND** 不声称验证或发布已完成

#### Scenario: Checkpoint cannot resolve a reference
- **WHEN** 暂存图、附件或 panel 引用过期或跨 session
- **THEN** resume 返回有界不可用原因且不继续执行

### Requirement: Recovery reuses committed facts and applies replay contracts

显式 resume SHALL 重建私有模型上下文与已提交工具结果，从当前动作继续。已提交结果 SHALL 复用；未提交动作 SHALL 按其副作用契约重放或阻止。模型/VLM 远端结果未提交时 MAY 在显式 resume 后重新请求；不可核对的外部副作用结果不明时 SHALL 阻止自动执行。

#### Scenario: Batch resumes after two committed results
- **WHEN** 三个工具调用的前两个结果已提交
- **THEN** 子 Run 复用前两个结果并执行第三个调用
- **AND** 父 Run 的事件与终态不变

#### Scenario: Unqueryable side effect remains blocked
- **WHEN** 下一动作可能已修改外部系统且无法核对
- **THEN** 子 Run 不自动重放该动作
- **AND** 返回稳定的安全阻止原因

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
