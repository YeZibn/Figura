## ADDED Requirements

### Requirement: Measurement repair lifecycle is inspectable

执行追踪 SHALL 区分普通测量、定向重测、repair action 被拒绝和修复预算耗尽。相关事件 SHALL 保留 bounded run、panel、attempt、父 attempt、target 类型、状态和下一动作摘要，但不得记录原始图片、绝对路径、密钥或 provider 原始 payload。

#### Scenario: A repair attempt is correlated with its parent

- **WHEN** Agent 根据某次测量的质量 issue 发起定向重测
- **THEN** trace 可以关联 repair request、子 attempt、父 attempt、panel 和结果状态
- **AND** 客户端能够区分这次调用是修复测量而不是新的无关测量

#### Scenario: Reconnected clients retain repair history

- **WHEN** 客户端在 repair request 与 repair result 之间断开后按 sequence 重连
- **THEN** 它可以按顺序恢复已有 repair 事件和最终状态
- **AND** 过大的 target 或 result 只截断诊断正文，不丢失调用身份

#### Scenario: Exhausted repair is explicit

- **WHEN** 定向重测无法收敛或达到预算上限
- **THEN** trace 发布明确的 repair-exhausted 或等价非发布状态及下一动作
- **AND** 不把未接受测量渲染为成功完成的证据
