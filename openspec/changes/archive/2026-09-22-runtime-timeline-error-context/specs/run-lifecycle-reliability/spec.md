## ADDED Requirements

### Requirement: Deterministic provider rejection is not an uncertain recovery block

当 provider 已明确拒绝请求并且系统能够确认该结果时，run SHALL 以 provider-blocked 或等价的确定性失败终止，保留可展示的原因和重试建议。该结果不得被标记为远端操作结果未知，也不得自动创建 resume checkpoint。

#### Scenario: Provider returns a known rejection

- **WHEN** 模型请求收到确定性的余额、授权、参数或限流拒绝
- **THEN** run 进入唯一的 failed terminal outcome，并记录稳定分类和 provider 原因
- **AND** `recovery_blocked` 只用于真正的恢复不确定性，不覆盖该失败原因

#### Scenario: User retries after a deterministic rejection

- **WHEN** 用户针对已失败的 provider rejection 显式发起 retry
- **THEN** 系统创建可归因的新 child run
- **AND** 父 run 的失败原因和事件保持不变

### Requirement: Recovery blocking remains reserved for unknown outcomes

只有在系统无法判断远端是否接受了模型、工具或发布操作时，系统 SHALL 进入 uncertain/recovery-blocked 语义。网络或超时失败的历史记录 SHALL 同时保留操作上下文和恢复所需的第一失败引用。

#### Scenario: Timeout has unknown outcome

- **WHEN** 请求超时且没有确认 provider 未接受该请求
- **THEN** run 标记 operation outcome uncertain 并阻止不安全的自动继续
- **AND** 用户可以看到需要显式 retry 或 resume 判断的原因
