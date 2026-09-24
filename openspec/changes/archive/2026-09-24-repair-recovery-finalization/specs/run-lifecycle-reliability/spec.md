# run-lifecycle-reliability Specification

## ADDED Requirements

### Requirement: Replayed finalization converges idempotently

Run SHALL 能够重复完成已提交最终回答的终态收敛。对同一 Run 重复应用相同的最终结果 SHALL 保持一个 `completed` 终态和一个可重放的最终回答结果；不得因提交与终态持久化之间的中断而触发新的模型执行，也不得以迟到结果覆盖已存在的终态。

#### Scenario: Finalization is retried after interruption
- **WHEN** 已提交的最终回答在 Run 完成前遇到进程中断，随后恢复流程重试终态收敛
- **THEN** Run 以该已提交回答进入 `completed`
- **AND** 重试不会产生新的模型请求或重复的同 Run 最终回答事件

#### Scenario: A terminal outcome already exists
- **WHEN** 最终回答收敛操作再次到达一个已有终态的 Run
- **THEN** 系统返回或保留已有终态
- **AND** 不追加重复的终态转换或覆盖终态原因
