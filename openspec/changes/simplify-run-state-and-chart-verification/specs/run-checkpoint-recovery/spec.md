## REMOVED Requirements

### Requirement: Safe checkpoints describe committed next actions

**Reason**: 旧状态或快照控制契约已由提交事实和单一验证链路替代。
**Migration**: 使用 durable-execution-record 或 generated-chart-verification 的对应要求。

### Requirement: Operation records prevent unsafe replay

**Reason**: 旧状态或快照控制契约已由提交事实和单一验证链路替代。
**Migration**: 使用 durable-execution-record 或 generated-chart-verification 的对应要求。

### Requirement: Checkpoints retain source and panel references

**Reason**: 旧状态或快照控制契约已由提交事实和单一验证链路替代。
**Migration**: 使用 durable-execution-record 或 generated-chart-verification 的对应要求。

### Requirement: Review recovery is resumable but bounded

**Reason**: 旧状态或快照控制契约已由提交事实和单一验证链路替代。
**Migration**: 使用 durable-execution-record 或 generated-chart-verification 的对应要求。

### Requirement: Checkpoints preserve the active review gate

**Reason**: 旧状态或快照控制契约已由提交事实和单一验证链路替代。
**Migration**: 使用 durable-execution-record 或 generated-chart-verification 的对应要求。

## ADDED Requirements

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
